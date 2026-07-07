from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.permission_store import BotPermissionStore
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
    storage.write_text(
        json.dumps(
            {
                "bots": [
                    {
                        "alias": "team2",
                        "token": "team_tok",
                        "cli_type": "codex",
                        "cli_path": "codex",
                        "working_dir": str(tmp_path / "team2"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path / "main"),
        ),
        str(storage),
    )


def _build_server(
    manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> WebApiServer:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    return WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())


@pytest.mark.asyncio
async def test_guest_enters_main_bot_with_readonly_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch, tmp_path)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            origin = str(test_server.make_url("/")).rstrip("/")
            login_response = await client.post("/api/auth/guest")
            login_payload = await login_response.json()

            bots_response = await client.get("/api/bots")
            bots_payload = await bots_response.json()

            overview_response = await client.get("/api/bots/main")
            overview_payload = await overview_response.json()

            chat_response = await client.post(
                "/api/bots/main/chat",
                json={"message": "hello"},
                headers={"Origin": origin},
            )
            chat_payload = await chat_response.json()

    assert login_response.status == 200, login_payload
    assert "view_bots" in login_payload["data"]["capabilities"]
    assert "chat_send" not in login_payload["data"]["capabilities"]
    assert bots_response.status == 200, bots_payload
    assert [item["alias"] for item in bots_payload["data"]] == ["main"]
    assert bots_payload["data"][0]["can_operate"] is True
    assert bots_payload["data"][0]["effective_capabilities"] == sorted(login_payload["data"]["capabilities"])
    assert overview_response.status == 200, overview_payload
    assert overview_payload["data"]["bot"]["alias"] == "main"
    assert overview_payload["data"]["bot"]["can_operate"] is True
    assert chat_response.status == 403, chat_payload
    assert chat_payload["error"]["code"] == "forbidden"
