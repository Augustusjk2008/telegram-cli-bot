from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_agent_id(agent_id: str | None) -> str:
    return str(agent_id or "main").strip().lower() or "main"


def _parse_session_key(key: str) -> tuple[int, int, str]:
    parts = str(key or "").split(":")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1]), "main"
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), _normalize_agent_id(parts[2])
    raise ValueError(f"invalid session key: {key}")


class SessionStoreSQLite:
    def __init__(
        self,
        path: Path | str,
        *,
        legacy_json_path: Path | str | None = None,
        flush_interval_seconds: float = 0.1,
    ) -> None:
        self.path = Path(path)
        self.legacy_json_path = (
            Path(legacy_json_path)
            if legacy_json_path is not None
            else self.path.with_suffix(".json")
        )
        self.marker_path = self.path.with_suffix(f"{self.path.suffix}.migration.json")
        self.flush_interval_seconds = max(0.01, float(flush_interval_seconds))
        self._lock = threading.RLock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, tuple[int, int, str, dict[str, Any] | None]] = {}
        self._worker_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._closing = False
        self._initialized = False
        self._write_batch_count = 0
        self._queued_write_count = 0

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_key TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_identity
            ON sessions(bot_id, user_id, agent_id)
            """
        )
        return connection

    def ensure_ready(self) -> None:
        with self._lock:
            if self._initialized:
                return
            database_existed = self.path.exists()
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connect()
                if not database_existed and self.legacy_json_path.is_file():
                    self._migrate_legacy_json(connection)
                connection.commit()
                self._initialized = True
            except Exception:
                if connection is not None:
                    connection.close()
                    connection = None
                if not database_existed:
                    self.path.unlink(missing_ok=True)
                    self.path.with_name(f"{self.path.name}-wal").unlink(missing_ok=True)
                    self.path.with_name(f"{self.path.name}-shm").unlink(missing_ok=True)
                raise
            finally:
                if connection is not None:
                    connection.close()

    def _migrate_legacy_json(self, connection: sqlite3.Connection) -> None:
        raw = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("legacy session store must be a JSON object")
        rows: list[tuple[str, int, int, str, str, str]] = []
        now = _utc_now()
        for key, payload in raw.items():
            if not isinstance(payload, dict):
                raise ValueError(f"invalid session payload: {key}")
            bot_id, user_id, agent_id = _parse_session_key(key)
            rows.append(
                (
                    str(key),
                    bot_id,
                    user_id,
                    agent_id,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                )
            )
        with connection:
            connection.executemany(
                """
                INSERT INTO sessions(
                    session_key,
                    bot_id,
                    user_id,
                    agent_id,
                    payload_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            count_row = connection.execute(
                "SELECT COUNT(*) AS count FROM sessions"
            ).fetchone()
            imported_count = int(count_row["count"] or 0) if count_row is not None else 0
            if imported_count != len(rows):
                raise RuntimeError(
                    f"session migration count mismatch: expected={len(rows)} actual={imported_count}"
                )
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.legacy_json_path.with_name(
            f"{self.legacy_json_path.stem}.pre-sqlite-{timestamp}{self.legacy_json_path.suffix}"
        )
        shutil.copy2(self.legacy_json_path, backup_path)
        marker = {
            "migrated_at": _utc_now(),
            "legacy_json_path": str(self.legacy_json_path),
            "backup_path": str(backup_path),
            "sqlite_path": str(self.path),
            "record_count": len(rows),
        }
        self.marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_all(self) -> dict[str, dict[str, Any]]:
        self.ensure_ready()
        with self._lock:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT session_key, payload_json FROM sessions"
                ).fetchall()
            with self._pending_lock:
                pending = dict(self._pending)
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                result[str(row["session_key"])] = payload
        for key, (_bot_id, _user_id, _agent_id, payload) in pending.items():
            if payload is None:
                result.pop(key, None)
            else:
                result[key] = dict(payload)
        return result

    def get(self, key: str) -> dict[str, Any] | None:
        normalized = str(key or "").strip()
        self.ensure_ready()
        with self._lock:
            with self._pending_lock:
                pending = self._pending.get(normalized)
            if pending is not None:
                payload = pending[3]
                return dict(payload) if payload is not None else None
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT payload_json FROM sessions WHERE session_key = ?",
                    (normalized,),
                ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def queue_upsert(
        self,
        key: str,
        *,
        bot_id: int,
        user_id: int,
        agent_id: str,
        payload: dict[str, Any] | None,
    ) -> None:
        self.ensure_ready()
        normalized = str(key or "").strip()
        item = (
            int(bot_id),
            int(user_id),
            _normalize_agent_id(agent_id),
            dict(payload) if payload is not None else None,
        )
        with self._lock:
            with self._pending_lock:
                self._pending[normalized] = item
                self._queued_write_count += 1
                self._ensure_worker_locked()
        self._worker_event.set()

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._closing = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name=f"session-store-{self.path.stem}",
            daemon=True,
        )
        self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            self._worker_event.wait()
            self._worker_event.clear()
            if self._closing:
                return
            deadline = time.monotonic() + self.flush_interval_seconds
            while not self._closing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._worker_event.wait(timeout=remaining)
                self._worker_event.clear()
            if self._closing:
                return
            try:
                self.flush()
            except Exception:
                logger.exception("SQLite 会话存储后台 flush 失败: %s", self.path)

    def flush(self) -> int:
        self.ensure_ready()
        with self._lock:
            with self._pending_lock:
                if not self._pending:
                    return 0
                batch = self._pending
                self._pending = {}
            try:
                self._write_batch(batch)
            except Exception:
                with self._pending_lock:
                    for key, item in batch.items():
                        self._pending.setdefault(key, item)
                raise
        return len(batch)

    def _write_batch(
        self,
        batch: dict[str, tuple[int, int, str, dict[str, Any] | None]],
    ) -> None:
        now = _utc_now()
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    for key, (bot_id, user_id, agent_id, payload) in batch.items():
                        if payload is None:
                            connection.execute(
                                "DELETE FROM sessions WHERE session_key = ?",
                                (key,),
                            )
                            continue
                        connection.execute(
                            """
                            INSERT INTO sessions(
                                session_key,
                                bot_id,
                                user_id,
                                agent_id,
                                payload_json,
                                updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(session_key) DO UPDATE SET
                                bot_id = excluded.bot_id,
                                user_id = excluded.user_id,
                                agent_id = excluded.agent_id,
                                payload_json = excluded.payload_json,
                                updated_at = excluded.updated_at
                            """,
                            (
                                key,
                                bot_id,
                                user_id,
                                agent_id,
                                json.dumps(payload, ensure_ascii=False),
                                now,
                            ),
                        )
            self._write_batch_count += 1

    def replace_all(self, data: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self.flush()
            rows: dict[str, tuple[int, int, str, dict[str, Any] | None]] = {}
            for key, payload in data.items():
                bot_id, user_id, agent_id = _parse_session_key(key)
                rows[str(key)] = (bot_id, user_id, agent_id, dict(payload))
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("DELETE FROM sessions")
                    for key, item in rows.items():
                        bot_id, user_id, agent_id, payload = item
                        connection.execute(
                            """
                            INSERT INTO sessions(
                                session_key,
                                bot_id,
                                user_id,
                                agent_id,
                                payload_json,
                                updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                key,
                                bot_id,
                                user_id,
                                agent_id,
                                json.dumps(payload, ensure_ascii=False),
                                _utc_now(),
                            ),
                        )
            self._write_batch_count += 1

    def close(self) -> None:
        with self._pending_lock:
            self._closing = True
            worker = self._worker
        self._worker_event.set()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(1.0, self.flush_interval_seconds * 4))
        self.flush()

    def diagnostics(self) -> dict[str, int | str]:
        with self._pending_lock:
            pending_count = len(self._pending)
            queued_write_count = self._queued_write_count
        return {
            "path": str(self.path),
            "pending_count": pending_count,
            "queued_write_count": queued_write_count,
            "write_batch_count": self._write_batch_count,
        }
