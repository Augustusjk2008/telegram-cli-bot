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
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()
