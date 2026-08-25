from __future__ import annotations

import asyncio

import importlib

import re

import sqlite3

import threading

from concurrent.futures import ThreadPoolExecutor

from datetime import date, datetime, timezone

from pathlib import Path

import pytest

def _core_modules():
    try:
        return (
            importlib.import_module("bot.codex_usage.models"),
            importlib.import_module("bot.codex_usage.store"),
            importlib.import_module("bot.codex_usage.service"),
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"Codex usage store/service 核心包尚未实现: {exc}")

def test_store_migrates_v1_provider_totals_to_default_model_without_changing_them(
    tmp_path: Path,
) -> None:
    _, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
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
            INSERT INTO providers(provider_id, provider_key, kind, base_url)
            VALUES (1, 'openai_official', 'openai_official', NULL);
            INSERT INTO daily_usage(
                day, provider_id, request_count, input_tokens,
                cached_input_tokens, output_tokens, reasoning_output_tokens
            ) VALUES (20260726, 1, 3, 1200000, 200000, 50000, 10000);
            PRAGMA user_version=1;
            """
        )

    store = store_module.CodexUsageStore(db_path)
    result = store.query(
        date(2026, 7, 26),
        date(2026, 7, 26),
        daily_page=1,
        daily_page_size=10,
    )

    assert result.totals.request_count == 3
    assert result.totals.total_tokens == 1_250_000
    assert len(result.by_provider_model) == 1
    assert result.by_provider_model[0].model == "gpt-5.6-sol"
    assert result.by_provider_model[0].totals == result.totals
    assert len(result.daily_by_provider_model) == 1
    assert result.daily_by_provider_model[0].model == "gpt-5.6-sol"
    assert result.daily_pagination is not None
    assert result.daily_pagination.total_items == 1
    assert result.rate_limit_samples == ()
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 5
    store.close()


def test_store_migrates_v2_to_current_without_changing_token_totals(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    provider = models.ProviderInfo(
        key="openai_official",
        kind="openai_official",
        base_url=None,
    )
    old_store = store_module.CodexUsageStore(db_path)
    old_store.record(
        provider,
        models.CodexTokenUsage(input_tokens=12, output_tokens=3),
        terminal_at=date(2026, 8, 10),
    )
    assert old_store._connection is not None
    old_store._connection.execute("DROP TABLE IF EXISTS rate_limit_samples")
    old_store._connection.execute("PRAGMA user_version=2")
    old_store._connection.commit()
    old_store.close()

    store = store_module.CodexUsageStore(db_path)
    result = store.query(date(2026, 8, 10), date(2026, 8, 10))

    assert result.totals.request_count == 1
    assert result.totals.total_tokens == 15
    assert result.rate_limit_samples == ()
    assert store._connection is not None
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert store._connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rate_limit_samples'"
    ).fetchone() is not None
    store.close()


def test_store_migrates_v3_rate_limits_to_general_bucket(tmp_path: Path) -> None:
    _, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    with sqlite3.connect(db_path) as connection:
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
                day, sampled_at_ms, used_percent,
                window_minutes, resets_at, plan_type
            ) VALUES (20260811, 1786413473123, 8, 10080, 1787011285, 'pro');
            PRAGMA user_version=3;
            """
        )

    store = store_module.CodexUsageStore(db_path)
    result = store.query(date(2026, 8, 11), date(2026, 8, 11))

    assert len(result.rate_limit_samples) == 1
    assert result.rate_limit_samples[0].limit_id == "codex"
    assert store._connection is not None
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert store._connection.execute(
        "SELECT limit_id FROM rate_limit_samples"
    ).fetchone()[0] == "codex"
    store.close()


