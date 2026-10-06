from __future__ import annotations

import json

from pathlib import Path

import pytest

from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager

from bot.models import BotProfile

from bot.git_contract import GIT_CAPABILITIES_REQUIRING_CONFIRMATION, GIT_CAPABILITY_NAMES

from bot.web.api_common import AuthContext

from bot.web import git_service

from bot.web.auth_store import CAP_GIT_OPS

from bot.web.server import WebApiServer

class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
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

def _build_manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )

def _build_server(manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch) -> WebApiServer:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    return WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

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
async def test_git_commit_message_config_routes_reject_member_without_git_ops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)
    monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context())
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/bots/main/git/commit-message/config")
            payload = await response.json()

    assert response.status == 403
    assert payload["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_git_capabilities_route_requires_git_ops_and_returns_complete_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)
    auth = _auth_context()
    monkeypatch.setattr(server, "_auth_context", lambda _request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)
    monkeypatch.setattr(git_service, "_run_git", lambda *_args, **_kwargs: type("Result", (), {"returncode": 0})())

    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/bots/main/git/capabilities")
        assert response.status == 403
        auth.capabilities.add(CAP_GIT_OPS)
        response = await client.get("/api/bots/main/git/capabilities")
        payload = await response.json()

    assert response.status == 200
    capabilities = payload["data"]["capabilities"]
    assert set(capabilities) == set(GIT_CAPABILITY_NAMES)
    for name, capability in capabilities.items():
        assert capability["available"] is True
        assert capability["reason"] == ""
        assert capability["requires_confirmation"] is (name in GIT_CAPABILITIES_REQUIRING_CONFIRMATION)


@pytest.mark.asyncio
async def test_git_capabilities_reports_git_not_found_without_repository_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)
    auth = _auth_context(CAP_GIT_OPS)
    monkeypatch.setattr(server, "_auth_context", lambda _request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)

    def missing_git(*_args, **_kwargs):
        raise git_service.WebApiError(500, "git_not_found", "hidden executable detail")

    monkeypatch.setattr(git_service, "_run_git", missing_git)

    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/bots/main/git/capabilities")
        payload = await response.json()

    assert response.status == 200
    assert all(
        capability == {
            "available": False,
            "reason": "git_not_found",
            "requires_confirmation": name in GIT_CAPABILITIES_REQUIRING_CONFIRMATION,
        }
        for name, capability in payload["data"]["capabilities"].items()
    )
