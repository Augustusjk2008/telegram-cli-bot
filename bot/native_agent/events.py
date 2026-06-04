from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NativeAgentEvent:
    type: str
    payload: dict[str, Any]
    directory: str = ""
    raw: dict[str, Any] | None = None


def unwrap_event(raw: dict[str, Any]) -> NativeAgentEvent | None:
    if not isinstance(raw, dict):
        return None
    directory = str(raw.get("directory") or raw.get("cwd") or "").strip()
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        payload = raw
    event_type = (
        payload.get("type")
        or payload.get("event")
        or payload.get("name")
        or raw.get("type")
        or raw.get("event")
        or ""
    )
    normalized_type = str(event_type or "").strip()
    if not normalized_type:
        return None
    return NativeAgentEvent(
        type=normalized_type,
        payload=dict(payload),
        directory=directory,
        raw=dict(raw),
    )


def event_session_id(event: NativeAgentEvent) -> str:
    payload = event.payload
    for key in ("sessionID", "session_id", "sessionId"):
        value = payload.get(key)
        if value:
            return str(value)
    properties = payload.get("properties")
    if isinstance(properties, dict):
        for key in ("sessionID", "session_id", "sessionId"):
            value = properties.get(key)
            if value:
                return str(value)
    message = payload.get("message")
    if isinstance(message, dict):
        for key in ("sessionID", "session_id", "sessionId"):
            value = message.get(key)
            if value:
                return str(value)
    part = payload.get("part")
    if isinstance(part, dict):
        for key in ("sessionID", "session_id", "sessionId"):
            value = part.get(key)
            if value:
                return str(value)
    return ""


def is_relevant_event(event: NativeAgentEvent, *, session_id: str, cwd: str) -> bool:
    event_session = event_session_id(event)
    if event_session and event_session != session_id:
        return False
    if event.directory and cwd:
        return event.directory == cwd
    return True
