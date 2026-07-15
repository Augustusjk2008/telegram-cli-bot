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
                native_session_id TEXT,
                native_session_meta_json TEXT,
                assistant_home TEXT,
                managed_prompt_hash TEXT,
                prompt_surface_version TEXT,
                agent_prompt_hash TEXT,
                title TEXT,
                last_message_preview TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived_at TEXT,
                revision INTEGER NOT NULL DEFAULT 0,
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
                error_message TEXT,
                trace_recovery_attempted_at TEXT,
                trace_recovery_status TEXT,
                context_usage_json TEXT,
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


def test_chat_store_migrates_removed_assistant_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "chat.sqlite"
    metadata_path = tmp_path / "workspace.json"
    _create_legacy_chat_db(db_path)
    clear_chat_store_prepare_cache()
    monkeypatch.setattr(chat_store_module, "get_chat_history_db_path", lambda _workspace: db_path)
    monkeypatch.setattr(chat_store_module, "get_chat_workspace_metadata_path", lambda _workspace: metadata_path)
    monkeypatch.setattr(chat_store_module, "get_legacy_project_chat_db_path", lambda _workspace: tmp_path / "missing.sqlite")

    store = ChatStore(tmp_path / "workspace")
    migrated = store.get_conversation("conv-legacy")

    with sqlite3.connect(db_path) as conn:
        conversation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversations)")}
        turn_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(turns)")}
        stored_turn = conn.execute("SELECT id FROM turns WHERE id = 'turn-legacy'").fetchone()

    assert {
        "bot_mode",
        "assistant_home",
        "managed_prompt_hash",
        "prompt_surface_version",
    }.isdisjoint(conversation_columns)
    assert "managed_prompt_hash" not in turn_columns
    assert migrated["id"] == "conv-legacy"
    assert migrated["title"] == "旧会话"
    assert "bot_mode" not in migrated
    assert stored_turn == ("turn-legacy",)
