"""
会话ID持久化存储测试
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.session_store import (
    _make_key,
    load_session,
    load_session_ids,
    migrate_sessions_to_shared,
    rename_bot_sessions,
    remove_all_sessions_for_bot,
    remove_session,
    save_session,
    save_session_ids,
)


class TestSaveAndLoadSession:
    """测试保存和加载会话"""

    def test_save_and_load_session(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            # 保存会话
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_abc123",
                claude_session_id="uuid_456",
            )
            
            # 加载会话
            data = load_session(1, 100)
            assert data is not None
            assert data["codex_session_id"] == "thread_abc123"
            assert data["claude_session_id"] == "uuid_456"

    def test_save_and_load_native_agent_session_id(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                native_agent_session_id="native-session-1",
            )

            data = load_session(1, 100)

        assert data is not None
        assert data["native_agent_session_id"] == "native-session-1"


class TestRemoveAllSessionsForBot:
    """测试删除指定bot的所有会话"""

    def test_remove_all_sessions_for_bot(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            # 保存多个会话
            save_session(1, 100, codex_session_id="t1")
            save_session(1, 200, codex_session_id="t2")
            save_session(2, 100, codex_session_id="t3")
            
            # 删除 bot 1 的所有会话
            remove_all_sessions_for_bot(1)
            
            assert load_session(1, 100) is None
            assert load_session(1, 200) is None
            assert load_session(2, 100) is not None


class TestRenameBotSessions:
    """测试 bot 改名时迁移会话快照"""

    def test_rename_bot_sessions_merges_into_new_bot_id(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        workdir = temp_dir / "repo"
        workdir.mkdir()

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread-old",
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=3,
                last_activity="2026-04-23T08:00:00",
                local_history_backend="local_v1",
                session_epoch=0,
            )
            save_session(
                bot_id=9,
                user_id=100,
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=0,
                last_activity="2026-04-23T09:00:00",
                local_history_backend="local_v1",
                session_epoch=0,
            )
            save_session(
                bot_id=1,
                user_id=200,
                claude_session_id="claude-old",
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=1,
                last_activity="2026-04-23T08:30:00",
                local_history_backend="local_v1",
                session_epoch=2,
            )

            moved = rename_bot_sessions(1, 9)

            assert moved == 2
            assert load_session(1, 100) is None
            assert load_session(1, 200) is None

            merged = load_session(9, 100)
            assert merged is not None
            assert merged["codex_session_id"] == "thread-old"
            assert merged["working_dir"] == str(workdir)
            assert merged["browse_dir"] == str(workdir)
            assert merged["message_count"] == 3
            assert merged["last_activity"] == "2026-04-23T09:00:00"
            assert merged["local_history_backend"] == "local_v1"
            assert merged["session_epoch"] == 0

            moved_snapshot = load_session(9, 200)
            assert moved_snapshot is not None
            assert moved_snapshot["claude_session_id"] == "claude-old"
            assert moved_snapshot["session_epoch"] == 2
