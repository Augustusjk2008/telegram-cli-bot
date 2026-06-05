from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TRANSPORT_EVENT_TYPES = {"server.connected", "server.heartbeat"}


@dataclass(frozen=True)
class NormalizedNativeAgentEvent:
    type: str
    payload: dict[str, Any]
    directory: str = ""
    raw: dict[str, Any] | None = None
    session_id: str = ""
    message_id: str = ""
    part: dict[str, Any] = field(default_factory=dict)
    delta: str = ""
    status: str = ""
    permission: dict[str, Any] = field(default_factory=dict)
    transport: bool = False


def normalize_event(raw: dict[str, Any]) -> NormalizedNativeAgentEvent | None:
    if not isinstance(raw, dict):
        return None

    directory = str(raw.get("directory") or raw.get("cwd") or "").strip()
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    event_type = _first_text(payload, properties, raw, keys=("type", "event", "name"))
    if not event_type:
        return None

    part = _first_dict(payload.get("part"), properties.get("part"))
    message = _first_dict(payload.get("message"), properties.get("message"), payload.get("info"), properties.get("info"))
    permission = _permission_payload(event_type, payload, properties)
    delta = _first_text(payload, properties, part, keys=("delta",))
    status = _first_text(payload, properties, keys=("status", "state"))
    session_id = _first_text(
        payload,
        properties,
        message,
        part,
        permission,
        keys=("sessionID", "session_id", "sessionId"),
    )
    message_id = _first_text(
        payload,
        properties,
        message,
        part,
        keys=("messageID", "message_id", "messageId", "id"),
    )

    normalized_payload = dict(payload)
    if properties and "properties" not in normalized_payload:
        normalized_payload["properties"] = properties
    for key in ("field", "partID", "part_id", "partId"):
        if key in properties and key not in normalized_payload:
            normalized_payload[key] = properties[key]
    if part and "part" not in normalized_payload:
        normalized_payload["part"] = part
    if message and "message" not in normalized_payload:
        normalized_payload["message"] = message
    if permission and "permission" not in normalized_payload:
        normalized_payload["permission"] = permission
    if delta and "delta" not in normalized_payload:
        normalized_payload["delta"] = delta
    if session_id and "sessionID" not in normalized_payload:
        normalized_payload["sessionID"] = session_id
    if message_id and "messageID" not in normalized_payload:
        normalized_payload["messageID"] = message_id

    return NormalizedNativeAgentEvent(
        type=event_type,
        payload=normalized_payload,
        directory=directory,
        raw=dict(raw),
        session_id=session_id,
        message_id=message_id,
        part=part,
        delta=delta,
        status=status,
        permission=permission,
        transport=event_type in TRANSPORT_EVENT_TYPES,
    )


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_text(*records: dict[str, Any], keys: tuple[str, ...]) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = record.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _permission_payload(event_type: str, payload: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("permission"), dict):
        return dict(payload["permission"])
    if isinstance(properties.get("permission"), dict):
        return dict(properties["permission"])
    if event_type in {"permission.updated", "permission.replied"}:
        return dict(properties or payload)
    return {}
