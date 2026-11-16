"""SQLite persistence for scheduled agent tasks and their run history."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from bot.scheduler.triggers import to_utc_iso, utc_now

RUN_ACTIVE_STATUSES = frozenset({"pending", "waiting", "running"})
RUN_STATUSES = frozenset({
    *RUN_ACTIVE_STATUSES,
    "completed",
    "failed",
    "cancelled",
    "skipped",
    "missed",
    "interrupted",
})
RUN_HISTORY_LIMIT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL DEFAULT 1,
    bot_alias TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'main',
    prompt TEXT NOT NULL,
    trigger_json TEXT NOT NULL,
    timezone TEXT NOT NULL,
    busy_policy TEXT NOT NULL DEFAULT 'wait',
    max_wait_minutes INTEGER NOT NULL DEFAULT 15,
    misfire_grace_minutes INTEGER NOT NULL DEFAULT 10,
    allow_unsafe_cli INTEGER NOT NULL DEFAULT 0,
    unsafe_authorized_by TEXT NOT NULL DEFAULT '',
    next_run_at TEXT,
    disabled_reason TEXT NOT NULL DEFAULT '',
    created_by_account_id TEXT NOT NULL DEFAULT '',
    created_by_username TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_runs (
    id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL,
    planned_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    reason_message TEXT NOT NULL DEFAULT '',
    bot_alias TEXT NOT NULL DEFAULT '',
    conversation_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    assistant_message_id TEXT NOT NULL DEFAULT '',
    preview TEXT NOT NULL DEFAULT '',
    unsafe_downgraded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    UNIQUE (schedule_id, planned_at)
);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule_created
    ON schedule_runs (schedule_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_status ON schedule_runs (status);
"""

_SCHEDULE_COLUMNS = (
    "id", "name", "enabled", "revision", "bot_alias", "agent_id", "prompt", "trigger_json",
    "timezone", "busy_policy", "max_wait_minutes", "misfire_grace_minutes", "allow_unsafe_cli",
    "unsafe_authorized_by", "next_run_at", "disabled_reason", "created_by_account_id",
    "created_by_username", "created_at", "updated_at",
)
_MUTABLE_SCHEDULE_FIELDS = frozenset({
    "name", "enabled", "bot_alias", "prompt", "trigger", "timezone", "busy_policy",
    "max_wait_minutes", "misfire_grace_minutes", "allow_unsafe_cli", "unsafe_authorized_by",
    "next_run_at", "disabled_reason",
})
_MUTABLE_RUN_FIELDS = frozenset({
    "status", "reason_code", "reason_message", "bot_alias", "conversation_id", "turn_id",
    "assistant_message_id", "preview", "unsafe_downgraded", "started_at", "finished_at",
})


class ScheduleStoreError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now_iso() -> str:
    return to_utc_iso(utc_now())


def _now_iso_precise() -> str:
    # Run rows order by creation time, so keep sub-second precision.
    return utc_now().isoformat(timespec="microseconds")


def _schedule_from_row(row: sqlite3.Row) -> dict[str, Any]:
    data = {key: row[key] for key in _SCHEDULE_COLUMNS}
    try:
        trigger = json.loads(data.pop("trigger_json") or "{}")
    except json.JSONDecodeError:
        trigger = {}
    data["trigger"] = trigger if isinstance(trigger, dict) else {}
    data["enabled"] = bool(data["enabled"])
    data["allow_unsafe_cli"] = bool(data["allow_unsafe_cli"])
    data["revision"] = int(data["revision"])
    data["max_wait_minutes"] = int(data["max_wait_minutes"])
    data["misfire_grace_minutes"] = int(data["misfire_grace_minutes"])
    return data


def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    data = {key: row[key] for key in row.keys()}
    data["unsafe_downgraded"] = bool(data.get("unsafe_downgraded"))
    return data


