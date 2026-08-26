from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
) -> CodexRateLimitSample:
    sampled = sampled_at or datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
    return CodexRateLimitSample(
        sampled_at=sampled,
        used_percent=used_percent,
        window_minutes=window_minutes,
        resets_at=sampled + timedelta(days=3),
        plan_type="pro",
        limit_id=limit_id,
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


def test_store_records_and_queries_only_supported_quota_samples(tmp_path: Path) -> None:
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    general = _sample(sampled_at=datetime(2026, 8, 10, 8, tzinfo=timezone.utc))
    weekly = _sample(
        sampled_at=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
    )
    short_secondary = _sample(
        sampled_at=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
        window_minutes=300,
    )
    outside = _sample(sampled_at=datetime(2026, 8, 11, 8, tzinfo=timezone.utc))

    for sample in (weekly, general, short_secondary, outside):
        store.record_rate_limit_sample(sample)

    assert store.query(date(2026, 8, 10), date(2026, 8, 10)) == (general, weekly)
    assert store.available_range() == (date(2026, 8, 10), date(2026, 8, 11))


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
