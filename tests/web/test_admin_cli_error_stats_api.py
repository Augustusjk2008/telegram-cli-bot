from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import bot.runtime_paths as runtime_paths
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_service import get_session_for_alias
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.server import WebApiServer


@pytest.mark.asyncio
async def test_admin_cli_error_stats_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(workdir)),
        str(storage_file),
    )
    session = get_session_for_alias(manager, "main", 1001)
    session.working_dir = str(workdir)
    service = ChatHistoryService(ChatStore(workdir))
    handle = service.start_turn(
        profile=manager.main_profile,
        session=session,
        user_text="resume",
        native_provider="codex",
    )
    service.complete_turn(
        handle,
        content="failed to resume: conversation not found",
        completion_state="error",
        error_code="error",
        error_message="failed to resume: conversation not found",
    )

    app = WebApiServer(manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/admin/cli-errors?hours=72&limit=50")
            payload = await response.json()

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["data"]["summary"]["total"] == 1
    assert payload["data"]["summary"]["by_category"] == {"resume_session": 1}
    assert payload["data"]["items"][0]["conversation_id"] == handle.conversation_id