class ScheduleStore:
    """Thread-safe store; every call opens a short-lived connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialized = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._initialized:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            try:
                if not self._initialized:
                    connection.executescript(_SCHEMA)
                    self._initialized = True
                with connection:
                    yield connection
            finally:
                connection.close()

    # Schedules -----------------------------------------------------------

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM schedules ORDER BY created_at, id").fetchall()
        return [_schedule_from_row(row) for row in rows]

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return _schedule_from_row(row) if row is not None else None

    def require_schedule(self, schedule_id: str) -> dict[str, Any]:
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            raise ScheduleStoreError(404, "schedule_not_found", "定时任务不存在")
        return schedule

    def create_schedule(self, record: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        schedule_id = f"sch_{uuid.uuid4().hex[:16]}"
        values = {
            "id": schedule_id,
            "name": record["name"],
            "enabled": 1 if record.get("enabled", True) else 0,
            "revision": 1,
            "bot_alias": record["bot_alias"],
            "agent_id": record.get("agent_id") or "main",
            "prompt": record["prompt"],
            "trigger_json": json.dumps(record["trigger"], ensure_ascii=False, sort_keys=True),
            "timezone": record["timezone"],
            "busy_policy": record.get("busy_policy") or "wait",
            "max_wait_minutes": int(record.get("max_wait_minutes", 15)),
            "misfire_grace_minutes": int(record.get("misfire_grace_minutes", 10)),
            "allow_unsafe_cli": 1 if record.get("allow_unsafe_cli") else 0,
            "unsafe_authorized_by": str(record.get("unsafe_authorized_by") or ""),
            "next_run_at": record.get("next_run_at"),
            "disabled_reason": str(record.get("disabled_reason") or ""),
            "created_by_account_id": str(record.get("created_by_account_id") or ""),
            "created_by_username": str(record.get("created_by_username") or ""),
            "created_at": now,
            "updated_at": now,
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self._connect() as connection:
            connection.execute(f"INSERT INTO schedules ({columns}) VALUES ({placeholders})", tuple(values.values()))
        return self.require_schedule(schedule_id)

    def update_schedule(
        self,
        schedule_id: str,
        changes: dict[str, Any],
        *,
        expected_revision: int | None = None,
        bump_revision: bool = True,
        expected_next_run_at: Any = ...,
    ) -> dict[str, Any] | None:
        """Apply ``changes``; returns ``None`` when ``expected_next_run_at`` no longer matches."""
        unknown = set(changes) - _MUTABLE_SCHEDULE_FIELDS
        if unknown:
            raise ValueError(f"unsupported schedule fields: {sorted(unknown)}")
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if key == "trigger":
                assignments.append("trigger_json = ?")
                params.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
            elif key in {"enabled", "allow_unsafe_cli"}:
                assignments.append(f"{key} = ?")
                params.append(1 if value else 0)
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        assignments.append("updated_at = ?")
        params.append(_now_iso())
        if bump_revision:
            assignments.append("revision = revision + 1")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, next_run_at FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
            if row is None:
                raise ScheduleStoreError(404, "schedule_not_found", "定时任务不存在")
            if expected_revision is not None and int(row["revision"]) != int(expected_revision):
                raise ScheduleStoreError(409, "schedule_conflict", "定时任务已在其他地方修改，请刷新后重试")
            if expected_next_run_at is not ... and row["next_run_at"] != expected_next_run_at:
                return None
            connection.execute(
                f"UPDATE schedules SET {', '.join(assignments)} WHERE id = ?",
                (*params, schedule_id),
            )
        return self.require_schedule(schedule_id)

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._connect() as connection:
            deleted = connection.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,)).rowcount
            connection.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,))
        return bool(deleted)

    def due_schedules(self, now_iso: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?"
                " ORDER BY next_run_at, id",
                (now_iso,),
            ).fetchall()
        return [_schedule_from_row(row) for row in rows]

    def earliest_next_run_at(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(next_run_at) AS value FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL"
            ).fetchone()
        return row["value"] if row is not None else None

    def rename_alias(self, old_alias: str, new_alias: str) -> int:
        with self._connect() as connection:
            return connection.execute(
                "UPDATE schedules SET bot_alias = ?, updated_at = ?, revision = revision + 1 WHERE bot_alias = ?",
                (new_alias, _now_iso(), old_alias),
            ).rowcount

    def disable_for_alias(self, alias: str, reason: str) -> int:
        with self._connect() as connection:
            return connection.execute(
                "UPDATE schedules SET enabled = 0, disabled_reason = ?, next_run_at = NULL, updated_at = ?,"
                " revision = revision + 1 WHERE bot_alias = ?",
                (reason, _now_iso(), alias),
            ).rowcount

    # Runs ----------------------------------------------------------------

    def claim_run(
        self,
        schedule_id: str,
        *,
        planned_at: str,
        trigger: str,
        bot_alias: str,
        status: str = "pending",
        reason_code: str = "",
        reason_message: str = "",
    ) -> dict[str, Any] | None:
        """Insert a run for ``(schedule_id, planned_at)``; ``None`` if it was already claimed."""
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status: {status}")
        now = _now_iso_precise()
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        finished_at = "" if status in RUN_ACTIVE_STATUSES else now
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO schedule_runs (id, schedule_id, planned_at, trigger, status, reason_code,"
                    " reason_message, bot_alias, created_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, schedule_id, planned_at, trigger, status, reason_code, reason_message,
                     bot_alias, now, finished_at),
                )
            except sqlite3.IntegrityError:
                return None
            self._prune_runs_locked(connection, schedule_id)
        return self.get_run(run_id)

    def _prune_runs_locked(self, connection: sqlite3.Connection, schedule_id: str) -> None:
        placeholders = ", ".join("?" for _ in RUN_ACTIVE_STATUSES)
        connection.execute(
            f"DELETE FROM schedule_runs WHERE schedule_id = ? AND status NOT IN ({placeholders}) AND id NOT IN ("
            " SELECT id FROM schedule_runs WHERE schedule_id = ? ORDER BY created_at DESC, id DESC LIMIT ?)",
            (schedule_id, *sorted(RUN_ACTIVE_STATUSES), schedule_id, RUN_HISTORY_LIMIT),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM schedule_runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row is not None else None

    def update_run(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        unknown = set(changes) - _MUTABLE_RUN_FIELDS
        if unknown:
            raise ValueError(f"unsupported run fields: {sorted(unknown)}")
        if "status" in changes and changes["status"] not in RUN_STATUSES:
            raise ValueError(f"unknown run status: {changes['status']}")
        if not changes:
            return self.get_run(run_id)
        assignments = ", ".join(f"{key} = ?" for key in changes)
        params = [
            (1 if value else 0) if key == "unsafe_downgraded" else value
            for key, value in changes.items()
        ]
        with self._connect() as connection:
            connection.execute(f"UPDATE schedule_runs SET {assignments} WHERE id = ?", (*params, run_id))
        return self.get_run(run_id)

    def list_runs(self, schedule_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (schedule_id, max(1, min(int(limit), RUN_HISTORY_LIMIT))),
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def latest_runs(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT r.* FROM schedule_runs r JOIN ("
                " SELECT schedule_id, MAX(created_at || ' ' || id) AS marker FROM schedule_runs GROUP BY schedule_id"
                ") latest ON latest.schedule_id = r.schedule_id AND latest.marker = r.created_at || ' ' || r.id"
            ).fetchall()
        return {row["schedule_id"]: _run_from_row(row) for row in rows}

    def mark_unfinished_runs(self, status: str, reason_code: str, reason_message: str) -> int:
        placeholders = ", ".join("?" for _ in RUN_ACTIVE_STATUSES)
        with self._connect() as connection:
            return connection.execute(
                f"UPDATE schedule_runs SET status = ?, reason_code = ?, reason_message = ?, finished_at = ?"
                f" WHERE status IN ({placeholders})",
                (status, reason_code, reason_message, _now_iso(), *sorted(RUN_ACTIVE_STATUSES)),
            ).rowcount


__all__ = [
    "RUN_ACTIVE_STATUSES",
    "RUN_HISTORY_LIMIT",
    "RUN_STATUSES",
    "ScheduleStore",
    "ScheduleStoreError",
]
