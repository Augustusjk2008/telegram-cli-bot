from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import (
    CodexRateLimitSample,
    CodexTokenUsage,
    DEFAULT_CODEX_MODEL,
    DailyProviderModelUsage,
    DailyProviderUsage,
    DailyUsagePagination,
    DayLike,
    DayUsage,
    ProviderInfo,
    ProviderModelUsage,
    ProviderUsage,
    UsageQueryResult,
    UsageTotals,
    coerce_token_usage,
    day_from_number,
    day_number,
    normalize_model_key,
)


SCHEMA_VERSION = 4
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

CREATE TABLE IF NOT EXISTS daily_model_usage (
    day INTEGER NOT NULL,
    provider_id INTEGER NOT NULL REFERENCES providers(provider_id),
    model_key TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    cached_input_tokens INTEGER NOT NULL DEFAULT 0
        CHECK (cached_input_tokens >= 0 AND cached_input_tokens <= input_tokens),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    reasoning_output_tokens INTEGER NOT NULL DEFAULT 0
        CHECK (reasoning_output_tokens >= 0 AND reasoning_output_tokens <= output_tokens),
    PRIMARY KEY (day, provider_id, model_key)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_daily_model_usage_provider_day
ON daily_model_usage(provider_id, day);

CREATE TABLE IF NOT EXISTS rate_limit_samples (
    sample_id INTEGER PRIMARY KEY,
    day INTEGER NOT NULL,
    model_key TEXT NOT NULL CHECK (trim(model_key) <> ''),
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
        if version not in {0, 1, 2, 3, SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 Codex usage schema 版本: {version}")
        connection.executescript(_SCHEMA_SQL)
        if version == 1:
            with connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO daily_model_usage(
                        day, provider_id, model_key, request_count, input_tokens,
                        cached_input_tokens, output_tokens, reasoning_output_tokens
                    )
                    SELECT
                        day, provider_id, ?, request_count, input_tokens,
                        cached_input_tokens, output_tokens, reasoning_output_tokens
                    FROM daily_usage
                    """,
                    (DEFAULT_CODEX_MODEL,),
                )
        if version == 3:
            with connection:
                connection.execute(
                    f"""
                    ALTER TABLE rate_limit_samples
                    ADD COLUMN model_key TEXT NOT NULL
                    DEFAULT '{DEFAULT_CODEX_MODEL}'
                    CHECK (trim(model_key) <> '')
                    """
                )
        if version != SCHEMA_VERSION:
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
    def _rate_limit_from_row(row: sqlite3.Row) -> CodexRateLimitSample:
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return CodexRateLimitSample(
            sampled_at=epoch + timedelta(milliseconds=int(row["sampled_at_ms"])),
            used_percent=float(row["used_percent"]),
            window_minutes=int(row["window_minutes"]),
            resets_at=epoch + timedelta(seconds=int(row["resets_at"])),
            plan_type=row["plan_type"],
            model=str(row["model_key"]),
        )

    @staticmethod
    def _empty_query(
        *,
        rate_limit_samples: tuple[CodexRateLimitSample, ...] = (),
        daily_pagination: DailyUsagePagination | None = None,
    ) -> UsageQueryResult:
        return UsageQueryResult(
            totals=UsageTotals(),
            by_provider=(),
            by_day=(),
            daily_by_provider=(),
            by_provider_model=(),
            daily_by_provider_model=(),
            rate_limit_samples=rate_limit_samples,
            daily_pagination=daily_pagination,
        )

    @staticmethod
    def _daily_pagination(
        *,
        page: int,
        page_size: int,
        total_items: int,
    ) -> DailyUsagePagination:
        total_pages = (total_items + page_size - 1) // page_size
        return DailyUsagePagination(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_previous=page > 1,
            has_next=page < total_pages,
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
        model_key: str = DEFAULT_CODEX_MODEL,
        terminal_at: datetime | date | None = None,
    ) -> None:
        if provider.kind not in {"openai_official", "base_url", "unknown"}:
            raise ValueError("provider kind 无效")
        if not provider.key:
            raise ValueError("provider key 不能为空")
        if provider.kind == "base_url" and not provider.base_url:
            raise ValueError("自定义 provider 必须包含 base_url")
        token_usage = coerce_token_usage(usage)
        normalized_model = normalize_model_key(model_key)
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
                connection.execute(
                    """
                    INSERT INTO daily_model_usage(
                        day, provider_id, model_key, request_count, input_tokens,
                        cached_input_tokens, output_tokens, reasoning_output_tokens
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(day, provider_id, model_key) DO UPDATE SET
                        request_count = daily_model_usage.request_count + excluded.request_count,
                        input_tokens = daily_model_usage.input_tokens + excluded.input_tokens,
                        cached_input_tokens = (
                            daily_model_usage.cached_input_tokens
                            + excluded.cached_input_tokens
                        ),
                        output_tokens = daily_model_usage.output_tokens + excluded.output_tokens,
                        reasoning_output_tokens = (
                            daily_model_usage.reasoning_output_tokens
                            + excluded.reasoning_output_tokens
                        )
                    """,
                    (
                        terminal_day,
                        int(provider_row["provider_id"]),
                        normalized_model,
                        token_usage.input_tokens,
                        token_usage.cached_input_tokens,
                        token_usage.output_tokens,
                        token_usage.reasoning_output_tokens,
                    ),
                )

    write_usage = record

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
                        day, model_key, sampled_at_ms, used_percent,
                        window_minutes, resets_at, plan_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sample_day,
                        sample.model,
                        sampled_at_ms,
                        sample.used_percent,
                        sample.window_minutes,
                        resets_at,
                        sample.plan_type,
                    ),
                )

    def query(
        self,
        start_day: DayLike,
        end_day: DayLike,
        *,
        provider_keys: Iterable[str] | None = None,
        daily_page: int | None = None,
        daily_page_size: int | None = None,
    ) -> UsageQueryResult:
        start = day_number(start_day)
        end = day_number(end_day)
        if start > end:
            raise ValueError("起始日期不能晚于结束日期")
        pagination_requested = daily_page is not None or daily_page_size is not None
        empty_pagination: DailyUsagePagination | None = None
        if pagination_requested:
            if daily_page is None or daily_page_size is None:
                raise ValueError("daily_page 和 daily_page_size 必须同时提供")
            if (
                isinstance(daily_page, bool)
                or not isinstance(daily_page, int)
                or daily_page <= 0
            ):
                raise ValueError("daily_page 必须是正整数")
            if (
                isinstance(daily_page_size, bool)
                or not isinstance(daily_page_size, int)
                or daily_page_size <= 0
            ):
                raise ValueError("daily_page_size 必须是正整数")
            if daily_page_size > 100:
                raise ValueError("daily_page_size 不能超过 100")
            empty_pagination = self._daily_pagination(
                page=daily_page,
                page_size=daily_page_size,
                total_items=0,
            )
        selected_keys = None
        if provider_keys is not None:
            selected_keys = tuple(dict.fromkeys(str(item) for item in provider_keys))
            if not selected_keys:
                return self._empty_query(daily_pagination=empty_pagination)
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return self._empty_query(daily_pagination=empty_pagination)
            rate_limit_samples: tuple[CodexRateLimitSample, ...] = ()
            if selected_keys is None or "openai_official" in selected_keys:
                rate_limit_rows = connection.execute(
                    """
                    SELECT model_key, sampled_at_ms, used_percent, window_minutes, resets_at, plan_type
                    FROM rate_limit_samples
                    WHERE day >= ? AND day <= ?
                    ORDER BY sampled_at_ms ASC, sample_id ASC
                    """,
                    (start, end),
                ).fetchall()
                rate_limit_samples = tuple(
                    self._rate_limit_from_row(row) for row in rate_limit_rows
                )
            where = ["daily_usage.day >= ?", "daily_usage.day <= ?"]
            model_where = [
                "daily_model_usage.day >= ?",
                "daily_model_usage.day <= ?",
            ]
            parameters: list[object] = [start, end]
            if selected_keys is not None:
                placeholders = ", ".join("?" for _ in selected_keys)
                where.append(f"providers.provider_key IN ({placeholders})")
                model_where.append(f"providers.provider_key IN ({placeholders})")
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
                return self._empty_query(
                    rate_limit_samples=rate_limit_samples,
                    daily_pagination=empty_pagination,
                )
            model_total_rows = connection.execute(
                f"""
                SELECT
                    daily_model_usage.model_key,
                    SUM(daily_model_usage.request_count) AS request_count,
                    SUM(daily_model_usage.input_tokens) AS input_tokens,
                    SUM(daily_model_usage.cached_input_tokens) AS cached_input_tokens,
                    SUM(daily_model_usage.output_tokens) AS output_tokens,
                    SUM(daily_model_usage.reasoning_output_tokens) AS reasoning_output_tokens,
                    providers.provider_key,
                    providers.kind,
                    providers.base_url
                FROM daily_model_usage
                JOIN providers ON providers.provider_id = daily_model_usage.provider_id
                WHERE {' AND '.join(model_where)}
                GROUP BY
                    daily_model_usage.provider_id,
                    daily_model_usage.model_key,
                    providers.provider_key,
                    providers.kind,
                    providers.base_url
                ORDER BY
                    CASE providers.kind
                        WHEN 'openai_official' THEN 0
                        WHEN 'base_url' THEN 1
                        WHEN 'unknown' THEN 2
                        ELSE 99
                    END ASC,
                    providers.provider_key ASC,
                    daily_model_usage.model_key ASC
                """,
                parameters,
            ).fetchall()
            daily_pagination: DailyUsagePagination | None = None
            if pagination_requested:
                assert daily_page is not None
                assert daily_page_size is not None
                count_row = connection.execute(
                    f"""
                    SELECT COUNT(*) AS total_items
                    FROM daily_model_usage
                    JOIN providers ON providers.provider_id = daily_model_usage.provider_id
                    WHERE {' AND '.join(model_where)}
                    """,
                    parameters,
                ).fetchone()
                total_items = int(count_row["total_items"])
                daily_pagination = self._daily_pagination(
                    page=daily_page,
                    page_size=daily_page_size,
                    total_items=total_items,
                )
                if daily_page > daily_pagination.total_pages:
                    model_rows: list[sqlite3.Row] = []
                else:
                    offset = (daily_page - 1) * daily_page_size
                    model_rows = connection.execute(
                        f"""
                        SELECT
                            daily_model_usage.day,
                            daily_model_usage.model_key,
                            daily_model_usage.request_count,
                            daily_model_usage.input_tokens,
                            daily_model_usage.cached_input_tokens,
                            daily_model_usage.output_tokens,
                            daily_model_usage.reasoning_output_tokens,
                            providers.provider_key,
                            providers.kind,
                            providers.base_url
                        FROM daily_model_usage
                        JOIN providers ON providers.provider_id = daily_model_usage.provider_id
                        WHERE {' AND '.join(model_where)}
                        ORDER BY
                            daily_model_usage.day DESC,
                            CASE providers.kind
                                WHEN 'openai_official' THEN 0
                                WHEN 'base_url' THEN 1
                                WHEN 'unknown' THEN 2
                                ELSE 99
                            END ASC,
                            providers.provider_key ASC,
                            daily_model_usage.model_key ASC
                        LIMIT ? OFFSET ?
                        """,
                        [*parameters, daily_page_size, offset],
                    ).fetchall()
            else:
                model_rows = connection.execute(
                    f"""
                    SELECT
                        daily_model_usage.day,
                        daily_model_usage.model_key,
                        daily_model_usage.request_count,
                        daily_model_usage.input_tokens,
                        daily_model_usage.cached_input_tokens,
                        daily_model_usage.output_tokens,
                        daily_model_usage.reasoning_output_tokens,
                        providers.provider_key,
                        providers.kind,
                        providers.base_url
                    FROM daily_model_usage
                    JOIN providers ON providers.provider_id = daily_model_usage.provider_id
                    WHERE {' AND '.join(model_where)}
                    ORDER BY
                        daily_model_usage.day ASC,
                        providers.provider_key ASC,
                        daily_model_usage.model_key ASC
                    """,
                    parameters,
                ).fetchall()
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
            if not pagination_requested:
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
        daily_by_provider = () if pagination_requested else tuple(
            sorted(
                daily_rows,
                key=lambda item: (
                    item.day,
                    kind_order.get(item.provider.kind, 99),
                    item.provider.key,
                ),
            )
        )
        provider_model_totals: dict[
            tuple[str, str], tuple[ProviderInfo, str, UsageTotals]
        ] = {}
        daily_model_rows: list[DailyProviderModelUsage] = []
        for row in model_total_rows:
            provider = self._provider_from_row(row)
            model = normalize_model_key(row["model_key"])
            totals = self._totals_from_row(row)
            key = (provider.key, model)
            current = provider_model_totals.get(key)
            provider_model_totals[key] = (
                provider,
                model,
                totals if current is None else current[2].plus(totals),
            )
        for row in model_rows:
            provider = self._provider_from_row(row)
            model = normalize_model_key(row["model_key"])
            totals = self._totals_from_row(row)
            daily_model_rows.append(
                DailyProviderModelUsage(
                    day=day_from_number(int(row["day"])),
                    provider=provider,
                    model=model,
                    totals=totals,
                )
            )
        by_provider_model = tuple(
            ProviderModelUsage(provider=provider, model=model, totals=totals)
            for provider, model, totals in sorted(
                provider_model_totals.values(),
                key=lambda item: (
                    kind_order.get(item[0].kind, 99),
                    item[0].key,
                    item[1],
                ),
            )
        )
        if pagination_requested:
            daily_by_provider_model = tuple(daily_model_rows)
        else:
            daily_by_provider_model = tuple(
                sorted(
                    daily_model_rows,
                    key=lambda item: (
                        item.day,
                        kind_order.get(item.provider.kind, 99),
                        item.provider.key,
                        item.model,
                    ),
                )
            )
        return UsageQueryResult(
            totals=total,
            by_provider=by_provider,
            by_day=by_day,
            daily_by_provider=daily_by_provider,
            by_provider_model=by_provider_model,
            daily_by_provider_model=daily_by_provider_model,
            rate_limit_samples=rate_limit_samples,
            daily_pagination=daily_pagination,
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
            providers = [self._provider_from_row(row) for row in rows]
            has_rate_limits = connection.execute(
                "SELECT 1 FROM rate_limit_samples LIMIT 1"
            ).fetchone() is not None
            if has_rate_limits and not any(
                provider.key == "openai_official" for provider in providers
            ):
                providers.insert(
                    0,
                    ProviderInfo(
                        key="openai_official",
                        kind="openai_official",
                        base_url=None,
                        resolution="resolved",
                    ),
                )
            return tuple(providers)

    def available_range(self) -> tuple[date | None, date | None]:
        with self._lock:
            connection = self._get_connection(create=False)
            if connection is None:
                return None, None
            row = connection.execute(
                """
                SELECT MIN(day), MAX(day)
                FROM (
                    SELECT day FROM daily_usage
                    UNION ALL
                    SELECT day FROM rate_limit_samples
                )
                """
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
