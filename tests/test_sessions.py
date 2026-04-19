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
        """测试恢复旧快照时切换到 local_v1 并清理原生 session_id"""
        from unittest.mock import patch
        from bot.session_store import LOCAL_HISTORY_BACKEND, load_session, save_session
        
        # 先保存会话到持久化存储
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread_restored_123",
                claude_session_id="claude_restored_789",
            )
            
            # 清除内存中的会话
            with sessions_lock:
                sessions.clear()
            
            # 重新获取会话，应该执行 cutover 而不是恢复旧的原生 session_id
            other_dir = temp_dir / "other"
            other_dir.mkdir()
            s = get_session(1, "main", 100, str(other_dir))

            assert s.codex_session_id is None
            assert s.claude_session_id is None
            assert s.claude_session_initialized is False
            assert s.local_history_backend == LOCAL_HISTORY_BACKEND
            assert s.session_epoch == 1
            persisted = load_session(1, 100)
            assert persisted["local_history_backend"] == LOCAL_HISTORY_BACKEND
            assert persisted["session_epoch"] == 1
            assert persisted["working_dir"] == str(other_dir)
            assert persisted["browse_dir"] == str(other_dir)
            assert "codex_session_id" not in persisted
            assert "claude_session_id" not in persisted
            assert not hasattr(s, "ki" "mi_session_id")

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

    def test_session_restored_after_restart(self, temp_dir: Path):
        """测试重启后恢复旧快照时触发 local_v1 cutover"""
        from unittest.mock import patch
        from bot.session_store import LOCAL_HISTORY_BACKEND, load_session, save_session
        
        with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
            # 模拟之前保存的会话
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="codex_prev_session",
            )
            
            # 验证存储存在
            assert load_session(1, 100) is not None
            
            # 清除内存会话，模拟重启
            with sessions_lock:
                sessions.clear()
            
            # 重新获取会话（模拟重启后）时应该清掉旧的原生 session_id
            s = get_session(1, "main", 100, str(temp_dir))

            assert s.codex_session_id is None
            assert s.claude_session_id is None
            assert s.claude_session_initialized is False
            assert s.local_history_backend == LOCAL_HISTORY_BACKEND
            assert s.session_epoch == 1
            persisted = load_session(1, 100)
            assert persisted["local_history_backend"] == LOCAL_HISTORY_BACKEND
            assert persisted["session_epoch"] == 1
            assert persisted["working_dir"] == str(temp_dir)
            assert persisted["browse_dir"] == str(temp_dir)
            assert "codex_session_id" not in persisted
            assert not hasattr(s, "ki" "mi_session_id")

    def test_persist_saves_local_history_backend_without_legacy_overlay_fields(self, temp_dir: Path):
        """测试会话快照只持久化 local_v1 元数据，不再保存 overlay/running 字段"""
        from unittest.mock import patch
        from bot.session_store import load_session

        store_file = temp_dir / ".session_store.json"
        overlay = {
            "provider": "claude",
            "native_session_id": "claude-session-1",
            "user_text": "继续",
            "started_at": "2026-04-14T10:00:00",
            "updated_at": "2026-04-14T10:00:04",
            "summary_text": "已终止，未返回可显示内容",
            "summary_kind": "partial_preview",
            "completion_state": "cancelled",
            "trace": [{"kind": "cancelled", "summary": "用户终止输出"}],
            "locator_hint": {"cwd": "/srv/demo/repo"},
        }
        with patch("bot.session_store.STORE_FILE", store_file):
            session = get_session(1, "main", 100, str(temp_dir))
            session.working_dir = str(temp_dir / "workspace")
            session.local_history_backend = "local_v1"
            session.session_epoch = 2
            session.touch()
            session.add_to_history("user", "hello")
            session.web_turn_overlays = [overlay]
            session.persist()
            session.start_running_reply("continue")
            session.update_running_reply("partial")

            data = load_session(1, 100)
            assert data is not None
            assert data["working_dir"] == str(temp_dir / "workspace")
            assert data["message_count"] == 1
            assert data["local_history_backend"] == "local_v1"
            assert data["session_epoch"] == 2
            assert "history" not in data
            assert "web_turn_overlays" not in data
            assert "running_user_text" not in data
            assert "running_preview_text" not in data
            assert "last_activity" in data

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
            assert session.working_dir == str(restored_dir)
            assert session.history == []
            assert getattr(session, "web_turn_overlays", []) == []
            assert session.running_user_text is None
            assert session.running_preview_text == ""
            assert session.running_started_at is None
            assert session.running_updated_at is None
            assert session.is_processing is False
