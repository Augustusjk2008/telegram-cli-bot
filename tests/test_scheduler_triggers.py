from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.scheduler.triggers import TriggerError, next_fire, normalize_trigger, resolve_timezone


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_daily_weekday_mask_skips_to_next_allowed_day() -> None:
    tz = resolve_timezone("Asia/Shanghai")
    trigger = normalize_trigger({"type": "daily", "time": "09:00", "weekdays": [5, 1, 2, 3, 4]}, tz)

    assert trigger["weekdays"] == [1, 2, 3, 4, 5]
    # Friday 2026-11-20 10:00 local (02:00 UTC) -> Monday 2026-11-23 09:00 local.
    assert next_fire(trigger, tz, _utc(2026, 11, 20, 2, 0)) == _utc(2026, 11, 23, 1, 0)
    # Strictly after: exactly at the slot moves to the next weekday.
    assert next_fire(trigger, tz, _utc(2026, 11, 23, 1, 0)) == _utc(2026, 11, 24, 1, 0)


def test_daily_dst_gap_moves_forward_and_overlap_uses_first_occurrence() -> None:
    tz = resolve_timezone("America/New_York")
    gap = {"type": "daily", "time": "02:30", "weekdays": [1, 2, 3, 4, 5, 6, 7]}
    # 2026-03-08 02:30 does not exist; it fires at 03:30 EDT (07:30 UTC).
    assert next_fire(gap, tz, _utc(2026, 3, 8, 5, 0)) == _utc(2026, 3, 8, 7, 30)

    overlap = {"type": "daily", "time": "01:30", "weekdays": [1, 2, 3, 4, 5, 6, 7]}
    # 2026-11-01 01:30 happens twice; the first (EDT, 05:30 UTC) is used.
    assert next_fire(overlap, tz, _utc(2026, 11, 1, 4, 0)) == _utc(2026, 11, 1, 5, 30)


def test_interval_is_anchored_and_strictly_after() -> None:
    tz = resolve_timezone("UTC")
    trigger = normalize_trigger({"type": "interval", "minutes": 60, "anchor": "2026-11-16T09:00:00+00:00"}, tz)

    assert next_fire(trigger, tz, _utc(2026, 11, 16, 8, 0)) == _utc(2026, 11, 16, 9, 0)
    assert next_fire(trigger, tz, _utc(2026, 11, 16, 10, 0)) == _utc(2026, 11, 16, 11, 0)
    assert next_fire(trigger, tz, _utc(2026, 11, 16, 10, 30)) == _utc(2026, 11, 16, 11, 0)


def test_once_accepts_naive_local_time_and_expires() -> None:
    tz = resolve_timezone("Asia/Shanghai")
    trigger = normalize_trigger({"type": "once", "at": "2026-11-17T09:00"}, tz)

    assert trigger["at"] == "2026-11-17T09:00:00+08:00"
    assert next_fire(trigger, tz, _utc(2026, 11, 17, 0, 59)) == _utc(2026, 11, 17, 1, 0)
    assert next_fire(trigger, tz, _utc(2026, 11, 17, 1, 0)) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "interval", "minutes": 4},
        {"type": "daily", "time": "24:00"},
        {"type": "daily", "time": "09:00", "weekdays": []},
        {"type": "daily", "time": "09:00", "weekdays": [8]},
        {"type": "cron", "expr": "* * * * *"},
        "daily",
    ],
)
def test_invalid_triggers_are_rejected(raw) -> None:
    with pytest.raises(TriggerError):
        normalize_trigger(raw, resolve_timezone("UTC"))


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(TriggerError):
        resolve_timezone("Mars/Olympus")
