"""
数据模型测试

直接导入 bot.models 中的 BotProfile 和 UserSession 进行测试
"""

import time
import threading
from datetime import datetime
from pathlib import Path

import pytest

from bot.models import BotProfile, UserSession


class TestBotProfile:
    """测试 BotProfile"""

    def test_creation(self):
        p = BotProfile(alias="test", token="tok123")
        assert p.alias == "test"
        assert p.token == "tok123"
        assert p.enabled is True

    def test_to_dict(self):
        p = BotProfile(alias="sub1", token="tok", cli_type="claude", cli_path="/usr/bin/claude",
                        working_dir="/work", enabled=False)
        d = p.to_dict()
        assert d["alias"] == "sub1"
        assert d["token"] == "tok"
        assert d["cli_type"] == "claude"
        assert d["cli_path"] == "/usr/bin/claude"
        assert d["working_dir"] == "/work"
        assert d["enabled"] is False

    def test_defaults(self):
        p = BotProfile(alias="x", token="y")
        assert p.enabled is True
        assert p.cli_type == "codex"
        assert p.cli_path == "codex"
        assert p.cli_params.codex["model"] == "gpt-5.4"
        assert p.cli_params.codex["reasoning_effort"] == "xhigh"
        assert p.cli_params.codex["yolo"] is True


class TestUserSession:
    """测试 UserSession"""

    def test_creation(self, temp_dir: Path):
        s = UserSession(bot_id=1, bot_alias="main", user_id=100, working_dir=str(temp_dir))
        assert s.bot_id == 1
        assert s.bot_alias == "main"
        assert s.user_id == 100
        assert s.working_dir == str(temp_dir)
        assert s.history == []
        assert s.codex_session_id is None
        assert s.kimi_session_id is None
        assert s.claude_session_id is None
        assert s.claude_session_initialized is False
        assert s.process is None
        assert s.is_processing is False
        assert s.message_count == 0
        assert isinstance(s.last_activity, datetime)
        assert isinstance(s._lock, threading.Lock)

    def test_touch(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        old_time = s.last_activity
        old_count = s.message_count
        time.sleep(0.01)
        s.touch()
        assert s.last_activity > old_time
        assert s.message_count == old_count + 1

    def test_is_expired(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        assert s.is_expired() is False
        # 强制过期
        from bot.config import SESSION_TIMEOUT
        s.last_activity = datetime(2000, 1, 1)
        assert s.is_expired() is True

    def test_add_to_history(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        s.add_to_history("user", "hello")
        s.add_to_history("assistant", "world")
        assert len(s.history) == 2
        assert s.history[0]["role"] == "user"
        assert s.history[0]["content"] == "hello"
        assert "timestamp" in s.history[0]
        assert s.history[1]["role"] == "assistant"

    def test_add_to_history_preserves_elapsed_seconds(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        s.add_to_history("assistant", "world", elapsed_seconds=3)

        assert s.history[0]["role"] == "assistant"
        assert s.history[0]["content"] == "world"
        assert s.history[0]["elapsed_seconds"] == 3

    def test_history_truncation(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        for i in range(120):
            s.add_to_history("user", f"msg{i}")
        assert len(s.history) == 100

    def test_terminate_process_no_process(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        s.terminate_process()  # 不应报错

    def test_terminate_process_with_process(self):
        from unittest.mock import MagicMock
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_proc.kill = MagicMock()
        s.process = mock_proc
        s.is_processing = True
        s.terminate_process()
        mock_proc.terminate.assert_called_once()
        assert s.process is None
        assert s.is_processing is False
