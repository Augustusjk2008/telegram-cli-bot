from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import CodexTokenUsage


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
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def read_failed_turn_usage(
    rollout_path: Path | str,
    *,
    started_at: datetime,
) -> CodexTokenUsage | None:
    """Return the current turn's usage as a cumulative rollout delta."""

    capture_started_at = started_at
    if capture_started_at.tzinfo is None:
        capture_started_at = capture_started_at.replace(tzinfo=timezone.utc)
    else:
        capture_started_at = capture_started_at.astimezone(timezone.utc)

    baseline = {field: 0 for field in _USAGE_FIELDS}
    latest: dict[str, int] | None = None
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
                usage = _total_usage(payload)
                if usage is None:
                    continue
                if target_started:
                    latest = usage
                else:
                    baseline = usage
    except OSError:
        return None

    if not target_started or latest is None:
        return None
    delta = {field: latest[field] - baseline[field] for field in _USAGE_FIELDS}
    if any(value < 0 for value in delta.values()) or not any(delta.values()):
        return None
    try:
        return CodexTokenUsage(**delta)
    except ValueError:
        return None


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


__all__ = ["read_failed_turn_usage", "resolve_failed_turn_usage"]
