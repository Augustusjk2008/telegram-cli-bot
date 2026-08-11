from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import SQLITE_INT64_MAX, CodexRateLimitSample, CodexTokenUsage


_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _payload(line: str) -> tuple[datetime | None, Mapping[str, Any]] | None:
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, Mapping):
        return None
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    return _timestamp(event.get("timestamp")), payload


def _total_usage(payload: Mapping[str, Any]) -> dict[str, int] | None:
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, Mapping):
        return None
    raw_usage = info.get("total_token_usage")
    if not isinstance(raw_usage, Mapping):
        return None
    values: dict[str, int] = {}
    for field in _USAGE_FIELDS:
        value = raw_usage.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        values[field] = value
    if values["cached_input_tokens"] > values["input_tokens"]:
        return None
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return None
    return values


def _capture_started_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _scan_turn(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> tuple[
    dict[str, int],
    dict[str, int] | None,
    CodexRateLimitSample | None,
] | None:
    capture_started_at = _capture_started_at(started_at)
    baseline = {field: 0 for field in _USAGE_FIELDS}
    latest_usage: dict[str, int] | None = None
    latest_rate_limit: CodexRateLimitSample | None = None
    target_started = False
    try:
        with Path(rollout_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = _payload(line)
                if parsed is None:
                    continue
                event_time, payload = parsed
                if payload.get("type") == "task_started":
                    if target_started:
                        break
                    if event_time is not None and event_time >= capture_started_at:
                        target_started = True
                    continue
                if target_started:
                    usage = _total_usage(payload)
                    if usage is not None:
                        latest_usage = usage
                    rate_limit = _rate_limit_sample(event_time, payload)
                    if rate_limit is not None:
                        latest_rate_limit = rate_limit
                    continue
                usage = _total_usage(payload)
                if usage is not None:
                    baseline = usage
    except OSError:
        return None
    if not target_started:
        return None
    return baseline, latest_usage, latest_rate_limit


def _rate_limit_sample(
    event_time: datetime | None,
    payload: Mapping[str, Any],
) -> CodexRateLimitSample | None:
    if payload.get("type") != "token_count" or event_time is None:
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, Mapping) or rate_limits.get("limit_id") != "codex":
        return None
    primary = rate_limits.get("primary")
    if not isinstance(primary, Mapping):
        return None
    used_percent = primary.get("used_percent")
    window_minutes = primary.get("window_minutes")
    resets_at = primary.get("resets_at")
    if (
        isinstance(used_percent, bool)
        or not isinstance(used_percent, (int, float))
        or (isinstance(used_percent, float) and not math.isfinite(used_percent))
        or not 0 <= used_percent <= 100
    ):
        return None
    if (
        isinstance(window_minutes, bool)
        or not isinstance(window_minutes, int)
        or window_minutes <= 0
        or window_minutes > SQLITE_INT64_MAX
    ):
        return None
    if isinstance(resets_at, bool) or not isinstance(resets_at, int) or resets_at < 0:
        return None
    try:
        reset_time = datetime.fromtimestamp(resets_at, timezone.utc)
        return CodexRateLimitSample(
            sampled_at=event_time,
            used_percent=float(used_percent),
            window_minutes=window_minutes,
            resets_at=reset_time,
            plan_type=rate_limits.get("plan_type"),
        )
    except (OSError, OverflowError, ValueError):
        return None


def read_failed_turn_usage(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> CodexTokenUsage | None:
    """Return the current turn's usage as a cumulative rollout delta."""

    scanned = _scan_turn(rollout_path, started_at=started_at)
    if scanned is None:
        return None
    baseline, latest, _rate_limit = scanned
    if latest is None:
        return None
    delta = {field: latest[field] - baseline[field] for field in _USAGE_FIELDS}
    if any(value < 0 for value in delta.values()) or not any(delta.values()):
        return None
    try:
        return CodexTokenUsage(**delta)
    except ValueError:
        return None


def read_turn_rate_limit(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> CodexRateLimitSample | None:
    scanned = _scan_turn(rollout_path, started_at=started_at)
    if scanned is None:
        return None
    return scanned[2]


def resolve_failed_turn_usage(
    *,
    session_id: str,
    started_at: datetime,
    codex_home: Path,
) -> CodexTokenUsage | None:
    from bot.web.native_history_locator import locate_codex_transcript

    located = locate_codex_transcript(session_id, codex_home=codex_home)
    if located is None:
        return None
    return read_failed_turn_usage(located.path, started_at=started_at)


def resolve_turn_rate_limit(
    *,
    session_id: str,
    started_at: datetime,
    codex_home: Path,
) -> CodexRateLimitSample | None:
    from bot.web.native_history_locator import locate_codex_transcript

    located = locate_codex_transcript(session_id, codex_home=codex_home)
    if located is None:
        return None
    return read_turn_rate_limit(located.path, started_at=started_at)


__all__ = [
    "read_failed_turn_usage",
    "read_turn_rate_limit",
    "resolve_failed_turn_usage",
    "resolve_turn_rate_limit",
]
