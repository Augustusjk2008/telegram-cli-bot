from __future__ import annotations

import re
from typing import Any


INTERACTIVE_UI_KINDS = {"confirm", "select", "input", "editor"}
NON_INTERACTIVE_UI_KINDS = {"notify", "setstatus", "setwidget"}


def pi_json_to_events(
    raw: dict[str, Any],
    *,
    cwd: str = "",
    fallback_session_id: str = "",
    assistant_message_id: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []

    raw_type = _raw_type(raw)
    session_id = extract_session_id(raw) or str(fallback_session_id or "").strip()
    directory = str(raw.get("directory") or raw.get("cwd") or cwd or "").strip()
    message_id = _message_id(raw) or str(assistant_message_id or "").strip() or "msg_pi_assistant"

    if raw_type in {"agent_start", "turn_start"}:
        status = _status_text(raw)
        if not status:
            return []
        return [_wrap_event("session.status", raw, session_id=session_id, directory=directory, status=status, piEventType=raw_type)]

    if raw_type == "message_start":
        if _is_non_assistant_role(raw):
            return []
        error = _message_error_text(raw)
        message = {
            "id": message_id,
            "role": "assistant",
            "sessionID": session_id,
            "state": "error" if error else "running",
        }
        if error:
            message["error"] = error
        return [_wrap_event("message.updated", raw, session_id=session_id, directory=directory, message_id=message_id, message=message)]

    if raw_type == "message_update":
        if _is_non_assistant_role(raw):
            return []
        part_id = _part_id(raw) or f"{message_id}:text"
        explicit_delta = _explicit_delta(raw)
        if explicit_delta:
            return [
                _wrap_event(
                    "message.part.delta",
                    raw,
                    session_id=session_id,
                    directory=directory,
                    message_id=message_id,
                    partID=part_id,
                    field="text",
                    delta=explicit_delta,
                    part={"id": part_id, "type": "text", "messageID": message_id, "sessionID": session_id},
                )
            ]
        text = _message_text(raw)
        if not text:
            return []
        part = {
            "id": part_id,
            "type": "text",
            "text": text,
            "messageID": message_id,
            "sessionID": session_id,
        }
        return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, message_id=message_id, part=part)]

    if raw_type == "message_end":
        if _is_non_assistant_role(raw):
            return []
        if _finish_expects_followup(_finish_reason(raw)) and (_message_text(raw) or _has_tool_call_content(raw)):
            record_message_id = _message_id(raw) or _message_response_id(raw) or message_id
            return _message_record_to_events(raw, session_id=session_id, directory=directory, message_id=record_message_id)
        error = _message_error_text(raw)
        message = {
            "id": message_id,
            "role": "assistant",
            "sessionID": session_id,
            "finish": _finish_reason(raw) or ("error" if error else "stop"),
            "time": {"completed": raw.get("completed_at") or raw.get("completedAt") or True},
        }
        if error:
            message["state"] = "error"
            message["error"] = error
        return [_wrap_event("message.updated", raw, session_id=session_id, directory=directory, message_id=message_id, message=message)]

    if raw_type == "message":
        return _message_record_to_events(raw, session_id=session_id, directory=directory, message_id=message_id)

    if raw_type in {"tool_execution_start", "tool_execution_update", "tool_execution_end"}:
        part = _tool_part(raw, raw_type=raw_type, session_id=session_id, message_id=message_id)
        return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, message_id=message_id, part=part)]

    if raw_type == "extension_ui_request":
        return _extension_ui_request_to_events(raw, session_id=session_id, directory=directory, message_id=message_id)

    if raw_type == "extension_error":
        return [
            _wrap_event(
                "session.error",
                raw,
                session_id=session_id,
                directory=directory,
                message_id=message_id,
                error=_value_text(raw.get("error") or raw.get("message") or raw.get("summary") or raw) or "Pi extension error",
            )
        ]

    if raw_type in {"agent_end", "turn_end"}:
        error = _message_error_text(raw)
        if error:
            return [
                _wrap_event(
                    "session.error",
                    raw,
                    session_id=session_id,
                    directory=directory,
                    message_id=message_id,
                    error=error,
                )
            ]
        events: list[dict[str, Any]] = []
        if raw_type == "turn_end":
            message = _completion_message(raw, session_id=session_id, message_id=message_id)
            if message:
                events.append(_wrap_event("message.updated", raw, session_id=session_id, directory=directory, message_id=message_id, message=message))
        events.append(_wrap_event("session.idle", raw, session_id=session_id, directory=directory, message_id=message_id, piEventType=raw_type))
        return events

    if raw_type == "diagnostic":
        return [
            _wrap_event(
                "pi.diagnostic",
                raw,
                session_id=session_id,
                directory=directory,
                summary=_value_text(raw.get("message") or raw.get("summary") or raw.get("raw")) or "Pi diagnostic",
                source=str(raw.get("source") or "pi_rpc_transport"),
                level=str(raw.get("level") or ""),
            )
        ]

    return []


