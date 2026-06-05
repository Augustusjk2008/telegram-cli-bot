from __future__ import annotations

import time
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


def build_run_finished_event(*, state: AgUiTurnState, completion_state: str, content: str) -> core.RunFinishedEvent:
    if completion_state == "cancelled":
        outcome: Any = core.RunFinishedInterruptOutcome(type="interrupt", interrupts=[])
    else:
        outcome = core.RunFinishedSuccessOutcome(type="success")
    return core.RunFinishedEvent(
        threadId=state.thread_id,
        runId=state.run_id,
        timestamp=_timestamp_ms(),
        result={"content": content, "completion_state": completion_state},
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
    if result.snapshot:
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
    if result.status:
        mapped.append(
            _build_status_event(
                state=state,
                activity_type="TCB_STATUS",
                content={
                    "previewText": result.status,
                    "rawType": event.type,
                    "source": "native_agent",
                },
            )
        )
    if result.trace:
        mapped.extend(_map_trace_events(result.trace, state))
    return mapped


def build_text_end_event(*, state: AgUiTurnState) -> core.TextMessageEndEvent | None:
    if not state.text_started or state.text_ended:
        return None
    state.text_ended = True
    return core.TextMessageEndEvent(
        timestamp=_timestamp_ms(),
        messageId=state.assistant_message_id,
    )


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
    ).strip() or f"permission_{state.run_id}"
    message_id = state.permission_message_ids.setdefault(permission_id, f"activity_{permission_id}")
    title = str(permission.get("title") or permission.get("message") or permission.get("action") or "").strip()
    content = {
        "id": permission_id,
        "permissionId": permission_id,
        "permission_id": permission_id,
        "title": title or "原生 agent 请求权限",
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
        mapped.append(
            core.ActivitySnapshotEvent(
                timestamp=_timestamp_ms(),
                messageId=f"activity_{state.run_id}_{len(mapped)}",
                activityType="TCB_NATIVE_AGENT_TRACE",
                content={
                    "kind": kind or "event",
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


def _timestamp_ms() -> int:
    return int(time.time() * 1000)
