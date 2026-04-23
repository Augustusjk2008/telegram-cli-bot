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
    rename_bot_sessions,
    remove_all_sessions_for_bot,
    remove_session,
    save_session,
    save_session_ids,
)


class TestMakeKey:
    """测试键生成"""

    def test_make_key(self):
        assert _make_key(1, 100) == "1:100"
        assert _make_key(123, 456) == "123:456"


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

    def test_save_without_session_ids(self, temp_dir: Path):
        """测试不保存任何 session_id 时删除记录"""
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            # 先保存一个有 session_id 的记录
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_123",
            )
            assert load_session(1, 100) is not None
            
            # 再保存一个没有 session_id 的，应该删除记录
            save_session(
                bot_id=1,
                user_id=100,
            )
            
            data = load_session(1, 100)
            assert data is None

    def test_save_partial_session_ids(self, temp_dir: Path):
        """测试只保存部分 session_id"""
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_abc123",
            )
            
            data = load_session(1, 100)
            assert data is not None
            assert data["codex_session_id"] == "thread_abc123"
            assert "claude_session_id" not in data

    def test_save_session_omits_legacy_overlay_fields_and_marks_local_history_backend(self, temp_dir: Path):
        """测试 local_v1 快照只持久化仍有意义的元数据"""
        store_file = temp_dir / ".session_store.json"

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=1001,
                codex_session_id="thread-1",
                claude_session_id="claude-1",
                working_dir=str(temp_dir),
                browse_dir=str(temp_dir),
                message_count=3,
                last_activity="2026-04-18T10:00:00+00:00",
                local_history_backend="local_v1",
                session_epoch=2,
                running_user_text="legacy",
                running_preview_text="legacy-preview",
                web_turn_overlays=[{"summary_text": "legacy"}],
            )

            data = load_session(1, 1001)
            assert data is not None
            assert data["local_history_backend"] == "local_v1"
            assert data["session_epoch"] == 2
            assert data["codex_session_id"] == "thread-1"
            assert data["message_count"] == 3
            assert "running_user_text" not in data
            assert "running_preview_text" not in data
            assert "web_turn_overlays" not in data


class TestRemoveSession:
    """测试删除会话"""

    def test_remove_existing_session(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            # 先保存
            save_session(1, 100, codex_session_id="thread_123")
            assert load_session(1, 100) is not None
            
            # 删除
            remove_session(1, 100)
            assert load_session(1, 100) is None

    def test_remove_nonexistent_session(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            # 删除不存在的会话不应该报错
            remove_session(999, 999)


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


class TestLoadSessionIds:
    """测试加载所有会话ID"""

    def test_load_empty_file(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            data = load_session_ids()
            assert data == {}

    def test_load_nonexistent_file(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            data = load_session_ids()
            assert data == {}

    def test_load_invalid_json(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        store_file.write_text("not valid json")
        
        with patch("bot.session_store.STORE_FILE", store_file):
            data = load_session_ids()
            assert data == {}


class TestSaveSessionIds:
    """测试保存所有会话ID"""

    def test_save_session_ids(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        
        with patch("bot.session_store.STORE_FILE", store_file):
            data = {
                "1:100": {
                    "codex_session_id": "thread_123",
                }
            }
            save_session_ids(data)
            
            # 验证文件内容
            with open(store_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            assert saved == data
