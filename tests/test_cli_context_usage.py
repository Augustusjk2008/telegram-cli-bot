import json
import os
from pathlib import Path

from bot.web.cli_context_usage import (
    cleanup_antigravity_statusline_telemetry,
    record_antigravity_statusline_payload,
    resolve_antigravity_statusline_usage,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "antigravity"


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
