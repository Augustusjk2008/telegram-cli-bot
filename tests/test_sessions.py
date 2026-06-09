"""
会话管理测试

直接导入 bot.sessions 中的真实函数进行测试
"""

import json
import threading
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
    save_all_sessions,
    sessions,
    sessions_lock,
    update_bot_working_dir,
)
from bot.chat_identity import chat_session_user_id


class TestGetSession:
    """测试 get_session"""

    def test_create_new_session(self, temp_dir: Path):
        s = get_session(1, "main", 100, str(temp_dir))
        assert s.bot_id == 1
        assert s.bot_alias == "main"
        assert s.user_id == chat_session_user_id(100)
        assert s.working_dir == str(temp_dir)

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

class TestClearBotSessions:
    """测试 clear_bot_sessions"""

    def test_update_workdir_resets_all_agent_native_sessions(self, temp_dir: Path):
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        main = get_or_create_session(1, "main", 100, str(old_dir), agent_id="main")
        reviewer = get_or_create_session(1, "main", 100, str(old_dir), agent_id="reviewer")
        main.codex_session_id = "codex-main"
        reviewer.codex_session_id = "codex-reviewer"
        main.native_agent_session_id = "native-main"
        reviewer.native_agent_session_id = "native-reviewer"

        update_bot_working_dir("main", str(new_dir))

        assert main.working_dir == str(new_dir)
        assert reviewer.working_dir == str(new_dir)
        assert main.codex_session_id is None
        assert reviewer.codex_session_id is None
        assert main.native_agent_session_id is None
        assert reviewer.native_agent_session_id is None

class TestSessionPersistence:
    """测试会话持久化功能"""

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

    def test_reset_session_clears_persisted_native_agent_session_id(self, temp_dir: Path):
        from unittest.mock import patch
        from bot.session_store import save_session, load_session

        store_file = temp_dir / ".session_store.json"

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(1, 100, native_agent_session_id="native-1", working_dir=str(temp_dir))
            with sessions_lock:
                sessions.clear()

            session = get_session(1, "main", 100, str(temp_dir))
            assert session.native_agent_session_id == "native-1"

            assert reset_session(1, 100) is True
            assert load_session(1, 100) is None
