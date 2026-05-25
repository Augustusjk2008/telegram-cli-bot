"""
数据模型测试

直接导入 bot.models 中的 BotProfile 和 UserSession 进行测试
"""

import threading
import time

from bot.models import BotProfile, UserSession, normalize_prompt_presets

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

    def test_prompt_presets_round_trip_and_trim(self):
        p = BotProfile.from_dict(
            {
                "alias": "sub1",
                "prompt_presets": [
                    {
                        "id": " preset-1 ",
                        "title": "  审查  ",
                        "content": "  请审查代码  ",
                        "ignored": True,
                    }
                ],
            }
        )

        assert p.prompt_presets == [
            {"id": "preset-1", "title": "审查", "content": "请审查代码"}
        ]
        assert BotProfile.from_dict(p.to_dict()).prompt_presets == p.prompt_presets

    def test_prompt_presets_normalizer_enforces_limits(self):
        items = [
            {"id": f"id-{index}", "title": "T" * 100, "content": "C" * 13000}
            for index in range(60)
        ]

        normalized = normalize_prompt_presets(items)

        assert len(normalized) == 50
        assert len(normalized[0]["title"]) == 80
        assert len(normalized[0]["content"]) == 12000

    def test_prompt_presets_strict_mode_rejects_blank_fields(self):
        try:
            normalize_prompt_presets([{"id": "p1", "title": "", "content": "内容"}], strict=True)
        except ValueError as exc:
            assert "标题不能为空" in str(exc)
        else:
            raise AssertionError("expected ValueError")

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

    def test_persist_is_safe_when_called_while_session_lock_is_held(self):
        s = UserSession(bot_id=1, bot_alias="m", user_id=2, working_dir="/tmp")
        persisted = []
        finished = threading.Event()
        s.persist_hook = lambda current: persisted.append(current)

        def worker():
            with s._lock:
                s.codex_session_id = "codex-session"
                s.persist()
            finished.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        assert finished.wait(timeout=0.5), "持有 session 锁时调用 persist 会死锁"
        assert persisted == [s]
