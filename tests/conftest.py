from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# A completed storage migration commits ~/.tcb/storage.json, which makes the
# locator authoritative for every process.  Test modules import bot while
# pytest collects them, so reading the developer's real home profile would
# either point the suite at production data or raise StoragePathError before
# any fixture can isolate it.  Keep the whole session on a throwaway home;
# tests that need another one monkeypatch Path.home themselves.
_SESSION_HOME = Path(tempfile.mkdtemp(prefix="orbit-safe-claw-pytest-home-"))
Path.home = staticmethod(lambda: _SESSION_HOME)

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