def test_store_migrates_v4_model_labels_to_limit_ids(tmp_path: Path) -> None:
    _, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    with sqlite3.connect(db_path) as connection:
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
                (20260811, 'gpt-5.6-sol', 1786413473123, 8, 10080, 1787011285, 'pro'),
                (20260811, 'gpt-5.3-codex-spark', 1786413533123, 42, 300, 1787011285, 'pro');
            PRAGMA user_version=4;
            """
        )

    store = store_module.CodexUsageStore(db_path)
    result = store.query(date(2026, 8, 11), date(2026, 8, 11))

    assert [sample.limit_id for sample in result.rate_limit_samples] == ["codex"]
    assert store._connection is not None
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 5
    stored_limit_ids = store._connection.execute(
        "SELECT limit_id FROM rate_limit_samples ORDER BY sample_id"
    ).fetchall()
    assert [row[0] for row in stored_limit_ids] == ["codex", "codex_bengalfox"]
    store.close()


def test_store_queries_rate_limit_samples_by_date_and_time(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    later = models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 11, 9, 0, 0, 456_000, tzinfo=timezone.utc),
        used_percent=9.5,
        window_minutes=10_080,
        resets_at=datetime(2026, 8, 18, 8, 1, 25, tzinfo=timezone.utc),
        plan_type="pro",
        limit_id="codex_bengalfox",
    )
    earlier = models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 11, 8, 0, 0, 123_000, tzinfo=timezone.utc),
        used_percent=8,
        window_minutes=300,
        resets_at=datetime(2026, 8, 11, 13, 0, 0, tzinfo=timezone.utc),
        plan_type=None,
    )
    outside = models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc),
        used_percent=10,
        window_minutes=300,
        resets_at=datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc),
        plan_type="pro",
    )
    store.record_rate_limit_sample(later)
    store.record_rate_limit_sample(earlier)
    store.record_rate_limit_sample(outside)

    result = store.query(date(2026, 8, 11), date(2026, 8, 11))

    assert result.totals.request_count == 0
    assert result.rate_limit_samples == (earlier, later)
    assert [sample.limit_id for sample in result.rate_limit_samples] == [
        "codex",
        "codex_bengalfox",
    ]
    store.close()


def test_store_hides_secondary_model_five_hour_samples(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    five_hour = models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc),
        used_percent=42,
        window_minutes=300,
        resets_at=datetime(2026, 8, 11, 13, 0, tzinfo=timezone.utc),
        plan_type="pro",
        limit_id="codex_bengalfox",
    )
    weekly = models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        used_percent=64,
        window_minutes=10_080,
        resets_at=datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc),
        plan_type="pro",
        limit_id="codex_bengalfox",
    )
    store.record_rate_limit_sample(five_hour)
    store.record_rate_limit_sample(weekly)

    result = store.query(date(2026, 8, 11), date(2026, 8, 11))

    assert result.rate_limit_samples == (weekly,)
    store.close()


@pytest.mark.parametrize(
    "provider_keys,expected_count",
    [
        (None, 1),
        (["openai_official"], 1),
        (["openai_official", "custom:https://example.test"], 1),
        (["custom:https://example.test"], 0),
        (["unknown"], 0),
    ],
)
def test_store_rate_limit_provider_filter_semantics(
    tmp_path: Path,
    provider_keys: list[str] | None,
    expected_count: int,
) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    store.record_rate_limit_sample(
        models.CodexRateLimitSample(
            sampled_at=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc),
            used_percent=8,
            window_minutes=10_080,
            resets_at=datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
            plan_type="pro",
        )
    )

    result = store.query(
        date(2026, 8, 11),
        date(2026, 8, 11),
        provider_keys=provider_keys,
        daily_page=2,
        daily_page_size=10,
    )

    assert len(result.rate_limit_samples) == expected_count
    assert result.daily_pagination is not None
    assert result.daily_pagination.total_items == 0
    store.close()


def test_store_available_range_unions_token_and_rate_limit_days(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    store.record(
        models.ProviderInfo(
            key="openai_official",
            kind="openai_official",
            base_url=None,
        ),
        models.CodexTokenUsage(input_tokens=1, output_tokens=1),
        terminal_at=date(2026, 8, 11),
    )
    store.record_rate_limit_sample(
        models.CodexRateLimitSample(
            sampled_at=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
            used_percent=8,
            window_minutes=10_080,
            resets_at=datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc),
            plan_type="pro",
        )
    )

    assert store.available_range() == (date(2026, 8, 9), date(2026, 8, 11))
    store.close()


def test_usage_query_result_preserves_daily_pagination_as_seventh_position() -> None:
    models, _, _ = _core_modules()
    pagination = models.DailyUsagePagination(
        page=1,
        page_size=10,
        total_items=0,
        total_pages=0,
        has_previous=False,
        has_next=False,
    )

    result = models.UsageQueryResult(
        models.UsageTotals(),
        (),
        (),
        (),
        (),
        (),
        pagination,
    )

    assert result.daily_pagination is pagination
    assert result.rate_limit_samples == ()
