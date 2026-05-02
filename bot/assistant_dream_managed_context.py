from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession


@dataclass(frozen=True)
class ManagedBotDreamContext:
    text: str
    stats: dict[str, Any]


def _clip_text(value: str, *, limit: int) -> str:
    compact = str(value or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iter_managed_profiles(manager: MultiBotManager, *, current_alias: str) -> list[BotProfile]:
    current = str(current_alias or "").strip().lower()
    return [
        profile
        for alias, profile in sorted(manager.managed_profiles.items())
        if alias.strip().lower() != current and profile.enabled
    ]


def _filter_recent_history(items: list[dict[str, Any]], *, cutoff: datetime) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if (_parse_iso_datetime(str(item.get("created_at") or item.get("timestamp") or "")) or datetime.min.replace(tzinfo=UTC))
        >= cutoff
    ]


def _iter_recent_capture_records(working_dir: str, *, capture_limit: int, cutoff: datetime) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    captures_dir = Path(working_dir) / ".assistant" / "inbox" / "captures"
    if not captures_dir.exists():
        return items
    for path in sorted(captures_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created_at = _parse_iso_datetime(str(payload.get("created_at") or ""))
        if created_at is None or created_at < cutoff:
            continue
        items.append(payload)
        if len(items) >= capture_limit:
            break
    items.reverse()
    return items


def _format_history_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        role = str(item.get("role") or "unknown").strip() or "unknown"
        created_at = str(item.get("created_at") or item.get("timestamp") or "").strip()
        content = _clip_text(str(item.get("content") or ""), limit=320)
        if not content:
            continue
        lines.append(f"- [{created_at}] {role}: {content}")
    return "\n".join(lines)


def _format_capture_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        created_at = str(item.get("created_at") or "").strip()
        user_text = _clip_text(str(item.get("user_text") or ""), limit=220)
        assistant_text = _clip_text(str(item.get("assistant_text") or ""), limit=320)
        lines.append(f"- [{created_at}] user: {user_text}")
        lines.append(f"  assistant: {assistant_text}")
    return "\n".join(lines)


def collect_managed_bot_dream_context(
    manager: MultiBotManager,
    *,
    current_alias: str,
    context_user_id: int,
    lookback_hours: int,
    history_limit: int,
    capture_limit: int,
    session_resolver: Callable[[str, int], UserSession],
    history_service_factory: Callable[[UserSession], Any],
) -> ManagedBotDreamContext:
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, int(lookback_hours)))
    per_bot_history_limit = max(1, min(int(history_limit), 8))
    per_bot_capture_limit = max(1, min(int(capture_limit), 6))

    lines: list[str] = []
    history_count = 0
    capture_count = 0
    error_count = 0
    profiles = _iter_managed_profiles(manager, current_alias=current_alias)

    for profile in profiles:
        lines.append(f"### {profile.alias}")
        lines.append(f"- mode: {profile.bot_mode}, cli_type: {profile.cli_type}, working_dir: {profile.working_dir}")
        try:
            session = session_resolver(profile.alias, context_user_id)
            history_service = history_service_factory(session)
            raw_history = history_service.list_history(profile, session, limit=per_bot_history_limit)
            recent_history = _filter_recent_history(list(raw_history), cutoff=cutoff)
            recent_captures = _iter_recent_capture_records(
                profile.working_dir,
                capture_limit=per_bot_capture_limit,
                cutoff=cutoff,
            )
            history_count += len(recent_history)
            capture_count += len(recent_captures)
            lines.append(f"- history_count: {len(recent_history)}")
            lines.append(f"- capture_count: {len(recent_captures)}")
            lines.append("#### 最近聊天")
            lines.append(_format_history_items(recent_history) or "- 无")
            lines.append("#### 最近 captures")
            lines.append(_format_capture_items(recent_captures) or "- 无")
        except Exception as exc:
            error_count += 1
            lines.append(f"- error: {_clip_text(str(exc), limit=220)}")
        lines.append("")

    return ManagedBotDreamContext(
        text="\n".join(lines).strip(),
        stats={
            "managed_bot_count": len(profiles),
            "managed_history_count": history_count,
            "managed_capture_count": capture_count,
            "managed_error_count": error_count,
        },
    )
