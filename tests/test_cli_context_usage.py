import json
import os
from pathlib import Path

import pytest

import bot.web.cli_context_usage as cli_context_usage
from bot.web.native_history_locator import LocatedTranscript
from bot.web.cli_context_usage import (
    cleanup_antigravity_statusline_telemetry,
    clear_context_usage_cache,
    record_antigravity_statusline_payload,
    record_claude_context_windows,
    resolve_antigravity_statusline_usage,
    resolve_cli_context_usage,
    resolve_deepseek_context_usage,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "antigravity"


def test_deepseek_context_usage_reads_context_pressure_projection(tmp_path, monkeypatch):
    path = tmp_path / "storages" / "session_projcache" / "sessions" / "session-dsh.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "record": {
                "rows": {
                    "contextPressure": {
                        "ver": 5,
                        "seq": 12,
                        "val": {
                            "contextWindow": 1_000_000,
                            "pressureTokens": 6_000,
                            "projectedTokens": 123_456,
                        },
                    },
                },
            },
        }),
        encoding="utf-8",
    )

    result = resolve_deepseek_context_usage("session-dsh", dsh_home=tmp_path)

    assert result == {
        "provider": "deepseek",
        "source": "deepseek_context_pressure",
        "session_id": "session-dsh",
        "usage_scope": "conversation",
        "used_tokens": 123_456,
        "context_window": 1_000_000,
        "context_left_percent": 88,
        "used_display": "123K",
        "window_display": "1000K",
        "status_text": "88% context left · 123K / 1000K",
    }
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    assert resolve_cli_context_usage("deepseek", "session-dsh") == result


def test_antigravity_statusline_usage_reads_latest_valid_payload(tmp_path):
    path = tmp_path / "statusline.jsonl"
    payload = json.loads((FIXTURE_DIR / "statusline_context.json").read_text(encoding="utf-8"))
    payload["cwd"] = str(tmp_path)
    assert record_antigravity_statusline_payload(payload, path=path) is not None

    result = resolve_antigravity_statusline_usage(
        "agy-statusline-session",
        str(tmp_path),
        telemetry_path=path,
    )

    assert result is not None
    assert result["source"] == "antigravity_statusline"
    assert result["used_tokens"] == 124245
    assert result["window_display"] == "1M"
    assert result["status_text"] == "88.2% context left · 124.2K / 1M"


def test_antigravity_statusline_usage_prefers_matching_session_over_blank_bootstrap(tmp_path):
    path = tmp_path / "statusline.jsonl"
    payload = json.loads((FIXTURE_DIR / "statusline_context.json").read_text(encoding="utf-8"))
    payload["conversation_id"] = ""
    payload["context_window"]["remaining_percentage"] = 99
    payload["context_window"]["used_percentage"] = 1
    record_antigravity_statusline_payload(payload, path=path)
    payload["conversation_id"] = "agy-statusline-session"
    payload["context_window"]["remaining_percentage"] = 88.15
    payload["context_window"]["used_percentage"] = 11.85
    record_antigravity_statusline_payload(payload, path=path)

    result = resolve_antigravity_statusline_usage(
        "agy-statusline-session",
        telemetry_path=path,
    )

    assert result is not None
    assert result["context_left_percent"] == 88.15


def test_antigravity_statusline_usage_expires_and_cleans_temp_file(tmp_path):
    path = tmp_path / "statusline.jsonl"
    payload = json.loads((FIXTURE_DIR / "statusline_context.json").read_text(encoding="utf-8"))
    record_antigravity_statusline_payload(payload, path=path)
    old_time = 1_000.0
    os.utime(path, (old_time, old_time))

    assert resolve_antigravity_statusline_usage(
        "agy-statusline-session",
        telemetry_path=path,
        now=old_time + 31,
    ) is None
    assert not path.exists()


def test_antigravity_statusline_cleanup_removes_only_expired_files(tmp_path):
    fresh = tmp_path / "fresh.jsonl"
    stale = tmp_path / "stale.jsonl"
    fresh.write_text("{}\n", encoding="utf-8")
    stale.write_text("{}\n", encoding="utf-8")
    os.utime(fresh, (1000, 1000))
    os.utime(stale, (900, 900))

    assert cleanup_antigravity_statusline_telemetry(root=tmp_path, now=1000, max_age_seconds=50) == 1
    assert fresh.exists()
    assert not stale.exists()


@pytest.mark.parametrize(
    ("model", "window"),
    [
        ("claude-fable-5-2", 1_000_000),
        ("claude-mythos-5-1", 1_000_000),
        ("claude-opus-4-8[1m]", 1_000_000),
        ("opus", 1_000_000),
        ("claude-opus-4-5-20251101", 200_000),
        ("claude-sonnet-5-5", 1_000_000),
        ("claude-sonnet-4-6", 1_000_000),
        ("claude-sonnet-4-20250514", 200_000),
        ("claude-haiku-5-5", 1_000_000),
        ("claude-haiku-4-5-20251001", 200_000),
        ("claude-3-5-sonnet-20241022", 200_000),
        ("deepseek-chat", 256_000),
    ],
)
def test_claude_context_window_fallback_by_model_family(model, window):
    assert cli_context_usage._lookup_claude_context_window(model) == window


def test_claude_reported_context_window_replaces_fallback(tmp_path, monkeypatch):
    clear_context_usage_cache()
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-5",
                "usage": {"input_tokens": 10_000, "cache_read_input_tokens": 90_000, "output_tokens": 50},
            },
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_context_usage,
        "locate_claude_transcript",
        lambda session_id, cwd_hint=None: LocatedTranscript("claude", session_id, transcript),
    )

    fallback = resolve_cli_context_usage("claude", "claude-session")
    assert fallback["context_window"] == 200_000
    assert fallback["context_left_percent"] == 50

    # Claude Code keys modelUsage by the requested model, including the [1m] opt-in suffix.
    record_claude_context_windows("claude-session", {"claude-sonnet-4-5[1m]": 1_000_000, "claude-haiku-4-5": 0})
    reported = resolve_cli_context_usage("claude", "claude-session")

    assert reported["context_window"] == 1_000_000
    assert reported["context_left_percent"] == 90
    assert reported["status_text"] == "90% context left · 100k / 1m"
    clear_context_usage_cache()
