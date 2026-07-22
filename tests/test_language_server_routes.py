from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT
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


class FakeLanguageServerInstaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def install(self, provider_id: str, *, update: bool = False) -> dict[str, object]:
        self.calls.append((provider_id, update))
        return {"provider": provider_id, "status": "installed", "update": update}


class FakeLanguageServerCatalog:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.redetect_calls = 0

    def snapshot(self) -> dict[str, object]:
        self.snapshot_calls += 1
        return {"enabled": True, "providers": [{"id": "pyright", "status": "missing"}]}

    def redetect(self) -> dict[str, object]:
        self.redetect_calls += 1
        return self.api_snapshot()

    def api_snapshot(self) -> dict[str, object]:
        self.snapshot_calls += 1
        return {
            "providers": [
                {
                    "provider": "pyright",
                    "status": "available",
                    "source": "managed",
                    "version": "1.0.0",
                    "command_summary": "pyright",
                    "can_install": True,
                    "can_update": True,
                    "error": "",
                }
            ],
            "can_refresh": True,
        }


def _build_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: FakeLanguageServerCatalog,
    installer: FakeLanguageServerInstaller,
) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(
        manager,
        host="127.0.0.1",
        port=8765,
        tunnel_service=DummyTunnelService(),
        language_server_catalog=catalog,  # type: ignore[arg-type]
        language_server_installer=installer,  # type: ignore[arg-type]
    )
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
async def test_language_server_status_endpoints_are_read_only_and_require_read_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = FakeLanguageServerCatalog()
    installer = FakeLanguageServerInstaller()
    server = _build_server(tmp_path, monkeypatch, catalog=catalog, installer=installer)
    app = server._build_app()
    offloaded: list[object] = []

    async def fake_to_thread(function, *args, **kwargs):
        offloaded.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr("bot.web.server.asyncio.to_thread", fake_to_thread)

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context())
            forbidden = await client.get("/api/language-servers/status")
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_READ_FILE_CONTENT))
            allowed = await client.get("/api/language-servers/status")
            refreshed = await client.post("/api/language-servers/refresh")
            workspace = await client.get("/api/bots/main/workspace/language-servers")
            payload = await allowed.json()
            refreshed_payload = await refreshed.json()
            workspace_payload = await workspace.json()

    assert forbidden.status == 403
    assert allowed.status == 200, payload
    assert refreshed.status == 200, refreshed_payload
    assert workspace.status == 200, workspace_payload
    assert payload["data"]["providers"][0]["provider"] == "pyright"
    assert installer.calls == []
    assert catalog.snapshot_calls == 3
    assert sum(function == catalog.api_snapshot for function in offloaded) == 3


@pytest.mark.asyncio
async def test_language_server_install_update_and_redetect_are_admin_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = FakeLanguageServerCatalog()
    installer = FakeLanguageServerInstaller()
    server = _build_server(tmp_path, monkeypatch, catalog=catalog, installer=installer)
    app = server._build_app()
    offloaded: list[object] = []

    async def fake_to_thread(function, *args, **kwargs):
        offloaded.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr("bot.web.server.asyncio.to_thread", fake_to_thread)

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_READ_FILE_CONTENT))
            forbidden = await client.post("/api/admin/language-servers/pyright/install")
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_ADMIN_OPS))
            installed = await client.post("/api/admin/language-servers/pyright/install")
            updated_from_install = await client.post("/api/admin/language-servers/pyright/install", json={"update": True})
            updated = await client.post("/api/admin/language-servers/pyright/update")
            redetected = await client.post("/api/admin/language-servers/redetect")
            installed_payload = await installed.json()
            updated_from_install_payload = await updated_from_install.json()
            updated_payload = await updated.json()
            redetected_payload = await redetected.json()

    assert forbidden.status == 403
    assert installed.status == 200, installed_payload
    assert updated_from_install.status == 200, updated_from_install_payload
    assert updated.status == 200, updated_payload
    assert redetected.status == 200, redetected_payload
    assert installer.calls == [("pyright", False), ("pyright", True), ("pyright", True)]
    assert installed_payload["data"]["providers"][0]["status"] == "available"
    assert redetected_payload["data"]["providers"][0]["provider"] == "pyright"
    assert catalog.redetect_calls == 1
    assert catalog.redetect in offloaded
    assert sum(function == catalog.api_snapshot for function in offloaded) == 3
