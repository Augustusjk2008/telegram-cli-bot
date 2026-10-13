from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.codex_usage.models import (
    GENERAL_CODEX_RATE_LIMIT_ID,
    SECONDARY_CODEX_RATE_LIMIT_ID,
    CodexRateLimitSample,
)
from bot.codex_usage.store import SCHEMA_VERSION, CodexUsageStore


def _sample(
    *,
    sampled_at: datetime | None = None,
    limit_id: str = GENERAL_CODEX_RATE_LIMIT_ID,
    window_minutes: int = 10_080,
    used_percent: float = 35,
    plan_type: str = "pro",
    credits_balance: str | None = None,
) -> CodexRateLimitSample:
    sampled = sampled_at or datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
    return CodexRateLimitSample(
        sampled_at=sampled,
        used_percent=used_percent,
        window_minutes=window_minutes,
        resets_at=sampled + timedelta(days=3),
        plan_type=plan_type,
        limit_id=limit_id,
        credits_balance=credits_balance,
    )


def test_schema_6_removes_usage_tables_and_preserves_quota_data(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE providers (
            provider_id INTEGER PRIMARY KEY,
            provider_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            base_url TEXT
        );
        CREATE TABLE daily_usage (
            day INTEGER NOT NULL,
            provider_id INTEGER NOT NULL,
            request_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            reasoning_output_tokens INTEGER NOT NULL,
            PRIMARY KEY (day, provider_id)
        ) WITHOUT ROWID;
        CREATE TABLE daily_model_usage (
            day INTEGER NOT NULL,
            provider_id INTEGER NOT NULL,
            model_key TEXT NOT NULL,
            request_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            reasoning_output_tokens INTEGER NOT NULL,
            PRIMARY KEY (day, provider_id, model_key)
        ) WITHOUT ROWID;
        CREATE TABLE rate_limit_samples (
            sample_id INTEGER PRIMARY KEY,
            day INTEGER NOT NULL,
            limit_id TEXT NOT NULL,
            sampled_at_ms INTEGER NOT NULL,
            used_percent REAL NOT NULL,
            window_minutes INTEGER NOT NULL,
            resets_at INTEGER NOT NULL,
            plan_type TEXT
        );
        INSERT INTO providers(provider_id, provider_key, kind)
        VALUES (1, 'openai_official', 'openai_official');
        INSERT INTO daily_usage
        VALUES (20260810, 1, 2, 100, 20, 30, 10);
        INSERT INTO daily_model_usage
        VALUES (20260810, 1, 'gpt-5.6-sol', 2, 100, 20, 30, 10);
        INSERT INTO rate_limit_samples(
            day, limit_id, sampled_at_ms, used_percent,
            window_minutes, resets_at, plan_type
        ) VALUES (20260810, 'codex', 1786348800000, 35, 10080, 1786608000, 'pro');
        PRAGMA user_version=5;
        """
    )
    connection.close()

    store = CodexUsageStore(db_path)
    samples = store.query(date(2026, 8, 10), date(2026, 8, 10))

    assert len(samples) == 1
    assert samples[0].used_percent == 35
    schema_connection = sqlite3.connect(db_path)
    table_names = {
        row[0]
        for row in schema_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert table_names == {"settings", "rate_limit_samples"}
    assert schema_connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    schema_connection.close()


def test_store_records_and_queries_only_supported_long_term_quota_samples(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    general = _sample(
        sampled_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
        credits_balance="123.45",
    )
    weekly = _sample(
        sampled_at=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
    )
    short_general = _sample(
        sampled_at=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
        window_minutes=300,
    )
    short_secondary = _sample(
        sampled_at=datetime(2026, 8, 10, 11, tzinfo=timezone.utc),
        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
        window_minutes=300,
    )
    monthly_free = _sample(
        sampled_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        window_minutes=43_200,
        plan_type="free",
    )
    outside = _sample(sampled_at=datetime(2026, 8, 11, 8, tzinfo=timezone.utc))

    for sample in (weekly, general, short_general, short_secondary, monthly_free, outside):
        store.record_rate_limit_sample(sample)

    assert store.query(date(2026, 8, 10), date(2026, 8, 10)) == (
        general,
        weekly,
        monthly_free,
    )
    assert store.available_range() == (date(2026, 8, 10), date(2026, 8, 11))


@pytest.mark.parametrize(
    "balances",
    [(None, None, None, None), ("123.45", "123.450", "1.2345E2", "123.4500")],
)
def test_store_keeps_flat_quota_endpoints(
    tmp_path: Path, balances: tuple[str | None, ...]
) -> None:
    db_path = tmp_path / "usage.sqlite3"
    store = CodexUsageStore(db_path)
    base = _sample()
    samples = [
        replace(
            base,
            sampled_at=base.sampled_at + timedelta(minutes=index),
            credits_balance=balance,
        )
        for index, balance in enumerate(balances)
    ]
    day = base.sampled_at.date()

    for index, sample in enumerate(samples):
        store.record_rate_limit_sample(sample)
        expected = tuple(samples[: index + 1]) if index < 2 else (samples[0], sample)
        assert store.query(day, day) == expected
        store.close()
        store = CodexUsageStore(db_path)

    assert store.query(day, day) == (samples[0], samples[-1])
    store.close()


@pytest.mark.parametrize("changed_index", [0, 1, 2])
@pytest.mark.parametrize(
    "changes",
    [
        {"used_percent": 36},
        {"credits_balance": "123.45000000000000001"},
        {"credits_balance": None},
        {"resets_at": datetime(2026, 8, 14, 8, tzinfo=timezone.utc)},
        {"plan_type": "free"},
    ],
)
def test_store_preserves_quota_changes(
    tmp_path: Path, changed_index: int, changes: dict[str, object]
) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    base = _sample(credits_balance="123.45")
    samples = [
        replace(base, sampled_at=base.sampled_at + timedelta(minutes=index))
        for index in range(3)
    ]
    samples[changed_index] = replace(samples[changed_index], **changes)

    for sample in samples:
        store.record_rate_limit_sample(sample)

    day = base.sampled_at.date()
    assert store.query(day, day) == tuple(samples)


def test_store_compacts_quota_buckets_and_windows_independently(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    base = _sample()
    buckets = [
        base,
        replace(base, limit_id=SECONDARY_CODEX_RATE_LIMIT_ID),
        replace(base, window_minutes=43_200),
    ]
    samples = [
        replace(bucket, sampled_at=base.sampled_at + timedelta(minutes=index * 3 + offset))
        for index in range(3)
        for offset, bucket in enumerate(buckets)
    ]

    for sample in samples:
        store.record_rate_limit_sample(sample)

    day = base.sampled_at.date()
    assert store.query(day, day) == tuple(samples[:3] + samples[-3:])


def test_store_preserves_existing_points_when_quota_arrives_out_of_order(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    base = _sample()
    samples = [
        replace(
            base,
            sampled_at=base.sampled_at + timedelta(minutes=index),
            used_percent=0 if index == 0 else 35,
        )
        for index in range(4)
    ]

    for index in (0, 2, 3, 1):
        store.record_rate_limit_sample(samples[index])

    day = base.sampled_at.date()
    assert store.query(day, day) == tuple(samples)


def test_schema_6_preserves_v3_general_quota_sample(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE rate_limit_samples (
            sample_id INTEGER PRIMARY KEY,
            day INTEGER NOT NULL,
            sampled_at_ms INTEGER NOT NULL,
            used_percent REAL NOT NULL,
            window_minutes INTEGER NOT NULL,
            resets_at INTEGER NOT NULL,
            plan_type TEXT
        );
        INSERT INTO rate_limit_samples(
            day, sampled_at_ms, used_percent, window_minutes, resets_at, plan_type
        ) VALUES (20260810, 1786348800000, 35, 10080, 1786608000, 'pro');
        PRAGMA user_version=3;
        """
    )
    connection.close()

    samples = CodexUsageStore(db_path).query(date(2026, 8, 10), date(2026, 8, 10))

    assert len(samples) == 1
    assert samples[0].limit_id == GENERAL_CODEX_RATE_LIMIT_ID


