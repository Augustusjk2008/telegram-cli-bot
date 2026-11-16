"""Structured schedule triggers and next-fire computation.

Supported triggers (stored as JSON on the schedule):

- ``{"type": "daily", "time": "HH:MM", "weekdays": [1..7]}`` with ISO weekdays
  (1 = Monday). All seven weekdays mean "every day".
- ``{"type": "interval", "minutes": N, "anchor": ISO}``: fires at
  ``anchor + k * N minutes``, so the cadence never drifts.
- ``{"type": "once", "at": ISO}``: fires a single time.

Daily times are wall-clock times in the schedule timezone. ``zoneinfo`` maps a
time inside a DST gap forward (the pre-transition offset is applied) and picks
the first occurrence of an ambiguous time (``fold=0``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 7 * 24 * 60
TRIGGER_TYPES = ("daily", "interval", "once")
ALL_WEEKDAYS = (1, 2, 3, 4, 5, 6, 7)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class TriggerError(ValueError):
    """Raised when a trigger or timezone is invalid; the message is user-facing."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso_datetime(value: Any, tz: ZoneInfo | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise TriggerError("缺少时间")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError as exc:
        raise TriggerError(f"时间格式无效：{text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz or timezone.utc)
    return parsed


def resolve_timezone(name: Any) -> ZoneInfo:
    text = str(name or "").strip()
    if not text:
        raise TriggerError("缺少时区")
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TriggerError(f"未知时区：{text}") from exc


def detect_default_timezone() -> str:
    """Best-effort IANA name of the host timezone, falling back to a fixed offset."""
    candidates: list[str] = []
    env_tz = str(os.environ.get("TZ") or "").strip().lstrip(":")
    if env_tz:
        candidates.append(env_tz)
    try:
        link = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in link:
            candidates.append(link.split(marker, 1)[1])
    except OSError:
        pass
    try:
        with open("/etc/timezone", encoding="utf-8") as handle:
            candidates.append(handle.read().strip())
    except OSError:
        pass
    for candidate in candidates:
        try:
            ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        return candidate
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    seconds = int(offset.total_seconds())
    if seconds == 0 or seconds % 3600:
        return "UTC"
    hours = seconds // 3600
    # POSIX-style Etc names invert the sign: Etc/GMT-8 is UTC+08:00.
    return f"Etc/GMT{-hours:+d}"


def normalize_trigger(raw: Any, tz: ZoneInfo, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate and normalize a trigger payload. Raises :class:`TriggerError`."""
    if not isinstance(raw, dict):
        raise TriggerError("触发规则格式无效")
    trigger_type = str(raw.get("type") or "").strip().lower()
    current = now or utc_now()
    if trigger_type == "daily":
        time_text = str(raw.get("time") or "").strip()
        if not _TIME_RE.match(time_text):
            raise TriggerError("每日时间需为 HH:MM 格式")
        weekdays_raw = raw.get("weekdays")
        if weekdays_raw is None:
            weekdays = list(ALL_WEEKDAYS)
        else:
            if not isinstance(weekdays_raw, list):
                raise TriggerError("星期需为列表")
            try:
                weekdays = sorted({int(day) for day in weekdays_raw})
            except (TypeError, ValueError) as exc:
                raise TriggerError("星期需为 1-7 的整数") from exc
            if not weekdays or any(day < 1 or day > 7 for day in weekdays):
                raise TriggerError("至少选择一天，星期需为 1-7")
        return {"type": "daily", "time": time_text, "weekdays": weekdays}
    if trigger_type == "interval":
        try:
            minutes = int(raw.get("minutes"))
        except (TypeError, ValueError) as exc:
            raise TriggerError("间隔分钟数需为整数") from exc
        if minutes < MIN_INTERVAL_MINUTES or minutes > MAX_INTERVAL_MINUTES:
            raise TriggerError(f"间隔需在 {MIN_INTERVAL_MINUTES} 到 {MAX_INTERVAL_MINUTES} 分钟之间")
        anchor_raw = raw.get("anchor")
        anchor = parse_iso_datetime(anchor_raw, tz) if str(anchor_raw or "").strip() else current
        return {
            "type": "interval",
            "minutes": minutes,
            "anchor": anchor.astimezone(tz).isoformat(timespec="seconds"),
        }
    if trigger_type == "once":
        at = parse_iso_datetime(raw.get("at"), tz)
        return {"type": "once", "at": at.astimezone(tz).isoformat(timespec="seconds")}
    raise TriggerError("触发类型需为 daily、interval 或 once")


def next_fire(trigger: dict[str, Any], tz: ZoneInfo, after: datetime) -> datetime | None:
    """Return the first fire time strictly after ``after`` (UTC), or ``None``."""
    after_utc = after.astimezone(timezone.utc)
    trigger_type = trigger.get("type")
    if trigger_type == "once":
        at = parse_iso_datetime(trigger.get("at"), tz).astimezone(timezone.utc)
        return at if at > after_utc else None
    if trigger_type == "interval":
        step = timedelta(minutes=int(trigger["minutes"]))
        anchor = parse_iso_datetime(trigger.get("anchor"), tz).astimezone(timezone.utc)
        if anchor > after_utc:
            return anchor
        elapsed_steps = (after_utc - anchor) // step + 1
        return anchor + step * elapsed_steps
    if trigger_type == "daily":
        hour, minute = (int(part) for part in str(trigger["time"]).split(":"))
        weekdays = set(trigger.get("weekdays") or ALL_WEEKDAYS)
        local_date = after_utc.astimezone(tz).date()
        # Eight days cover every weekday plus the case where today's slot passed.
        for offset in range(9):
            day = local_date + timedelta(days=offset)
            if day.isoweekday() not in weekdays:
                continue
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)
            if candidate > after_utc:
                return candidate
        return None
    raise TriggerError("未知触发类型")


__all__ = [
    "ALL_WEEKDAYS",
    "MAX_INTERVAL_MINUTES",
    "MIN_INTERVAL_MINUTES",
    "TRIGGER_TYPES",
    "TriggerError",
    "detect_default_timezone",
    "next_fire",
    "normalize_trigger",
    "parse_iso_datetime",
    "resolve_timezone",
    "to_utc_iso",
    "utc_now",
]
