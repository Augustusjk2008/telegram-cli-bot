from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def clean_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import bot.session_store as session_store
    from bot.sessions import sessions, sessions_lock

    isolated_store = tmp_path / ".session_store.json"
    monkeypatch.setattr(session_store, "STORE_FILE", isolated_store)

    with sessions_lock:
        existing_sessions = list(sessions.values())
        sessions.clear()

    for session in existing_sessions:
        session.disable_persistence()
        try:
            session.terminate_process()
        except Exception:
            pass

    yield isolated_store

    with sessions_lock:
        remaining_sessions = list(sessions.values())
        sessions.clear()

    for session in remaining_sessions:
        session.disable_persistence()
        try:
            session.terminate_process()
        except Exception:
            pass
