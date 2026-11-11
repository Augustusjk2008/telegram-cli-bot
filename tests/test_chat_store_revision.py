from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from bot.web.chat_store import ChatStore, clear_chat_store_prepare_cache
from bot.web import api_service


def _begin(
    store: ChatStore,
    *,
    conversation_id: str | None = None,
    text: str = "hello",
    user_id: int = 2,
    agent_id: str = "main",
):
    return store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=user_id,
        agent_id=agent_id,
        cli_type="codex",
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        user_text=text,
        native_provider="codex",
        conversation_id=conversation_id,
    )


def test_history_revision_delta_tracks_add_stream_update_and_finalize(tmp_path: Path) -> None:
    # ChatStore keeps workspace databases under the process-level TCB root;
    # use a fresh workspace key when pytest reuses its temp directory.
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)

    initial = store.get_history_delta(handle.conversation_id, revision=0, limit=20)
    assert initial["reset"] is True
    assert {item["id"] for item in initial["items"]} == {
        handle.user_message_id,
        handle.assistant_message_id,
    }
    first_revision = initial["revision"]

    store.replace_assistant_content(handle, "partial", state="streaming")
    streaming = store.get_history_delta(handle.conversation_id, revision=first_revision, limit=20)
    assert [item["id"] for item in streaming["items"]] == [handle.assistant_message_id]
    assert streaming["items"][0]["content"] == "partial"

    store.complete_turn(handle, content="final", completion_state="completed")
    finalized = store.get_history_delta(
        handle.conversation_id,
        revision=streaming["revision"],
        limit=20,
    )
    assert finalized["items"][0]["content"] == "final"
    assert finalized["items"][0]["state"] == "done"
    assert finalized["deleted_ids"] == []


def test_endless_group_and_events_survive_history_reload(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    first = _begin(store, text="原始问题")
    store.complete_turn(first, content="第一次失败", completion_state="error")
    group_id = store.ensure_endless_group(first.assistant_message_id, "endless_group_1")

    # The continuation reopens the original durable turn instead of creating
    # another user/assistant pair.
    retry = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        agent_id="main",
        cli_type="codex",
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        user_text="Continue",
        native_provider="codex",
        conversation_id=first.conversation_id,
        endless_group_id=group_id,
    )
    assert retry == first
    store.complete_turn(retry, content="第二次失败", completion_state="error")
    store.append_endless_event(
        turn_id=retry.turn_id,
        event={"kind": "error", "attempt": 1, "text": "第二次失败"},
    )
    store.append_endless_event(
        turn_id=retry.turn_id,
        event={"kind": "continue", "attempt": 1, "text": "Continue"},
    )

    history = store.list_messages(first.conversation_id)
    assistants = [item for item in history if item["role"] == "assistant"]
    users = [item for item in history if item["role"] == "user"]
    assert len(users) == 1
    assert len(assistants) == 1
    assert assistants[0]["meta"]["endless_group_id"] == group_id
    assert [event["kind"] for event in assistants[0]["meta"]["endless_events"]] == [
        "error", "error", "continue",
    ]
    assert assistants[0]["meta"]["endless_continue_count"] == 1


