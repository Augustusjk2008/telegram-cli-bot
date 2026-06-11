from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import bot.runtime_paths as runtime_paths
from bot.models import BotProfile, UserSession
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


def _native_turns(store: ChatStore, workspace: Path):
    profile = BotProfile(alias="main", working_dir=str(workspace), supported_execution_modes=["cli", "native_agent"])
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(workspace))
    history = ChatHistoryService(store, native_provider_filter="native_agent")
    first = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    history.append_trace_event(first, {"kind": "tool_call", "summary": "first"})
    history.complete_turn(first, content="一回", completion_state="completed", native_session_id="sess-1")
    store.update_turn_workspace_history(first.turn_id, "head-1", 1)
    second = history.start_turn(profile=profile, session=session, user_text="二", native_provider="native_agent")
    history.complete_turn(second, content="二回", completion_state="completed", native_session_id="sess-1")
    store.update_turn_workspace_history(second.turn_id, "head-2", 2)
    return profile, session, history, first, second


def test_chat_store_upgrades_old_turns_schema(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    store = ChatStore(workspace)
    store.db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                bot_alias TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL DEFAULT 'main',
                bot_mode TEXT NOT NULL,
                cli_type TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                session_epoch INTEGER NOT NULL,
                status TEXT NOT NULL,
                native_provider TEXT,
                native_session_id TEXT,
                native_session_meta_json TEXT,
                title TEXT,
                last_message_preview TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE turns (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                user_message_id TEXT NOT NULL,
                assistant_message_id TEXT NOT NULL,
                assistant_state TEXT NOT NULL,
                completion_state TEXT NOT NULL,
                native_provider TEXT,
                native_session_id TEXT,
                managed_prompt_hash TEXT,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                error_code TEXT,
                error_message TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                content_format TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE trace_events (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
    from bot.web import chat_store as chat_store_module

    chat_store_module.clear_chat_store_prepare_cache()
    store.get_conversation("missing") if False else store.count_history(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
    )

    with sqlite3.connect(store.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(turns)").fetchall()}
    assert {"workspace_history_head", "workspace_history_index", "workspace_history_discarded_at"} <= columns


def test_workspace_history_meta_and_discarded_history(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    store = ChatStore(workspace)
    profile, session, history, first, second = _native_turns(store, workspace)

    messages = history.list_history(profile, session)
    assistant = messages[1]

    assert assistant["meta"]["workspace_history_head"] == "head-1"
    assert assistant["meta"]["linear_index"] == 1
    assert assistant["meta"]["rollback_supported"] is True
    assert assistant["meta"]["degraded"] is False
    assert "changed_paths" not in json.dumps(messages, ensure_ascii=False)

    store.mark_turns_after_discarded(first.conversation_id, first.turn_id)
    active = history.list_history(profile, session)
    conversation = store.get_conversation(first.conversation_id)

    assert [item["content"] for item in active] == ["一", "一回"]
    assert conversation["message_count"] == 2
    assert conversation["last_message_preview"] == "一回"
    with pytest.raises(KeyError):
        store.get_message_trace(second.assistant_message_id)
    assert store.latest_active_workspace_history(first.conversation_id) == {
        "turn_id": first.turn_id,
        "workspace_history_head": "head-1",
        "linear_index": 1,
    }
