from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from bot.native_agent.events import NativeAgentEvent

PROCESS_EVENT_KINDS = {"file.edited"}
NOISE_EVENT_TYPES = {"file.watcher.updated"}


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


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _message_id(message: dict[str, Any]) -> str:
    for key in ("id", "messageID", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)
    return ""


def _message_id_from_payload(payload: dict[str, Any], part: dict[str, Any] | None = None) -> str:
    records: list[dict[str, Any]] = []
    if isinstance(part, dict):
        records.append(part)
    properties = payload.get("properties")
    if isinstance(properties, dict):
        records.append(properties)
    records.append(payload)
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


def _normalized_commentary_summary(text: str) -> str:
    return " ".join(str(text or "").split())


def _commentary_summary_key(text: str) -> str:
    return "".join(str(text or "").split())


def _is_unstable_commentary_message_id(message_id: str) -> bool:
    normalized = str(message_id or "").strip()
    return not normalized or normalized.startswith("evt_")


@dataclass
class NativeAgentAggregationResult:
    delta: str = ""
    snapshot: str = ""
    replace_text: bool = False
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
        self.part_orders: dict[str, int] = {}
        self.next_part_order = 1
        self.part_message_ids: dict[str, str] = {}
        self.text_parts: dict[str, str] = {}
        self.reasoning_parts: dict[str, str] = {}
        self.followup_message_ids: set[str] = set()
        self.saw_tool_activity = False
        self.saw_tool_failure = False
        self.tool_failure_message = ""
        self.pending_followup = False
        self.final_message_id = ""
        self.tool_call_emitted: set[str] = set()
        self.tool_result_signatures: dict[str, str] = {}
        self.commentary_trace_summary_message_ids: dict[str, set[str]] = {}
        self.final_text = ""
        self.permission_pending: dict[str, dict[str, Any]] = {}
        self.assistant_completed = False
        self.has_followup_activity = False
        self.completed_message_ids: set[str] = set()
        self.reconciled_trace: list[dict[str, Any]] = []

    def text(self) -> str:
        if self.text_parts:
            return "".join(self.text_parts[key] for key in self._ordered_part_ids(self.text_parts))
        return self.final_text

    def pop_reconciled_trace(self) -> list[dict[str, Any]]:
        trace = list(self.reconciled_trace)
        self.reconciled_trace.clear()
        return trace

    def apply(self, event: NativeAgentEvent) -> NativeAgentAggregationResult:
        event_type = event.type
        payload = event.payload
        if event_type == "message.updated":
            result = self._message_updated(payload)
        elif event_type == "message.part.updated":
            result = self._part_updated(payload)
        elif event_type == "message.part.delta":
            result = self._part_delta(payload)
        elif event_type == "message.part.removed":
            result = self._part_removed(payload)
        elif event_type in {"permission.updated", "permission.replied"}:
            result = self._permission_updated(event_type, payload)
        elif event_type in {"session.status", "session.idle"}:
            result = NativeAgentAggregationResult()
            result.status = event.status or _value_text(payload.get("status") or payload.get("state") or event_type)
            has_non_followup_text = bool(
                self.assistant_message_id
                and self.assistant_message_id not in self.followup_message_ids
                and self.text()
            )
            has_current_turn_activity = bool(
                self.assistant_message_id
                or self.text()
                or self.saw_tool_activity
                or self.assistant_completed
            )
            result.done = event_type == "session.idle" and (
                has_current_turn_activity
                and (not self.pending_followup or self.assistant_completed or has_non_followup_text)
            )
        elif event_type == "session.error":
            result = NativeAgentAggregationResult()
            result.error = _value_text(payload.get("error") or payload.get("message") or payload)
        elif event_type in {"session.retry", "message.retry"}:
            result = NativeAgentAggregationResult()
            result.trace.append(self._trace("retry", "原生 agent 正在重试", payload))
        elif event_type in NOISE_EVENT_TYPES:
            result = NativeAgentAggregationResult()
        else:
            result = NativeAgentAggregationResult()
            trace = self._trace_from_payload(event_type, payload)
            if trace is not None:
                result.trace.append(trace)
        failure = _explicit_failure_message(event_type, payload)
        if failure and not result.error:
            result.error = failure
        return result

    def _message_updated(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        if not message:
            properties = payload.get("properties")
            if isinstance(properties, dict):
                message = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                if not message:
                    message = properties.get("message") if isinstance(properties.get("message"), dict) else {}
                if not message:
                    message = properties.get("info") if isinstance(properties.get("info"), dict) else {}
        if not message:
            message = payload
        role = str(message.get("role") or "").lower()
        message_id = _message_id(message)
        text = _value_text(message.get("text") or message.get("content")) or _message_parts_text(message.get("parts"))
        is_completed_final_message = role == "assistant" and bool(message_id) and _message_completed(message)
        should_suppress_switch_trace = (
            is_completed_final_message
            and bool(text)
            and _normalized_commentary_summary(text) == _normalized_commentary_summary(self.text())
        )
        switched_message = False
        if role == "assistant" and message_id:
            previous_message_id = self.assistant_message_id
            switched, discarded_text = self._switch_assistant_message(message_id, preserve_message_id=message_id)
            if switched:
                switched_message = True
                result.snapshot = ""
                result.replace_text = True
                if not should_suppress_switch_trace:
                    trace = self._build_commentary_trace(
                        message_id=previous_message_id,
                        text=discarded_text,
                        reason="assistant-message-switched",
                        payload=payload,
                    )
                    if trace is not None:
                        result.trace.append(trace)
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        if role == "assistant" and message_id and _message_expects_followup(message):
            self.followup_message_ids.add(message_id)
            self.pending_followup = True
            self.has_followup_activity = True
            changed, discarded_text = self._discard_message_text(message_id)
            if changed:
                result.snapshot = self.text()
                result.replace_text = True
                trace = self._build_commentary_trace(
                    message_id=message_id,
                    text=discarded_text,
                    reason="tool-calls",
                    payload=payload,
                )
                if trace is not None:
                    result.trace.append(trace)
            return result
        if role == "assistant" and text:
            previous = self.final_text
            self.final_text = text
            if switched_message:
                result.delta = ""
                result.snapshot = text
                result.replace_text = True
            elif text.startswith(previous):
                result.delta = text[len(previous):]
            else:
                result.snapshot = text
        error = _value_text(message.get("error"))
        if error:
            result.error = error
        if _message_completed(message):
            self.assistant_completed = True
            self.pending_followup = False
            if message_id:
                self.final_message_id = message_id
                self.completed_message_ids.add(message_id)
            if not self.has_followup_activity and len(self.completed_message_ids) >= 2:
                result.done = True
        return result

    def _part_updated(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        part = payload.get("part") if isinstance(payload.get("part"), dict) else payload
        message_id = _message_id_from_payload(payload, part)
        if message_id == self.user_message_id:
            return result
        switched_message = False
        if message_id and self._part_belongs_to_current_turn(message_id):
            previous_message_id = self.assistant_message_id
            switched, discarded_text = self._switch_assistant_message(message_id, preserve_message_id=message_id)
            if switched:
                switched_message = True
                result.snapshot = ""
                result.replace_text = True
                trace = self._build_commentary_trace(
                    message_id=previous_message_id,
                    text=discarded_text,
                    reason="assistant-message-switched",
                    payload=payload,
                )
                if trace is not None:
                    result.trace.append(trace)
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        part_id = _part_id_from_payload(payload, part) or str(len(self.parts) + 1)
        self._remember_part_order(part_id)
        self.parts[part_id] = dict(part)
        if message_id:
            self.part_message_ids[part_id] = message_id
        kind = str(part.get("type") or part.get("kind") or "").lower()
        if _is_noise_part_kind(kind):
            return result
        delta = _value_text(payload.get("delta") or part.get("delta"))
        full_text = _value_text(part.get("text") or part.get("content"))
        if kind in {"text", "assistant_text", "message"} or (not kind and (delta or full_text)):
            if message_id in self.followup_message_ids:
                changed, discarded_text = self._discard_message_text(message_id)
                if changed:
                    result.snapshot = self.text()
                    result.replace_text = True
                    trace = self._build_commentary_trace(
                        message_id=message_id,
                        text=discarded_text,
                        reason="followup-part-updated",
                        payload=payload,
                    )
                    if trace is not None:
                        result.trace.append(trace)
                return result
            if delta:
                self.text_parts[part_id] = self.text_parts.get(part_id, "") + delta
                if switched_message:
                    result.snapshot = self.text()
                    result.replace_text = True
                else:
                    result.delta = delta
            elif full_text:
                previous = self.text_parts.get(part_id, "")
                self.text_parts[part_id] = full_text
                if switched_message:
                    result.snapshot = self.text()
                    result.replace_text = True
                elif full_text.startswith(previous):
                    result.delta = full_text[len(previous):]
                else:
                    result.snapshot = self.text()
            return result
        if kind in {"reasoning", "thinking"}:
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
        switched_message = False
        if message_id and self._part_belongs_to_current_turn(message_id):
            previous_message_id = self.assistant_message_id
            switched, discarded_text = self._switch_assistant_message(message_id, preserve_message_id=message_id)
            if switched:
                switched_message = True
                result.snapshot = ""
                result.replace_text = True
                trace = self._build_commentary_trace(
                    message_id=previous_message_id,
                    text=discarded_text,
                    reason="assistant-message-switched",
                    payload=payload,
                )
                if trace is not None:
                    result.trace.append(trace)
            self.assistant_message_id = message_id
            result.assistant_message_id = message_id
        field = str(payload.get("field") or properties.get("field") or "").strip().lower()
        if field and field != "text":
            return result
        delta = _value_text(payload.get("delta") or properties.get("delta"))
        if not delta:
            return result
        part_id = _part_id_from_payload(payload, part) or str(len(self.parts) + 1)
        self._remember_part_order(part_id)
        existing_part = self.parts.get(part_id, {})
        effective_part = part or existing_part
        kind = str(effective_part.get("type") or effective_part.get("kind") or "").strip().lower()
        if kind in {"reasoning", "thinking"} or _is_noise_part_kind(kind) or _is_tool_part(effective_part):
            return result
        if message_id in self.followup_message_ids:
            changed, discarded_text = self._discard_message_text(message_id)
            if changed:
                result.snapshot = self.text()
                result.replace_text = True
                trace = self._build_commentary_trace(
                    message_id=message_id,
                    text=discarded_text,
                    reason="followup-part-delta",
                    payload=payload,
                )
                if trace is not None:
                    result.trace.append(trace)
            return result
        if part:
            self.parts[part_id] = dict(part)
        if message_id:
            self.part_message_ids[part_id] = message_id
        self.text_parts[part_id] = self.text_parts.get(part_id, "") + delta
        if switched_message:
            result.snapshot = self.text()
            result.replace_text = True
        else:
            result.delta = delta
        return result

    def _tool_part_updated(self, part: dict[str, Any]) -> NativeAgentAggregationResult:
        result = NativeAgentAggregationResult()
        self.saw_tool_activity = True
        call_id = _tool_call_id(part) or _part_id(part) or str(len(self.parts))
        part_id = _part_id(part)
        message_id = (
            self.part_message_ids.get(part_id or "", "")
            or str(part.get("messageID") or part.get("message_id") or part.get("messageId") or "").strip()
            or self.assistant_message_id
        )
        tool_name = str(part.get("tool") or part.get("toolName") or part.get("name") or part.get("command") or "tool").strip()
        state_payload = part.get("state") if isinstance(part.get("state"), dict) else {}
        state = str(
            state_payload.get("status")
            or part.get("state")
            or part.get("status")
            or ""
        ).strip().lower()
        args_value = (
            part.get("arguments")
            or part.get("raw_arguments")
            or part.get("args")
            or part.get("input")
            or part.get("params")
            or state_payload.get("input")
            or state_payload.get("raw")
        )
        args_text = _json_text(args_value)
        metadata = state_payload.get("metadata") if isinstance(state_payload.get("metadata"), dict) else {}
        result_text = _value_text(
            part.get("result")
            or part.get("output")
            or part.get("error")
            or state_payload.get("result")
            or state_payload.get("output")
            or state_payload.get("error")
            or metadata.get("output")
            or metadata.get("error")
        )
        payload = {
            **part,
            "callID": call_id,
            "toolName": tool_name,
            "arguments": args_text,
        }
        if call_id not in self.tool_call_emitted and (args_text or state not in {"", "pending"}):
            trace = self._flush_message_text_as_commentary(
                message_id=message_id,
                reason="tool-call",
                payload=payload,
            )
            if trace is not None:
                result.snapshot = self.text()
                result.replace_text = True
                result.trace.append(trace)
            self.tool_call_emitted.add(call_id)
            result.trace.append(self._trace("tool_call", args_text or tool_name, payload, raw_type="message.part.updated"))
        result_signature = result_text.strip() if result_text else f"<empty:{state}>"
        if (
            result_text or state in {"completed", "done", "finished", "success", "error", "failed"}
        ) and self.tool_result_signatures.get(call_id) != result_signature:
            self.tool_result_signatures[call_id] = result_signature
            result.trace.append(
                self._trace(
                    "tool_result",
                    result_text or state or "已返回，无可显示内容",
                    {**payload, "output": result_text, "state": state},
                    raw_type="message.part.updated",
                )
            )
        if state in {"error", "failed", "failure", "cancelled", "canceled", "aborted", "abort"} or _value_text(part.get("error") or state_payload.get("error")):
            self.saw_tool_failure = True
            self.tool_failure_message = result_text or state or "工具执行失败"
            result.error = self.tool_failure_message
        return result

    def _part_removed(self, payload: dict[str, Any]) -> NativeAgentAggregationResult:
        part = payload.get("part") if isinstance(payload.get("part"), dict) else payload
        part_id = _part_id_from_payload(payload, part)
        if part_id:
            self.parts.pop(part_id, None)
            self.part_orders.pop(part_id, None)
            self.text_parts.pop(part_id, None)
            self.reasoning_parts.pop(part_id, None)
            self.part_message_ids.pop(part_id, None)
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
        if kind in NOISE_EVENT_TYPES or str(raw_type or "").lower() in NOISE_EVENT_TYPES:
            return None
        if kind in {"text", "message", "assistant_text", "sync", "session.updated", "session.diff", "session.next.agent.switched", "session.next.model.switched"}:
            return None
        if _is_noise_part_kind(kind) or str(raw_type or "").lower() in {"part.step-start", "part.step-finish"}:
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
        is_tool_like_event = kind not in PROCESS_EVENT_KINDS and any(
            token in kind for token in ("tool", "bash", "file", "patch")
        )
        trace_kind = "tool_call" if is_tool_like_event else "event"
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

    def _build_commentary_trace(
        self,
        *,
        message_id: str,
        text: str,
        reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        summary = _normalized_commentary_summary(text)
        if not summary:
            return None
        message_key = str(message_id or "").strip()
        summary_key = _commentary_summary_key(summary)
        seen_message_ids = self.commentary_trace_summary_message_ids.setdefault(summary_key, set())
        if message_key in seen_message_ids:
            return None
        unstable_message_id = _is_unstable_commentary_message_id(message_key)
        if unstable_message_id and seen_message_ids:
            return None
        if not unstable_message_id and any(_is_unstable_commentary_message_id(seen) for seen in seen_message_ids):
            return None
        seen_message_ids.add(message_key)
        return self._trace(
            "commentary",
            summary,
            {
                **payload,
                "messageID": str(message_id or ""),
                "reason": str(reason or ""),
            },
            raw_type="message.text.reclassified",
        )

    def reconcile_messages(self, messages: list[dict[str, Any]], *, require_completed: bool = False) -> str:
        selected_text = ""
        selected_message_id = ""
        selected_completed = False
        for message in messages:
            role = str(message.get("role") or "").lower()
            if role != "assistant":
                continue
            is_followup = _message_expects_followup(message)
            message_id = _message_id(message)
            completed = _message_completed(message)
            if is_followup and message_id:
                self.followup_message_ids.add(message_id)
                self.has_followup_activity = True
                self._discard_message_text(message_id)
            parts = message.get("parts") if isinstance(message.get("parts"), list) else []
            for part in parts:
                if not isinstance(part, dict) or not _is_tool_part(part) or not _tool_part_failed(part):
                    continue
                effective_part = dict(part)
                if message_id and not _message_id_from_payload(effective_part, effective_part):
                    effective_part["messageID"] = message_id
                result = self._tool_part_updated(effective_part)
                self.reconciled_trace.extend(result.trace)
            text = _message_parts_text(message.get("parts")) or _value_text(message.get("text") or message.get("content"))
            if is_followup or not text or (require_completed and not completed):
                continue
            selected_text = text
            selected_message_id = message_id
            selected_completed = completed
        if selected_text:
            self.final_text = selected_text
            self.text_parts.clear()
            self.pending_followup = False
            if selected_message_id:
                self.assistant_message_id = selected_message_id
                self.final_message_id = selected_message_id
            if selected_completed:
                self.assistant_completed = True
        return self.text()

    def _part_belongs_to_current_turn(self, message_id: str) -> bool:
        normalized = str(message_id or "").strip()
        if not normalized:
            return False
        if normalized.startswith("evt_"):
            return False
        current = str(self.assistant_message_id or "").strip()
        if current and normalized != current:
            return current in self.followup_message_ids or self.has_followup_activity or bool(self.text())
        return True

    def _remember_part_order(self, part_id: str) -> None:
        normalized = str(part_id or "").strip()
        if not normalized or normalized in self.part_orders:
            return
        self.part_orders[normalized] = self.next_part_order
        self.next_part_order += 1

    def _ordered_part_ids(self, values: dict[str, Any] | list[str]) -> list[str]:
        part_ids = list(values.keys()) if isinstance(values, dict) else list(values)
        return sorted(part_ids, key=lambda part_id: (self.part_orders.get(part_id, 1_000_000), part_id))

    def _discard_message_text(self, message_id: str) -> tuple[bool, str]:
        target = str(message_id or "").strip()
        if not target:
            return False, ""
        changed = False
        discarded_chunks: list[str] = []
        target_part_ids = [
            part_id
            for part_id, part_message_id in self.part_message_ids.items()
            if part_message_id == target
        ]
        for part_id in self._ordered_part_ids(target_part_ids):
            discarded = self.text_parts.pop(part_id, None)
            if discarded is not None:
                changed = True
                discarded_chunks.append(discarded)
        if target == self.assistant_message_id:
            changed = bool(self.final_text) or changed
            if self.final_text:
                part_text = "".join(discarded_chunks)
                if self.final_text != part_text:
                    discarded_chunks.append(self.final_text)
            self.final_text = ""
        return changed, "".join(discarded_chunks)

    def _switch_assistant_message(self, message_id: str, *, preserve_message_id: str = "") -> tuple[bool, str]:
        target = str(message_id or "").strip()
        current = str(self.assistant_message_id or "").strip()
        if not target or not current or target == current:
            return False, ""
        preserve_target = str(preserve_message_id or "").strip()
        preserved_text_parts: dict[str, str] = {}
        discarded_chunks: list[str] = []
        for part_id in self._ordered_part_ids(self.text_parts):
            text = self.text_parts.get(part_id, "")
            if preserve_target and self.part_message_ids.get(part_id) == preserve_target:
                preserved_text_parts[part_id] = text
            elif text:
                discarded_chunks.append(text)
        if self.final_text:
            discarded_chunks.append(self.final_text)
        discarded_text = "".join(discarded_chunks)
        changed = bool(discarded_text)
        self.text_parts = preserved_text_parts
        self.final_text = ""
        self.assistant_completed = False
        self.final_message_id = ""
        return changed, discarded_text

    def _flush_message_text_as_commentary(
        self,
        *,
        message_id: str,
        reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        changed, discarded_text = self._discard_message_text(message_id)
        if not changed:
            return None
        return self._build_commentary_trace(
            message_id=message_id,
            text=discarded_text,
            reason=reason,
            payload=payload,
        )


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


def _tool_part_failed(part: dict[str, Any]) -> bool:
    state_payload = part.get("state") if isinstance(part.get("state"), dict) else {}
    state = str(
        state_payload.get("status")
        or part.get("state")
        or part.get("status")
        or ""
    ).strip().lower()
    return state in {"error", "failed", "failure", "cancelled", "canceled", "aborted", "abort"} or bool(
        _value_text(part.get("error") or state_payload.get("error"))
    )


def _is_noise_part_kind(kind: str) -> bool:
    normalized = str(kind or "").strip().lower()
    return normalized in {"step-start", "step-finish"} or normalized.startswith("step-")


def _explicit_failure_message(event_type: str, payload: dict[str, Any]) -> str:
    raw_text = _json_text(payload)
    if "MessageAbortedError" in raw_text:
        return "MessageAbortedError"
    if "Tool execution aborted" in raw_text:
        return "Tool execution aborted"
    error = _first_failure_text(payload, keys=("error", "errorMessage", "error_message"))
    if error:
        return error
    state = _first_failure_text(payload, keys=("state", "status"))
    if str(event_type or "").strip().lower() == "session.error":
        return _value_text(payload.get("message") or payload) or "原生 agent 执行失败"
    if state.lower() in {"error", "failed", "failure", "cancelled", "canceled", "aborted", "abort"}:
        return state
    return ""


def _first_failure_text(value: Any, *, keys: tuple[str, ...]) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_failure_text(item, keys=keys)
            if text:
                return text
        return ""
    if not isinstance(value, dict):
        return ""
    for key in keys:
        current = value.get(key)
        if current is None:
            continue
        if isinstance(current, dict):
            text = _first_failure_text(current, keys=keys) or _value_text(current)
        else:
            text = _value_text(current)
        if text:
            return text
    for key in ("payload", "properties", "message", "part", "state", "info", "metadata"):
        nested = value.get(key)
        text = _first_failure_text(nested, keys=keys)
        if text:
            return text
    return ""


def _message_expects_followup(message: dict[str, Any]) -> bool:
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    return finish in {"tool-calls", "tool_calls", "tool-call", "tool_call"}


def _message_completed(message: dict[str, Any]) -> bool:
    if _message_expects_followup(message):
        return False
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    if finish in {"stop", "stopped", "complete", "completed", "done", "success", "end", "finished"}:
        return True
    time_payload = message.get("time")
    if isinstance(time_payload, dict) and time_payload.get("completed"):
        return True
    for key in ("completed", "completed_at", "completedAt"):
        if message.get(key):
            return True
    state = str(message.get("state") or message.get("status") or "").strip().lower()
    return state in {"completed", "done", "idle", "success"}