def test_endless_event_timestamps_survive_reload(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _begin(store, text="带时间的重试")
    store.complete_turn(handle, content="失败", completion_state="error")
    group_id = store.ensure_endless_group(handle.assistant_message_id, "endless_timestamps")
    store.append_endless_event(
        turn_id=handle.turn_id,
        event={
            "kind": "error",
            "attempt": 1,
            "text": "失败",
            "created_at": "2026-10-31T00:00:02+00:00",
        },
    )
    store.append_endless_event(
        turn_id=handle.turn_id,
        event={
            "kind": "continue",
            "attempt": 1,
            "text": "Continue",
            "created_at": "2026-10-31T00:00:03+00:00",
        },
    )

    clear_chat_store_prepare_cache()
    reloaded = ChatStore(tmp_path)
    assistant = next(item for item in reloaded.list_messages(handle.conversation_id) if item["role"] == "assistant")
    assert assistant["meta"]["endless_group_id"] == group_id
    timestamped_events = [event for event in assistant["meta"]["endless_events"] if event.get("created_at")]
    assert [event["created_at"] for event in timestamped_events] == [
        "2026-10-31T00:00:02+00:00",
        "2026-10-31T00:00:03+00:00",
    ]


def test_trace_stats_exclude_duplicate_final_commentary(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _begin(store, text="过程统计")
    store.append_trace_event(handle.turn_id, kind="commentary", summary="分析过程")
    store.append_trace_event(handle.turn_id, kind="commentary", summary="最终回答")
    store.complete_turn(handle, content="最终回答", completion_state="completed")

    assistant = next(item for item in store.list_messages(handle.conversation_id) if item["role"] == "assistant")
    assert assistant["meta"]["trace_count"] == 1
    assert assistant["meta"]["process_count"] == 1
    details = store.get_message_trace(handle.assistant_message_id)
    assert details["trace_count"] == 1
    assert details["process_count"] == 1


def test_legacy_endless_group_is_consolidated_in_database(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    first = _begin(store, text="原始问题")
    store.complete_turn(first, content="第一次失败", completion_state="error")
    retry = _begin(store, conversation_id=first.conversation_id, text="Continue")
    store.complete_turn(retry, content="第二次失败", completion_state="error")
    group_id = "legacy_endless_group"
    with store._connect_for_write() as conn:
        conn.execute(
            """
            UPDATE turns
            SET endless_group_id = ?, endless_events_json = ?
            WHERE id = ?
            """,
            (
                group_id,
                json.dumps([{"kind": "error", "attempt": 0, "text": "第一次失败"}], ensure_ascii=False),
                first.turn_id,
            ),
        )
        conn.execute(
            """
            UPDATE turns
            SET endless_group_id = ?, endless_events_json = ?
            WHERE id = ?
            """,
            (
                group_id,
                json.dumps([
                    {"kind": "error", "attempt": 1, "text": "第二次失败"},
                    {"kind": "continue", "attempt": 1, "text": "Continue"},
                ], ensure_ascii=False),
                retry.turn_id,
            ),
        )
    store.append_trace_event(first.turn_id, kind="event", summary="first process")
    store.append_trace_event(retry.turn_id, kind="event", summary="retry process")

    clear_chat_store_prepare_cache()
    migrated = ChatStore(tmp_path)
    history = migrated.list_messages(first.conversation_id)
    assistants = [item for item in history if item["role"] == "assistant"]
    assert len([item for item in history if item["role"] == "user"]) == 1
    assert len(assistants) == 1
    assert assistants[0]["content"] == "第二次失败"
    assert [event["kind"] for event in assistants[0]["meta"]["endless_events"]] == [
        "error", "error", "continue",
    ]
    assert assistants[0]["meta"]["trace_count"] == 2
    with migrated._connect(create=False) as conn:
        assert conn is not None
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM turns WHERE conversation_id = ?",
            (first.conversation_id,),
        ).fetchone()["count"] == 1


def test_append_user_message_to_active_turn_keeps_scope_and_revision(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _begin(store, text="first")
    before = store.get_conversation_revision(handle.conversation_id)

    appended = store.append_user_message_to_turn(
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="follow-up",
        agent_input_text="follow-up translated",
        translation={"status": "completed", "text": "follow-up translated"},
        actor={"user_id": 9, "account_id": "acct", "username": "tester"},
        native_provider="codex",
    )

    assert appended["turn_id"] == handle.turn_id
    assert appended["conversation_id"] == handle.conversation_id
    assert appended["content"] == "follow-up"
    assert appended["agent_input_text"] == "follow-up translated"
    assert appended["translation"]["text"] == "follow-up translated"
    assert appended["author"] == {"user_id": 9, "account_id": "acct", "username": "tester"}
    messages = store.list_messages(handle.conversation_id)
    assert [message["id"] for message in messages] == [
        handle.user_message_id,
        appended["id"],
        handle.assistant_message_id,
    ]
    conversation = store.get_conversation(handle.conversation_id)
    assert conversation["message_count"] == 3
    assert conversation["last_message_preview"] == "follow-up"
    delta = store.get_history_delta(handle.conversation_id, revision=before, limit=20)
    assert delta["revision"] == before + 1
    assert [item["id"] for item in delta["items"]] == [appended["id"]]


def test_latest_completed_turn_at_ignores_incomplete_turns(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    completed = _begin(store, text="completed")
    store.complete_turn(completed, content="answer", completion_state="completed")
    first_latest = store.get_latest_completed_turn_at(bot_id=1, user_id=2)
    incomplete = _begin(store, conversation_id=completed.conversation_id, text="incomplete")
    store.complete_turn(incomplete, content="error", completion_state="error")
    other = _begin(store, text="other", user_id=3)
    store.complete_turn(other, content="other answer", completion_state="completed")

    latest = store.get_latest_completed_turn_at(bot_id=1, user_id=2)

    assert first_latest
    assert latest == first_latest
    assert latest != store.get_latest_completed_turn_at(bot_id=1, user_id=3)


def test_latest_notifiable_turn_at_includes_errors_but_ignores_cancelled_turns(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    completed = _begin(store, text="completed")
    store.complete_turn(completed, content="answer", completion_state="completed")
    first_latest = store.get_latest_notifiable_turn_at(bot_id=1, user_id=2)

    failed = _begin(store, conversation_id=completed.conversation_id, text="failed")
    store.complete_turn(failed, content="error", completion_state="error")
    failed_latest = store.get_latest_notifiable_turn_at(bot_id=1, user_id=2)

    cancelled = _begin(store, conversation_id=completed.conversation_id, text="cancelled")
    store.complete_turn(cancelled, content="stopped", completion_state="cancelled")

    assert first_latest
    assert failed_latest > first_latest
    assert store.get_latest_notifiable_turn_at(bot_id=1, user_id=2) == failed_latest


def test_latest_answer_times_ignore_child_agent_turns(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    main = _begin(store, text="main")
    store.complete_turn(main, content="main answer", completion_state="completed")
    main_times = store.get_latest_answer_times(bot_id=1, user_id=2)

    child = _begin(store, text="child", agent_id="cluster-slot-1")
    store.complete_turn(child, content="child answer", completion_state="completed")
    conn = store._connect(create=False)
    assert conn is not None
    try:
        with conn:
            conn.execute(
                "UPDATE turns SET completed_at = ? WHERE id = ?",
                ("2099-01-01T00:00:00+00:00", child.turn_id),
            )
    finally:
        conn.close()

    assert store.get_latest_answer_times(bot_id=1, user_id=2) == main_times




def test_history_delta_keeps_legacy_after_id_and_uses_revision_only_when_requested(monkeypatch) -> None:
    items = [{"id": "m1"}, {"id": "m2"}]

    class FakeHistoryService:
        def list_history(self, _profile, _session, *, limit):
            assert limit == 50
            return items

        def list_history_delta(self, _profile, _session, **kwargs):
            return {"items": [{"id": "updated"}], "deleted_ids": ["gone"], **kwargs}

    profile = SimpleNamespace()
    session = SimpleNamespace()
    service = FakeHistoryService()
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args: (profile, None, session))
    monkeypatch.setattr(api_service, "_resolve_requested_execution_mode", lambda *_args: "cli")
    monkeypatch.setattr(api_service, "_history_service_for_execution_mode", lambda *_args: service)

    legacy = api_service.get_history_delta(None, "main", 1, "m1")
    revision = api_service.get_history_delta(None, "main", 1, "", revision=3, cursor="7")

    assert legacy == {"items": [{"id": "m2"}], "reset": False}
    assert revision["items"] == [{"id": "updated"}]
    assert revision["deleted_ids"] == ["gone"]
    assert revision["revision"] == 3
    assert revision["cursor"] == "7"
