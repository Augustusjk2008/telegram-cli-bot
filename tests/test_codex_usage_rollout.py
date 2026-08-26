from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot.codex_usage.models import (
    GENERAL_CODEX_RATE_LIMIT_ID,
    SECONDARY_CODEX_RATE_LIMIT_ID,
)
from bot.codex_usage.rollout import (
    read_turn_rate_limit,
    read_turn_rate_limit_resolution,
)


def _event(timestamp: str, payload: dict[str, object]) -> str:
    return json.dumps({"timestamp": timestamp, "payload": payload})


def _rate_limit_payload(
    *,
    limit_id: str = GENERAL_CODEX_RATE_LIMIT_ID,
    used_percent: object = 42,
    window_minutes: object = 10_080,
    resets_at: object = 1_800_000_000,
) -> dict[str, object]:
    window_name = "secondary" if limit_id == SECONDARY_CODEX_RATE_LIMIT_ID else "primary"
    return {
        "type": "token_count",
        "rate_limits": {
            "limit_id": limit_id,
            "plan_type": "pro",
            window_name: {
                "used_percent": used_percent,
                "window_minutes": window_minutes,
                "resets_at": resets_at,
            },
        },
    }


def test_read_turn_rate_limit_uses_target_turn_only(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "\n".join(
            [
                _event("2026-08-10T07:59:00Z", {"type": "task_started"}),
                _event("2026-08-10T07:59:01Z", _rate_limit_payload(used_percent=10)),
                _event("2026-08-10T08:00:01Z", {"type": "task_started"}),
                _event("2026-08-10T08:00:02Z", _rate_limit_payload(used_percent=35)),
                _event("2026-08-10T08:00:03Z", _rate_limit_payload(used_percent=40)),
                _event("2026-08-10T08:01:00Z", {"type": "task_started"}),
                _event("2026-08-10T08:01:01Z", _rate_limit_payload(used_percent=90)),
            ]
        ),
        encoding="utf-8",
    )

    sample = read_turn_rate_limit(
        rollout,
        started_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
    )

    assert sample is not None
    assert sample.used_percent == 40
    assert sample.limit_id == GENERAL_CODEX_RATE_LIMIT_ID


def test_secondary_bucket_uses_secondary_window_and_requests_general_refresh(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "\n".join(
            [
                _event("2026-08-10T08:00:01Z", {"type": "task_started"}),
                _event(
                    "2026-08-10T08:00:02Z",
                    _rate_limit_payload(
                        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
                        used_percent=64,
                    ),
                ),
            ]
        ),
        encoding="utf-8",
    )

    resolution = read_turn_rate_limit_resolution(
        rollout,
        started_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
    )

    assert resolution is not None
    assert resolution.refresh_general is True
    assert resolution.sample is not None
    assert resolution.sample.limit_id == SECONDARY_CODEX_RATE_LIMIT_ID
    assert resolution.sample.used_percent == 64


def test_invalid_quota_values_are_ignored(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "\n".join(
            [
                _event("2026-08-10T08:00:01Z", {"type": "task_started"}),
                _event("2026-08-10T08:00:02Z", _rate_limit_payload(used_percent=101)),
            ]
        ),
        encoding="utf-8",
    )

    assert read_turn_rate_limit(
        rollout,
        started_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
    ) is None


def test_missing_rollout_returns_none(tmp_path: Path) -> None:
    assert read_turn_rate_limit(
        tmp_path / "missing.jsonl",
        started_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
    ) is None
