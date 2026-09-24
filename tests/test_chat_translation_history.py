from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore, clear_chat_store_prepare_cache


def _begin(store: ChatStore, *, text: str = "原始提问", provider: str = "codex", conversation_id=None):
    return store.begin_turn(
        bot_id=1, bot_alias="main", user_id=2, agent_id="main", cli_type=provider,
        working_dir=str(store.workspace_dir), session_epoch=0, user_text=text,
        native_provider=provider, conversation_id=conversation_id,
    )


def _translation(content: str, status: str = "completed") -> dict:
    value = {
        "status": status,
        "target_language": "English",
        "source_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    if status == "completed":
        value.update(text="Translated text", completed_at="2026-09-16T10:00:00+00:00")
    elif status == "failed":
        value["error"] = "timeout"
    return value


def _save(store, message_id, translation, **kwargs):
    return store.update_message_translation(
        message_id, source_digest=translation["source_digest"], translation=translation, **kwargs,
    )


def _turn_record(store, turn_id):
    with sqlite3.connect(store.db_path) as conn:
        return conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()


def _session(store, handle):
    return SimpleNamespace(
        bot_id=1, user_id=2, agent_id="main", working_dir=str(store.workspace_dir),
        session_epoch=0, active_conversation_id=handle.conversation_id,
        _lock=threading.RLock(), is_processing=False,
    )


def test_translation_persists_in_snapshot_and_delta_without_completing_turn_again(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    original = "  原始回答\n🙂\n"
    before = store.complete_turn(handle, content=original, completion_state="completed")
    conversation_before = store.get_conversation(handle.conversation_id)
    turn_before = _turn_record(store, handle.turn_id)
    answer_times = store.get_latest_answer_times(bot_id=1, user_id=2)
    revision = store.get_conversation_revision(handle.conversation_id)
    translation = _translation(original)
    history = ChatHistoryService(store)

    assert _save(history, handle.assistant_message_id, translation)
    reopened = ChatStore(tmp_path)
    for limit in (None, 10):
        message = reopened.list_messages(handle.conversation_id, limit=limit)[-1]
        assert message["content"] == original
        assert message["translation"] == translation
        assert message["agent_input_text"] is None
        assert message["created_at"] == before["created_at"]
        assert message["updated_at"] == before["updated_at"]
        assert message["meta"]["completion_state"] == "completed"
    delta = history.list_history_delta(SimpleNamespace(), _session(store, handle), revision=revision)
    assert [item["id"] for item in delta["items"]] == [handle.assistant_message_id]
    assert delta["items"][0]["translation"] == translation
    assert delta["revision"] == revision + 1
    assert delta["deleted_ids"] == []
    assert _turn_record(store, handle.turn_id) == turn_before
    conversation_after = store.get_conversation(handle.conversation_id)
    assert {key: value for key, value in conversation_after.items() if key != "revision"} == {
        key: value for key, value in conversation_before.items() if key != "revision"
    }
    assert store.get_latest_answer_times(bot_id=1, user_id=2) == answer_times


@pytest.mark.asyncio
async def test_async_translation_write_preserves_input_and_rejects_late_pending(tmp_path: Path):
    store = ChatStore(tmp_path)
    history = ChatHistoryService(store)
    handle = _begin(store)
    pending = _translation("原始提问", "pending")
    completed = _translation("原始提问")
    assert await history.update_message_translation_async(
        handle.user_message_id, source_digest=pending["source_digest"], translation=pending,
        agent_input_text="Actual prompt",
    )
    assert _save(history, handle.user_message_id, completed)
    revision = store.get_conversation_revision(handle.conversation_id)
    assert not await history.async_store.update_message_translation(
        handle.user_message_id, source_digest=pending["source_digest"], translation=pending,
        agent_input_text="Old prompt",
    )
    assert not _save(history, handle.user_message_id, _translation("原始提问", "failed"))
    assert not _save(history, handle.user_message_id, completed)
    assert store.get_conversation_revision(handle.conversation_id) == revision
    delta = await history.async_store.get_scoped_history_delta(
        bot_id=1, user_id=2, agent_id="main", working_dir=str(tmp_path), session_epoch=0,
        conversation_id=handle.conversation_id, revision=0,
    )
    assert delta["items"][0]["translation"] == completed
    assert delta["items"][0]["agent_input_text"] == "Actual prompt"


def test_cancelled_translation_rejects_late_pending_write(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    failed = {**_translation("原始提问", "failed"), "error": "cancelled"}
    assert _save(store, handle.user_message_id, failed)
    revision = store.get_conversation_revision(handle.conversation_id)
    assert not _save(store, handle.user_message_id, _translation("原始提问", "pending"))
    assert store.get_message(handle.user_message_id)["translation"] == failed
    assert store.get_conversation_revision(handle.conversation_id) == revision


def test_only_failed_answer_can_be_reopened_for_manual_retry(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    store.complete_turn(handle, content="回答", completion_state="completed")
    answer_failed = _translation("回答", "failed")
    question_failed = _translation("原始提问", "failed")
    assert _save(store, handle.assistant_message_id, answer_failed)
    assert _save(store, handle.user_message_id, question_failed)
    assert not _save(store, handle.assistant_message_id, _translation("回答", "pending"))
    assert not _save(store, handle.user_message_id, _translation("原始提问", "pending"), retry_failed_answer=True)
    assert _save(store, handle.assistant_message_id, _translation("回答", "pending"), retry_failed_answer=True)
    assert _save(store, handle.assistant_message_id, _translation("回答"))
    assert not _save(store, handle.assistant_message_id, _translation("回答", "pending"), retry_failed_answer=True)


def test_retry_target_is_limited_to_active_session_conversation(tmp_path: Path):
    store = ChatStore(tmp_path)
    first = _begin(store)
    store.complete_turn(first, content="回答", completion_state="completed")
    scoped = dict(bot_id=1, user_id=2, agent_id="main", working_dir=str(tmp_path),
                  session_epoch=0, conversation_id=first.conversation_id)
    assert store.get_scoped_message(first.assistant_message_id, **scoped)["id"] == first.assistant_message_id
    assert store.get_scoped_message(first.assistant_message_id, **{**scoped, "user_id": 3}) is None
    assert store.get_scoped_message(first.assistant_message_id, **{**scoped, "conversation_id": "elsewhere"}) is None


def test_untranslated_input_and_failed_translation_are_persisted(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store, text="//help")
    failed = _translation("//help", "failed")
    assert store.update_message_translation(
        handle.user_message_id, source_digest=failed["source_digest"], translation=None,
        agent_input_text="/help",
    )
    assert store.get_message(handle.user_message_id)["translation"] is None
    assert _save(store, handle.user_message_id, failed)
    message = store.get_message(handle.user_message_id)
    assert message["translation"] == failed
    assert message["agent_input_text"] == "/help"
    assert message["content"] == "//help"


@pytest.mark.parametrize("status", [None, "pending", "completed", "failed"])
def test_none_translation_preserves_saved_state_when_updating_input(tmp_path: Path, status):
    store = ChatStore(tmp_path)
    history = ChatHistoryService(store)
    handle = _begin(store, text="//help")
    translation = _translation("//help", status) if status else None
    if translation is not None:
        assert _save(history, handle.user_message_id, translation)
    digest = hashlib.sha256("//help".encode("utf-8")).hexdigest()
    revision = store.get_conversation_revision(handle.conversation_id)

    assert history.update_message_translation(
        handle.user_message_id, source_digest=digest, translation=None, agent_input_text="/help",
    )
    assert not history.update_message_translation(
        handle.user_message_id, source_digest=digest, translation=None, agent_input_text="/help",
    )
    assert not history.update_message_translation(
        handle.user_message_id, source_digest=hashlib.sha256(b"/help").hexdigest(),
        translation=None, agent_input_text="incorrect",
    )
    delta = store.get_history_delta(handle.conversation_id, revision=revision)
    assert delta["revision"] == revision + 1
    assert delta["items"][0]["translation"] == translation
    assert delta["items"][0]["agent_input_text"] == "/help"
    assert delta["items"][0]["content"] == "//help"


@pytest.mark.parametrize("invalidation", ["content", "discard", "delete", "digest", "payload_digest"])
def test_stale_translation_does_not_write_or_increment_revision(tmp_path: Path, invalidation: str):
    store = ChatStore(tmp_path)
    first = _begin(store)
    store.complete_turn(first, content="first", completion_state="completed")
    handle = _begin(store, conversation_id=first.conversation_id)
    store.complete_turn(handle, content="原文", completion_state="completed")
    translation = _translation("原文")
    if invalidation == "content":
        assert _save(store, handle.assistant_message_id, translation)
        store.replace_message_content(handle.assistant_message_id, "已修改原文")
        assert store.get_message(handle.assistant_message_id)["translation"] is None
    elif invalidation == "discard":
        store.mark_turns_after_discarded(first.conversation_id, first.turn_id)
    elif invalidation == "delete":
        store.delete_conversation_by_id(handle.conversation_id)
    digest = translation["source_digest"]
    if invalidation == "digest":
        digest = hashlib.sha256(" 原文".encode("utf-8")).hexdigest()
        translation["source_digest"] = digest
    elif invalidation == "payload_digest":
        translation["source_digest"] = "wrong"
    with sqlite3.connect(store.db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM history_changes").fetchone()
    assert not store.update_message_translation(
        handle.assistant_message_id, source_digest=digest, translation=translation,
    )
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM history_changes").fetchone() == before


def test_legacy_messages_migrate_with_nullable_translation_fields(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    store.complete_turn(handle, content="旧回答", completion_state="completed")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE messages DROP COLUMN translation_json")
        conn.execute("ALTER TABLE messages DROP COLUMN agent_input_text")
    clear_chat_store_prepare_cache()

    messages = ChatStore(tmp_path).list_messages(handle.conversation_id)
    assert [message["content"] for message in messages] == ["原始提问", "旧回答"]
    assert all(message["translation"] is None and message["agent_input_text"] is None for message in messages)


def test_restart_fails_old_pending_and_emits_delta_without_changing_turn(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    store.complete_turn(handle, content="回答", completion_state="completed")
    completed = _translation("原始提问")
    pending = _translation("回答", "pending")
    assert _save(store, handle.user_message_id, completed, agent_input_text="Translated input")
    assert _save(store, handle.assistant_message_id, pending)
    revision = store.get_conversation_revision(handle.conversation_id)
    turn_before = _turn_record(store, handle.turn_id)
    assert ChatStore(tmp_path).get_message(handle.assistant_message_id)["translation"] == pending

    clear_chat_store_prepare_cache()
    restarted = ChatStore(tmp_path)
    delta = restarted.get_history_delta(handle.conversation_id, revision=revision)
    assert [item["id"] for item in delta["items"]] == [handle.assistant_message_id]
    assert delta["items"][0]["translation"] == {**pending, "status": "failed", "error": "interrupted"}
    assert delta["revision"] == revision + 1
    assert restarted.get_message(handle.user_message_id)["translation"] == completed
    assert _turn_record(restarted, handle.turn_id) == turn_before
    assert ChatStore(tmp_path).get_conversation_revision(handle.conversation_id) == revision + 1


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("translated", [False, True])
def test_trace_recovery_and_completion_reconcile_use_actual_input(tmp_path: Path, monkeypatch, provider, translated):
    store = ChatStore(tmp_path)
    handle = _begin(store, provider=provider)
    input_text = "Translated input" if translated else "原始提问"
    if translated:
        assert _save(store, handle.user_message_id, _translation("原始提问"), agent_input_text=input_text)
    store.complete_turn(handle, content="回答", completion_state="completed", native_session_id="native-session")
    resolver = Mock(return_value={
        "trace_count": 1, "tool_call_count": 1,
        "trace": [{"kind": "tool_call", "tool_name": "Read", "summary": "读取文件", "call_id": "call"}],
    })
    monkeypatch.setattr("bot.web.chat_history_service.resolve_native_trace_for_turn", resolver)
    history = ChatHistoryService(store)
    profile = SimpleNamespace(cli_type=provider)
    session = _session(store, handle)
    trace = history.get_message_trace(profile, session, handle.assistant_message_id)
    assert trace["trace"][0]["tool_name"] == "Read"
    assert resolver.call_args.kwargs["user_text"] == input_text
    store.replace_trace_events(handle.turn_id, [])
    assert history.reconcile_turn_trace(
        handle, profile=profile, session=session, user_text="未持久化的调用参数",
        assistant_text="回答", native_session_id="native-session",
    )
    assert resolver.call_args.kwargs["user_text"] == input_text
