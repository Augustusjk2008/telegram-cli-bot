from __future__ import annotations

from pathlib import Path

from bot.web.chat_store import ChatStore


def _voice_handle(store: ChatStore, *, user_id: int = 2):
    return store.ensure_voice_turn(
        bot_id=1,
        bot_alias="main",
        user_id=user_id,
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        task_submission_key="submission-1",
        codex_turn_id="codex-turn-1",
        realtime_session_id="realtime-1",
    )


def test_voice_submission_key_is_scoped_to_explicit_conversation(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    first = _voice_handle(store)
    second_conversation = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        agent_id="main",
        cli_type="codex",
        working_dir=str(tmp_path),
        session_epoch=0,
        native_provider="codex",
    )

    second = store.ensure_voice_turn(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        working_dir=str(tmp_path),
        session_epoch=0,
        task_submission_key="submission-1",
        codex_turn_id="codex-turn-2",
        realtime_session_id="realtime-2",
        conversation_id=second_conversation,
    )

    assert second.conversation_id == second_conversation
    assert second.turn_id != first.turn_id


def test_voice_schema_submission_and_event_are_idempotent(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _voice_handle(store)
    duplicate = _voice_handle(store)

    assert duplicate == handle
    running = store.get_running_reply(
        bot_id=1,
        user_id=2,
        working_dir=str(tmp_path),
        session_epoch=0,
        conversation_id=handle.conversation_id,
        native_provider="codex",
    )
    assert running is not None
    assert running["voice"]["tcb_turn_id"] == handle.turn_id
    assert running["voice"]["state"] == "active"
    revision = store.get_conversation_revision(handle.conversation_id)
    event = {
        "event_id": "event-1",
        "seq": 1,
        "event_name": "transcript.completed",
        "item_id": "user-item-1",
        "role": "user",
        "transcript": "hello",
        "is_final": True,
        "task_state": "active",
    }
    assert store.record_voice_event(handle, event) is True
    after_event = store.get_conversation_revision(handle.conversation_id)
    assert after_event == revision + 1
    assert store.record_voice_event(
        handle,
        {
            "event_id": "assistant-preview",
            "role": "assistant",
            "transcript": "partial answer",
            "is_final": True,
            "task_state": "active",
        },
    ) is True
    running = store.get_running_reply(
        bot_id=1,
        user_id=2,
        working_dir=str(tmp_path),
        session_epoch=0,
        conversation_id=handle.conversation_id,
        native_provider="codex",
    )
    assert running is not None
    assert running["voice"]["state"] == "active"
    after_preview = store.get_conversation_revision(handle.conversation_id)

    event["transcript"] = "different"
    assert store.record_voice_event(handle, event) is False
    assert store.get_conversation_revision(handle.conversation_id) == after_preview

    assistant_event = {
        "event_id": "event-2",
        "seq": 2,
        "event_name": "turn.completed",
        "item_id": "assistant-item-1",
        "role": "assistant",
        "transcript": "answer",
        "is_final": True,
        "task_state": "completed",
        "trace_events": [{"kind": "tool_call", "summary": "run tool"}],
    }
    assert store.record_voice_event(handle, assistant_event) is True
    assert store.record_voice_event(
        handle,
        {**assistant_event, "transcript": "late answer", "task_state": "failed"},
    ) is False

    task = store.get_voice_task(handle)
    assert task["state"] == "completed"
    assert task["codex_turn_id"] == "codex-turn-1"
    assert task["realtime_session_id"] == "realtime-1"
    assert task["transcript_state"]["user_final"] is True
    assert task["transcript_state"]["assistant_final"] is True
    assert task["persistence"]["trace"] is True
    assert task["persistence"]["voice_events"] == 3

    messages = store.list_messages(handle.conversation_id)
    assistant = next(item for item in messages if item["id"] == handle.assistant_message_id)
    assert assistant["content"] == "answer"
    assert assistant["meta"]["voice"]["state"] == "completed"
    assert assistant["meta"]["voice"]["assistant_message_id"] == handle.assistant_message_id
    assert assistant["meta"]["tool_call_count"] == 1


def test_voice_turn_is_skipped_by_stale_stream_reconcile_and_supports_request_id(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _voice_handle(store)
    assert store.mark_stale_streaming_turns(
        bot_id=1,
        user_id=2,
        working_dir=str(tmp_path),
        session_epoch=0,
        conversation_id=handle.conversation_id,
        native_provider="codex",
    ) == 0

    before_append = store.get_conversation_revision(handle.conversation_id)
    appended = store.append_user_message_to_turn(
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="follow-up",
        request_id="request-1",
        native_provider="codex",
    )
    after_append = store.get_conversation_revision(handle.conversation_id)
    assert after_append == before_append + 1
    duplicate = store.append_user_message_to_turn(
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="different follow-up",
        request_id="request-1",
        native_provider="codex",
    )
    assert duplicate["id"] == appended["id"]
    assert store.get_conversation_revision(handle.conversation_id) == after_append
    assert store.find_voice_steer_request(handle.turn_id, "request-1")["id"] == appended["id"]

    by_message_id = store.append_user_message_to_turn(
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="message-id follow-up",
        message_id="msg_steer_fixed",
        native_provider="codex",
    )
    message_id_duplicate = store.append_user_message_to_turn(
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="different message-id follow-up",
        message_id="msg_steer_fixed",
        native_provider="codex",
    )
    assert message_id_duplicate["id"] == by_message_id["id"]
    assert [item["role"] for item in store.list_messages(handle.conversation_id)] == [
        "user", "user", "user", "assistant",
    ]


def test_voice_completion_closes_interim_user_message_without_marking_transcript_final(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _voice_handle(store)
    assert store.record_voice_event(
        handle,
        {
            "event_id": "user-interim",
            "role": "user",
            "transcript": "unfinished user transcript",
            "is_final": False,
            "task_state": "active",
        },
    ) is True

    store.complete_voice_turn(
        handle,
        content="completed answer",
        completion_state="completed",
    )

    messages = store.list_messages(handle.conversation_id)
    user = next(item for item in messages if item["id"] == handle.user_message_id)
    assistant = next(item for item in messages if item["id"] == handle.assistant_message_id)
    assert user["state"] == "done"
    assert assistant["state"] == "done"
    task = store.get_voice_task(handle)
    assert task["state"] == "completed"
    assert task["transcript_state"]["user_final"] is False


def test_terminal_voice_event_persists_native_session_and_closes_user_message(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _voice_handle(store)
    assert store.record_voice_event(
        handle,
        {
            "event_id": "user-interim",
            "role": "user",
            "transcript": "unfinished user transcript",
            "is_final": False,
            "task_state": "active",
        },
    ) is True
    assert store.record_voice_event(
        handle,
        {
            "event_id": "turn-completed",
            "task_state": "completed",
            "native_session_id": "runtime-thread-1",
        },
    ) is True

    context = store.get_trace_recovery_context(handle.assistant_message_id)
    assert context["completion_state"] == "completed"
    assert context["native_session_id"] == "runtime-thread-1"
    user = store.get_message(handle.user_message_id)
    assert user["state"] == "done"
    assert store.get_voice_task(handle)["transcript_state"]["user_final"] is False
