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

    def test_save_session_omits_legacy_history_snapshot_fields(self, temp_dir: Path):
        """测试保存会话快照时不再持久化聊天历史"""
        store_file = temp_dir / ".session_store.json"
        history = [
            {
                "timestamp": "2026-04-09T12:00:00",
                "role": "user",
                "content": "hello",
            }
        ]

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_abc123",
                working_dir="C:\\workspace\\saved",
                history=history,
                message_count=3,
                last_activity="2026-04-09T12:00:01",
                running_user_text="continue",
                running_preview_text="partial",
                running_started_at="2026-04-09T12:00:02",
                running_updated_at="2026-04-09T12:00:03",
            )

            data = load_session(1, 100)
            assert data is not None
            assert data["working_dir"] == "C:\\workspace\\saved"
            assert "history" not in data
            assert data["message_count"] == 3
            assert data["last_activity"] == "2026-04-09T12:00:01"
            assert data["running_user_text"] == "continue"
            assert data["running_preview_text"] == "partial"
            assert data["running_started_at"] == "2026-04-09T12:00:02"
            assert data["running_updated_at"] == "2026-04-09T12:00:03"


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
