"""
会话管理测试

直接导入 bot.sessions 中的真实函数进行测试
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.sessions import (
    clear_bot_sessions,
    get_session,
    is_bot_processing,
    reset_session,
    sessions,
    sessions_lock,
)


class TestGetSession:
    """测试 get_session"""

    def test_create_new_session(self, temp_dir: Path):
        s = get_session(1, "main", 100, str(temp_dir))
        assert s.bot_id == 1
        assert s.bot_alias == "main"
        assert s.user_id == 100
        assert s.working_dir == str(temp_dir)

    def test_get_existing_session(self, temp_dir: Path):
        s1 = get_session(1, "main", 100, str(temp_dir))
        s2 = get_session(1, "main", 100, str(temp_dir))
        assert s1 is s2

    def test_different_users_different_sessions(self, temp_dir: Path):
        s1 = get_session(1, "main", 100, str(temp_dir))
        s2 = get_session(1, "main", 200, str(temp_dir))
        assert s1 is not s2

    def test_different_bots_different_sessions(self, temp_dir: Path):
        s1 = get_session(1, "main", 100, str(temp_dir))
        s2 = get_session(2, "sub", 100, str(temp_dir))
        assert s1 is not s2

    def test_expired_session_recreated(self, temp_dir: Path):
        s1 = get_session(1, "main", 100, str(temp_dir))
        s1.last_activity = datetime(2000, 1, 1)  # 强制过期
        s2 = get_session(1, "main", 100, str(temp_dir))
        assert s1 is not s2


class TestResetSession:
    """测试 reset_session"""

    def test_reset_existing(self, temp_dir: Path):
        get_session(1, "main", 100, str(temp_dir))
        result = reset_session(1, 100)
        assert result is True
        # 再获取应该是新的
        key = (1, 100)
        with sessions_lock:
            assert key not in sessions

    def test_reset_nonexistent(self):
        result = reset_session(999, 999)
        assert result is False

    def test_reset_clears_persisted_store_without_in_memory_session(self, temp_dir: Path):
        from unittest.mock import patch
        from bot.session_store import load_session, save_session

        store_file = temp_dir / ".session_store.json"
        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(bot_id=7, user_id=8, codex_session_id="thread-only-store")
            with sessions_lock:
                sessions.pop((7, 8), None)

            result = reset_session(7, 8)

            assert result is True
            assert load_session(7, 8) is None


class TestClearBotSessions:
    """测试 clear_bot_sessions"""

    def test_clear_specific_bot(self, temp_dir: Path):
        get_session(1, "main", 100, str(temp_dir))
        get_session(1, "main", 200, str(temp_dir))
        get_session(2, "sub", 100, str(temp_dir))

        clear_bot_sessions(1)

        with sessions_lock:
            assert (1, 100) not in sessions
            assert (1, 200) not in sessions
            assert (2, 100) in sessions


class TestIsBotProcessing:
    """测试 is_bot_processing"""

    def test_not_processing(self, temp_dir: Path):
        get_session(1, "main", 100, str(temp_dir))
        assert is_bot_processing(1) is False

    def test_is_processing(self, temp_dir: Path):
        s = get_session(1, "main", 100, str(temp_dir))
        s.is_processing = True
        assert is_bot_processing(1) is True

    def test_nonexistent_bot(self):
        assert is_bot_processing(999) is False


class TestSessionPersistence:
    """测试会话持久化功能"""

    def test_assistant_session_does_not_write_project_session_store(self, temp_dir: Path):
        workdir = temp_dir / "assistant-root"
        workdir.mkdir()
        session = get_session(1, "assistant1", 100, str(workdir))
        session.persist_hook = lambda current: None
        session.add_to_history("user", "hello")

        store_file = temp_dir / ".session_store.json"
        assert not store_file.exists()

    def test_session_restored_from_store(self, temp_dir: Path):
        """测试从持久化存储恢复会话（不检查工作目录）"""
        from unittest.mock import patch
        from bot.session_store import save_session
        
        # 先保存会话到持久化存储
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_restored_123",
                kimi_session_id="kimi_restored_456",
                claude_session_id="claude_restored_789",
            )
            
            # 清除内存中的会话
            with sessions_lock:
                sessions.clear()
            
            # 重新获取会话，应该恢复 session_id（不管工作目录是什么）
            other_dir = temp_dir / "other"
            other_dir.mkdir()
            s = get_session(1, "main", 100, str(other_dir))
            
            assert s.codex_session_id == "thread_restored_123"
            assert s.kimi_session_id == "kimi_restored_456"
            assert s.claude_session_id == "claude_restored_789"
            assert s.claude_session_initialized is True

    def test_reset_session_clears_persistent_store(self, temp_dir: Path):
        """测试重置会话时清除持久化存储"""
        from unittest.mock import patch
        from bot.session_store import save_session, load_session
        
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_to_clear",
            )
            
            # 先创建会话
            get_session(1, "main", 100, str(temp_dir))
            
            # 重置会话
            reset_session(1, 100)
            
            # 持久化存储应该被清除
            assert load_session(1, 100) is None

    def test_save_all_sessions(self, temp_dir: Path):
        """测试保存所有会话"""
        from unittest.mock import patch
        from bot.session_store import load_session
        from bot.sessions import save_all_sessions
        
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            # 创建带有 session_id 的会话
            s1 = get_session(1, "main", 100, str(temp_dir))
            s1.codex_session_id = "thread_s1"
            s1.kimi_session_id = "kimi_s1"
            
            s2 = get_session(1, "main", 200, str(temp_dir))
            s2.claude_session_id = "claude_s2"
            
            # 保存所有会话
            save_all_sessions()
            
            # 验证持久化存储
            data1 = load_session(1, 100)
            assert data1["codex_session_id"] == "thread_s1"
            assert data1["kimi_session_id"] == "kimi_s1"
            
            data2 = load_session(1, 200)
            assert data2["claude_session_id"] == "claude_s2"

    def test_session_restored_after_restart(self, temp_dir: Path):
        """测试重启后恢复会话"""
        from unittest.mock import patch
        from bot.session_store import save_session, load_session
        
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            # 模拟之前保存的会话
            save_session(
                bot_id=1,
                user_id=100,
                kimi_session_id="kimi_prev_session",
            )
            
            # 验证存储存在
            assert load_session(1, 100) is not None
            
            # 清除内存会话，模拟重启
            with sessions_lock:
                sessions.clear()
            
            # 重新获取会话（模拟重启后）
            s = get_session(1, "main", 100, str(temp_dir))
            
            # 应该恢复之前的 session_id
            assert s.kimi_session_id == "kimi_prev_session"

    def test_persist_saves_history_workdir_and_running_reply(self, temp_dir: Path):
        """测试会话快照会自动持久化"""
        from unittest.mock import patch
        from bot.session_store import load_session

        store_file = temp_dir / ".session_store.json"
        with patch("bot.session_store.STORE_FILE", store_file):
            session = get_session(1, "main", 100, str(temp_dir))
            session.working_dir = str(temp_dir / "workspace")
            session.touch()
            session.add_to_history("user", "hello")
            session.start_running_reply("continue")
            session.update_running_reply("partial")

            data = load_session(1, 100)
            assert data is not None
            assert data["working_dir"] == str(temp_dir / "workspace")
            assert data["message_count"] == 1
            assert data["history"][0]["content"] == "hello"
            assert data["running_user_text"] == "continue"
            assert data["running_preview_text"] == "partial"
            assert "last_activity" in data

    def test_session_restored_with_history_workdir_and_running_reply(self, temp_dir: Path):
        """测试从持久化存储恢复完整会话快照"""
        from unittest.mock import patch
        from bot.session_store import save_session

        store_file = temp_dir / ".session_store.json"
        restored_dir = temp_dir / "restored"
        restored_dir.mkdir()
        history = [
            {
                "timestamp": "2026-04-09T10:00:00",
                "role": "user",
                "content": "continue",
            },
            {
                "timestamp": "2026-04-09T10:00:02",
                "role": "assistant",
                "content": "partial result",
            },
        ]

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_restored_123",
                working_dir=str(restored_dir),
                history=history,
                message_count=7,
                last_activity="2026-04-09T10:00:03",
                running_user_text="continue",
                running_preview_text="still running",
                running_started_at="2026-04-09T10:00:01",
                running_updated_at="2026-04-09T10:00:04",
            )

            with sessions_lock:
                sessions.clear()

            session = get_session(1, "main", 100, str(temp_dir))

            assert session.codex_session_id == "thread_restored_123"
            assert session.working_dir == str(restored_dir)
            assert session.history == history
            assert session.message_count == 7
            assert session.running_user_text == "continue"
            assert session.running_preview_text == "still running"
            assert session.running_started_at == "2026-04-09T10:00:01"
            assert session.running_updated_at == "2026-04-09T10:00:04"
            assert session.is_processing is False
