from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
COST_PROVIDERS: tuple[str, ...] = ("claude", "codex")
_MAX_EVENT_ID = (1 << 63) - 1

_ENABLED_KEY_PREFIX = "enabled:"
_PROVIDER_PLACEHOLDERS = ", ".join("?" for _ in COST_PROVIDERS)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS cost_events (
    event_id INTEGER PRIMARY KEY,
    invocation_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    cli_type TEXT NOT NULL,
    day INTEGER NOT NULL,
    hour INTEGER NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    bot_alias TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user TEXT NOT NULL,
    model TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    raw_total REAL NOT NULL,
    baseline REAL,
    is_partial INTEGER NOT NULL,
    source TEXT,
    conversation_id TEXT,
    turn_id TEXT,
    native_session_id TEXT,
    -- 1 when raw_total is a running session total that later turns may subtract
    cumulative INTEGER NOT NULL DEFAULT 0,
    -- cumulative record whose raw_total is the baseline; NULL for a caller-supplied baseline
    baseline_event_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cost_events_provider_day
ON cost_events(provider, day);

CREATE INDEX IF NOT EXISTS idx_cost_events_session
ON cost_events(provider, native_session_id, recorded_at_ms);
"""


@dataclass(frozen=True, slots=True)
class CostCube:
    """Raw aggregates of one query, read under a single store lock."""

    # (day, hour | None, provider, bot_alias, agent_id, user, model, currency, amount, turns, partial_turns)
    groups: tuple[tuple[Any, ...], ...]
    # (provider, currency, amount, turns)
    previous_totals: tuple[tuple[str, str, float, int], ...]
    available_range: tuple[date | None, date | None]


def day_number(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def day_from_number(value: int) -> date:
    return date(value // 10000, value // 100 % 100, value % 100)


def normalize_cost_provider(provider: object) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in COST_PROVIDERS:
        raise ValueError(f"不支持的费用统计 provider: {provider}")
    return normalized


def _amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _text(value: object) -> str:
    return str(value or "").strip()


def _optional_text(value: object) -> str | None:
    return _text(value) or None


class CostStatsStore:
    """Synchronous, process-local SQLite store for per-turn CLI cost."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    @staticmethod
    def _is_recoverable_io_error(exc: BaseException) -> bool:
        return isinstance(exc, sqlite3.OperationalError) and "disk i/o error" in str(exc).casefold()

    def _discard_connection(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            pass

    def _read_with_recovery(self, operation):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not self._is_recoverable_io_error(exc):
                raise
            self._discard_connection()
            return operation()

    def _get_connection(self, *, create: bool) -> sqlite3.Connection | None:
        if self._connection is not None:
            return self._connection
        if not create and not self.db_path.exists():
            return None
        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA wal_autocheckpoint=100")
            connection.execute("PRAGMA journal_size_limit=1048576")
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
            raise RuntimeError(f"不支持的费用统计 schema 版本: {version}")
        connection.executescript(_SCHEMA_SQL)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(cost_events)")}
        if "baseline_event_id" not in columns:
            # Nullable column added in place, so the version stays readable by the same build.
            with connection:
                connection.execute("ALTER TABLE cost_events ADD COLUMN baseline_event_id INTEGER")
        if version != SCHEMA_VERSION:
            with connection:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # -- settings ---------------------------------------------------------

    def get_enabled_flags(self) -> dict[str, bool]:
        """Return the enable flag of every provider; all ``False`` without a database."""

        flags = {provider: False for provider in COST_PROVIDERS}
        with self._lock:
            def read() -> dict[str, bool]:
                connection = self._get_connection(create=False)
                if connection is None:
                    return flags
                rows = connection.execute(
                    "SELECT key, value FROM settings WHERE key >= ? AND key < ?",
                    (_ENABLED_KEY_PREFIX, _ENABLED_KEY_PREFIX + "￿"),
                ).fetchall()
                for key, value in rows:
                    provider = str(key)[len(_ENABLED_KEY_PREFIX):]
                    if provider in flags:
                        flags[provider] = str(value).strip().lower() in {"1", "true", "yes", "on"}
                return flags

            return self._read_with_recovery(read)

    def set_enabled(self, provider: str, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是布尔值")
        normalized_provider = normalize_cost_provider(provider)
        with self._lock:
            # Turning statistics off on a machine that never used them keeps it file-free.
            connection = self._get_connection(create=enabled)
            if connection is None:
                return
            with connection:
                connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (
                        _ENABLED_KEY_PREFIX + normalized_provider,
                        "true" if enabled else "false",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    # -- writes -----------------------------------------------------------

    def record_event(
        self,
        *,
        invocation_id: str,
        provider: str,
        cli_type: str,
        bot_alias: str,
        agent_id: str,
        user: str,
        model: str,
        currency: str,
        total: float,
        cumulative: bool = False,
        previous_total: float | None = None,
        is_partial: bool = False,
        source: str | None = None,
        conversation_id: str | None = None,
        turn_id: str | None = None,
        native_session_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> bool:
        """Record one CLI invocation; a repeated ``invocation_id`` replaces its values.

        Returns ``False`` without writing when the total is not a finite,
        non-negative number or the identity is unusable.
        """

        raw_total = _amount(total)
        invocation = _text(invocation_id)
        if raw_total is None or not invocation:
            return False
        normalized_provider = normalize_cost_provider(provider)
        normalized_cli_type = _text(cli_type) or normalized_provider
        normalized_currency = _text(currency).upper()
        session_id = _optional_text(native_session_id)
        moment = (recorded_at or datetime.now()).astimezone()
        values = {
            "invocation_id": invocation,
            "provider": normalized_provider,
            "cli_type": normalized_cli_type,
            "bot_alias": _text(bot_alias),
            "agent_id": _text(agent_id),
            "user": _text(user),
            "model": _text(model),
            "currency": normalized_currency,
            "raw_total": raw_total,
            "is_partial": 1 if is_partial else 0,
            "source": _optional_text(source),
            "conversation_id": _optional_text(conversation_id),
            "turn_id": _optional_text(turn_id),
            "native_session_id": session_id,
            "cumulative": 1 if cumulative else 0,
        }
        with self._lock:
            connection = self._get_connection(create=True)
            assert connection is not None
            with connection:
                existing = connection.execute(
                    """
                    SELECT event_id, recorded_at_ms, baseline, baseline_event_id, cumulative
                    FROM cost_events WHERE invocation_id = ?
                    """,
                    (invocation,),
                ).fetchone()
                if existing is not None:
                    event_id, recorded_at_ms = int(existing[0]), int(existing[1])
                    position = (recorded_at_ms, event_id)
                    if not cumulative:
                        baseline = anchor = None
                    elif existing[4]:
                        # The baseline of an invocation is fixed by its first cumulative record.
                        baseline = existing[2]
                        anchor = self._anchor_by_id(connection, existing[3])
                    else:
                        # A running total arriving after a partial estimate still needs a baseline.
                        baseline, anchor = self._cumulative_baseline(
                            connection,
                            provider=normalized_provider,
                            native_session_id=session_id,
                            currency=normalized_currency,
                            previous_total=previous_total,
                            before=position,
                        )
                    baseline, anchor, amount = self._turn_amount(
                        connection,
                        raw_total,
                        baseline,
                        anchor,
                        provider=normalized_provider,
                        native_session_id=session_id,
                        currency=normalized_currency,
                        before=position,
                    )
                    connection.execute(
                        """
                        UPDATE cost_events SET
                            provider = :provider, cli_type = :cli_type, bot_alias = :bot_alias,
                            agent_id = :agent_id, user = :user, model = :model, currency = :currency,
                            amount = :amount, raw_total = :raw_total, is_partial = :is_partial,
                            source = :source, conversation_id = :conversation_id, turn_id = :turn_id,
                            native_session_id = :native_session_id, baseline = :baseline,
                            baseline_event_id = :baseline_event_id, cumulative = :cumulative
                        WHERE event_id = :event_id
                        """,
                        {
                            **values,
                            "amount": amount,
                            "baseline": baseline,
                            "baseline_event_id": anchor[1] if anchor else None,
                            "event_id": event_id,
                        },
                    )
                    return True
                recorded_at_ms = int(moment.timestamp() * 1000)
                # A new row sorts after every stored row of the same millisecond.
                position = (recorded_at_ms, _MAX_EVENT_ID)
                baseline = anchor = None
                if cumulative:
                    baseline, anchor = self._cumulative_baseline(
                        connection,
                        provider=normalized_provider,
                        native_session_id=session_id,
                        currency=normalized_currency,
                        previous_total=previous_total,
                        before=position,
                    )
                baseline, anchor, amount = self._turn_amount(
                    connection,
                    raw_total,
                    baseline,
                    anchor,
                    provider=normalized_provider,
                    native_session_id=session_id,
                    currency=normalized_currency,
                    before=position,
                )
                connection.execute(
                    """
                    INSERT INTO cost_events(
                        invocation_id, provider, cli_type, day, hour, recorded_at_ms,
                        bot_alias, agent_id, user, model, currency, amount, raw_total, baseline,
                        is_partial, source, conversation_id, turn_id, native_session_id, cumulative,
                        baseline_event_id
                    ) VALUES (
                        :invocation_id, :provider, :cli_type, :day, :hour, :recorded_at_ms,
                        :bot_alias, :agent_id, :user, :model, :currency, :amount, :raw_total, :baseline,
                        :is_partial, :source, :conversation_id, :turn_id, :native_session_id, :cumulative,
                        :baseline_event_id
                    )
                    """,
                    {
                        **values,
                        "day": day_number(moment.date()),
                        "hour": moment.hour,
                        "recorded_at_ms": recorded_at_ms,
                        "amount": amount,
                        "baseline": baseline,
                        "baseline_event_id": anchor[1] if anchor else None,
                    },
                )
        return True

    @classmethod
    def _turn_amount(
        cls,
        connection: sqlite3.Connection,
        raw_total: float,
        baseline: float | None,
        anchor: tuple[int, int] | None,
        *,
        provider: str,
        native_session_id: str | None,
        currency: str,
        before: tuple[int, int],
    ) -> tuple[float | None, tuple[int, int] | None, float]:
        """Return ``(baseline, anchor, amount)`` for one record.

        A lower running total means the session restarted, so the amount stands on
        its own; an equal one means nothing was spent. Partial estimates recorded
        between the anchor and this record were already counted on their own.
        """

        if baseline is None:
            return None, None, raw_total
        if raw_total < baseline:
            return None, None, raw_total
        amount = raw_total - baseline
        if anchor is not None and native_session_id:
            amount -= cls._partial_sum_between(
                connection,
                provider=provider,
                native_session_id=native_session_id,
                currency=currency,
                after=anchor,
                before=before,
            )
        return baseline, anchor, max(0.0, amount)

    @staticmethod
    def _partial_sum_between(
        connection: sqlite3.Connection,
        *,
        provider: str,
        native_session_id: str,
        currency: str,
        after: tuple[int, int],
        before: tuple[int, int],
    ) -> float:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM cost_events
            WHERE provider = ? AND native_session_id = ?
              AND (recorded_at_ms, event_id) > (?, ?)
              AND (recorded_at_ms, event_id) < (?, ?)
              AND cumulative = 0 AND currency = ?
            """,
            (provider, native_session_id, *after, *before, currency),
        ).fetchone()
        return float(row[0] or 0.0)

    @staticmethod
    def _anchor_by_id(connection: sqlite3.Connection, event_id: object) -> tuple[int, int] | None:
        if event_id is None:
            return None
        row = connection.execute(
            "SELECT recorded_at_ms, event_id FROM cost_events WHERE event_id = ?",
            (int(event_id),),
        ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else None

    @staticmethod
    def _cumulative_baseline(
        connection: sqlite3.Connection,
        *,
        provider: str,
        native_session_id: str | None,
        currency: str,
        previous_total: float | None,
        before: tuple[int, int],
    ) -> tuple[float | None, tuple[int, int] | None]:
        """Return the previous running total and the position of the record holding it.

        Without a stored running total the caller-supplied one is used, with no anchor.
        """

        if native_session_id:
            # Per-turn amounts (app-server, partial estimates) are not running totals.
            row = connection.execute(
                """
                SELECT raw_total, recorded_at_ms, event_id FROM cost_events
                WHERE provider = ? AND native_session_id = ?
                  AND (recorded_at_ms, event_id) < (?, ?)
                  AND cumulative = 1 AND currency = ?
                ORDER BY recorded_at_ms DESC, event_id DESC
                LIMIT 1
                """,
                (provider, native_session_id, *before, currency),
            ).fetchone()
            if row is not None:
                return float(row[0]), (int(row[1]), int(row[2]))
        return _amount(previous_total), None

    # -- reads ------------------------------------------------------------

    def query_cube(
        self,
        start_day: date,
        end_day: date,
        *,
        bucket: str,
        previous_start: date,
        previous_end: date,
    ) -> CostCube:
        """Aggregate a day range in SQL; ``bucket`` is ``hour``, ``day`` or ``month``."""

        if bucket not in {"hour", "day", "month"}:
            raise ValueError(f"不支持的聚合粒度: {bucket}")
        start = day_number(start_day)
        end = day_number(end_day)
        if start > end:
            raise ValueError("起始日期不能晚于结束日期")
        bucket_columns = {
            "hour": "day, hour",
            "day": "day, NULL",
            # YYYYMMDD / 100 keeps the month, so months fold without leaving SQLite.
            "month": "day / 100 * 100 + 1, NULL",
        }[bucket]
        with self._lock:
            def read() -> CostCube:
                connection = self._get_connection(create=False)
                if connection is None:
                    return CostCube((), (), (None, None))
                groups = connection.execute(
                    f"""
                    SELECT {bucket_columns}, provider, bot_alias, agent_id, user, model, currency,
                           SUM(amount), COUNT(*), SUM(is_partial)
                    FROM cost_events
                    WHERE provider IN ({_PROVIDER_PLACEHOLDERS}) AND day >= ? AND day <= ?
                    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
                    ORDER BY 1, 2, 3, 4, 5, 6, 7, 8
                    """,
                    (*COST_PROVIDERS, start, end),
                ).fetchall()
                previous_totals = connection.execute(
                    f"""
                    SELECT provider, currency, SUM(amount), COUNT(*)
                    FROM cost_events
                    WHERE provider IN ({_PROVIDER_PLACEHOLDERS}) AND day >= ? AND day <= ?
                    GROUP BY provider, currency
                    ORDER BY provider, currency
                    """,
                    (*COST_PROVIDERS, day_number(previous_start), day_number(previous_end)),
                ).fetchall()
                return CostCube(
                    groups=tuple(tuple(row) for row in groups),
                    previous_totals=tuple(
                        (str(row[0]), str(row[1]), float(row[2]), int(row[3]))
                        for row in previous_totals
                    ),
                    available_range=self._available_range(connection),
                )

            return self._read_with_recovery(read)

    @staticmethod
    def _available_range(connection: sqlite3.Connection) -> tuple[date | None, date | None]:
        first: int | None = None
        last: int | None = None
        for provider in COST_PROVIDERS:
            # One MIN and one MAX per statement, so each is a single index seek.
            row = connection.execute(
                """
                SELECT (SELECT MIN(day) FROM cost_events WHERE provider = ?),
                       (SELECT MAX(day) FROM cost_events WHERE provider = ?)
                """,
                (provider, provider),
            ).fetchone()
            if row is None or row[0] is None:
                continue
            first = int(row[0]) if first is None else min(first, int(row[0]))
            last = int(row[1]) if last is None else max(last, int(row[1]))
        if first is None or last is None:
            return None, None
        return day_from_number(first), day_from_number(last)

    def available_range(self) -> tuple[date | None, date | None]:
        with self._lock:
            def read() -> tuple[date | None, date | None]:
                connection = self._get_connection(create=False)
                if connection is None:
                    return None, None
                return self._available_range(connection)

            return self._read_with_recovery(read)

    def diagnostics(self) -> dict[str, int | bool | str]:
        with self._lock:
            return {
                "database_size_bytes": self._file_size(self.db_path),
                "wal_size_bytes": self._file_size(Path(f"{self.db_path}-wal")),
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
