from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT, CAP_WRITE_FILES
from bot.web.server import WebApiServer


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


def _build_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(
            alias="main",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path / "workspace"),
        ),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)
    return server


def _auth_context(*capabilities: str) -> AuthContext:
    return AuthContext(
        user_id=123,
        token_used=True,
        account_id="member-1",
        username="alice",
        capabilities=set(capabilities),
        is_local_admin=False,
    )


@pytest.mark.asyncio
async def test_admin_ops_can_read_and_write_an_absolute_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("before", encoding="utf-8")
    server = _build_server(tmp_path, monkeypatch)
    app = server._build_app()
    admin_auth = _auth_context(CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT, CAP_WRITE_FILES)

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: admin_auth)
            allowed_read = await client.get(
                "/api/bots/main/files/read",
                params={"filename": str(outside_file), "mode": "cat", "lines": "0"},
            )
            allowed_read_payload = await allowed_read.json()
            allowed_write = await client.post(
                "/api/bots/main/files/write",
                json={"path": str(outside_file), "content": "after"},
            )
            allowed_write_payload = await allowed_write.json()

            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_READ_FILE_CONTENT))
            denied_read = await client.get(
                "/api/bots/main/files/read",
                params={"filename": str(outside_file), "mode": "cat", "lines": "0"},
            )
            denied_read_payload = await denied_read.json()

    assert allowed_read.status == 200, allowed_read_payload
    assert allowed_read_payload["data"]["content"] == "before"
    assert allowed_write.status == 200, allowed_write_payload
    assert outside_file.read_text(encoding="utf-8") == "after"
    assert denied_read.status == 400, denied_read_payload
    assert denied_read_payload["error"]["code"] == "unsafe_path"
