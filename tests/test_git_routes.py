from __future__ import annotations

import json

from pathlib import Path

import pytest

from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager

from bot.models import BotProfile

from bot.web.api_common import AuthContext

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
