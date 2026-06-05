from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.native_agent.events import NativeAgentEvent


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
        for key in ("text", "content", "value", "message", "summary", "delta"):
            if key in value:
                return _value_text(value.get(key))
    return ""


def _message_id(message: dict[str, Any]) -> str:
    for key in ("id", "messageID", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)
    return ""


def _message_id_from_payload(payload: dict[str, Any], part: dict[str, Any] | None = None) -> str:
    records: list[dict[str, Any]] = [payload]
    properties = payload.get("properties")
    if isinstance(properties, dict):
        records.append(properties)
    if isinstance(part, dict):
        records.append(part)
    for record in records:
        for key in ("messageID", "message_id", "messageId"):
            value = record.get(key)
            if value:
                return str(value)
    return ""


def _part_id(part: dict[str, Any]) -> str:
    for key in ("id", "partID", "part_id", "partId"):
        value = part.get(key)
        if value:
            return str(value)
    return ""


def _part_id_from_payload(payload: dict[str, Any], part: dict[str, Any] | None = None) -> str:
    if isinstance(part, dict):
        part_id = _part_id(part)
        if part_id:
            return part_id
    properties = payload.get("properties")
    records = [payload, properties] if isinstance(properties, dict) else [payload]
    for record in records:
        for key in ("partID", "part_id", "partId", "id"):
            value = record.get(key)
            if value:
                return str(value)
    return ""


def _message_parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return _value_text(parts)
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            text = _value_text(part)
            if text:
                texts.append(text)
            continue
        kind = str(part.get("type") or part.get("kind") or "").strip().lower()
        if kind and kind not in {"text", "assistant_text", "message"}:
            continue
        text = _value_text(part.get("text") or part.get("content") or part.get("value") or part)
        if text:
            texts.append(text)
    return "".join(texts)


@dataclass
class NativeAgentAggregationResult:
    delta: str = ""
    snapshot: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    status: str = ""
    done: bool = False
    error: str = ""
    assistant_message_id: str = ""


