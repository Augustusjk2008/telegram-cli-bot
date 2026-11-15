"""Channel-neutral final-completion notification contracts and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompletionNotification:
    alias: str
    agent_id: str = "main"
    conversation_id: str = ""
    turn_id: str = ""
    assistant_message_id: str = ""
    content: str = ""
    completion_state: str = "completed"
    context_usage: dict[str, Any] | None = None
    source_chat_id: int | None = None
    source_channel: str = ""
    source_external_id: str = ""
    endless_group_id: str = ""
    terminal_at: str = ""
    endless_completion_token: str = ""


_ACTIVE_NOTIFIERS: dict[str, dict[str, Any]] = {}


def register_channel_notifier(channel: str, notifier: Any, *, key: str = "default") -> None:
    normalized = str(channel or "").strip().lower()
    if not normalized or notifier is None:
        return
    _ACTIVE_NOTIFIERS.setdefault(normalized, {})[str(key or "default")] = notifier


def unregister_channel_notifier(
    channel: str,
    notifier: Any | None = None,
    *,
    key: str | None = None,
) -> None:
    normalized = str(channel or "").strip().lower()
    entries = _ACTIVE_NOTIFIERS.get(normalized)
    if not entries:
        return
    if key is not None:
        current = entries.get(str(key))
        if notifier is None or current is notifier:
            entries.pop(str(key), None)
    elif notifier is not None:
        for entry_key, current in list(entries.items()):
            if current is notifier:
                entries.pop(entry_key, None)
    else:
        entries.clear()
    if not entries:
        _ACTIVE_NOTIFIERS.pop(normalized, None)


def get_active_channel_notifiers(channel: str | None = None) -> list[Any]:
    if channel:
        return list(_ACTIVE_NOTIFIERS.get(str(channel).strip().lower(), {}).values())
    result: list[Any] = []
    for entries in _ACTIVE_NOTIFIERS.values():
        result.extend(entries.values())
    return result


def get_active_channel_notifier(channel: str, key: str) -> Any | None:
    return _ACTIVE_NOTIFIERS.get(str(channel or "").strip().lower(), {}).get(str(key or "default"))


def get_active_notifiers() -> list[Any]:
    return get_active_channel_notifiers()


__all__ = [
    "CompletionNotification",
    "get_active_channel_notifier",
    "get_active_channel_notifiers",
    "get_active_notifiers",
    "register_channel_notifier",
    "unregister_channel_notifier",
]
