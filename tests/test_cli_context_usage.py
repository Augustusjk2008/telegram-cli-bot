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
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

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
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [{"type": "event_msg", "payload": {"type": "agent_message"}}])
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_codex_transcript",
        lambda session_id: LocatedTranscript("codex", session_id, transcript),
    )

    assert resolve_cli_context_usage("codex", "thread-1") is None


def test_resolve_codex_context_usage_reuses_cache_until_transcript_changes(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()
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
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_codex_transcript",
        lambda session_id: LocatedTranscript("codex", session_id, transcript),
    )

    assert resolve_cli_context_usage("codex", "thread-1")["used_tokens"] == 32000
    assert resolve_cli_context_usage("codex", "thread-1")["used_tokens"] == 32000

    _write_jsonl(
        transcript,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"total_tokens": 64000},
                        "model_context_window": 258400,
                    },
                },
            },
        ],
    )

    assert resolve_cli_context_usage("codex", "thread-1")["used_tokens"] == 64000


def test_resolve_codex_context_usage_reads_tail_without_full_text_read(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "session.jsonl"
    prefix = [
        {"type": "event_msg", "payload": {"type": "agent_message", "text": f"line-{index}"}}
        for index in range(400)
    ]
    _write_jsonl(
        transcript,
        [
            *prefix,
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"total_tokens": 76593},
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

    original_read_text = Path.read_text

    def fail_read_text(path: Path, *args, **kwargs):
        if path == transcript:
            raise AssertionError("full transcript read not allowed")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    usage = resolve_cli_context_usage("codex", "thread-1")

    assert usage is not None
    assert usage["used_tokens"] == 76593


def test_resolve_cli_context_usage_ignores_unknown_and_kimi():
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    assert resolve_cli_context_usage("kimi", "thread-1") is None
    assert resolve_cli_context_usage("unknown", "thread-1") is None


def test_resolve_codex_context_usage_returns_none_when_session_missing(monkeypatch):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    monkeypatch.setattr("bot.web.cli_context_usage.locate_codex_transcript", lambda session_id: None)

    assert resolve_cli_context_usage("codex", "missing") is None


def test_resolve_claude_context_usage_reads_latest_context_meta(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "user",
                "isMeta": True,
                "message": {
                    "role": "user",
                    "content": "## Context Usage\n\n**Model:** claude-opus-4-7[1m]\n**Tokens:** 12.0k / 1m (1%)\n\n| Free space | 988.0k | 98.8% |",
                },
                "sessionId": "claude-1",
            },
            {
                "type": "user",
                "isMeta": True,
                "message": {
                    "role": "user",
                    "content": "## Context Usage\n\n**Model:** claude-opus-4-7[1m]\n**Tokens:** 80.1k / 1m (8%)\n\n### Estimated usage by category\n\n| Category | Tokens | Percentage |\n|----------|--------|------------|\n| Skills | 7.2k | 0.7% |\n| Messages | 72.9k | 7.3% |\n| Free space | 919.9k | 92.0% |\n",
                },
                "sessionId": "claude-1",
            },
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-1", cwd_hint=str(tmp_path))

    assert usage == {
        "provider": "claude",
        "source": "claude_context_command",
        "session_id": "claude-1",
        "used_tokens": 80100,
        "context_window": 1000000,
        "context_left_percent": 92,
        "used_display": "80.1k",
        "window_display": "1m",
        "status_text": "92% context left · 80.1k / 1m",
    }


def test_resolve_claude_context_usage_reads_context_stdout(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<command-name>/context</command-name>",
                "sessionId": "claude-1",
            },
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<local-command-stdout>\u001b[1mContext Usage\u001b[22m\n80.1k/1m tokens (8%)\nFree space: 919.9k (92.0%)</local-command-stdout>",
                "sessionId": "claude-1",
            },
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-1", cwd_hint=str(tmp_path))

    assert usage["source"] == "claude_context_command"
    assert usage["used_tokens"] == 80100
    assert usage["context_window"] == 1000000
    assert usage["context_left_percent"] == 92
    assert usage["status_text"] == "92% context left · 80.1k / 1m"


def test_resolve_claude_context_usage_keeps_real_200k_context_window(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<command-name>/context</command-name>",
                "sessionId": "claude-1",
            },
            {
                "type": "system",
                "subtype": "local_command",
                "content": "<local-command-stdout>Context Usage\n120k/200k tokens (60%)\nFree space: 80k (40.0%)</local-command-stdout>",
                "sessionId": "claude-1",
            },
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-1", cwd_hint=str(tmp_path))

    assert usage["source"] == "claude_context_command"
    assert usage["used_tokens"] == 120000
    assert usage["context_window"] == 200000
    assert usage["context_left_percent"] == 40
    assert usage["window_display"] == "200k"
    assert usage["status_text"] == "40% context left · 120k / 200k"


def test_resolve_claude_context_usage_falls_back_to_known_message_model(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "opus[1m]",
                    "usage": {
                        "input_tokens": 98809,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "sessionId": "claude-1",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-7[1m]",
                    "usage": {
                        "input_tokens": 358148,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "sessionId": "claude-1",
            },
        ],
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
        "used_tokens": 358148,
        "context_window": 1000000,
        "context_left_percent": 64,
        "used_display": "358.1k",
        "window_display": "1m",
        "status_text": "64% context left · 358.1k / 1m",
    }


def test_resolve_claude_context_usage_falls_back_to_default_256k_window(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-future-unknown",
                    "usage": {
                        "input_tokens": 358148,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "sessionId": "claude-1",
            },
        ],
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
        "used_tokens": 358148,
        "context_window": 256000,
        "context_left_percent": 0,
        "used_display": "358.1k",
        "window_display": "256k",
        "status_text": "0% context left · 358.1k / 256k",
    }


def test_resolve_claude_context_usage_uses_256k_for_non_opus_47_model(monkeypatch, tmp_path: Path):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    transcript = tmp_path / "claude-session.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "usage": {
                        "input_tokens": 128000,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "sessionId": "claude-1",
            },
        ],
    )
    monkeypatch.setattr(
        "bot.web.cli_context_usage.locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript, cwd_hint),
    )

    usage = resolve_cli_context_usage("claude", "claude-1", cwd_hint=str(tmp_path))

    assert usage["context_window"] == 256000
    assert usage["context_left_percent"] == 50
    assert usage["window_display"] == "256k"
    assert usage["status_text"] == "50% context left · 128k / 256k"


def test_resolve_claude_context_usage_returns_none_when_session_missing(monkeypatch):
    from bot.web.cli_context_usage import clear_context_usage_cache, resolve_cli_context_usage

    clear_context_usage_cache()

    monkeypatch.setattr("bot.web.cli_context_usage.locate_claude_transcript", lambda session_id, cwd_hint=None: None)

    assert resolve_cli_context_usage("claude", "missing", cwd_hint="C:\\repo") is None
