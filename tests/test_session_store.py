"""
会话ID持久化存储测试
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.session_store import (
    _make_key,
    close_session_store,
    flush_session_store,
    load_session,
    load_session_ids,
    migrate_sessions_to_shared,
    rename_bot_sessions,
    remove_all_sessions_for_bot,
    remove_session,
    save_session,
    save_session_ids,
    session_store_diagnostics,
)


def test_session_store_defaults_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_STORE_BACKEND", raising=False)
    monkeypatch.delenv("TCB_SESSION_STORE_BACKEND", raising=False)

    assert session_store_diagnostics()["requested_backend"] == "sqlite"
    close_session_store()


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

    def test_save_and_load_native_agent_session_id(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                native_agent_session_id="native-session-1",
            )

            data = load_session(1, 100)

        assert data is not None
        assert data["native_agent_session_id"] == "native-session-1"


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


class TestRenameBotSessions:
    """测试 bot 改名时迁移会话快照"""

    def test_rename_bot_sessions_merges_into_new_bot_id(self, temp_dir: Path):
        store_file = temp_dir / ".session_store.json"
        workdir = temp_dir / "repo"
        workdir.mkdir()

        with patch("bot.session_store.STORE_FILE", store_file):
            save_session(
                bot_id=1,
                user_id=100,
                codex_session_id="thread-old",
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=3,
                last_activity="2026-04-23T08:00:00",
                local_history_backend="local_v1",
                session_epoch=0,
            )
            save_session(
                bot_id=9,
                user_id=100,
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=0,
                last_activity="2026-04-23T09:00:00",
                local_history_backend="local_v1",
                session_epoch=0,
            )
            save_session(
                bot_id=1,
                user_id=200,
                claude_session_id="claude-old",
                working_dir=str(workdir),
                browse_dir=str(workdir),
                message_count=1,
                last_activity="2026-04-23T08:30:00",
                local_history_backend="local_v1",
                session_epoch=2,
            )

            moved = rename_bot_sessions(1, 9)

            assert moved == 2
            assert load_session(1, 100) is None
            assert load_session(1, 200) is None

            merged = load_session(9, 100)
            assert merged is not None
            assert merged["codex_session_id"] == "thread-old"
            assert merged["working_dir"] == str(workdir)
            assert merged["browse_dir"] == str(workdir)
            assert merged["message_count"] == 3
            assert merged["last_activity"] == "2026-04-23T09:00:00"
            assert merged["local_history_backend"] == "local_v1"
            assert merged["session_epoch"] == 0

            moved_snapshot = load_session(9, 200)
            assert moved_snapshot is not None
            assert moved_snapshot["claude_session_id"] == "claude-old"
            assert moved_snapshot["session_epoch"] == 2


def test_sqlite_backend_migrates_json_and_keeps_backup(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    store_file = temp_dir / "session_store.json"
    legacy = {
        "1:100": {
            "codex_session_id": "thread-1",
            "working_dir": str(temp_dir / "repo"),
            "active_conversation_id": "conv-1",
            "local_history_backend": "local_v1",
        }
    }
    store_file.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SESSION_STORE_BACKEND", "sqlite")

    with patch("bot.session_store.STORE_FILE", store_file):
        loaded = load_session_ids()
        diagnostics = session_store_diagnostics()
        close_session_store()

    assert loaded == legacy
    assert diagnostics["active_backend"] == "sqlite"
    assert store_file.is_file()
    assert store_file.with_suffix(".sqlite3").is_file()
    assert store_file.with_suffix(".sqlite3.migration.json").is_file()
    assert list(temp_dir.glob("session_store.pre-sqlite-*.json"))


def test_sqlite_backend_coalesces_repeated_session_updates(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    store_file = temp_dir / "session_store.json"
    monkeypatch.setenv("SESSION_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SESSION_STORE_FLUSH_INTERVAL_SECONDS", "10")

    with patch("bot.session_store.STORE_FILE", store_file):
        for index in range(1000):
            save_session(
                1,
                100,
                codex_session_id=f"thread-{index}",
                working_dir=str(temp_dir),
            )
        before_flush = session_store_diagnostics()
        flushed = flush_session_store()
        after_flush = session_store_diagnostics()
        loaded = load_session(1, 100)
        close_session_store()

    assert before_flush["pending_count"] == 1
    assert before_flush["queued_write_count"] == 1000
    assert flushed == 1
    assert after_flush["write_batch_count"] == 1
    assert loaded is not None
    assert loaded["codex_session_id"] == "thread-999"


def test_sqlite_reads_wait_for_inflight_pending_batch(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    from bot.session_store_sqlite import SessionStoreSQLite

    store = SessionStoreSQLite(
        temp_dir / "session_store.sqlite3",
        flush_interval_seconds=0.01,
    )
    key = "1:100"
    store.queue_upsert(
        key,
        bot_id=1,
        user_id=100,
        agent_id="main",
        payload={"codex_session_id": "old"},
    )
    store.flush()

    write_started = threading.Event()
    allow_write = threading.Event()
    original_write_batch = store._write_batch

    def blocked_write_batch(batch):
        write_started.set()
        assert allow_write.wait(timeout=1)
        original_write_batch(batch)

    monkeypatch.setattr(store, "_write_batch", blocked_write_batch)
    store.queue_upsert(
        key,
        bot_id=1,
        user_id=100,
        agent_id="main",
        payload={"codex_session_id": "new"},
    )
    assert write_started.wait(timeout=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        result_future = executor.submit(store.get, key)
        time.sleep(0.03)
        allow_write.set()
        loaded = result_future.result(timeout=1)

    store.close()
    assert loaded == {"codex_session_id": "new"}


@pytest.mark.parametrize(
    ("queued_payload", "expected_payload"),
    [
        ({"codex_session_id": "new"}, {"codex_session_id": "new"}),
        (None, None),
    ],
)
def test_sqlite_replace_all_preserves_concurrent_queued_mutation(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
    queued_payload: dict[str, str] | None,
    expected_payload: dict[str, str] | None,
) -> None:
    from bot.session_store_sqlite import SessionStoreSQLite

    store = SessionStoreSQLite(
        temp_dir / "session_store.sqlite3",
        flush_interval_seconds=60,
    )
    key = "1:100"
    store.queue_upsert(
        key,
        bot_id=1,
        user_id=100,
        agent_id="main",
        payload={"codex_session_id": "old"},
    )
    store.flush()
    stale_snapshot = store.load_all()

    replace_flushed = threading.Event()
    allow_replace = threading.Event()
    original_flush = store.flush

    def pause_replace_after_flush() -> int:
        flushed = original_flush()
        replace_flushed.set()
        assert allow_replace.wait(timeout=2)
        return flushed

    monkeypatch.setattr(store, "flush", pause_replace_after_flush)

    try:
        mutation_started = threading.Event()
        mutation_flushed = threading.Event()

        def queue_and_flush() -> None:
            mutation_started.set()
            store.queue_upsert(
                key,
                bot_id=1,
                user_id=100,
                agent_id="main",
                payload=queued_payload,
            )
            original_flush()
            mutation_flushed.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            replace_future = executor.submit(store.replace_all, stale_snapshot)
            assert replace_flushed.wait(timeout=2)

            mutation_future = executor.submit(queue_and_flush)
            assert mutation_started.wait(timeout=2)
            mutation_flushed.wait(timeout=0.2)
            allow_replace.set()
            replace_future.result(timeout=2)
            mutation_future.result(timeout=2)

        assert store.get(key) == expected_payload
    finally:
        allow_replace.set()
        store.close()


def test_sqlite_migration_failure_falls_back_to_legacy_json(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    from bot.session_store_sqlite import SessionStoreSQLite

    store_file = temp_dir / "session_store.json"
    legacy = {"1:100": {"codex_session_id": "thread-legacy"}}
    store_file.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setenv("SESSION_STORE_BACKEND", "sqlite")

    def fail_migration(*_args, **_kwargs):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(
        SessionStoreSQLite,
        "_migrate_legacy_json",
        fail_migration,
    )

    with patch("bot.session_store.STORE_FILE", store_file):
        loaded = load_session_ids()
        diagnostics = session_store_diagnostics()
        close_session_store()

    assert loaded == legacy
    assert diagnostics["active_backend"] == "json"
    assert store_file.is_file()
    assert not store_file.with_suffix(".sqlite3").exists()
