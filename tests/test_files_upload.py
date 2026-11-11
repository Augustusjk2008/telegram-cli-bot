from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext, WebApiError, get_session_for_alias
from bot.web.auth_store import CAP_WRITE_FILES
from bot.web.routes import files_routes
from bot.web.server import WebApiServer


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "docs" / "资料 #1").mkdir(parents=True)
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(root)), str(storage))
    return manager, root


async def upload_request(manager, parent_path):
    server = object.__new__(WebApiServer)
    server.manager = manager
    auth = AuthContext(user_id=42, token_used=True, capabilities={CAP_WRITE_FILES})
    server._auth_context = lambda _request: auth
    server._can_operate_bot = lambda _auth, alias: alias == "main"
    app = web.Application()
    files_routes.register(app, server)
    query = "?" + urlencode({"parent_path": parent_path}) if parent_path is not None else ""
    request = make_mocked_request("POST", "/api/bots/main/files/upload" + query, app=app)
    request._match_info = await app.router.resolve(request)
    field = SimpleNamespace(name="file", filename="report.bin", read_chunk=AsyncMock(side_effect=[b"\x00\xff", b"contents", b""]))
    request.multipart = AsyncMock(return_value=SimpleNamespace(next=AsyncMock(return_value=field)))
    return await request.match_info.handler(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_kind", ["default", "relative", "absolute"])
async def test_upload_saves_in_target_without_changing_browse_directory(workspace, parent_kind):
    manager, root = workspace
    directory = root if parent_kind == "default" else root / "docs" / "资料 #1"
    parent_path = {"default": None, "relative": "docs/资料 #1", "absolute": str(directory)}[parent_kind]
    session = get_session_for_alias(manager, "main", 42)
    browse_dir = session.browse_dir

    response = await upload_request(manager, parent_path)

    assert response.status == 200
    result = json.loads(response.text)["data"]
    assert Path(result["saved_path"]) == directory / "report.bin"
    assert (directory / "report.bin").read_bytes() == b"\x00\xffcontents"
    assert list(root.rglob("report.bin")) == [directory / "report.bin"]
    assert session.browse_dir == browse_dir
    assert session.working_dir == str(root)


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_kind,code", [
    ("outside_relative", "unsafe_write_path"),
    ("outside_absolute", "unsafe_write_path"),
    ("missing", "dir_not_found"),
    ("file", "dir_not_found"),
])
async def test_upload_rejects_invalid_target_without_falling_back_to_root(workspace, parent_kind, code):
    manager, root = workspace
    outside = root.parent / "outside"
    outside.mkdir()
    (root / "file.txt").write_text("existing", encoding="utf-8")
    parent_path = {
        "outside_relative": "../outside",
        "outside_absolute": str(outside),
        "missing": "missing",
        "file": "file.txt",
    }[parent_kind]

    with pytest.raises(WebApiError) as error:
        await upload_request(manager, parent_path)

    assert error.value.code == code
    assert not list(root.parent.rglob("report.bin"))
