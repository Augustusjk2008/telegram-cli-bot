from __future__ import annotations

import json
from pathlib import Path

import pytest

import bot.runtime_paths as runtime_paths
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.cli_error_stats import classify_cli_error, collect_cli_error_stats, normalize_error_message
from bot.web.api_service import get_session_for_alias


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("authentication_failed: invalid api key", "auth"),
        ("HTTP 429 rate limit reached", "rate_limit"),
        ("502 upstream error", "server_5xx"),
        ("fetch failed after dns timeout", "network"),
        ("failed to resume: conversation not found", "resume_session"),
        ("mcp tool unavailable: server not configured", "mcp"),
        ("permission denied by sandbox approval", "permission"),
        ("json decode failed: invalid json", "parse"),
        ("unexpected failure", "unknown"),
    ],
)
def test_classify_cli_error(message: str, category: str):
    assert classify_cli_error(message) == category


def test_classify_stale_stream_recovered_as_interrupted():
    assert classify_cli_error("stale_stream_recovered 上次运行未正常结束") == "interrupted"
    assert classify_cli_error("unknown thread") == "resume_session"


def test_normalize_error_message_redacts_noisy_parts():
    message = (
        "failed C:\\Users\\Kai\\very\\long\\repo\\file.py "
        "https://example.com/api?token=secret&x=1 token=abc123 "
        "0123456789abcdef0123456789abcdef"
    )

    normalized = normalize_error_message(message)

    assert "<path>" in normalized
    assert "?" not in normalized
    assert "token=<redacted>" in normalized
    assert "<hash>" in normalized
    assert len(normalized) <= 240


def test_collect_cli_error_stats_groups_by_cli_bot_category(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(workdir)),
        str(storage_file),
    )
    session = get_session_for_alias(manager, "main", 1001)
    session.working_dir = str(workdir)
    service = ChatHistoryService(ChatStore(workdir))

    failed = service.start_turn(
        profile=manager.main_profile,
        session=session,
        user_text="hello",
        native_provider="codex",
    )
    service.complete_turn(
        failed,
        content="HTTP 429 rate limit reached",
        completion_state="failed",
        error_code="failed",
        error_message="HTTP 429 rate limit reached",
    )
    completed = service.start_turn(
        profile=manager.main_profile,
        session=session,
        user_text="ok",
        native_provider="codex",
    )
    service.complete_turn(completed, content="ok", completion_state="completed")

    stats = collect_cli_error_stats(manager, hours=24, limit=20)

    assert stats["summary"]["total"] == 1
    assert stats["summary"]["by_cli_type"] == {"codex": 1}
    assert stats["summary"]["by_bot"] == {"main": 1}
    assert stats["summary"]["by_category"] == {"rate_limit": 1}
    assert stats["items"][0]["turn_id"] == failed.turn_id
    assert stats["items"][0]["duration_ms"] is not None
    assert stats["top_errors"][0]["count"] == 1


def test_collect_cli_error_stats_reconciles_stale_streaming_turns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "repo"
    workdir.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(workdir)),
        str(storage_file),
    )
    session = get_session_for_alias(manager, "main", 1001)
    session.working_dir = str(workdir)
    service = ChatHistoryService(ChatStore(workdir))
    service.start_turn(
        profile=manager.main_profile,
        session=session,
        user_text="hello",
        native_provider="codex",
    )
    with session._lock:
        session.is_processing = False

    stats = collect_cli_error_stats(manager, hours=24, limit=20)

    assert stats["summary"]["total"] == 1
    assert stats["summary"]["by_category"] == {"interrupted": 1}
    assert stats["items"][0]["error_code"] == "stale_stream_recovered"
