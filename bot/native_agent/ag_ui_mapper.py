from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from typing import Any

from ag_ui import core

from bot.native_agent.aggregator import NativeAgentAggregationResult
from bot.native_agent.events import NativeAgentEvent

_FILTERED_EVENT_TYPES = {"server.connected", "server.heartbeat"}


@dataclass
class AgUiTurnState:
    thread_id: str
    run_id: str
    user_message_id: str
    assistant_message_id: str
    started: bool = False
    text_started: bool = False
    text_ended: bool = False
    last_status_message_id: str = ""
    permission_message_ids: dict[str, str] = field(default_factory=dict)
    reasoning_started: set[str] = field(default_factory=set)
    reasoning_text: dict[str, str] = field(default_factory=dict)
    reasoning_ended: set[str] = field(default_factory=set)
    tool_call_started: set[str] = field(default_factory=set)
    tool_call_args: dict[str, str] = field(default_factory=dict)
    tool_call_ended: set[str] = field(default_factory=set)
    tool_call_results: dict[str, str] = field(default_factory=dict)
    trace_activity_count: int = 0


def should_filter_event(event: NativeAgentEvent | None) -> bool:
    return event is None or event.type in _FILTERED_EVENT_TYPES


def build_run_started_event(
    *,
    state: AgUiTurnState,
    user_text: str,
) -> core.RunStartedEvent:
    state.started = True
    return core.RunStartedEvent(
        threadId=state.thread_id,
        runId=state.run_id,
        timestamp=_timestamp_ms(),
        input=core.RunAgentInput(
            threadId=state.thread_id,
            runId=state.run_id,
            state={},
            messages=[
                core.UserMessage(
                    id=state.user_message_id,
                    content=user_text,
                )
            ],
            tools=[],
            context=[],
            forwardedProps={},
        ),
    )


def build_run_finished_event(
    *,
    state: AgUiTurnState,
    completion_state: str,
    content: str,
    context_usage: dict[str, Any] | None = None,
    message: dict[str, Any] | None = None,
    turn_id: str = "",
    assistant_message_id: str = "",
) -> core.RunFinishedEvent:
    if completion_state != "completed":
        outcome: Any = core.RunFinishedInterruptOutcome(
            type="interrupt",
            interrupts=[{"id": f"interrupt_{state.run_id}", "reason": completion_state}],
        )
    else:
        outcome = core.RunFinishedSuccessOutcome(type="success")
    result: dict[str, Any] = {
        "content": content,
        "completion_state": completion_state,
        "turn_id": str(turn_id or state.run_id),
        "assistant_message_id": str(assistant_message_id or state.assistant_message_id),
    }
    if message:
        result["message"] = dict(message)
    if context_usage:
        result["context_usage"] = context_usage
        result["contextUsage"] = context_usage
    return core.RunFinishedEvent(
        threadId=state.thread_id,
        runId=state.run_id,
        timestamp=_timestamp_ms(),
        result=result,
        outcome=outcome,
    )


def build_run_error_event(message: str, *, code: str = "native_agent_error") -> core.RunErrorEvent:
    return core.RunErrorEvent(
        timestamp=_timestamp_ms(),
        message=message,
        code=code,
    )


