from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import (
    GENERAL_CODEX_RATE_LIMIT_ID,
    KNOWN_CODEX_RATE_LIMIT_IDS,
    SECONDARY_CODEX_RATE_LIMIT_ID,
    SQLITE_INT64_MAX,
    CodexRateLimitSample,
)


@dataclass(frozen=True, slots=True)
class TurnRateLimitResolution:
    """The usable quota sample or a signal to refresh the general bucket."""

    sample: CodexRateLimitSample | None = None
    refresh_general: bool = False


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


def _capture_started_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _scan_turn_rate_limit(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> TurnRateLimitResolution | None:
    capture_started_at = _capture_started_at(started_at)
    latest: TurnRateLimitResolution | None = None
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
                    resolution = _rate_limit_resolution(event_time, payload)
                    if resolution is not None:
                        latest = resolution
    except OSError:
        return None
    return latest if target_started else None


def _codex_rate_limit_sample(
    event_time: datetime | None,
    rate_limits: Mapping[str, Any],
    *,
    limit_id: str = GENERAL_CODEX_RATE_LIMIT_ID,
) -> CodexRateLimitSample | None:
    if event_time is None:
        return None
    window_name = "secondary" if limit_id == SECONDARY_CODEX_RATE_LIMIT_ID else "primary"
    window = rate_limits.get(window_name)
    if not isinstance(window, Mapping):
        return None
    used_percent = window.get("used_percent")
    window_minutes = window.get("window_minutes")
    resets_at = window.get("resets_at")
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
            limit_id=limit_id,
        )
    except (OSError, OverflowError, ValueError):
        return None


def _rate_limit_resolution(
    event_time: datetime | None,
    payload: Mapping[str, Any],
) -> TurnRateLimitResolution | None:
    if payload.get("type") != "token_count" or event_time is None:
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, Mapping):
        return None
    limit_id = rate_limits.get("limit_id")
    if limit_id not in KNOWN_CODEX_RATE_LIMIT_IDS:
        return None
    sample = _codex_rate_limit_sample(event_time, rate_limits, limit_id=limit_id)
    if sample is None:
        return None
    return TurnRateLimitResolution(
        sample=sample,
        refresh_general=limit_id == SECONDARY_CODEX_RATE_LIMIT_ID,
    )


def read_turn_rate_limit(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> CodexRateLimitSample | None:
    resolution = _scan_turn_rate_limit(rollout_path, started_at=started_at)
    return resolution.sample if resolution is not None else None


def read_turn_rate_limit_resolution(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> TurnRateLimitResolution | None:
    return _scan_turn_rate_limit(rollout_path, started_at=started_at)


def resolve_turn_rate_limit(
    *,
    session_id: str,
    started_at: datetime,
    codex_home: Path,
) -> CodexRateLimitSample | None:
    resolution = resolve_turn_rate_limit_resolution(
        session_id=session_id,
        started_at=started_at,
        codex_home=codex_home,
    )
    return resolution.sample if resolution is not None else None


def resolve_turn_rate_limit_resolution(
    *,
    session_id: str,
    started_at: datetime,
    codex_home: Path,
) -> TurnRateLimitResolution | None:
    from bot.web.native_history_locator import locate_codex_transcript

    located = locate_codex_transcript(session_id, codex_home=codex_home)
    if located is None:
        return None
    return read_turn_rate_limit_resolution(located.path, started_at=started_at)


__all__ = [
    "TurnRateLimitResolution",
    "read_turn_rate_limit",
    "read_turn_rate_limit_resolution",
    "resolve_turn_rate_limit",
    "resolve_turn_rate_limit_resolution",
]
