from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bot.native_agent.event_normalizer import NormalizedNativeAgentEvent, normalize_event


NativeAgentEvent = NormalizedNativeAgentEvent


def unwrap_event(raw: dict[str, Any]) -> NativeAgentEvent | None:
    return normalize_event(raw)


def event_session_id(event: NativeAgentEvent) -> str:
    if event.session_id:
        return event.session_id
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
    if event.transport:
        return False
    event_session = event_session_id(event)
    if event_session and event_session != session_id:
        return False
    if event.directory and cwd:
        return _normalize_path_for_compare(event.directory) == _normalize_path_for_compare(cwd)
    return True


def _normalize_path_for_compare(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        normalized = str(Path(text).expanduser().resolve(strict=False))
    except Exception:
        normalized = text
    return os.path.normcase(normalized).rstrip("\\/")
