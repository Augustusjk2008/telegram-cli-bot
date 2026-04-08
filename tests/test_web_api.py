"""Web API 相关测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_service import (
    WebApiError,
    change_working_directory,
    get_directory_listing,
    get_session_for_alias,
    get_overview,
    read_file_content,
    run_cli_chat,
    save_uploaded_file,
)
from bot.web.server import WebApiServer


@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="kimi",
        cli_path="kimi",
        working_dir=str(temp_dir),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


def test_overview_and_directory_listing(web_manager: MultiBotManager, temp_dir: Path):
    subdir = temp_dir / "workspace"
    subdir.mkdir()
    (subdir / "hello.txt").write_text("hello", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(subdir))
    overview = get_overview(web_manager, "main", 1001)
    assert overview["session"]["working_dir"] == str(subdir)

    listing = get_directory_listing(web_manager, "main", 1001)
    assert any(item["name"] == "hello.txt" for item in listing["entries"])


def test_change_working_directory_clears_session_ids(web_manager: MultiBotManager, temp_dir: Path):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.codex_session_id = "thread-old"
    session.kimi_session_id = "kimi-old"
    session.claude_session_id = "claude-old"
    session.claude_session_initialized = True

    subdir = temp_dir / "workspace"
    subdir.mkdir()

    result = change_working_directory(web_manager, "main", 1001, str(subdir))

    assert result["working_dir"] == str(subdir)
    assert session.working_dir == str(subdir)
    assert session.codex_session_id is None
    assert session.kimi_session_id is None
    assert session.claude_session_id is None
    assert session.claude_session_initialized is False


def test_save_and_read_file(web_manager: MultiBotManager, temp_dir: Path):
    result = save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\nline2\n")
    assert result["filename"] == "notes.txt"

    content = read_file_content(web_manager, "main", 1001, "notes.txt", mode="head", lines=1)
    assert content["content"] == "line1"


@pytest.mark.asyncio
async def test_auth_route_requires_token(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me")
            assert resp.status == 401

            resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer secret"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["user_id"] == 1001


@pytest.mark.asyncio
async def test_bot_overview_route(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["bot"]["alias"] == "main"
            assert payload["data"]["session"]["working_dir"] == web_manager.main_profile.working_dir


@pytest.mark.asyncio
async def test_chat_stream_route_returns_sse_events(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_chat(manager, alias, user_id, message):
        yield {"type": "meta", "alias": alias}
        yield {"type": "delta", "text": "hello"}
        yield {"type": "done", "returncode": 0, "timed_out": False}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_chat", fake_stream_chat):
                resp = await client.post("/api/bots/main/chat/stream", json={"message": "hi"})
                assert resp.status == 200
                body = await resp.text()
                assert "event: meta" in body
                assert "event: delta" in body
                assert "event: done" in body


def test_read_missing_file_raises(web_manager: MultiBotManager):
    with pytest.raises(WebApiError) as exc_info:
        read_file_content(web_manager, "main", 1001, "missing.txt")
    assert exc_info.value.code == "file_not_found"


@pytest.mark.asyncio
async def test_run_cli_chat_resets_and_persists_kimi_session(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.kimi_session_id = "kimi-stale"
    session.persist = MagicMock()

    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="kimi"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["kimi"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_process", new_callable=AsyncMock, return_value=("session expired", 1, False)):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["returncode"] == 1
    assert session.kimi_session_id is None
    session.persist.assert_called_once_with()
