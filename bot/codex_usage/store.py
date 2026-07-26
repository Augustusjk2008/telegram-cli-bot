from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import (
    CodexTokenUsage,
    DailyProviderUsage,
    DayLike,
    DayUsage,
    ProviderInfo,
    ProviderUsage,
    UsageQueryResult,
    UsageTotals,
    coerce_token_usage,
    day_from_number,
    day_number,
)


SCHEMA_VERSION = 1
_SETTING_ENABLED = "enabled"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS providers (
    provider_id INTEGER PRIMARY KEY,
    provider_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (
        kind IN ('openai_official', 'base_url', 'unknown')
    ),
    base_url TEXT
);

CREATE TABLE IF NOT EXISTS daily_usage (
    day INTEGER NOT NULL,
    provider_id INTEGER NOT NULL REFERENCES providers(provider_id),
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    cached_input_tokens INTEGER NOT NULL DEFAULT 0
        CHECK (cached_input_tokens >= 0 AND cached_input_tokens <= input_tokens),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    reasoning_output_tokens INTEGER NOT NULL DEFAULT 0
        CHECK (reasoning_output_tokens >= 0 AND reasoning_output_tokens <= output_tokens),
    PRIMARY KEY (day, provider_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_daily_usage_provider_day
ON daily_usage(provider_id, day);
"""


class CodexUsageStore:
    """Synchronous, process-local SQLite store for daily Codex provider usage."""

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
        if version not in {0, SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 Codex usage schema 版本: {version}")
        connection.executescript(_SCHEMA_SQL)
        if version == 0:
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _provider_from_row(row: sqlite3.Row) -> ProviderInfo:
        return ProviderInfo(
            key=str(row["provider_key"]),
            kind=str(row["kind"]),  # type: ignore[arg-type]
            base_url=row["base_url"],
            resolution="resolved",
        )

    @staticmethod
    def _totals_from_row(row: sqlite3.Row) -> UsageTotals:
        return UsageTotals(
            request_count=int(row["request_count"]),
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
        )

    @staticmethod
    def _empty_query() -> UsageQueryResult:
        return UsageQueryResult(
            totals=UsageTotals(),
            by_provider=(),
            by_day=(),
            daily_by_provider=(),
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

    def record(
        self,
        provider: ProviderInfo,
        usage: CodexTokenUsage | dict[str, object],
        *,
        terminal_at: datetime | date | None = None,
    ) -> None:
        if provider.kind not in {"openai_official", "base_url", "unknown"}:
            raise ValueError("provider kind 无效")
        if not provider.key:
            raise ValueError("provider key 不能为空")
        if provider.kind == "base_url" and not provider.base_url:
            raise ValueError("自定义 provider 必须包含 base_url")
        token_usage = coerce_token_usage(usage)
        terminal_day = day_number(terminal_at or datetime.now().astimezone())
        with self._lock:
            connection = self._get_connection(create=True)
            assert connection is not None
            with connection:
                connection.execute(
                    """
                    INSERT INTO providers(provider_key, kind, base_url)
                    VALUES (?, ?, ?)
                    ON CONFLICT(provider_key) DO NOTHING
                    """,
                    (provider.key, provider.kind, provider.base_url),
                )
                provider_row = connection.execute(
                    "SELECT provider_id FROM providers WHERE provider_key = ?",
                    (provider.key,),
                ).fetchone()
                if provider_row is None:  # pragma: no cover - SQLite consistency guard
                    raise RuntimeError("provider 插入后不存在")
                connection.execute(
                    """
                    INSERT INTO daily_usage(
                        day, provider_id, request_count, input_tokens,
                        cached_input_tokens, output_tokens, reasoning_output_tokens
                    ) VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(day, provider_id) DO UPDATE SET
                        request_count = daily_usage.request_count + excluded.request_count,
                        input_tokens = daily_usage.input_tokens + excluded.input_tokens,
                        cached_input_tokens = (
                            daily_usage.cached_input_tokens + excluded.cached_input_tokens
                        ),
                        output_tokens = daily_usage.output_tokens + excluded.output_tokens,
                        reasoning_output_tokens = (
                            daily_usage.reasoning_output_tokens
                            + excluded.reasoning_output_tokens
                        )
                    """,
                    (
                        terminal_day,
                        int(provider_row["provider_id"]),
                        token_usage.input_tokens,
                        token_usage.cached_input_tokens,
                        token_usage.output_tokens,
                        token_usage.reasoning_output_tokens,
                    ),
                )

    write_usage = record

    def query(
        self,
        start_day: DayLike,
        end_day: DayLike,
        *,
        provider_keys: Iterable[str] | None = None,
    ) -> UsageQueryResult:
        start = day_number(start_day)
        end = day_number(end_day)
        if start > end:
            raise ValueError("起始日期不能晚于结束日期")
        selected_keys = None
        if provider_keys is not None:
            selected_keys = tuple(dict.fromkeys(str(item) for item in provider_keys))
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return self._empty_query()
            where = ["daily_usage.day >= ?", "daily_usage.day <= ?"]
            parameters: list[object] = [start, end]
            if selected_keys is not None:
                if not selected_keys:
                    return self._empty_query()
                placeholders = ", ".join("?" for _ in selected_keys)
                where.append(f"providers.provider_key IN ({placeholders})")
                parameters.extend(selected_keys)
            rows = connection.execute(
                f"""
                SELECT
                    daily_usage.day,
                    daily_usage.request_count,
                    daily_usage.input_tokens,
                    daily_usage.cached_input_tokens,
                    daily_usage.output_tokens,
                    daily_usage.reasoning_output_tokens,
                    providers.provider_key,
                    providers.kind,
                    providers.base_url
                FROM daily_usage
                JOIN providers ON providers.provider_id = daily_usage.provider_id
                WHERE {' AND '.join(where)}
                ORDER BY daily_usage.day ASC, providers.provider_key ASC
                """,
                parameters,
            ).fetchall()
        if not rows:
            return self._empty_query()
        total = UsageTotals()
        provider_totals: dict[str, tuple[ProviderInfo, UsageTotals]] = {}
        day_totals: dict[date, UsageTotals] = {}
        daily_rows: list[DailyProviderUsage] = []
        for row in rows:
            provider = self._provider_from_row(row)
            totals = self._totals_from_row(row)
            current_provider = provider_totals.get(provider.key)
            provider_totals[provider.key] = (
                provider,
                totals if current_provider is None else current_provider[1].plus(totals),
            )
            current_day = day_from_number(int(row["day"]))
            day_totals[current_day] = day_totals.get(current_day, UsageTotals()).plus(totals)
            daily_rows.append(
                DailyProviderUsage(day=current_day, provider=provider, totals=totals)
            )
            total = total.plus(totals)
        kind_order = {"openai_official": 0, "base_url": 1, "unknown": 2}
        by_provider = tuple(
            ProviderUsage(provider=provider, totals=totals)
            for provider, totals in sorted(
                provider_totals.values(),
                key=lambda item: (kind_order.get(item[0].kind, 99), item[0].key),
            )
        )
        by_day = tuple(
            DayUsage(day=current_day, totals=totals)
            for current_day, totals in sorted(day_totals.items())
        )
        daily_by_provider = tuple(
            sorted(
                daily_rows,
                key=lambda item: (
                    item.day,
                    kind_order.get(item.provider.kind, 99),
                    item.provider.key,
                ),
            )
        )
        return UsageQueryResult(
            totals=total,
            by_provider=by_provider,
            by_day=by_day,
            daily_by_provider=daily_by_provider,
        )

    query_usage = query

    def list_providers(self) -> tuple[ProviderInfo, ...]:
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return ()
            rows = connection.execute(
                """
                SELECT provider_key, kind, base_url
                FROM providers
                ORDER BY CASE kind
                    WHEN 'openai_official' THEN 0
                    WHEN 'base_url' THEN 1
                    ELSE 2
                END, provider_key
                """
            ).fetchall()
            return tuple(self._provider_from_row(row) for row in rows)

    def available_range(self) -> tuple[date | None, date | None]:
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return None, None
            row = connection.execute("SELECT MIN(day), MAX(day) FROM daily_usage").fetchone()
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
