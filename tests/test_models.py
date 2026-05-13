"""
数据模型测试

直接导入 bot.models 中的 BotProfile 和 UserSession 进行测试
"""

import time

from bot.models import BotProfile, UserSession

class TestBotProfile:
    """测试 BotProfile"""

    def test_to_dict(self):
        p = BotProfile(alias="sub1", token="tok", cli_type="claude", cli_path="/usr/bin/claude",
                        working_dir="/work", enabled=False)
        d = p.to_dict()
        assert d["alias"] == "sub1"
        assert "token" not in d
        assert d["cli_type"] == "claude"
        assert d["cli_path"] == "/usr/bin/claude"
        assert d["working_dir"] == "/work"
        assert d["enabled"] is False

class TestUserSession:
    """测试 UserSession"""

    def test_touch(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        old_time = s.last_activity
        old_count = s.message_count
        time.sleep(0.01)
        s.touch()
        assert s.last_activity > old_time
        assert s.message_count == old_count + 1

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

    def test_terminate_process_with_process(self, monkeypatch):
        from unittest.mock import MagicMock

        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        mock_proc = MagicMock()
        s.process = mock_proc
        s.is_processing = True
        called = []
        monkeypatch.setattr("bot.session_runtime.terminate_session_process", lambda session: called.append(session))

        s.terminate_process()

        assert called == [s]
        assert s.process is None
        assert s.is_processing is False
