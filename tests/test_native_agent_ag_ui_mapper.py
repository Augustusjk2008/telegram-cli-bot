from bot.native_agent.ag_ui_mapper import AgUiTurnState, build_run_finished_event


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