def extract_session_id(raw: dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        return ""
    for record in _candidate_records(raw):
        for key in (
            "sessionID",
            "session_id",
            "sessionId",
            "conversation_id",
            "conversationId",
            "conversationID",
            "thread_id",
            "threadId",
        ):
            value = record.get(key)
            if value:
                return str(value)
    return ""


def extract_context_usage(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    candidates = [
        raw.get("context_usage"),
        raw.get("contextUsage"),
        raw.get("usage"),
        raw.get("tokens"),
    ]
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    candidates.extend([
        message.get("context_usage"),
        message.get("contextUsage"),
        message.get("usage"),
        message.get("tokens"),
    ])
    for item in candidates:
        if isinstance(item, dict):
            usage = dict(item)
            if raw.get("cost") is not None:
                usage.setdefault("cost", raw.get("cost"))
            if raw.get("model") is not None:
                usage.setdefault("model", raw.get("model"))
            return usage
    direct_keys = (
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "context_window",
        "context_used",
        "context_used_percent",
        "cost",
        "model",
    )
    usage = {key: raw[key] for key in direct_keys if key in raw}
    return usage


def build_extension_ui_response(
    request_id: str,
    *,
    accepted: bool,
    value: Any = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {"accepted": bool(accepted)}
    if value is not None:
        response["value"] = value
    return {
        "type": "extension_ui_response",
        "id": str(request_id or ""),
        "response": response,
    }


def _wrap_event(
    event_type: str,
    raw: dict[str, Any],
    *,
    session_id: str,
    directory: str,
    message_id: str = "",
    **fields: Any,
) -> dict[str, Any]:
    payload = {
        "type": event_type,
        "sessionID": session_id,
        "raw": raw,
        **fields,
    }
    if message_id:
        payload["messageID"] = message_id
    return {"directory": directory, "payload": payload}


def _extension_ui_request_to_events(
    raw: dict[str, Any],
    *,
    session_id: str,
    directory: str,
    message_id: str,
) -> list[dict[str, Any]]:
    ui_kind = _ui_kind(raw)
    normalized_kind = ui_kind.strip().lower()
    request_id = _request_id(raw) or f"pi_ui_{message_id}"
    summary = _status_text(raw) or str(raw.get("title") or "").strip() or "Pi 请求交互"
    if normalized_kind in INTERACTIVE_UI_KINDS:
        permission = {
            "id": request_id,
            "permissionID": request_id,
            "uiKind": ui_kind or "confirm",
            "title": str(raw.get("title") or "").strip(),
            "message": _value_text(raw.get("message") or raw.get("prompt") or raw.get("reason")),
            "options": _first_present(raw, "options", "choices", "items"),
            "defaultValue": _first_present(raw, "defaultValue", "default_value", "value"),
            "placeholder": _first_present(raw, "placeholder"),
            "state": "permission.updated",
            "status": "permission.updated",
            "source": "pi",
            "raw": raw,
        }
        return [_wrap_event("permission.updated", raw, session_id=session_id, directory=directory, message_id=message_id, permission=permission)]
    if normalized_kind in NON_INTERACTIVE_UI_KINDS or ui_kind:
        return [
            _wrap_event(
                "session.status",
                raw,
                session_id=session_id,
                directory=directory,
                message_id=message_id,
                status=summary,
                summary=summary,
                uiKind=ui_kind,
                piEventType="extension_ui_request",
                source="pi",
            )
        ]
    return []


def _message_record_to_events(
    raw: dict[str, Any],
    *,
    session_id: str,
    directory: str,
    message_id: str,
) -> list[dict[str, Any]]:
    source = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    role = str(source.get("role") or raw.get("role") or "").strip().lower()
    if role == "toolresult":
        part = _tool_result_message_part(raw, session_id=session_id, message_id=message_id)
        return [_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, message_id=message_id, part=part)]
    if role and role != "assistant":
        return []

    error = _message_error_text(raw)
    text = _message_text(raw)
    events: list[dict[str, Any]] = []
    if text:
        part_id = _part_id(raw) or f"{message_id}:text"
        events.append(
            _wrap_event(
                "message.part.updated",
                raw,
                session_id=session_id,
                directory=directory,
                message_id=message_id,
                part={
                    "id": part_id,
                    "type": "text",
                    "text": text,
                    "messageID": message_id,
                    "sessionID": session_id,
                },
            )
        )
    for part in _tool_call_message_parts(raw, session_id=session_id, message_id=message_id):
        events.append(_wrap_event("message.part.updated", raw, session_id=session_id, directory=directory, message_id=message_id, part=part))
    finish = _finish_reason(raw)
    if finish or error:
        message = dict(source)
        message["id"] = _message_id(raw) or str(message_id or "").strip()
        message["role"] = "assistant"
        message["sessionID"] = session_id
        if finish:
            message["finish"] = finish
        if error:
            message["state"] = "error"
            message["error"] = error
        message.setdefault("time", {"completed": raw.get("completed_at") or raw.get("completedAt") or source.get("timestamp") or True})
        events.append(_wrap_event("message.updated", raw, session_id=session_id, directory=directory, message_id=message_id, message=message))
    return events


def _tool_part(raw: dict[str, Any], *, raw_type: str, session_id: str, message_id: str) -> dict[str, Any]:
    call_id = _tool_call_id(raw) or _part_id(raw) or "pi-tool"
    tool_name = _tool_name(raw)
    state = "running"
    if raw_type == "tool_execution_end":
        state = "completed"
    elif raw_type == "tool_execution_update":
        state = str(raw.get("state") or raw.get("status") or "running")
    if _value_text(raw.get("error")):
        state = "error"

    part: dict[str, Any] = {
        "id": call_id,
        "type": "tool",
        "callID": call_id,
        "toolCallId": call_id,
        "tool": tool_name,
        "toolName": tool_name,
        "messageID": message_id,
        "sessionID": session_id,
        "state": state,
    }
    arguments = _first_present(raw, "arguments", "raw_arguments", "args", "input", "params")
    if arguments is not None:
        part["arguments"] = arguments
    output = _first_present(raw, "output", "result")
    if output is not None:
        part["output"] = output
    error = _first_present(raw, "error")
    if error is not None:
        part["error"] = error
    return part


def _tool_call_message_parts(raw: dict[str, Any], *, session_id: str, message_id: str) -> list[dict[str, Any]]:
    source = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    content = source.get("content") if isinstance(source.get("content"), list) else raw.get("content")
    if not isinstance(content, list):
        return []
    parts: list[dict[str, Any]] = []
    for index, item in enumerate(content, 1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("kind") or "").strip().lower()
        if kind not in {"toolcall", "tool_call", "tool-use", "tool_use"}:
            continue
        call_id = str(item.get("id") or item.get("callID") or item.get("toolCallId") or f"{message_id}:tool:{index}").strip()
        tool_name = str(item.get("name") or item.get("tool") or item.get("toolName") or "tool").strip()
        part: dict[str, Any] = {
            "id": call_id,
            "type": "tool",
            "callID": call_id,
            "toolCallId": call_id,
            "tool": tool_name,
            "toolName": tool_name,
            "messageID": message_id,
            "sessionID": session_id,
            "state": "running",
        }
        arguments = item.get("arguments")
        if arguments is None:
            arguments = item.get("args", item.get("input", item.get("params")))
        if arguments is not None:
            part["arguments"] = arguments
        parts.append(part)
    return parts


def _has_tool_call_content(raw: dict[str, Any]) -> bool:
    source = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    content = source.get("content") if isinstance(source.get("content"), list) else raw.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("kind") or "").strip().lower()
        if kind in {"toolcall", "tool_call", "tool-use", "tool_use"}:
            return True
    return False


def _tool_result_message_part(raw: dict[str, Any], *, session_id: str, message_id: str) -> dict[str, Any]:
    source = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    call_id = _tool_call_id(raw) or str(source.get("toolCallId") or source.get("tool_call_id") or source.get("call_id") or "pi-tool").strip()
    tool_name = _tool_name(raw)
    output = _message_text(raw)
    error = _message_error_text(raw)
    is_error = bool(source.get("isError") or raw.get("isError") or error)
    part: dict[str, Any] = {
        "id": call_id,
        "type": "tool",
        "callID": call_id,
        "toolCallId": call_id,
        "tool": tool_name,
        "toolName": tool_name,
        "messageID": message_id,
        "sessionID": session_id,
        "state": "error" if is_error else "completed",
    }
    if output:
        part["output"] = output
    if error:
        part["error"] = error
    return part


def _candidate_records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    records = [raw]
    for key in ("session", "conversation", "message", "part", "properties", "payload", "data", "request"):
        value = raw.get(key)
        if isinstance(value, dict):
            records.append(value)
    return records


def _raw_type(raw: dict[str, Any]) -> str:
    return str(raw.get("type") or raw.get("event") or raw.get("name") or "").strip()


def _message_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("messageID", "message_id", "messageId"):
            value = record.get(key)
            if value:
                return str(value)
    message = raw.get("message")
    if isinstance(message, dict) and message.get("id"):
        return str(message["id"])
    if _raw_type(raw) == "message" and raw.get("id"):
        return str(raw["id"])
    if _raw_type(raw).startswith("message_") and raw.get("id"):
        return str(raw["id"])
    return ""


def _message_response_id(raw: dict[str, Any]) -> str:
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    for record in (raw, message):
        for key in ("responseId", "response_id", "responseID"):
            value = record.get(key)
            if value:
                return str(value)
    return ""


def _part_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("partID", "part_id", "partId"):
            value = record.get(key)
            if value:
                return str(value)
    part = raw.get("part")
    if isinstance(part, dict) and part.get("id"):
        return str(part["id"])
    return ""


def _tool_call_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("callID", "toolCallId", "tool_call_id", "call_id", "execution_id", "executionId"):
            value = record.get(key)
            if value:
                return str(value)
    if _raw_type(raw).startswith("tool_execution") and raw.get("id"):
        return str(raw["id"])
    return ""


def _request_id(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("request_id", "requestId", "permissionID", "permission_id", "id"):
            value = record.get(key)
            if value:
                return str(value)
    return ""


def _tool_name(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("tool", "toolName", "name", "command"):
            value = record.get(key)
            if value:
                return str(value)
    return "tool"


def _ui_kind(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("uiKind", "ui_kind", "kind", "requestType", "request_type"):
            value = record.get(key)
            if value:
                return str(value)
    return "confirm"


def _role(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        value = record.get("role")
        if value:
            return str(value).strip().lower()
    return ""


def _is_non_assistant_role(raw: dict[str, Any]) -> bool:
    role = _role(raw)
    return bool(role and role != "assistant")


def _explicit_delta(raw: dict[str, Any]) -> str:
    event = _assistant_message_event(raw)
    if str(event.get("type") or "").strip() == "text_delta":
        return _value_text(event.get("delta"))
    if "delta" not in raw and "delta_text" not in raw and "deltaText" not in raw:
        return ""
    return _value_text(raw.get("delta") or raw.get("delta_text") or raw.get("deltaText"))


def _message_text(raw: dict[str, Any]) -> str:
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    event = _assistant_message_event(raw)
    event_type = str(event.get("type") or "").strip()
    event_text = ""
    if event_type in {"text_end", "text"}:
        event_text = _value_text(event.get("content") or event.get("partial"))
    return _clean_visible_text(_value_text(
        raw.get("content")
        or raw.get("text")
        or raw.get("value")
        or message.get("content")
        or message.get("text")
        or message.get("parts")
        or event_text
    ))


def _status_text(raw: dict[str, Any]) -> str:
    return _value_text(
        raw.get("summary")
        or raw.get("status")
        or raw.get("state")
        or raw.get("message")
        or raw.get("text")
    )


def _finish_reason(raw: dict[str, Any]) -> str:
    for record in _candidate_records(raw):
        for key in ("finish", "finish_reason", "finishReason", "stopReason", "stop_reason", "reason"):
            value = record.get(key)
            if value:
                return str(value).strip()
    return ""


def _finish_expects_followup(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized in {"tool-calls", "tool-call", "tooluse", "tool-use"}


def _completion_message(raw: dict[str, Any], *, session_id: str, message_id: str) -> dict[str, Any]:
    source = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    role = str(source.get("role") or "").strip().lower()
    if role and role != "assistant":
        return {}
    text = _message_text(raw)
    finish = _finish_reason(raw)
    if not text and not finish:
        return {}
    message = dict(source)
    message["id"] = _message_id(raw) or str(message_id or "").strip()
    message["role"] = "assistant"
    message["sessionID"] = session_id
    if finish:
        message["finish"] = finish
    if text and "content" not in message and "text" not in message:
        message["content"] = text
    message.setdefault("time", {"completed": raw.get("completed_at") or raw.get("completedAt") or True})
    return message


def _message_error_text(raw: dict[str, Any]) -> str:
    error = _value_text(_first_present(raw, "error", "errorMessage", "error_message"))
    if error:
        return error
    finish = _finish_reason(raw).strip().lower()
    if finish in {"error", "failed", "failure"}:
        return "Pi agent 执行失败"
    return ""


def _assistant_message_event(raw: dict[str, Any]) -> dict[str, Any]:
    event = raw.get("assistantMessageEvent")
    return event if isinstance(event, dict) else {}


def _first_present(raw: dict[str, Any], *keys: str) -> Any:
    for record in _candidate_records(raw):
        for key in keys:
            if key in record:
                return record[key]
    return None


_THINKING_BLOCK_RE = re.compile(r"<thinking>.*?(?:</thinking>|$)", re.IGNORECASE | re.DOTALL)


def _clean_visible_text(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    cleaned = _THINKING_BLOCK_RE.sub("", value)
    return cleaned.strip()


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(_value_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "value", "message", "summary", "delta", "status"):
            text = _value_text(value.get(key))
            if text:
                return text
    return ""