class NativeAgentAggregator:
    def __init__(self, *, user_message_id: str) -> None:
        self.user_message_id = user_message_id
        self.assistant_message_id = ""
        self.parts: dict[str, dict[str, Any]] = {}
        self.text_parts: dict[str, str] = {}
        self.reasoning_parts: dict[str, str] = {}
        self.final_text = ""
        self.permission_pending: dict[str, dict[str, Any]] = {}
        self.assistant_completed = False

    def text(self) -> str:
        if self.text_parts:
            return "".join(self.text_parts[key] for key in sorted(self.text_parts))
        return self.final_text

    def apply(self, event: NativeAgentEvent) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        event_type = event.type
        payload = event.payload
        if event_type == "message.updated":
            return self._message_updated(payload)
        if event_type == "message.part.updated":
            return self._part_updated(payload)
        if event_type == "message.part.delta":
            return self._part_delta(payload)
        if event_type == "message.part.removed":
            return self._part_removed(payload)
        if event_type in {"permission.updated", "permission.replied"}:
            return self._permission_updated(event_type, payload)
        if event_type in {"session.status", "session.idle"}:
            result.status = event.status or _value_text(payload.get("status") or payload.get("state") or event_type)
            result.done = event_type == "session.idle" or result.status == "idle"
            return result
        if event_type == "session.error":
            result.error = _value_text(payload.get("error") or payload.get("message") or payload)
            return result
        if event_type in {"session.retry", "message.retry"}:
            result.trace.append(self._trace("retry", "原生 agent 正在重试", payload))
            return result
        if event_type:
            trace = self._trace_from_payload(event_type, payload)
            if trace is not None:
                result.trace.append(trace)
        return result

    def _message_updated(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
        role = str(message.get("role") or "").lower()
        message_id = _message_id(message)
        if role == "assistant" and message_id:
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        text = _value_text(message.get("text") or message.get("content")) or _message_parts_text(message.get("parts"))
        if role == "assistant" and text:
            previous = self.final_text
            self.final_text = text
            if text.startswith(previous):
                result.delta = text[len(previous):]
            else:
                result.snapshot = text
        error = _value_text(message.get("error"))
        if error:
            result.error = error
        completed = message.get("time", {}).get("completed") if isinstance(message.get("time"), dict) else None
        if completed:
            self.assistant_completed = True
            result.done = True
        return result

    def _part_updated(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        part = payload.get("part") if isinstance(payload.get("part"), dict) else payload
        message_id = _message_id_from_payload(payload, part)
        if message_id == self.user_message_id:
            return result
        if message_id:
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        part_id = _part_id_from_payload(payload, part) or str(len(self.parts) + 1)
        self.parts[part_id] = dict(part)
        kind = str(part.get("type") or part.get("kind") or "").lower()
        delta = _value_text(payload.get("delta") or part.get("delta"))
        full_text = _value_text(part.get("text") or part.get("content"))
        if kind in {"text", "assistant_text", "message"} or (not kind and (delta or full_text)):
            if delta:
                self.text_parts[part_id] = self.text_parts.get(part_id, "") + delta
                result.delta = delta
            elif full_text:
                previous = self.text_parts.get(part_id, "")
                self.text_parts[part_id] = full_text
                if full_text.startswith(previous):
                    result.delta = full_text[len(previous):]
                else:
                    result.snapshot = self.text()
            return result
        if kind in {"reasoning", "thinking"}:
            text = delta or full_text
            if text:
                self.reasoning_parts[part_id] = self.reasoning_parts.get(part_id, "") + text
                result.trace.append(self._trace("reasoning", text, part))
            return result
        if _is_tool_part(part):
            return self._tool_part_updated(part)
        trace = self._trace_from_payload(f"part.{kind or 'updated'}", part)
        if trace is not None:
            result.trace.append(trace)
        return result

    def _part_delta(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        part = payload.get("part") if isinstance(payload.get("part"), dict) else {}
        message_id = _message_id_from_payload(payload, part)
        if message_id == self.user_message_id:
            return result
        if message_id:
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        field = str(payload.get("field") or properties.get("field") or "").strip().lower()
        if field and field != "text":
            return result
        delta = _value_text(payload.get("delta") or properties.get("delta"))
        if not delta:
            return result
        part_id = _part_id_from_payload(payload, part) or str(len(self.parts) + 1)
        if part:
            self.parts[part_id] = dict(part)
        self.text_parts[part_id] = self.text_parts.get(part_id, "") + delta
        result.delta = delta
        return result

    def _tool_part_updated(self, part: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        call_id = _tool_call_id(part) or _part_id(part) or str(len(self.parts))
        tool_name = str(part.get("tool") or part.get("toolName") or part.get("name") or part.get("command") or "tool").strip()
        state = str(part.get("state") or part.get("status") or "").strip().lower()
        args_text = _value_text(
            part.get("arguments")
            or part.get("raw_arguments")
            or part.get("args")
            or part.get("input")
            or part.get("params")
        )
        result_text = _value_text(part.get("result") or part.get("output") or part.get("error"))
        payload = {
            **part,
            "callID": call_id,
            "toolName": tool_name,
            "arguments": args_text,
        }
        result.trace.append(self._trace("tool_call", args_text or tool_name, payload, raw_type="message.part.updated"))
        if result_text or state in {"completed", "done", "finished", "success", "error", "failed"}:
            result.trace.append(
                self._trace(
                    "tool_result",
                    result_text or state or "已返回，无可显示内容",
                    {**payload, "output": result_text, "state": state},
                    raw_type="message.part.updated",
                )
            )
        return result

    def _part_removed(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        part = payload.get("part") if isinstance(payload.get("part"), dict) else payload
        part_id = _part_id_from_payload(payload, part)
        if part_id:
            self.parts.pop(part_id, None)
            self.text_parts.pop(part_id, None)
            self.reasoning_parts.pop(part_id, None)
        return NativeAgentAggregationResult(snapshot=self.text())

    def _permission_updated(self, event_type: str, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        if isinstance(payload.get("permission"), dict):
            permission = payload["permission"]
        elif isinstance(payload.get("properties"), dict):
            permission = payload["properties"]
        else:
            permission = payload
        permission_id = str(
            permission.get("id")
            or permission.get("permissionID")
            or permission.get("permission_id")
            or ""
        )
        state = str(permission.get("status") or permission.get("state") or event_type).strip()
        if permission_id and event_type == "permission.updated":
            self.permission_pending[permission_id] = dict(permission)
        if permission_id and event_type == "permission.replied":
            self.permission_pending.pop(permission_id, None)
        summary = _value_text(permission.get("title") or permission.get("message") or permission.get("action"))
        if not summary:
            summary = "原生 agent 请求权限" if event_type == "permission.updated" else "原生 agent 权限已处理"
        return NativeAgentAggregationResult(
            trace=[self._trace("permission", summary, permission | {"state": state})],
            status=summary,
        )

    def _trace_from_payload(self, raw_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        kind = str(payload.get("type") or payload.get("kind") or raw_type or "event").lower()
        if kind in {"text", "message", "assistant_text"}:
            return None
        summary = _value_text(
            payload.get("summary")
            or payload.get("title")
            or payload.get("name")
            or payload.get("message")
            or payload.get("text")
            or payload.get("content")
        )
        if not summary and raw_type:
            summary = raw_type
        if not summary:
            return None
        trace_kind = "tool_call" if any(token in kind for token in ("tool", "bash", "file", "patch")) else "event"
        return self._trace(trace_kind, summary, payload, raw_type=raw_type)

    def _trace(
        self,
        kind: str,
        summary: str,
        payload: dict[str, Any],
        *,
        raw_type: str = "",
    ) -> dict[str, Any]:
        tool_name = str(payload.get("tool") or payload.get("toolName") or payload.get("name") or "")
        call_id = str(payload.get("callID") or payload.get("toolCallId") or payload.get("tool_call_id") or payload.get("call_id") or payload.get("id") or "")
        return {
            "kind": kind,
            "source": "native_agent",
            "raw_type": raw_type or str(payload.get("type") or payload.get("kind") or ""),
            "tool_name": tool_name,
            "call_id": call_id,
            "summary": str(summary or "").strip(),
            "payload": payload,
        }

    def reconcile_messages(self, messages: list[dict[str, Any]]) -> str:
        for message in messages:
            role = str(message.get("role") or "").lower()
            if role != "assistant":
                continue
            text = _message_parts_text(message.get("parts")) or _value_text(message.get("text") or message.get("content"))
            if text:
                self.final_text = text
                self.text_parts.clear()
        return self.text()


def _tool_call_id(part: dict[str, Any]) -> str:
    for key in ("callID", "toolCallId", "tool_call_id", "call_id"):
        value = part.get(key)
        if value:
            return str(value)
    return ""


def _is_tool_part(part: dict[str, Any]) -> bool:
    kind = str(part.get("type") or part.get("kind") or "").strip().lower()
    if kind in {"tool", "tool_call", "tool-call", "tool_use", "tool_use_delta"}:
        return True
    return any(key in part for key in ("tool", "toolName", "callID", "toolCallId", "arguments", "raw_arguments"))
