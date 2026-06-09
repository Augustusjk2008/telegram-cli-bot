from __future__ import annotations

import json
from typing import Any


def run_json_to_events(
    raw: dict[str, Any],
    *,
    cwd: str = "",
    fallback_session_id: str = "",
    assistant_message_id: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    raw_type = str(raw.get("type") or raw.get("event") or raw.get("name") or "").strip()
    session_id = extract_session_id(raw) or fallback_session_id
    message_id = _message_id(raw) or str(assistant_message_id or "").strip() or "msg_opencode_run_assistant"
    directory = str(raw.get("directory") or raw.get("cwd") or cwd or "").strip()

    if raw_type == "text" and isinstance(raw.get("part"), dict):
        part = _normalize_text_part(raw["part"], raw, message_id=message_id, session_id=session_id)
        return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, part=part, message_id=message_id)]

    if raw_type == "text":
        text = _value_text(raw.get("delta") or raw.get("text") or raw.get("content") or raw.get("message"))
        if text:
            part = {
                "id": str(raw.get("partID") or raw.get("part_id") or raw.get("partId") or "run-text"),
                "type": "text",
                "delta": text,
                "messageID": message_id,
                "sessionID": session_id,
            }
            return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, part=part, message_id=message_id)]

    part = raw.get("part")
    if isinstance(part, dict) and _part_is_tool(part):
        return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, part={**part, "messageID": _message_id(part) or message_id, "sessionID": session_id}, message_id=message_id)]

    if raw_type in {"step_finish", "step-finish", "step.finish"}:
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        if not message:
            message = {
                "id": message_id,
                "role": "assistant",
                "finish": "stop",
                "time": {"completed": raw.get("time") or raw.get("completed_at") or True},
            }
        message.setdefault("id", message_id)
        message.setdefault("role", "assistant")
        message.setdefault("finish", "stop")
        tokens = extract_step_finish_usage(raw)
        if tokens:
            message.setdefault("tokens", tokens)
        return [
            _wrap_event("message.updated", raw, session_id=session_id, directory=directory, message=message, message_id=message_id),
            _wrap_event("session.idle", raw, session_id=session_id, directory=directory, message_id=message_id),
        ]

    if raw_type in {"permission", "permission.updated", "permission.requested"} or isinstance(raw.get("permission"), dict):
        permission = raw.get("permission") if isinstance(raw.get("permission"), dict) else raw
        return [_wrap_event("permission.updated", raw, session_id=session_id, directory=directory, permission=permission, message_id=message_id)]

    summary = _unknown_summary(raw)
    if not summary:
        return []
    return [
        {
            "directory": directory,
            "payload": {
                "type": f"run.{raw_type or 'event'}",
                "sessionID": session_id,
                "summary": summary,
                "raw": raw,
            },
        }
    ]


def extract_session_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("sessionID", "session_id", "sessionId", "id"):
            value = record.get(key)
            if value and (key != "id" or str(raw.get("type") or "").startswith("session")):
                return str(value)
    return ""


def extract_step_finish_usage(raw: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        raw.get("tokens"),
        raw.get("usage"),
        raw.get("tokenUsage"),
        raw.get("token_usage"),
    ]
    cost = raw.get("cost")
    for item in candidates:
        if isinstance(item, dict):
            usage = dict(item)
            if cost is not None:
                usage.setdefault("cost", cost)
            return usage
    return {}


def _wrap_event(
    event_type: str,
    raw: dict[str, Any],
    *,
    session_id: str,
    directory: str,
    message_id: str = "",
    part: dict[str, Any] | None = None,
    message: dict[str, Any] | None = None,
    permission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "sessionID": session_id,
        "raw": raw,
    }
    if message_id:
        payload["messageID"] = message_id
    if part is not None:
        payload["part"] = part
    if message is not None:
        payload["message"] = message
    if permission is not None:
        payload["permission"] = permission
    return {"directory": directory, "payload": payload}


def _candidate_records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    records = [raw]
    for key in ("session", "message", "part", "properties"):
        value = raw.get(key)
        if isinstance(value, dict):
            records.append(value)
    return records


def _message_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("messageID", "message_id", "messageId", "id"):
            value = record.get(key)
            if value and key != "id":
                return str(value)
    message = raw.get("message")
    if isinstance(message, dict):
        value = message.get("id")
        if value:
            return str(value)
    return ""


def _normalize_text_part(part: dict[str, Any], raw: dict[str, Any], *, message_id: str, session_id: str) -> dict[str, Any]:
    normalized = dict(part)
    normalized.setdefault("id", str(raw.get("partID") or raw.get("part_id") or raw.get("partId") or "run-text"))
    normalized.setdefault("type", "text")
    if "delta" not in normalized:
        text = _value_text(normalized.get("text") or normalized.get("content") or raw.get("delta") or raw.get("text"))
        if text:
            normalized["delta"] = text
    normalized.setdefault("messageID", message_id)
    normalized.setdefault("sessionID", session_id)
    return normalized


def _part_is_tool(part: dict[str, Any]) -> bool:
    kind = str(part.get("type") or part.get("kind") or "").strip().lower()
    return kind in {"tool", "tool_call", "tool-call", "tool_use"} or any(
        key in part for key in ("tool", "toolName", "callID", "toolCallId", "arguments", "raw_arguments")
    )


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "content", "value", "message", "summary", "delta"):
            text = _value_text(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        return "".join(_value_text(item) for item in value)
    return ""


def _unknown_summary(raw: dict[str, Any]) -> str:
    text = _value_text(raw.get("summary") or raw.get("message") or raw.get("text") or raw.get("raw_text"))
    if text:
        return text[:2000]
    try:
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)[:2000]
    except TypeError:
        return str(raw)[:2000]
