"""
会话管理测试

直接导入 bot.sessions 中的真实函数进行测试
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.sessions import (
    clear_bot_sessions,
    get_session,
    get_or_create_session,
    is_bot_processing,
    reset_session,
    sessions,
    sessions_lock,
    update_bot_working_dir,
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

    def test_different_agents_different_sessions(self, temp_dir: Path):
        main = get_or_create_session(1, "main", 100, str(temp_dir), agent_id="main")
        reviewer = get_or_create_session(1, "main", 100, str(temp_dir), agent_id="reviewer")
        main.codex_session_id = "codex-main"
        reviewer.codex_session_id = "codex-reviewer"

        assert main is not reviewer
        assert main.agent_id == "main"
        assert reviewer.agent_id == "reviewer"
        assert main.codex_session_id == "codex-main"
        assert reviewer.codex_session_id == "codex-reviewer"

    def test_inactive_session_is_reused_instead_of_recreated(self, temp_dir: Path):
        s1 = get_session(1, "main", 100, str(temp_dir))
        s1.last_activity = datetime(2000, 1, 1)  # 强制过期
        s2 = get_session(1, "main", 100, str(temp_dir))
        assert s1 is s2


class TestResetSession:
    """测试 reset_session"""

    def test_reset_existing(self, temp_dir: Path):
        get_session(1, "main", 100, str(temp_dir))
        result = reset_session(1, 100)
        assert result is True
        # 再获取应该是新的
        key = (1, 100, "main")
        with sessions_lock:
            assert key not in sessions

    def test_reset_child_agent_keeps_main_agent(self, temp_dir: Path):
        main = get_or_create_session(1, "main", 100, str(temp_dir), agent_id="main")
        reviewer = get_or_create_session(1, "main", 100, str(temp_dir), agent_id="reviewer")
        main.codex_session_id = "codex-main"
        reviewer.codex_session_id = "codex-reviewer"

        result = reset_session(1, 100, agent_id="reviewer")

        assert result is True
        with sessions_lock:
            assert (1, 100, "main") in sessions
            assert (1, 100, "reviewer") not in sessions
        assert main.codex_session_id == "codex-main"

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
            assert (1, 100, "main") not in sessions
            assert (1, 200, "main") not in sessions
            assert (2, 100, "main") in sessions

    def test_update_workdir_resets_all_agent_native_sessions(self, temp_dir: Path):
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        main = get_or_create_session(1, "main", 100, str(old_dir), agent_id="main")
        reviewer = get_or_create_session(1, "main", 100, str(old_dir), agent_id="reviewer")
        main.codex_session_id = "codex-main"
        reviewer.codex_session_id = "codex-reviewer"

        update_bot_working_dir("main", str(new_dir))

        assert main.working_dir == str(new_dir)
        assert reviewer.working_dir == str(new_dir)
        assert main.codex_session_id is None
        assert reviewer.codex_session_id is None

    def test_update_workdir_resets_kimi_native_sessions(self, temp_dir: Path):
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        session = get_or_create_session(1, "main", 100, str(old_dir), agent_id="main")
        session.kimi_session_id = "kimi-main"

        update_bot_working_dir("main", str(new_dir))

        assert session.working_dir == str(new_dir)
        assert session.kimi_session_id is None


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
            
            s2 = get_session(1, "main", 200, str(temp_dir))
            s2.claude_session_id = "claude_s2"
            
            # 保存所有会话
            save_all_sessions()
            
            # 验证持久化存储
            data1 = load_session(1, 100)
            assert data1["codex_session_id"] == "thread_s1"
            
            data2 = load_session(1, 200)
            assert data2["claude_session_id"] == "claude_s2"

    def test_get_session_restores_kimi_session_id(self, temp_dir: Path):
        from unittest.mock import patch
        from bot.session_store import save_session

        store_file = temp_dir / ".session_store.json"

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(1, 100, kimi_session_id="kimi-session-1", working_dir=str(temp_dir))
            with sessions_lock:
                sessions.clear()

            session = get_session(1, "main", 100, str(temp_dir))

        assert session.kimi_session_id == "kimi-session-1"

    def test_get_or_create_session_clears_legacy_native_session_ids_on_cutover(self, temp_dir: Path):
        """测试首轮 cutover 会清掉 legacy native session 和可见 overlay 状态"""
        from unittest.mock import patch
        from bot.session_store import _make_key

        store_file = temp_dir / ".session_store.json"
        restored_dir = temp_dir / "restored"
        restored_dir.mkdir()
        overlay = {"provider": "codex", "summary_text": "部分预览"}

        with patch("bot.session_store.STORE_FILE", store_file):
            store_file.write_text(
                json.dumps(
                    {
                        _make_key(1, 100): {
                            "codex_session_id": "thread-old",
                            "claude_session_id": "claude-old",
                            "working_dir": str(restored_dir),
                            "web_turn_overlays": [overlay],
                            "running_started_at": "2026-04-18T10:00:00+00:00",
                            "running_user_text": "continue",
                            "running_preview_text": "still running",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with sessions_lock:
                sessions.clear()

            session = get_session(1, "main", 100, str(temp_dir))

            assert session.local_history_backend == "local_v1"
            assert session.session_epoch == 1
            assert session.codex_session_id is None
            assert session.claude_session_id is None
            assert session.kimi_session_id is None
            assert session.working_dir == str(restored_dir)
            assert session.history == []
            assert getattr(session, "web_turn_overlays", []) == []
            assert session.running_user_text is None
            assert session.running_preview_text == ""
            assert session.running_started_at is None
            assert session.running_updated_at is None
            assert session.is_processing is False
