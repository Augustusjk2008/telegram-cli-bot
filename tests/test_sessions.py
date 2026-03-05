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
