from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.codex_usage.models import CodexRateLimitSample
from bot.codex_usage.service import CodexUsageService
from bot.codex_usage.transfer import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    SampleDocumentError,
    parse_import_document,
)
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.routes import codex_usage_routes
from bot.web.server import error_middleware


WEEK_MINUTES = 7 * 24 * 60
RESETS_AT = datetime(2026, 11, 10, 9, tzinfo=timezone.utc)
NOVEMBER = {"start_date": date(2026, 11, 1), "end_date": date(2026, 11, 30)}


def _sample(minute: int, used_percent: float, *, millisecond: int = 0, day: int = 5) -> CodexRateLimitSample:
    return CodexRateLimitSample(
        sampled_at=datetime(2026, 11, day, 9, minute, 0, millisecond * 1_000, tzinfo=timezone.utc),
        used_percent=used_percent,
        window_minutes=WEEK_MINUTES,
        resets_at=RESETS_AT,
        plan_type="pro",
        limit_id="codex",
    )


def _curve(service: CodexUsageService, provider: str = "codex"):
    return [
        (sample.sampled_at.minute, sample.used_percent, sample.origin)
        for sample in service._store.query("2026-11-01", "2026-11-30", provider)
    ]


@pytest.mark.asyncio
async def test_samples_merge_across_machines_without_duplicates(tmp_path):
    laptop = CodexUsageService(db_path=tmp_path / "laptop.sqlite3")
    desktop = CodexUsageService(db_path=tmp_path / "desktop.sqlite3")
    for sample in (_sample(0, 10, millisecond=123), _sample(20, 20), _sample(25, 20)):
        await laptop.record_rate_limit_sample(sample)
    await laptop.record_rate_limit_sample(_sample(10, 5), "claude")
    await desktop.record_rate_limit_sample(_sample(10, 15))

    exported = await laptop.export_samples(
        **NOVEMBER,
        origin_label="laptop",
        now=datetime(2026, 11, 9, 4, 5, 6, tzinfo=timezone.utc),
    )
    assert exported["filename"].startswith("orbit-quota-samples-laptop-")
    assert exported["sample_count"] == 4
    assert exported["document"]["samples"][1]["sampled_at_ms"] % 1_000 == 123
    assert await desktop.import_samples(exported["document"]) == {
        "total": 4,
        "inserted": 4,
        "duplicates": 0,
        "invalid": 0,
        "inserted_by_provider": {"codex": 3, "claude": 1},
    }
    assert _curve(desktop) == [
        (0, 10, "laptop"),
        (10, 15, None),
        (20, 20, "laptop"),
        (25, 20, "laptop"),
    ]

    # A local run of equal readings must not collapse imported points away,
    # otherwise importing the same file again would re-add them.
    await desktop.record_rate_limit_sample(_sample(30, 20))
    again = await desktop.import_samples(exported["document"])
    assert (again["inserted"], again["duplicates"]) == (0, 4)

    returned = await desktop.export_samples(**NOVEMBER, origin_label="desktop")
    result = await laptop.import_samples(returned["document"])
    assert (result["inserted"], result["duplicates"]) == (2, 4)
    assert _curve(laptop) == [
        (0, 10, None),
        (10, 15, "desktop"),
        (20, 20, None),
        (25, 20, None),
        (30, 20, "desktop"),
    ]

    assert await desktop.delete_imported_samples() == {"deleted": 4}
    assert _curve(desktop) == [(10, 15, None), (30, 20, None)]
    assert _curve(desktop, "claude") == []
    laptop.close()
    desktop.close()


@pytest.mark.asyncio
async def test_export_keeps_only_samples_of_the_queried_days(tmp_path):
    service = CodexUsageService(db_path=tmp_path / "usage.sqlite3")
    for day, provider in ((2, "codex"), (5, "codex"), (5, "claude"), (8, "claude")):
        await service.record_rate_limit_sample(_sample(0, day, day=day), provider)
    # Days use the server-local calendar, like the chart query.
    queried_day = _sample(0, 0).sampled_at.astimezone().date()

    exported = await service.export_samples(start_date=queried_day, end_date=queried_day, origin_label="laptop")

    assert exported["sample_count"] == 2
    assert [(item["provider"], item["used_percent"]) for item in exported["document"]["samples"]] == [
        ("claude", 5),
        ("codex", 5),
    ]
    with pytest.raises(ValueError):
        await service.export_samples(start_date=date(2026, 11, 6), end_date=date(2026, 11, 5))
    service.close()


