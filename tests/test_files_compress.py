from __future__ import annotations

import json
import os
import stat
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import files_service
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_VIEW_FILE_TREE, CAP_WRITE_FILES
from bot.web.routes import files_routes, remote_routes
from bot.web.server import WebApiServer


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(root)), str(storage))
    return manager, root


def test_compress_preserves_tree_and_overwrites_full_directory_name(workspace):
    manager, root = workspace
    source = root / "父目录" / "项目.v1"
    (source / "空目录").mkdir(parents=True)
    (source / "子目录").mkdir()
    (source / "子目录" / "说明.txt").write_bytes(("压缩内容\n" * 100).encode("utf-8"))
    target = source.with_name(source.name + ".zip")
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("old.txt", "old contents")

    result = files_service.compress_directory(manager, "main", 42, "父目录\\项目.v1")

    assert result == {
        "source_path": "父目录/项目.v1",
        "path": "父目录/项目.v1.zip",
        "file_size_bytes": target.stat().st_size,
        "last_modified_ns": target.stat().st_mtime_ns,
    }
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            "项目.v1/", "项目.v1/空目录/", "项目.v1/子目录/", "项目.v1/子目录/说明.txt",
        }
        assert archive.read("项目.v1/子目录/说明.txt").decode("utf-8") == "压缩内容\n" * 100
        assert archive.getinfo("项目.v1/子目录/说明.txt").compress_type == zipfile.ZIP_DEFLATED
        assert archive.testzip() is None
    assert not list(source.parent.glob(".项目.v1.zip.*.tmp"))


def test_compress_empty_directory(workspace):
    manager, root = workspace
    (root / "empty").mkdir()
    files_service.compress_directory(manager, "main", 42, "empty")
    with zipfile.ZipFile(root / "empty.zip") as archive:
        assert archive.namelist() == ["empty/"]


@pytest.mark.parametrize(("path", "code"), [
    ("", "invalid_compress_path"),
    ("missing", "dir_not_found"),
    ("file.txt", "not_directory"),
    ("../outside", "unsafe_write_path"),
    (".", "unsafe_write_path"),
    ("folder/..", "invalid_compress_path"),
])
def test_compress_rejects_invalid_source(workspace, path, code):
    manager, root = workspace
    (root / "file.txt").write_text("contents", encoding="utf-8")
    (root / "folder").mkdir()
    with pytest.raises(WebApiError) as error:
        files_service.compress_directory(manager, "main", 42, path)
    assert error.value.code == code
    assert not list(root.rglob("*.zip"))


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_compress_failure_preserves_old_archive_and_cleans_temporary_file(workspace, monkeypatch, failure):
    manager, root = workspace
    (root / "folder").mkdir()
    (root / "folder.zip").write_bytes(b"old archive")
    if failure == "write":
        monkeypatch.setattr(zipfile.ZipFile, "write", Mock(side_effect=OSError("read failed")))
    else:
        monkeypatch.setattr(files_service.os, "replace", Mock(side_effect=PermissionError("replace failed")))

    with pytest.raises(WebApiError) as error:
        files_service.compress_directory(manager, "main", 42, "folder")

    assert error.value.code == "compress_directory_failed"
    assert (root / "folder.zip").read_bytes() == b"old archive"
    assert set(item.name for item in root.iterdir()) == {"folder", "folder.zip"}


@pytest.mark.parametrize("link_kind", ["source", "outside_file", "directory_loop", "target"])
def test_compress_rejects_symlinks_without_replacing_old_archive(workspace, link_kind):
    manager, root = workspace
    source = root / "folder"
    source.mkdir()
    outside_file = root.parent / "outside.txt"
    outside_file.write_bytes(b"private contents")
    target = root / "folder.zip"
    source_name = "folder"
    try:
        if link_kind == "source":
            (root / "linked").symlink_to(source, target_is_directory=True)
            source_name = "linked"
        elif link_kind == "outside_file":
            (source / "linked.txt").symlink_to(outside_file)
        elif link_kind == "directory_loop":
            (source / "loop").symlink_to(source, target_is_directory=True)
        else:
            target.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")
    if link_kind != "target":
        target.write_bytes(b"old archive")

    with pytest.raises(WebApiError) as error:
        files_service.compress_directory(manager, "main", 42, source_name)

    assert error.value.code == "unsupported_compress_entry"
    assert target.read_bytes() == (b"private contents" if link_kind == "target" else b"old archive")
    assert outside_file.read_bytes() == b"private contents"
    assert not list(root.glob(".*.tmp"))


def test_compress_rejects_windows_reparse_directory(workspace, monkeypatch):
    manager, root = workspace
    source = root / "folder"
    (source / "junction").mkdir(parents=True)
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == source / "junction":
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(files_service.os, "lstat", lstat)
    with pytest.raises(WebApiError) as error:
        files_service.compress_directory(manager, "main", 42, "folder")
    assert error.value.code == "unsupported_compress_entry"
    assert set(item.name for item in root.iterdir()) == {"folder"}


async def _compression_request(manager, capabilities):
    server = object.__new__(WebApiServer)
    server.manager = manager
    auth = AuthContext(user_id=42, token_used=True, capabilities=capabilities)
    server._auth_context = lambda _request: auth
    server._can_operate_bot = lambda _auth, alias: alias == "main"
    app = web.Application()
    files_routes.register(app, server)
    request = make_mocked_request("POST", "/api/bots/main/files/compress", app=app)
    request._match_info = await app.router.resolve(request)
    request.json = AsyncMock(return_value={"path": "folder"})
    return server, request


@pytest.mark.asyncio
@pytest.mark.parametrize("can_write", [True, False])
async def test_compress_route_enforces_permission_and_serializes_version(workspace, monkeypatch, can_write):
    manager, root = workspace
    (root / "folder").mkdir()
    capabilities = {CAP_WRITE_FILES} if can_write else set()
    _server, request = await _compression_request(manager, capabilities)
    request_thread = threading.get_ident()

    def compress(*args, **kwargs):
        assert threading.get_ident() != request_thread
        return files_service.compress_directory(*args, **kwargs)

    worker = Mock(side_effect=compress)
    monkeypatch.setattr("bot.web.server.compress_directory", worker)
    if not can_write:
        with pytest.raises(WebApiError) as error:
            await request.match_info.handler(request)
        assert error.value.status == 403
        worker.assert_not_called()
        assert not (root / "folder.zip").exists()
        return

    response = await request.match_info.handler(request)
    assert response.status == 200
    data = json.loads(response.text)
    assert data["ok"] is True
    assert data["data"]["path"] == "folder.zip"
    assert data["data"]["last_modified_ns"] == str((root / "folder.zip").stat().st_mtime_ns)
    worker.assert_called_once()


@pytest.mark.asyncio
async def test_compress_remote_route_does_not_touch_local_control_directory(workspace):
    manager, root = workspace
    (root / "folder").mkdir()
    manager.main_profile.remote_workspace = {"root": "/srv/project"}
    server, request = await _compression_request(manager, {CAP_VIEW_FILE_TREE, CAP_WRITE_FILES})
    with pytest.raises(WebApiError) as error:
        await remote_routes.middleware(server)(request, request.match_info.handler)
    assert error.value.status == 409
    assert error.value.code == "remote_feature_unavailable"
    assert not (root / "folder.zip").exists()
