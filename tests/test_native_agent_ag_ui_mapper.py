from ag_ui import core

from bot.native_agent.ag_ui_mapper import AgUiTurnState, build_run_finished_event, is_ag_ui_trace_event


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
    assert event.result["turn_id"] == "turn-1"
    assert event.result["assistant_message_id"] == "assistant-1"


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