def test_import_rejects_foreign_files_and_skips_malformed_rows():
    valid = {
        "provider": "codex",
        "limit_id": "codex",
        "window_minutes": WEEK_MINUTES,
        "sampled_at_ms": 1_793_869_200_000,
        "used_percent": 20.5,
        "resets_at": 1_794_474_000,
        "plan_type": "pro",
        "credits_balance": "12.50",
        "origin": "desktop",
    }
    for document in (
        [],
        {"format": "something-else", "version": 1, "samples": []},
        {"format": EXPORT_FORMAT, "version": True, "samples": []},
        {"format": EXPORT_FORMAT, "version": EXPORT_VERSION + 1, "samples": []},
        {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "samples": {}},
    ):
        with pytest.raises(SampleDocumentError):
            parse_import_document(document)

    parsed = parse_import_document({
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "source": "laptop",
        "samples": [
            valid,
            {**valid, "origin": None, "sampled_at_ms": valid["sampled_at_ms"] + 1},
            {**valid, "provider": "gemini"},
            {**valid, "used_percent": True},
            {**valid, "used_percent": 101},
            {**valid, "sampled_at_ms": 1.5},
            {**valid, "sampled_at_ms": 10**20},
            {**valid, "credits_balance": 12},
            "not an object",
        ],
    })
    assert parsed.invalid == 7
    assert [sample.origin for _provider, sample in parsed.samples] == ["desktop", "laptop"]


@pytest.mark.asyncio
async def test_sample_transfer_routes_require_admin_and_report_bad_files(tmp_path):
    service = CodexUsageService(db_path=tmp_path / "usage.sqlite3")
    server = SimpleNamespace(codex_usage_service=service, _with_capability=AsyncMock())
    app = web.Application(middlewares=[error_middleware])
    codex_usage_routes.register(app, server)
    document = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "source": "laptop",
        "samples": [{
            "provider": "codex",
            "limit_id": "codex",
            "window_minutes": WEEK_MINUTES,
            "sampled_at_ms": 1_793_869_200_000,
            "used_percent": 20,
            "resets_at": 1_794_474_000,
            "plan_type": "pro",
            "credits_balance": None,
        }],
    }

    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/admin/usage-samples/import", data=b"{not json")
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "invalid_json"

        response = await client.post("/api/admin/usage-samples/import", json={"format": "x"})
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "invalid_usage_samples"

        response = await client.post("/api/admin/usage-samples/import", json=document)
        assert response.status == 200
        assert (await response.json())["data"]["inserted"] == 1

        response = await client.get(
            "/api/admin/codex-usage/stats",
            params={"start_date": "2026-11-01", "end_date": "2026-11-30"},
        )
        assert [item["origin"] for item in (await response.json())["data"]["rate_limit_samples"]] == ["laptop"]

        response = await client.get("/api/admin/usage-samples/export")
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "invalid_date_range"

        response = await client.get(
            "/api/admin/usage-samples/export",
            params={"start_date": "2026-11-01", "end_date": "2026-11-30"},
        )
        exported = (await response.json())["data"]
        assert exported["filename"].endswith(".json")
        assert [item["origin"] for item in exported["document"]["samples"]] == ["laptop"]

        response = await client.get(
            "/api/admin/usage-samples/export",
            params={"start_date": "2026-12-01", "end_date": "2026-12-31"},
        )
        assert (await response.json())["data"]["sample_count"] == 0

        response = await client.delete("/api/admin/usage-samples/imported")
        assert (await response.json())["data"] == {"deleted": 1}

    assert server._with_capability.await_count == 8
    assert all(call.args[1] == CAP_ADMIN_OPS for call in server._with_capability.await_args_list)
    service.close()