def test_schema_6_normalizes_v4_quota_bucket_names(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE rate_limit_samples (
            sample_id INTEGER PRIMARY KEY,
            day INTEGER NOT NULL,
            model_key TEXT NOT NULL,
            sampled_at_ms INTEGER NOT NULL,
            used_percent REAL NOT NULL,
            window_minutes INTEGER NOT NULL,
            resets_at INTEGER NOT NULL,
            plan_type TEXT
        );
        INSERT INTO rate_limit_samples(
            day, model_key, sampled_at_ms, used_percent,
            window_minutes, resets_at, plan_type
        ) VALUES
            (20260810, 'gpt-5.6-sol', 1786348800000, 35, 10080, 1786608000, 'pro'),
            (20260810, 'gpt-5.3-codex-spark', 1786348860000, 64, 10080, 1786608000, 'pro');
        PRAGMA user_version=4;
        """
    )
    connection.close()

    samples = CodexUsageStore(db_path).query(date(2026, 8, 10), date(2026, 8, 10))

    assert [sample.limit_id for sample in samples] == [
        GENERAL_CODEX_RATE_LIMIT_ID,
        SECONDARY_CODEX_RATE_LIMIT_ID,
    ]


def test_reading_missing_store_does_not_create_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.sqlite3"
    store = CodexUsageStore(db_path)

    assert store.get_enabled() is False
    assert store.query(date(2026, 8, 1), date(2026, 8, 2)) == ()
    assert store.available_range() == (None, None)
    assert not db_path.exists()


def test_store_persists_quota_collection_setting(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")

    store.set_enabled(True)
    assert store.get_enabled() is True
    store.set_enabled(False)
    assert store.get_enabled() is False


def test_store_rejects_reversed_date_range(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")

    try:
        store.query(date(2026, 8, 2), date(2026, 8, 1))
    except ValueError as exc:
        assert "起始日期" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected ValueError")
