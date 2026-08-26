from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import (
    CodexRateLimitSample,
    DayLike,
    day_from_number,
    day_number,
)


SCHEMA_VERSION = 6
_SETTING_ENABLED = "enabled"
_WEEKLY_LIMIT_WINDOW_MINUTES = 7 * 24 * 60

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS rate_limit_samples (
    sample_id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    limit_id TEXT NOT NULL CHECK (trim(limit_id) <> ''),
    sampled_at_ms INTEGER NOT NULL,
    used_percent REAL NOT NULL
        CHECK (used_percent >= 0 AND used_percent <= 100),
    window_minutes INTEGER NOT NULL
        CHECK (window_minutes > 0),
    resets_at INTEGER NOT NULL
        CHECK (resets_at >= 0),
    plan_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_samples_day_time
ON rate_limit_samples(day, sampled_at_ms, sample_id);
"""


class CodexUsageStore:
    """Synchronous, process-local SQLite store for Codex quota samples."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    def _get_connection(self, *, create: bool) -> sqlite3.Connection | None:
        if self._connection is not None:
            return self._connection
        if not create and not self.db_path.exists():
            return None
        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA wal_autocheckpoint=100")
            connection.execute("PRAGMA journal_size_limit=1048576")
            connection.execute("PRAGMA foreign_keys=ON")
            self._ensure_schema(connection)
        except BaseException:
            try:
                connection.close()
            except Exception:
                pass
            raise
        self._connection = connection
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, 1, 2, 3, 4, 5, SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 Codex quota schema 版本: {version}")
        connection.executescript(_SCHEMA_SQL)
        if version == 3:
            with connection:
                connection.execute(
                    """
                    ALTER TABLE rate_limit_samples
                    ADD COLUMN limit_id TEXT NOT NULL
                    DEFAULT 'codex'
                    CHECK (trim(limit_id) <> '')
                    """
                )
        if version == 4:
            with connection:
                connection.execute(
                    "ALTER TABLE rate_limit_samples RENAME COLUMN model_key TO limit_id"
                )
                connection.execute(
                    """
                    UPDATE rate_limit_samples
                    SET limit_id = CASE
                        WHEN lower(trim(limit_id)) = 'gpt-5.3-codex-spark'
                            THEN 'codex_bengalfox'
                        ELSE 'codex'
                    END
                    """
                )
        if version != SCHEMA_VERSION:
            with connection:
                connection.execute("DROP TABLE IF EXISTS daily_model_usage")
                connection.execute("DROP TABLE IF EXISTS daily_usage")
                connection.execute("DROP TABLE IF EXISTS providers")
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            if version != 0:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")

    @staticmethod
    def _rate_limit_from_row(row: sqlite3.Row) -> CodexRateLimitSample:
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return CodexRateLimitSample(
            sampled_at=epoch + timedelta(milliseconds=int(row["sampled_at_ms"])),
            used_percent=float(row["used_percent"]),
            window_minutes=int(row["window_minutes"]),
            resets_at=epoch + timedelta(seconds=int(row["resets_at"])),
            plan_type=row["plan_type"],
            limit_id=str(row["limit_id"]),
        )

    def get_enabled(self) -> bool:
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return False
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                (_SETTING_ENABLED,),
            ).fetchone()
            if row is None:
                return False
            return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}

    is_enabled = get_enabled

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是布尔值")
        with self._lock:
            connection = self._get_connection(create=True)
            assert connection is not None
            updated_at = datetime.now(timezone.utc).isoformat()
            with connection:
                connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (_SETTING_ENABLED, "true" if enabled else "false", updated_at),
                )

    def record_rate_limit_sample(self, sample: CodexRateLimitSample) -> None:
        if not isinstance(sample, CodexRateLimitSample):
            raise ValueError("sample 必须是 CodexRateLimitSample")
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        sampled_delta = sample.sampled_at.astimezone(timezone.utc) - epoch
        reset_delta = sample.resets_at.astimezone(timezone.utc) - epoch
        sampled_at_ms = (
            sampled_delta.days * 86_400_000
            + sampled_delta.seconds * 1_000
            + sampled_delta.microseconds // 1_000
        )
        resets_at = reset_delta.days * 86_400 + reset_delta.seconds
        sample_day = day_number(sample.sampled_at)
        with self._lock:
            connection = self._get_connection(create=True)
            assert connection is not None
            with connection:
                connection.execute(
                    """
                    INSERT INTO rate_limit_samples(
                        day, limit_id, sampled_at_ms, used_percent,
                        window_minutes, resets_at, plan_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sample_day,
                        sample.limit_id,
                        sampled_at_ms,
                        sample.used_percent,
                        sample.window_minutes,
                        resets_at,
                        sample.plan_type,
                    ),
                )

    def query(self, start_day: DayLike, end_day: DayLike) -> tuple[CodexRateLimitSample, ...]:
        start = day_number(start_day)
        end = day_number(end_day)
        if start > end:
            raise ValueError("起始日期不能晚于结束日期")
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return ()
            rows = connection.execute(
                """
                SELECT limit_id, sampled_at_ms, used_percent, window_minutes,
                       resets_at, plan_type
                FROM rate_limit_samples
                WHERE day >= ? AND day <= ?
                  AND window_minutes = ?
                ORDER BY sampled_at_ms ASC, sample_id ASC
                """,
                (
                    start,
                    end,
                    _WEEKLY_LIMIT_WINDOW_MINUTES,
                ),
            ).fetchall()
            return tuple(self._rate_limit_from_row(row) for row in rows)

    def available_range(self) -> tuple[date | None, date | None]:
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return None, None
            row = connection.execute(
                "SELECT MIN(day), MAX(day) FROM rate_limit_samples"
            ).fetchone()
            if row is None or row[0] is None:
                return None, None
            return day_from_number(int(row[0])), day_from_number(int(row[1]))

    def diagnostics(self) -> dict[str, int | bool | str]:
        with self._lock:
            database_size = self._file_size(self.db_path)
            wal_size = self._file_size(Path(f"{self.db_path}-wal"))
            return {
                "database_size_bytes": database_size,
                "wal_size_bytes": wal_size,
                "connection_open": self._connection is not None,
                "schema_version": SCHEMA_VERSION,
            }

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            if connection is None:
                return
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                connection.close()
                self._connection = None


UsageStore = CodexUsageStore
