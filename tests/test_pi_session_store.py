from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key


def test_pi_session_store_save_load_empty_file(tmp_path: Path):
    store = PiSessionStore(tmp_path / "pi_sessions.json")
    key = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1")

    assert store.get(key) is None
    saved = store.upsert(PiSessionRecord(key=key, cwd=str(tmp_path), conversation_id="conv-1", pi_session_id="sess-1"))

    assert saved.pi_session_id == "sess-1"
    assert store.get(key).pi_session_id == "sess-1"  # type: ignore[union-attr]


def test_pi_session_store_corrupted_json_raises_clean_error(tmp_path: Path):
    path = tmp_path / "pi_sessions.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(RuntimeError):
        PiSessionStore(path).get("key")


def test_completed_turn_increments_once_per_turn(tmp_path: Path):
    store = PiSessionStore(tmp_path / "pi_sessions.json")
    key = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1")
    store.upsert(PiSessionRecord(key=key, cwd=str(tmp_path), conversation_id="conv-1"))

    first = store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-1", workspace_history_head="head-1")
    second = store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-1", workspace_history_head="head-1")
    third = store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-2", workspace_history_head="head-2")

    assert first.linear_index == 1
    assert second.linear_index == 1
    assert third.linear_index == 2
    assert [turn.linear_index for turn in third.turns] == [1, 2]


def test_degraded_and_discarded_state_persist(tmp_path: Path):
    store = PiSessionStore(tmp_path / "pi_sessions.json")
    key = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1")
    store.upsert(PiSessionRecord(key=key, cwd=str(tmp_path), conversation_id="conv-1"))
    store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-1", workspace_history_head="head-1")
    store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-2", workspace_history_head="head-2")
    store.mark_degraded(key, "plugin missing")

    rolled = store.mark_discarded_after(key, "turn-1")
    reloaded = PiSessionStore(tmp_path / "pi_sessions.json").get(key)

    assert rolled.linear_index == 1
    assert rolled.workspace_history_head == "head-1"
    assert reloaded is not None
    assert reloaded.degraded is True
    assert reloaded.degraded_reason == "plugin missing"
    assert reloaded.turns[1].status == "discarded"
    assert reloaded.turns[1].discarded_at


def test_pi_session_store_isolates_and_deletes_conversation(tmp_path: Path):
    store = PiSessionStore(tmp_path / "pi_sessions.json")
    key1 = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1")
    key2 = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1002, conversation_id="conv-1")
    store.upsert(PiSessionRecord(key=key1, cwd=str(tmp_path), conversation_id="conv-1", pi_session_id="sess-1"))
    store.upsert(PiSessionRecord(key=key2, cwd=str(tmp_path), conversation_id="conv-1", pi_session_id="sess-2"))

    assert store.delete_conversation(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1") is True

    assert store.get(key1) is None
    assert store.get(key2).pi_session_id == "sess-2"  # type: ignore[union-attr]
    payload = json.loads((tmp_path / "pi_sessions.json").read_text(encoding="utf-8"))
    assert set(payload["sessions"]) == {key2}


def test_pi_session_store_invalidate_binding_clears_session_and_chain(tmp_path: Path):
    store = PiSessionStore(tmp_path / "pi_sessions.json")
    key = pi_session_key(cwd=str(tmp_path), bot_id=1, user_id=1001, conversation_id="conv-1")
    store.upsert(PiSessionRecord(
        key=key,
        cwd=str(tmp_path),
        conversation_id="conv-1",
        pi_session_id="sess-1",
        session_meta={
            "cwd": str(tmp_path),
            "model_id": "anthropic/claude-sonnet-4",
            "pi_agent": "reviewer",
            "reasoning_effort": "high",
        },
    ))
    store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-1", workspace_history_head="head-1")
    store.update_after_completed_turn(key, pi_session_id="sess-1", turn_id="turn-2", workspace_history_head="head-2")

    invalidated = store.invalidate_binding(key, "binding changed")
    reloaded = store.get(key)

    assert invalidated.pi_session_id == ""
    assert invalidated.workspace_history_head == ""
    assert invalidated.linear_index == 0
    assert invalidated.last_turn_id == ""
    assert invalidated.session_meta["model_id"] == "anthropic/claude-sonnet-4"
    assert reloaded is not None
    assert reloaded.pi_session_id == ""
    assert reloaded.workspace_history_head == ""
    assert reloaded.linear_index == 0
    assert reloaded.turns[0].status == "discarded"
    assert reloaded.turns[0].discarded_at
    assert reloaded.turns[1].status == "discarded"
    assert reloaded.turns[1].discarded_at
