"""
会话管理测试

直接导入 bot.sessions 中的真实函数进行测试
"""

import json
import threading
import time
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
from bot.models import (
    UserSession,
    _SESSION_PERSISTENCE_SCHEDULER,
    flush_pending_session_persistence,
)


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

    def test_web_users_share_a_session_without_collapsing_bot_or_agent_boundaries(self, temp_dir: Path):
        main = get_or_create_session(801, "main", 101, str(temp_dir), load_persisted_state=False)
        same_shared_user = get_or_create_session(801, "main", 202, str(temp_dir), load_persisted_state=False)
        reviewer = get_or_create_session(801, "main", 101, str(temp_dir), load_persisted_state=False, agent_id="reviewer")
        other_bot = get_or_create_session(802, "other", 202, str(temp_dir), load_persisted_state=False)

        shared_user_id = chat_session_user_id(101)
        assert main is same_shared_user
        assert chat_session_user_id(202) == shared_user_id
        assert set(sessions) == {
            (801, shared_user_id, "main"),
            (801, shared_user_id, "reviewer"),
            (802, shared_user_id, "main"),
        }
        assert len({id(main), id(reviewer), id(other_bot)}) == 3

    def test_concurrent_restore_initializes_the_session_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        import bot.sessions as session_module

        start = threading.Barrier(3)
        load_started = threading.Event()
        release_load = threading.Event()
        counter_lock = threading.Lock()
        load_calls = 0
        migration_calls = 0
        results: list[UserSession] = []
        errors: list[BaseException] = []

        def fake_migrate(_bot_id: int, _user_id: int) -> int:
            nonlocal migration_calls
            with counter_lock:
                migration_calls += 1
            return 0

        def fake_load(_bot_id: int, _user_id: int, agent_id: str = "main") -> dict:
            nonlocal load_calls
            with counter_lock:
                load_calls += 1
            load_started.set()
            assert release_load.wait(timeout=2)
            return {"codex_session_id": f"restored-{agent_id}", "working_dir": str(temp_dir)}

        monkeypatch.setattr(session_module, "migrate_sessions_to_shared", fake_migrate)
        monkeypatch.setattr(session_module, "load_session", fake_load)

        def worker() -> None:
            try:
                start.wait(timeout=2)
                results.append(get_or_create_session(9101, "race", 100, str(temp_dir)))
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        start.wait(timeout=2)
        assert load_started.wait(timeout=1)
        time.sleep(0.05)
        release_load.set()
        for thread in threads:
            thread.join(timeout=2)

        assert errors == []
        assert len(results) == 2
        assert results[0] is results[1]
        assert load_calls == 1
        assert migration_calls == 1

    def test_shared_session_migration_runs_once_across_agent_sessions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        import bot.sessions as session_module

        migration_calls: list[tuple[int, int]] = []
        load_calls: list[str] = []
        monkeypatch.setattr(
            session_module,
            "migrate_sessions_to_shared",
            lambda bot_id, user_id: migration_calls.append((bot_id, user_id)) or 0,
        )
        monkeypatch.setattr(
            session_module,
            "load_session",
            lambda _bot_id, _user_id, agent_id="main": load_calls.append(agent_id) or None,
        )

        get_or_create_session(9102, "migration", 100, str(temp_dir), agent_id="main")
        get_or_create_session(9102, "migration", 100, str(temp_dir), agent_id="reviewer")

        assert migration_calls == [(9102, chat_session_user_id(100))]
        assert load_calls == ["main", "reviewer"]

