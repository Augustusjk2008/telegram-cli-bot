import pytest
from ag_ui import core

from bot.native_agent.ag_ui_mapper import (
    AgUiTurnState,
    build_run_finished_event,
    compact_run_finished_event,
    is_ag_ui_trace_event,
)


def test_run_finished_contains_authoritative_persisted_message() -> None:
    state = AgUiTurnState(
        thread_id="thread-1",
        run_id="run-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    message = {
        "id": "assistant-1",
        "turn_id": "turn-1",
        "role": "assistant",
        "content": "最终答复",
        "state": "done",
    }

    event = build_run_finished_event(
        state=state,
        completion_state="completed",
        content="最终答复",
        context_usage={"status_text": "90% context left"},
        message=message,
        turn_id="turn-1",
        assistant_message_id="assistant-1",
    )

    assert event.result["message"] == message
    assert event.result["content"] == "最终答复"
    assert event.result["turn_id"] == "turn-1"
    assert event.result["assistant_message_id"] == "assistant-1"
    assert compact_run_finished_event(event, 1) is event


@pytest.mark.parametrize(
    ("content", "message_content", "expects_content"),
    [
        ("最终答复", "最终答复", False),
        ("", "", False),
        ("流式答复", "持久化答复", True),
    ],
)
def test_compact_run_finished_deduplicates_only_matching_content(
    content: str,
    message_content: str,
    expects_content: bool,
) -> None:
    state = AgUiTurnState(
        thread_id="thread-compact",
        run_id="run-compact",
        user_message_id="user-compact",
        assistant_message_id="assistant-compact",
    )
    message = {
        "id": "assistant-compact",
        "turn_id": "turn-compact",
        "role": "assistant",
        "content": message_content,
        "state": "done",
    }

    canonical = build_run_finished_event(
        state=state,
        completion_state="completed",
        content=content,
        context_usage={"status_text": "90% context left"},
        message=message,
        turn_id="turn-compact",
        assistant_message_id="assistant-compact",
    )
    event = compact_run_finished_event(canonical, 2)

    assert canonical.result["content"] == content
    assert ("content" in event.result) is expects_content
    if expects_content:
        assert event.result["content"] == content
    assert event.result["message"] == message
    assert event.result["completion_state"] == "completed"
    assert event.result["context_usage"] == {"status_text": "90% context left"}
    assert event.result["contextUsage"] == {"status_text": "90% context left"}
    assert event.result["turn_id"] == "turn-compact"
    assert event.result["assistant_message_id"] == "assistant-compact"


def test_compact_run_finished_preserves_interrupt_outcome_and_message() -> None:
    state = AgUiTurnState(
        thread_id="thread-cancelled",
        run_id="run-cancelled",
        user_message_id="user-cancelled",
        assistant_message_id="assistant-cancelled",
    )
    message = {
        "id": "assistant-cancelled",
        "content": "任务已取消",
        "state": "done",
        "meta": {"completion_state": "cancelled"},
    }

    canonical = build_run_finished_event(
        state=state,
        completion_state="cancelled",
        content="任务已取消",
        message=message,
        turn_id="turn-cancelled",
        assistant_message_id="assistant-cancelled",
    )
    event = compact_run_finished_event(canonical, 2)

    assert canonical.result["content"] == "任务已取消"
    assert "content" not in event.result
    assert event.result["message"] == message
    assert event.result["completion_state"] == "cancelled"
    assert event.result["turn_id"] == "turn-cancelled"
    assert event.result["assistant_message_id"] == "assistant-cancelled"
    assert event.outcome.type == "interrupt"


def test_trace_visibility_keeps_permission_and_terminal_activity() -> None:
    tool_event = core.ToolCallStartEvent(toolCallId="call-1", toolCallName="shell_command")
    trace_event = core.ActivitySnapshotEvent(
        messageId="trace-1",
        activityType="TCB_NATIVE_AGENT_TRACE",
        content={},
    )
    permission_event = core.ActivitySnapshotEvent(
        messageId="permission-1",
        activityType="TCB_PERMISSION_REQUEST",
        content={},
    )
    finished_event = core.RunFinishedEvent(threadId="thread-1", runId="run-1", result={})

    assert is_ag_ui_trace_event(tool_event) is True
    assert is_ag_ui_trace_event(trace_event) is True
    assert is_ag_ui_trace_event(permission_event) is False
    assert is_ag_ui_trace_event(finished_event) is False
