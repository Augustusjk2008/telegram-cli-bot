from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import bot.web.chat_store as chat_store_module
from bot.web.chat_store import ChatStore, clear_chat_store_prepare_cache


def _create_legacy_chat_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
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
                assistant_home TEXT,
                managed_prompt_hash TEXT,
                prompt_surface_version TEXT,
                title TEXT,
                last_message_preview TEXT,
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
                UNIQUE(conversation_id, seq),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            INSERT INTO conversations (
                id, bot_id, bot_alias, user_id, agent_id, bot_mode, cli_type,
                working_dir, session_epoch, status, native_provider,
                assistant_home, managed_prompt_hash, prompt_surface_version,
                title, last_message_preview, created_at, updated_at
            ) VALUES (
                'conv-legacy', 1, 'legacy', 2, 'main', 'assistant', 'claude',
                'C:/legacy', 0, 'active', 'claude',
                'C:/legacy/.assistant', 'managed-hash', 'v1',
                '旧会话', '旧消息', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );

            INSERT INTO turns (
                id, conversation_id, seq, user_message_id, assistant_message_id,
                assistant_state, completion_state, native_provider,
                managed_prompt_hash, started_at, updated_at
            ) VALUES (
                'turn-legacy', 'conv-legacy', 1, 'msg-user', 'msg-assistant',
                'done', 'completed', 'claude', 'managed-hash',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """
        )


def _create_incomplete_chat_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                working_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            INSERT INTO conversations (
                id, bot_id, user_id, working_dir, created_at, updated_at
            ) VALUES (
                'conv-incomplete', 3, 4, 'C:/incomplete',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """
        )


def _open_legacy_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_db) -> tuple[Path, ChatStore]:
    db_path = tmp_path / "chat.sqlite"
    metadata_path = tmp_path / "workspace.json"
    create_db(db_path)
    clear_chat_store_prepare_cache()
    monkeypatch.setattr(chat_store_module, "get_chat_history_db_path", lambda _workspace: db_path)
    monkeypatch.setattr(chat_store_module, "get_chat_workspace_metadata_path", lambda _workspace: metadata_path)
    monkeypatch.setattr(chat_store_module, "get_legacy_project_chat_db_path", lambda _workspace: tmp_path / "missing.sqlite")
    return db_path, ChatStore(tmp_path / "workspace")


@pytest.mark.parametrize(
    ("create_db", "conversation_id", "bot_id", "user_id", "working_dir"),
    [
        (_create_legacy_chat_db, "conv-legacy", 1, 2, "C:/legacy"),
        (_create_incomplete_chat_db, "conv-incomplete", 3, 4, "C:/incomplete"),
    ],
)
def test_chat_store_migrates_legacy_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_db, conversation_id: str,
    bot_id: int, user_id: int, working_dir: str,
) -> None:
    db_path, store = _open_legacy_store(tmp_path, monkeypatch, create_db)
    conversation = store.get_conversation(conversation_id)
    listed = store.list_conversations(bot_id=bot_id, user_id=user_id, agent_id="main", working_dir=working_dir)

    with sqlite3.connect(db_path) as conn:
        conversation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversations)")}
        if conversation_id == "conv-legacy":
            turn_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(turns)")}
            stored_turn = conn.execute("SELECT id FROM turns WHERE id = 'turn-legacy'").fetchone()
    assert [item["id"] for item in listed] == [conversation_id]
    if conversation_id == "conv-legacy":
        assert {"bot_mode", "assistant_home", "managed_prompt_hash", "prompt_surface_version"}.isdisjoint(conversation_columns)
        assert "managed_prompt_hash" not in turn_columns
        assert conversation["title"] == "旧会话" and "bot_mode" not in conversation
        assert "bot_mode" not in listed[0] and stored_turn == ("turn-legacy",)
    else:
        assert {"bot_alias", "agent_id", "cli_type", "status", "revision"}.issubset(conversation_columns)
        assert (conversation["agent_id"], conversation["message_count"], conversation["pinned"]) == ("main", 0, False)
