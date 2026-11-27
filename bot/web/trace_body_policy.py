"""Workspace and deployment-wide v1 trace writes bound to a verified rollback reader."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from bot.update_state import UpdateConflict, UpdateStore, installation_id


PROGRAM_ROOT = Path(__file__).resolve().parents[2]
READER_FILES = ("bot/web/trace_previews.py", "bot/web/chat_store.py", "bot/web/trace_compaction.py")
_POLICY = "trace_body_pilot"
ALL_SESSIONS_FILE = "trace-body-compression.json"
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS trace_body_pilot (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), workspace_key TEXT NOT NULL,
        writer TEXT NOT NULL, rollback_root TEXT NOT NULL, rollback_digest TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS trace_body_pilot_events (
        event_id TEXT PRIMARY KEY REFERENCES trace_events(id) ON DELETE CASCADE) WITHOUT ROWID""",
)


@lru_cache(maxsize=64)
def _file_digest(path: Path, stamp: tuple) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def program_digest(root: Path, *, writer: bool = False) -> str:
    files = ("VERSION", *READER_FILES)
    if writer or (root / "bot/web/trace_body_policy.py").is_file():
        files += ("bot/web/trace_body_policy.py",)
    paths = [root / name for name in files]
    marker = root / ".update-manifest.json"
    if marker.is_file():
        paths.append(marker)
    digest = hashlib.sha256()
    for path in paths:
        info = path.stat()
        stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        digest.update(_file_digest(path, stamp).encode("ascii"))
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _package_generation(root: Path, state_file: Path, stamp: tuple) -> str:
    from bot.update_migration_gate import trace_rollback_origin
    state = UpdateStore(root, state_root=state_file.parent).read()
    job = state.get("job") or {}
    if job.get("phase") in {"waiting_restart", "applying", "awaiting_health", "rolling_back", "recovery_required"}:
        raise UpdateConflict("installation update is in progress")
    origin = trace_rollback_origin(job) or state.get("trace_rollback_origin") or {}
    return hashlib.sha256(json.dumps(origin, sort_keys=True).encode()).hexdigest() if origin else ""


def writer_identity() -> str:
    identity = installation_id(PROGRAM_ROOT) + ":" + program_digest(PROGRAM_ROOT, writer=True)
    if (PROGRAM_ROOT / ".update-manifest.json").is_file():
        from bot.runtime_paths import get_update_state_root
        state_file = get_update_state_root(PROGRAM_ROOT) / "state.json"
        if state_file.exists():
            info = state_file.stat()
            generation = _package_generation(PROGRAM_ROOT, state_file, (info.st_ino, info.st_size, info.st_mtime_ns))
            if generation:
                identity += ":" + generation
    return identity


def policy(conn: sqlite3.Connection):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_POLICY,)).fetchone():
        return None
    return conn.execute("SELECT workspace_key,writer,rollback_root,rollback_digest FROM trace_body_pilot WHERE singleton=1").fetchone()


class AllSessions(NamedTuple):
    state: str
    writer: str
    rollback_root: str
    rollback_digest: str
    excluded: tuple[str, ...] = ()

    def covers(self, workspace_key: str) -> bool:
        return self.state == "enabled" and workspace_key not in self.excluded


@lru_cache(maxsize=16)
def _read_all_sessions(path: Path, stamp: tuple) -> AllSessions:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1 or data.get("state") not in ("enabled", "disabling")
            or not all(isinstance(data.get(k), str) for k in ("writer", "rollback_root", "rollback_digest"))
            or not isinstance(data.get("excluded"), list) or not all(isinstance(k, str) for k in data["excluded"])):
        raise ValueError(f"invalid global trace compression setting: {path}")
    return AllSessions(data["state"], data["writer"], data["rollback_root"], data["rollback_digest"], tuple(data["excluded"]))


def all_sessions(root: Path) -> AllSessions | None:
    path = root / ALL_SESSIONS_FILE
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return _read_all_sessions(path, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))


def default_for_database(database: Path, workspace_key: str, *, root: Path | None = None) -> AllSessions | None:
    folder = database.parent
    if (database.name == "chat.sqlite" and folder.name == workspace_key and re.fullmatch(r"[0-9a-f]{64}", workspace_key)
            and folder.parent.name == "workspaces" and folder.parent.parent.name == "chat-history"
            and (root is None or folder.parent.parent == root)):
        return all_sessions(folder.parent.parent)
    return None


def verified(writer: str, rollback_root: str, rollback_digest: str) -> bool:
    try:
        rollback = Path(rollback_root)
        return (rollback.is_absolute() and rollback != PROGRAM_ROOT
                and writer == writer_identity() and program_digest(rollback) == rollback_digest)
    except (OSError, TypeError, ValueError, UpdateConflict):
        return False


def enabled(conn: sqlite3.Connection, workspace_key: str) -> bool:
    try:
        row = policy(conn)
        return row is not None and row[0] == workspace_key and verified(*row[1:])
    except sqlite3.Error:
        return False


def install_policy(conn: sqlite3.Connection, workspace_key: str, writer: str, rollback_root: str, rollback_digest: str) -> None:
    values = (workspace_key, writer, rollback_root, rollback_digest)
    current = policy(conn)
    if current is not None and tuple(current) == values:
        return
    for statement in _SCHEMA:
        conn.execute(statement)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_events'").fetchone():
        conn.execute("DELETE FROM trace_body_pilot_events")
    conn.execute("INSERT OR REPLACE INTO trace_body_pilot VALUES (1,?,?,?,?)", values)


def for_append(conn: sqlite3.Connection, workspace_key: str, database: Path) -> bool:
    # The caller holds the workspace writer lock before observing the deployment setting.
    try:
        default = default_for_database(database, workspace_key)
    except (OSError, ValueError):
        return False
    if default is None:
        return enabled(conn, workspace_key)
    if not default.covers(workspace_key) or not verified(default.writer, default.rollback_root, default.rollback_digest):
        return False
    install_policy(conn, workspace_key, default.writer, default.rollback_root, default.rollback_digest)
    return True


def enable(conn: sqlite3.Connection, workspace_key: str, rollback_root: Path, rollback_digest: str) -> None:
    install_policy(conn, workspace_key, writer_identity(), os.fspath(rollback_root), rollback_digest)


def disable(conn: sqlite3.Connection) -> None:
    if policy(conn) is not None:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_events'").fetchone():
            conn.execute("DELETE FROM trace_body_pilot_events")
        conn.execute("DELETE FROM trace_body_pilot")
