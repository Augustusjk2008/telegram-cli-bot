from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.plugins.service import PluginService
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_RUN_PLUGINS
from bot.web.routes import plugin_routes
from bot.web.server import WebApiServer


def _write_plugin(root: Path, folder: str, plugin_id: str) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": plugin_id,
                "name": plugin_id,
                "version": "1.0.0",
                "runtime": {
                    "type": "python",
                    "entry": "backend/main.py",
                    "protocol": "jsonrpc-stdio",
                    "permissions": {},
                },
                "views": [],
                "fileHandlers": [],
            }
        ),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.parametrize("runtime_state", ["matching", "changed", "missing"])
def test_bundled_manifest_sync_requires_matching_runtime_files(tmp_path: Path, runtime_state: str) -> None:
    source_root = tmp_path / "bundled"
    source = _write_plugin(source_root, "document", "document")
    backend = source / "backend"
    backend.mkdir()
    (backend / "main.py").write_text("from helper import render\n", encoding="utf-8")
    (backend / "helper.py").write_text("def render(): return {}\n", encoding="utf-8")
    plugins_root = tmp_path / "installed"
    installed = plugins_root / source.name
    shutil.copytree(source, installed)
    installed_raw = json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
    installed_raw.update(enabled=False, config={"theme": "dark"})
    (installed / "plugin.json").write_text(json.dumps(installed_raw), encoding="utf-8")
    source_raw = {
        **installed_raw,
        "enabled": True,
        "config": {"theme": "light", "pageSize": 20},
        "views": [{"id": "document", "renderer": "document", "viewMode": "session", "dataProfile": "light"}],
    }
    (source / "plugin.json").write_text(json.dumps(source_raw), encoding="utf-8")
    dependency = installed / "backend" / "helper.py"
    if runtime_state == "changed":
        dependency.write_text("def render(): return {'payload': {}}\n", encoding="utf-8")
    elif runtime_state == "missing":
        dependency.unlink()

    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=source_root)
    service.list_plugins(refresh=True)

    actual = json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
    expected = (
        {**source_raw, "enabled": False, "config": {"theme": "dark", "pageSize": 20}}
        if runtime_state == "matching" else installed_raw
    )
    assert actual == expected


@pytest.mark.asyncio
async def test_install_plugins_from_path_recursively_installs_nested_plugins(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    first = _write_plugin(source_root / "plugins", "first", "first-plugin")
    second = _write_plugin(source_root / "plugins" / "nested", "second", "second-plugin")
    plugins_root = tmp_path / "installed"
    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=tmp_path / "bundled")

    try:
        result = await service.install_plugins_from_path(source_root, force=True)
    finally:
        await service.shutdown()

    assert result["sourcePath"] == str(source_root.resolve())
    assert result["discovered"] == 2
    assert [item["id"] for item in result["installed"]] == ["first-plugin", "second-plugin"]
    assert (plugins_root / first.name / "plugin.json").is_file()
    assert (plugins_root / second.name / "plugin.json").is_file()


@pytest.mark.asyncio
async def test_install_plugins_from_path_rejects_duplicate_ids_before_copying(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    _write_plugin(source_root, "first", "duplicate")
    _write_plugin(source_root / "nested", "second", "duplicate")
    plugins_root = tmp_path / "installed"
    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=tmp_path / "bundled")

    try:
        with pytest.raises(ValueError, match="插件 ID 重复"):
            await service.install_plugins_from_path(source_root, force=True)
    finally:
        await service.shutdown()

    assert not plugins_root.exists()


@pytest.mark.asyncio
async def test_install_directory_route_installs_media_player(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "examples/plugins/media-player"
    service = PluginService(
        tmp_path, plugins_root=tmp_path / "installed", source_plugins_root=source.parent,
    )
    server = object.__new__(WebApiServer)
    server.manager = SimpleNamespace(
        main_profile=SimpleNamespace(alias="main"), managed_profiles={}, plugin_service=service,
    )
    auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_RUN_PLUGINS}, is_local_admin=True)
    monkeypatch.setattr(server, "_auth_context", lambda request: auth)
    app = web.Application()
    plugin_routes.register(app, server)
    app.freeze()
    request = make_mocked_request(
        "POST", "/api/plugins/install-directory", app=app, headers={"Host": "localhost"},
        transport=Mock(get_extra_info=Mock(return_value=("127.0.0.1", 12345))),
    )
    request._match_info = await app.router.resolve(request)
    request.json = AsyncMock(return_value={"sourcePath": str(source), "dev": True, "force": True})

    try:
        response = await request.match_info.handler(request)
        payload = json.loads(response.text)
        assert response.status == 200 and payload["ok"] is True
        assert [plugin["id"] for plugin in payload["data"]["installed"]] == ["media-player"]
        assert (service.plugins_root / "media-player/backend/main.py").is_file()
        assert service.resolve_file_target("sample.mp3")["pluginId"] == "media-player"
    finally:
        await service.shutdown()