class TestClearBotSessions:
    """测试 clear_bot_sessions"""

    def test_clear_bot_sessions_cancels_stale_persistence(self, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
        calls: list[int] = []
        flush_pending_session_persistence()
        monkeypatch.setattr(_SESSION_PERSISTENCE_SCHEDULER, "delay_seconds", 60.0)
        session = UserSession(
            bot_id=1,
            bot_alias="main",
            user_id=chat_session_user_id(100),
            working_dir=str(temp_dir),
            persist_hook=lambda _session: calls.append(1),
        )
        with sessions_lock:
            sessions[(session.bot_id, session.user_id, session.agent_id)] = session
        session.persist_debounced()

        clear_bot_sessions(1)
        flush_pending_session_persistence()
        session.persist()

        assert calls == []

    def test_update_workdir_resets_all_bot_sessions(self, temp_dir: Path):
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        main = get_or_create_session(1, "main", 100, str(old_dir), agent_id="main")
        reviewer = get_or_create_session(1, "main", 100, str(old_dir), agent_id="reviewer")
        main.codex_session_id = "codex-main"
        main.native_agent_session_id = "native-main"
        main.active_conversation_id = "conv-main"
        main.is_processing = True
        main.running_user_text = "text"
        main.running_preview_text = "preview"
        main.web_turn_overlays = [{"a": 1}]
        reviewer.codex_session_id = "codex-reviewer"
        reviewer.native_agent_session_id = "native-reviewer"
        reviewer.active_conversation_id = "conv-reviewer"
        reviewer.is_processing = True

        count = update_bot_working_dir("main", str(new_dir))

        assert count == 2
        for session in (main, reviewer):
            assert session.working_dir == str(new_dir)
            assert session.browse_dir == str(new_dir)
            assert session.codex_session_id is None
            assert session.native_agent_session_id is None
            assert session.native_agent_run_id is None
            assert session.native_agent_server_key is None
            assert session.active_conversation_id is None
            assert session.running_user_text is None
            assert session.running_preview_text == ""
            assert session.web_turn_overlays == []
            assert session.is_processing is False
            assert session.process is None
            assert session.message_count == 0
            assert session.session_epoch == 1

    def test_update_workdir_does_not_touch_other_alias_sessions(self, temp_dir: Path):
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        other_dir = temp_dir / "other"
        old_dir.mkdir()
        new_dir.mkdir()
        other_dir.mkdir()
        main = get_or_create_session(1, "main", 100, str(old_dir), agent_id="main")
        other = get_or_create_session(2, "other", 100, str(other_dir), agent_id="main")

        count = update_bot_working_dir("main", str(new_dir))

        assert count == 1
        assert main.working_dir == str(new_dir)
        assert other.working_dir == str(other_dir)

class TestSessionPersistence:
    """测试会话持久化功能"""

    def test_debounced_persistence_uses_single_process_worker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        flush_pending_session_persistence()
        calls: list[int] = []
        completed = threading.Event()
        session = UserSession(
            bot_id=99,
            bot_alias="worker-test",
            user_id=101,
            working_dir=str(temp_dir),
            persist_hook=lambda _session: (calls.append(1), completed.set()),
        )
        monkeypatch.setattr(
            _SESSION_PERSISTENCE_SCHEDULER,
            "delay_seconds",
            0.03,
        )

        for _ in range(100):
            session.persist_debounced()

        assert completed.wait(timeout=1)
        time.sleep(0.05)
        assert calls == [1]

    def test_disable_persistence_cancels_process_worker_entry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        flush_pending_session_persistence()
        calls: list[int] = []
        session = UserSession(
            bot_id=100,
            bot_alias="worker-cancel-test",
            user_id=102,
            working_dir=str(temp_dir),
            persist_hook=lambda _session: calls.append(1),
        )
        monkeypatch.setattr(
            _SESSION_PERSISTENCE_SCHEDULER,
            "delay_seconds",
            1.0,
        )

        session.persist_debounced()
        session.disable_persistence()
        flush_pending_session_persistence()

        assert calls == []

    def test_flush_pending_waits_for_inflight_worker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        flush_pending_session_persistence()
        started = threading.Event()
        release = threading.Event()
        flushed = threading.Event()
        session = UserSession(
            bot_id=101,
            bot_alias="worker-inflight-test",
            user_id=103,
            working_dir=str(temp_dir),
            persist_hook=lambda _session: (started.set(), release.wait(timeout=2)),
        )
        monkeypatch.setattr(_SESSION_PERSISTENCE_SCHEDULER, "delay_seconds", 0.01)

        session.persist_debounced()
        assert started.wait(timeout=1)

        flush_thread = threading.Thread(
            target=lambda: (flush_pending_session_persistence(), flushed.set()),
            daemon=True,
        )
        flush_thread.start()
        assert not flushed.wait(timeout=0.05)

        release.set()
        flush_thread.join(timeout=1)
        assert flushed.is_set()

    def test_disable_persistence_waits_for_inflight_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temp_dir: Path,
    ):
        flush_pending_session_persistence()
        started = threading.Event()
        release = threading.Event()
        disabled = threading.Event()
        session = UserSession(
            bot_id=102,
            bot_alias="worker-disable-inflight-test",
            user_id=104,
            working_dir=str(temp_dir),
            persist_hook=lambda _session: (started.set(), release.wait(timeout=2)),
        )
        monkeypatch.setattr(_SESSION_PERSISTENCE_SCHEDULER, "delay_seconds", 0.01)

        session.persist_debounced()
        assert started.wait(timeout=1)

        disable_thread = threading.Thread(
            target=lambda: (session.disable_persistence(), disabled.set()),
            daemon=True,
        )
        disable_thread.start()
        assert not disabled.wait(timeout=0.05)

        release.set()
        disable_thread.join(timeout=1)
        assert disabled.is_set()

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
