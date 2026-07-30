from __future__ import annotations

import json
from pathlib import Path

from bot.web.native_history_locator import LocatedTranscript


def test_claude_message_usage_counts_cached_input_tokens(monkeypatch, tmp_path: Path) -> None:
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-5",
                    "usage": {
                        "input_tokens": 61,
                        "cache_creation_input_tokens": 9_180,
                        "cache_read_input_tokens": 91_174,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 9_000,
                            "ephemeral_1h_input_tokens": 180,
                        },
                        "output_tokens": 45,
                    },
                },
                "sessionId": "claude-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-1", cwd_hint=str(tmp_path))

    assert usage == {
        "provider": "claude",
        "source": "claude_message_usage_estimate",
        "session_id": "claude-1",
        "used_tokens": 100_415,
        "input_tokens": 61,
        "cache_write_tokens": 9_180,
        "cache_read_tokens": 91_174,
        "output_tokens": 45,
        "context_window": 1_000_000,
        "context_left_percent": 90,
        "used_display": "100.4k",
        "window_display": "1m",
        "status_text": "90% context left · 100.4k / 1m",
    }


def test_claude_message_usage_falls_back_to_cache_creation_ttl_breakdown(monkeypatch, tmp_path: Path) -> None:
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-5",
                    "usage": {
                        "input_tokens": 8,
                        "cache_read_input_tokens": 100_000,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 5_000,
                            "ephemeral_1h_input_tokens": 1_000,
                        },
                        "output_tokens": 13,
                    },
                },
                "sessionId": "claude-2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-2", cwd_hint=str(tmp_path))

    assert usage is not None
    assert usage["used_tokens"] == 106_008
    assert usage["cache_write_tokens"] == 6_000
    assert usage["context_left_percent"] == 89