def map_event(
    *,
    event: NativeAgentEvent,
    result: NativeAgentAggregationResult,
    state: AgUiTurnState,
) -> list[core.BaseEvent]:
    if should_filter_event(event):
        return []
    mapped: list[core.BaseEvent] = []
    if event.type in {"permission.updated", "permission.replied"}:
        mapped.extend(_map_permission_event(event, state))
    if event.type == "session.status":
        mapped.extend(_map_status_event(event, state))
    structured_events = _map_structured_part_event(event, state)
    if result.delta:
        if not state.text_started:
            mapped.append(
                core.TextMessageStartEvent(
                    timestamp=_timestamp_ms(),
                    messageId=state.assistant_message_id,
                    role="assistant",
                )
            )
            state.text_started = True
        mapped.append(
            core.TextMessageContentEvent(
                timestamp=_timestamp_ms(),
                messageId=state.assistant_message_id,
                delta=result.delta,
            )
        )
    if result.snapshot or result.replace_text:
        if not state.text_started:
            mapped.append(
                core.TextMessageStartEvent(
                    timestamp=_timestamp_ms(),
                    messageId=state.assistant_message_id,
                    role="assistant",
                )
            )
            state.text_started = True
        mapped.append(
            core.MessagesSnapshotEvent(
                timestamp=_timestamp_ms(),
                messages=[
                    core.AssistantMessage(
                        id=state.assistant_message_id,
                        content=result.snapshot,
                    )
                ],
            )
        )
    if result.trace:
        trace_events = result.trace
        if structured_events:
            trace_events = [
                trace
                for trace in trace_events
                if str(trace.get("kind") or "").strip().lower() not in {"tool_call", "tool_result"}
            ]
        if trace_events:
            mapped.extend(_map_trace_events(trace_events, state))
    if structured_events:
        mapped.extend(structured_events)
    return mapped


def build_text_end_event(*, state: AgUiTurnState) -> core.TextMessageEndEvent | None:
    if not state.text_started or state.text_ended:
        return None
    state.text_ended = True
    return core.TextMessageEndEvent(
        timestamp=_timestamp_ms(),
        messageId=state.assistant_message_id,
    )


def build_text_message_events(*, state: AgUiTurnState, content: str) -> list[core.BaseEvent]:
    if not content:
        return []
    mapped: list[core.BaseEvent] = []
    if not state.text_started:
        mapped.append(
            core.TextMessageStartEvent(
                timestamp=_timestamp_ms(),
                messageId=state.assistant_message_id,
                role="assistant",
            )
        )
        state.text_started = True
    mapped.append(
        core.TextMessageContentEvent(
            timestamp=_timestamp_ms(),
            messageId=state.assistant_message_id,
            delta=content,
        )
    )
    return mapped


def _build_status_event(*, state: AgUiTurnState, activity_type: str, content: dict[str, Any]) -> core.ActivitySnapshotEvent:
    if not state.last_status_message_id:
        state.last_status_message_id = f"activity_{state.run_id}"
    return core.ActivitySnapshotEvent(
        timestamp=_timestamp_ms(),
        messageId=state.last_status_message_id,
        activityType=activity_type,
        content=content,
        replace=True,
    )


def _map_permission_event(event: NativeAgentEvent, state: AgUiTurnState) -> list[core.BaseEvent]:
    payload = event.payload
    if event.permission:
        permission = event.permission
    elif isinstance(payload.get("permission"), dict):
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
    ).strip() or f"permission_{state.run_id}"
    message_id = state.permission_message_ids.setdefault(permission_id, f"activity_{permission_id}")
    title = str(permission.get("title") or permission.get("message") or permission.get("action") or "").strip()
    content = {
        "id": permission_id,
        "permissionId": permission_id,
        "permission_id": permission_id,
        "title": title or "原生 agent 请求权限",
        "message": str(permission.get("message") or "").strip(),
        "uiKind": str(permission.get("uiKind") or permission.get("ui_kind") or "confirm").strip() or "confirm",
        "options": permission.get("options"),
        "defaultValue": permission.get("defaultValue") if "defaultValue" in permission else permission.get("default_value"),
        "placeholder": permission.get("placeholder"),
        "value": permission.get("value"),
        "state": str(permission.get("status") or permission.get("state") or event.type),
        "source": "native_agent",
        "payload": permission,
    }
    return [
        core.ActivitySnapshotEvent(
            timestamp=_timestamp_ms(),
            messageId=message_id,
            activityType="TCB_PERMISSION_REQUEST",
            content=content,
            replace=True,
        )
    ]


