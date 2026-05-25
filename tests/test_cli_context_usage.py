from __future__ import annotations

import json
from pathlib import Path

from bot.web.native_history_locator import LocatedTranscript


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
        encoding="utf-8",
    )


def test_resolve_codex_context_usage_reads_latest_token_count(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import resolve_cli_context_usage

    transcript = tmp_path / "session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"total_tokens": 32000},
                        "model_context_window": 258400,
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"total_tokens": 76593},
                        "total_token_usage": {"total_tokens": 900000},
                        "model_context_window": 258400,
                    },
                },
            },
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_codex_transcript",
        lambda session_id: LocatedTranscript("codex", session_id, transcript),
    )

    usage = resolve_cli_context_usage("codex", "thread-1")

    assert usage == {
        "provider": "codex",
        "source": "codex_session_token_count",
        "session_id": "thread-1",
        "used_tokens": 76593,
        "context_window": 258400,
        "context_left_percent": 74,
        "used_display": "76.6K",
        "window_display": "258K",
        "status_text": "74% context left · 76.6K / 258K",
    }


def test_resolve_codex_context_usage_returns_none_without_token_count(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import resolve_cli_context_usage

    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [{"type": "event_msg", "payload": {"type": "agent_message"}}])
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_codex_transcript",
        lambda session_id: LocatedTranscript("codex", session_id, transcript),
    )

    assert resolve_cli_context_usage("codex", "thread-1") is None


def test_resolve_cli_context_usage_ignores_non_codex():
    from bot.web.cli_context_usage import resolve_cli_context_usage

    assert resolve_cli_context_usage("claude", "thread-1") is None
    assert resolve_cli_context_usage("kimi", "thread-1") is None
    assert resolve_cli_context_usage("unknown", "thread-1") is None


def test_resolve_codex_context_usage_returns_none_when_session_missing(monkeypatch):
    from bot.web.cli_context_usage import resolve_cli_context_usage

    monkeypatch.setattr("bot.web.cli_context_usage.locate_codex_transcript", lambda session_id: None)

    assert resolve_cli_context_usage("codex", "missing") is None
