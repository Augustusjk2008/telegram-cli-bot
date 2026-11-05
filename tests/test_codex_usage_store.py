from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.codex_usage.models import CodexRateLimitSample
from bot.codex_usage.service import CodexUsageService
from bot.codex_usage.store import SCHEMA_VERSION, CodexUsageStore
from bot.web.routes import codex_usage_routes


def _sample(*, limit_id: str = "shared", used_percent: float = 20) -> CodexRateLimitSample:
    sampled_at = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    return CodexRateLimitSample(
        sampled_at=sampled_at,
        used_percent=used_percent,
        window_minutes=7 * 24 * 60,
        resets_at=sampled_at + timedelta(days=7),
        plan_type="pro",
        limit_id=limit_id,
    )


def test_shared_store_separates_provider_samples_and_settings(tmp_path):
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    codex_sample = _sample(used_percent=20)
    claude_sample = _sample(used_percent=40)

    store.record_rate_limit_sample(codex_sample)
    store.record_rate_limit_sample(claude_sample, "claude")
    store.set_enabled(True)
    store.set_enabled(True, "claude")

    assert store.query("2026-11-05", "2026-11-05") == (codex_sample,)
    assert store.query("2026-11-05", "2026-11-05", "claude") == (claude_sample,)
    assert store.available_range() == (datetime(2026, 11, 5, tzinfo=timezone.utc).date(),) * 2
    assert store.available_range("claude") == (datetime(2026, 11, 5, tzinfo=timezone.utc).date(),) * 2
    assert store.get_enabled() is True
    assert store.get_enabled("claude") is True

    store.close()


def test_schema_v7_migrates_existing_samples_to_codex_provider(tmp_path):
    path = tmp_path / "usage.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE rate_limit_samples (
            sample_id INTEGER PRIMARY KEY,
            day INTEGER NOT NULL,
            limit_id TEXT NOT NULL,
            sampled_at_ms INTEGER NOT NULL,
            used_percent REAL NOT NULL,
            window_minutes INTEGER NOT NULL,
            resets_at INTEGER NOT NULL,
            plan_type TEXT,
            credits_balance TEXT
        );
        PRAGMA user_version=7;
        """
    )
    connection.execute(
        """
        INSERT INTO rate_limit_samples(
            day, limit_id, sampled_at_ms, used_percent, window_minutes,
            resets_at, plan_type, credits_balance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (20261105, "codex", 1793869200000, 20, 10080, 1794474000, "pro", None),
    )
    connection.commit()
    connection.close()

    store = CodexUsageStore(path)
    assert store.query("2026-11-05", "2026-11-05")
    assert store.query("2026-11-05", "2026-11-05", "claude") == ()
    assert store.diagnostics()["schema_version"] == SCHEMA_VERSION
    store.close()


@pytest.mark.asyncio
async def test_claude_service_reads_shared_store_without_codex_cross_talk(tmp_path):
    store = CodexUsageStore(tmp_path / "usage.sqlite3")
    store.record_rate_limit_sample(_sample(used_percent=20))
    service = CodexUsageService(store=store)

    stats = await service.query_stats(
        start_date=datetime(2026, 11, 5, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 11, 5, tzinfo=timezone.utc).date(),
        provider="claude",
    )
    config = await service.config_snapshot(provider="claude")

    assert stats["rate_limit_samples"] == []
    assert stats["available_range"] == {"first_date": None, "last_date": None}
    assert config["enabled"] is False
    assert config["current_provider"]["label"] == "Claude 官方"
    service.close()


@pytest.mark.asyncio
async def test_claude_admin_routes_use_the_shared_service(tmp_path):
    service = CodexUsageService(db_path=tmp_path / "usage.sqlite3")
    server = SimpleNamespace(
        codex_usage_service=service,
        _with_capability=AsyncMock(),
    )
    app = web.Application()
    codex_usage_routes.register(app, server)

    async with TestClient(TestServer(app)) as client:
        config_response = await client.get("/api/admin/claude-usage/config")
        assert config_response.status == 200
        config = (await config_response.json())["data"]
        assert config["current_provider"]["label"] == "Claude 官方"

        patch_response = await client.patch(
            "/api/admin/claude-usage/config",
            json={"enabled": True},
        )
        assert patch_response.status == 200
        assert (await patch_response.json())["data"]["enabled"] is True

        stats_response = await client.get(
            "/api/admin/claude-usage/stats",
            params={"start_date": "2026-11-01", "end_date": "2026-11-05"},
        )
        assert stats_response.status == 200
        stats = (await stats_response.json())["data"]
        assert stats["enabled"] is True
        assert stats["rate_limit_samples"] == []

    service.close()