def _map_status_event(event: NativeAgentEvent, state: AgUiTurnState) -> list[core.BaseEvent]:
    payload = event.payload
    pi_event_type = str(payload.get("piEventType") or "").strip()
    ui_kind = str(payload.get("uiKind") or payload.get("ui_kind") or "").strip()
    if not pi_event_type and not ui_kind:
        return []
    status = event.status or _payload_text(payload.get("status") or payload.get("summary") or payload.get("message"))
    content = {
        "id": str(payload.get("id") or payload.get("messageID") or f"status_{state.run_id}"),
        "summary": status,
        "message": status,
        "previewText": status,
        "source": "native_agent",
        "rawType": "session.status",
        "rawKind": "status",
        "piEventType": pi_event_type,
        "uiKind": ui_kind or pi_event_type,
        "payload": payload,
    }
    return [_build_status_event(state=state, activity_type="TCB_STATUS", content=content)]


def _map_structured_part_event(event: NativeAgentEvent, state: AgUiTurnState) -> list[core.BaseEvent]:
    if event.type != "message.part.updated":
        return []
    part = event.part or (event.payload.get("part") if isinstance(event.payload.get("part"), dict) else {})
    if not isinstance(part, dict) or not part:
        return []
    kind = str(part.get("type") or part.get("kind") or "").strip().lower()
    if kind in {"reasoning", "thinking"}:
        return []
    if kind in {"step-start", "step-finish"} or kind.startswith("step-"):
        return []
    if _is_tool_part(part):
        return _map_tool_part(part, state)
    return []


def _map_reasoning_part(event: NativeAgentEvent, part: dict[str, Any], state: AgUiTurnState) -> list[core.BaseEvent]:
    message_id = _part_id(part) or event.message_id or f"reasoning_{state.run_id}"
    mapped: list[core.BaseEvent] = []
    if message_id not in state.reasoning_started:
        state.reasoning_started.add(message_id)
        mapped.append(core.ReasoningStartEvent(timestamp=_timestamp_ms(), messageId=message_id))
    incoming = event.delta or _payload_text(part.get("text") or part.get("content") or part.get("delta"))
    previous = state.reasoning_text.get(message_id, "")
    delta = ""
    if incoming:
        if event.delta:
            delta = incoming
            state.reasoning_text[message_id] = previous + incoming
        elif incoming.startswith(previous):
            delta = incoming[len(previous):]
            state.reasoning_text[message_id] = incoming
        else:
            delta = incoming
            state.reasoning_text[message_id] = incoming
    if delta:
        mapped.append(core.ReasoningMessageContentEvent(timestamp=_timestamp_ms(), messageId=message_id, delta=delta))
    part_state = str(part.get("state") or part.get("status") or "").strip().lower()
    if part_state in {"completed", "done", "finished"} and message_id not in state.reasoning_ended:
        state.reasoning_ended.add(message_id)
        mapped.append(core.ReasoningEndEvent(timestamp=_timestamp_ms(), messageId=message_id))
    return mapped


def _map_tool_part(part: dict[str, Any], state: AgUiTurnState) -> list[core.BaseEvent]:
    call_id = _tool_call_id(part) or _part_id(part) or f"tool_{len(state.tool_call_started) + 1}"
    tool_name = str(part.get("tool") or part.get("toolName") or part.get("name") or part.get("command") or "tool").strip()
    mapped: list[core.BaseEvent] = []
    if call_id not in state.tool_call_started:
        state.tool_call_started.add(call_id)
        mapped.append(
            core.ToolCallStartEvent(
                timestamp=_timestamp_ms(),
                toolCallId=call_id,
                toolCallName=tool_name,
                parentMessageId=state.assistant_message_id,
            )
        )
    args_text = _tool_args_text(part)
    if args_text:
        previous_args = state.tool_call_args.get(call_id, "")
        delta = args_text[len(previous_args):] if args_text.startswith(previous_args) else args_text
        if delta:
            mapped.append(core.ToolCallArgsEvent(timestamp=_timestamp_ms(), toolCallId=call_id, delta=delta))
            state.tool_call_args[call_id] = args_text
    state_text = str(part.get("state") or part.get("status") or "").strip().lower()
    result_text = _tool_result_text(part)
    if state_text in {"completed", "done", "finished", "success", "error", "failed"} and call_id not in state.tool_call_ended:
        state.tool_call_ended.add(call_id)
        mapped.append(core.ToolCallEndEvent(timestamp=_timestamp_ms(), toolCallId=call_id))
    if result_text and state.tool_call_results.get(call_id) != result_text:
        state.tool_call_results[call_id] = result_text
        mapped.append(
            core.ToolCallResultEvent(
                timestamp=_timestamp_ms(),
                messageId=f"tool_result_{call_id}",
                toolCallId=call_id,
                role="tool",
                content=result_text,
            )
        )
    return mapped


