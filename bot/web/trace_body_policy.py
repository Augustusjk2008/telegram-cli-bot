"""Workspace opt-in for v1 trace bodies, bound to a verified local rollback reader."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from bot.update_state import UpdateConflict, UpdateStore, installation_id


PROGRAM_ROOT = Path(__file__).resolve().parents[2]
READER_FILES = ("bot/web/trace_previews.py", "bot/web/chat_store.py", "bot/web/trace_compaction.py")
_POLICY = "trace_body_pilot"
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


def enabled(conn: sqlite3.Connection, workspace_key: str) -> bool:
    try:
        row = policy(conn)
        if row is None or row[0] != workspace_key or not isinstance(row[2], str):
            return False
        rollback = Path(row[2])
        return (rollback.is_absolute() and rollback != PROGRAM_ROOT
                and row[1] == writer_identity() and program_digest(rollback) == row[3])
    except (OSError, ValueError, sqlite3.Error, UpdateConflict):
        # Loss of the optional policy or its reader proof still permits the ordinary plaintext write.
        return False


def enable(conn: sqlite3.Connection, workspace_key: str, rollback_root: Path, rollback_digest: str) -> None:
    values = (workspace_key, writer_identity(), os.fspath(rollback_root), rollback_digest)
    for statement in _SCHEMA:
        conn.execute(statement)
    current = policy(conn)
    if current is not None and tuple(current) == values:
        return
    conn.execute("DELETE FROM trace_body_pilot_events")
    conn.execute("INSERT OR REPLACE INTO trace_body_pilot VALUES (1,?,?,?,?)", values)


def disable(conn: sqlite3.Connection) -> None:
    if policy(conn) is not None:
        conn.execute("DELETE FROM trace_body_pilot")
        conn.execute("DELETE FROM trace_body_pilot_events")
