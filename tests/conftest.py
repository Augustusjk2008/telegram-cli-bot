from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault(
    "TCB_DATA_DIR",
    str(Path(tempfile.gettempdir()) / f"orbit-safe-claw-pytest-data-{os.getpid()}"),
)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def clean_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import bot.session_store as session_store
    import bot.app_settings as app_settings
    from bot.sessions import sessions, sessions_lock

    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "runtime-data"))
    isolated_store = tmp_path / ".session_store.json"
    monkeypatch.setattr(session_store, "STORE_FILE", isolated_store)
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", tmp_path / ".web_admin_settings.json")

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