def _map_trace_events(trace_events: list[dict[str, Any]], state: AgUiTurnState) -> list[core.BaseEvent]:
    mapped: list[core.BaseEvent] = []
    for trace in trace_events:
        kind = str(trace.get("kind") or "").strip().lower()
        call_id = str(trace.get("call_id") or trace.get("tool_call_id") or trace.get("id") or "").strip()
        tool_name = str(trace.get("tool_name") or trace.get("name") or "").strip()
        summary = str(trace.get("summary") or "").strip()
        payload = trace.get("payload")
        if kind == "tool_call" and call_id:
            mapped.append(
                core.ToolCallStartEvent(
                    timestamp=_timestamp_ms(),
                    toolCallId=call_id,
                    toolCallName=tool_name or summary or "tool_call",
                    parentMessageId=state.assistant_message_id,
                )
            )
            args_text = _payload_text(payload)
            if args_text:
                mapped.append(
                    core.ToolCallArgsEvent(
                        timestamp=_timestamp_ms(),
                        toolCallId=call_id,
                        delta=args_text,
                    )
                )
            mapped.append(
                core.ToolCallEndEvent(
                    timestamp=_timestamp_ms(),
                    toolCallId=call_id,
                )
            )
            continue
        if kind == "tool_result" and call_id:
            mapped.append(
                core.ToolCallResultEvent(
                    timestamp=_timestamp_ms(),
                    messageId=f"tool_result_{call_id}",
                    toolCallId=call_id,
                    role="tool",
                    content=summary or _payload_text(payload),
                )
            )
            continue
        message_id = f"activity_{state.run_id}_trace_{state.trace_activity_count}"
        state.trace_activity_count += 1
        mapped.append(
            core.ActivitySnapshotEvent(
                timestamp=_timestamp_ms(),
                messageId=message_id,
                activityType="TCB_NATIVE_AGENT_TRACE",
                content={
                    "id": message_id,
                    "kind": kind or "event",
                    "rawKind": kind or "event",
                    "rawType": str(trace.get("raw_type") or ""),
                    "source": str(trace.get("source") or "native_agent"),
                    "summary": summary,
                    "payload": payload,
                },
                replace=True,
            )
        )
    return mapped


def _payload_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (int, float, bool)):
        return str(payload)
    if isinstance(payload, list):
        return "".join(_payload_text(item) for item in payload)
    if isinstance(payload, dict):
        for key in ("arguments", "args", "output", "result", "content", "text", "message", "summary"):
            if key in payload:
                text = _payload_text(payload.get(key))
                if text:
                    return text
        return ""
    return ""


def _part_id(part: dict[str, Any]) -> str:
    for key in ("id", "partID", "part_id", "partId"):
        value = part.get(key)
        if value:
            return str(value)
    return ""


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


def _tool_args_text(part: dict[str, Any]) -> str:
    for key in ("arguments", "raw_arguments", "args", "input", "params"):
        if key in part:
            return _json_text(part.get(key))
    return ""


def _tool_result_text(part: dict[str, Any]) -> str:
    for key in ("result", "output", "error"):
        if key in part:
            return _json_text(part.get(key))
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


def _timestamp_ms() -> int:
    return int(time.time() * 1000)
