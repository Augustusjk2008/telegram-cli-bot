from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.cost_stats.service import CostStatsService, resolve_granularity
from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.routes import cost_stats_routes
from bot.web.server import error_middleware


def _event(**overrides):
    fields = {
        "invocation_id": "inv",
        "provider": "claude",
        "cli_type": "claude",
        "bot_alias": "main",
        "agent_id": "main",
        "user": "alice",
        "model": "claude-opus-5-5",
        "currency": "USD",
        "total": 1.0,
        "recorded_at": datetime(2026, 11, 16, 9, 30),
    }
    fields.update(overrides)
    return fields


def _rows(path, columns="invocation_id, amount, baseline, day, hour"):
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT {columns} FROM cost_events ORDER BY event_id").fetchall()


async def _enabled_service(tmp_path) -> CostStatsService:
    service = CostStatsService(db_path=tmp_path / "cost.sqlite3")
    await service.set_enabled("claude", True)
    await service.set_enabled("codex", True)
    return service


@pytest.mark.asyncio
async def test_disabled_statistics_record_nothing_and_create_no_database(tmp_path):
    path = tmp_path / "cost.sqlite3"
    service = CostStatsService(db_path=path)
    load = Mock(wraps=service._store.get_enabled_flags)
    service._store.get_enabled_flags = load

    assert await service.record_turn(**_event()) is False
    assert await service.record_turn(**_event(provider="codex", cli_type="codex")) is False
    await service.set_enabled("codex", False)
    stats = await service.query_stats(start_date=date(2026, 11, 10), end_date=date(2026, 11, 16))

    assert not path.exists()
    assert load.call_count == 1
    assert stats["enabled"] == {"claude": False, "codex": False}
    assert stats["rows"] == [] and stats["top_turns"] == []
    assert stats["available_range"] == {"first_date": None, "last_date": None}
    assert len(stats["buckets"]) == 7


@pytest.mark.asyncio
async def test_enabling_one_provider_records_only_that_provider(tmp_path):
    service = CostStatsService(db_path=tmp_path / "cost.sqlite3")
    config = await service.update_enabled("claude", True)

    assert config["enabled"] == {"claude": True, "codex": False}
    assert await service.record_turn(**_event()) is True
    assert await service.record_turn(**_event(invocation_id="x", provider="codex", cli_type="codex")) is False
    assert await service.record_turn(**_event(invocation_id="nan", total=math.nan)) is False
    assert await service.record_turn(**_event(invocation_id="neg", total=-1.0)) is False
    assert [row[0] for row in _rows(service.db_path)] == ["inv"]
    config = await service.config_snapshot()
    assert config["available_range"] == {"first_date": "2026-11-16", "last_date": "2026-11-16"}
    assert set(config["time_basis"]) == {"mode", "utc_offset", "today"}


@pytest.mark.asyncio
async def test_codex_exec_records_the_increase_of_its_running_total(tmp_path):
    service = await _enabled_service(tmp_path)
    codex = {"provider": "codex", "cli_type": "codex", "cumulative": True, "native_session_id": "s1"}

    await service.record_turn(**_event(invocation_id="a", total=1.0, **codex))
    await service.record_turn(**_event(invocation_id="b", total=1.5, **codex,
                                       recorded_at=datetime(2026, 11, 16, 10, 0)))
    # App-server amounts are per turn: never a baseline, and already counted on their own.
    await service.record_turn(**_event(invocation_id="srv", total=0.3, provider="codex", cli_type="codex_server",
                                       native_session_id="s1", recorded_at=datetime(2026, 11, 16, 10, 30)))
    await service.record_turn(**_event(invocation_id="c", total=1.8, **codex,
                                       recorded_at=datetime(2026, 11, 16, 11, 0)))
    # A lower running total means the session restarted.
    await service.record_turn(**_event(invocation_id="d", total=0.2, **codex,
                                       recorded_at=datetime(2026, 11, 16, 12, 0)))
    # Without a stored turn the caller-supplied previous total is the baseline.
    await service.record_turn(**_event(invocation_id="e", total=3.4, previous_total=3.0,
                                       **{**codex, "native_session_id": "s2"}))
    # Re-recording an invocation replaces its numbers but keeps time bucket and baseline.
    await service.record_turn(**_event(invocation_id="b", total=1.7, **codex,
                                       recorded_at=datetime(2026, 11, 17, 23, 0)))

    rows = {row[0]: row[1:] for row in _rows(service.db_path)}
    assert len(rows) == 6
    assert rows["a"] == (pytest.approx(1.0), None, 20261116, 9)
    assert rows["b"] == (pytest.approx(0.7), 1.0, 20261116, 10)
    assert rows["srv"] == (pytest.approx(0.3), None, 20261116, 10)
    assert rows["c"] == (pytest.approx(0.0), 1.5, 20261116, 11)
    assert rows["d"] == (pytest.approx(0.2), None, 20261116, 12)
    assert rows["e"] == (pytest.approx(0.4), 3.0, 20261116, 9)


@pytest.mark.asyncio
async def test_codex_exec_equal_running_total_records_zero(tmp_path):
    service = await _enabled_service(tmp_path)
    codex = {"provider": "codex", "cli_type": "codex", "cumulative": True, "native_session_id": "s1"}

    await service.record_turn(**_event(invocation_id="a", total=2.0, **codex))
    await service.record_turn(**_event(invocation_id="b", total=2.0, **codex,
                                       recorded_at=datetime(2026, 11, 16, 10, 0)))
    await service.record_turn(**_event(invocation_id="b", total=2.0, **codex))

    rows = {row[0]: row[1:3] for row in _rows(service.db_path)}
    assert rows["b"] == (0.0, 2.0)


@pytest.mark.asyncio
async def test_codex_exec_turn_after_interrupted_turn_excludes_its_partial_cost(tmp_path):
    service = await _enabled_service(tmp_path)
    codex = {"provider": "codex", "cli_type": "codex", "native_session_id": "s1"}

    await service.record_turn(**_event(invocation_id="a", total=10.0, cumulative=True, **codex,
                                       recorded_at=datetime(2026, 11, 16, 9, 0)))
    await service.record_turn(**_event(invocation_id="b", total=2.0, is_partial=True, **codex,
                                       recorded_at=datetime(2026, 11, 16, 10, 0)))
    # Another session's partial turn does not touch this one.
    await service.record_turn(**_event(invocation_id="other", total=5.0, is_partial=True,
                                       **{**codex, "native_session_id": "s2"},
                                       recorded_at=datetime(2026, 11, 16, 10, 30)))
    await service.record_turn(**_event(invocation_id="c", total=13.0, cumulative=True, **codex,
                                       recorded_at=datetime(2026, 11, 16, 11, 0)))
    first = {row[0]: row[1:3] for row in _rows(service.db_path)}
    # A later partial turn must not change the amount of a re-recorded earlier one.
    await service.record_turn(**_event(invocation_id="d", total=0.5, is_partial=True, **codex,
                                       recorded_at=datetime(2026, 11, 16, 12, 0)))
    await service.record_turn(**_event(invocation_id="c", total=13.0, cumulative=True, **codex))
    # A partial turn at least as large as the increase leaves nothing below zero.
    await service.record_turn(**_event(invocation_id="e", total=13.2, cumulative=True, **codex,
                                       recorded_at=datetime(2026, 11, 16, 13, 0)))

    rows = {row[0]: row[1:3] for row in _rows(service.db_path)}
    assert first["c"] == (pytest.approx(1.0), 10.0)
    assert rows["b"] == (2.0, None)
    assert rows["c"] == (pytest.approx(1.0), 10.0)
    assert rows["e"] == (0.0, 13.0)
    stats = await service.query_stats(start_date=date(2026, 11, 16), end_date=date(2026, 11, 16), granularity="day")
    assert sum(row[7] for row in stats["rows"]) == pytest.approx(10.0 + 2.0 + 5.0 + 1.0 + 0.5)


@pytest.mark.parametrize(
    ("days", "requested", "expected"),
    [
        (1, "auto", "hour"), (2, "auto", "hour"), (3, "auto", "day"), (92, "auto", "day"),
        (93, "auto", "week"), (730, "auto", "week"), (731, "auto", "month"),
        (7, "hour", "hour"), (8, "hour", "day"), (400, "day", "day"), (3, "month", "month"),
    ],
)
def test_granularity_resolution(days, requested, expected):
    start = date(2026, 1, 1)
    end = date.fromordinal(start.toordinal() + days - 1)
    assert resolve_granularity(requested, start, end) == expected


def test_granularity_rejects_unknown_values():
    with pytest.raises(ValueError):
        resolve_granularity("year", date(2026, 1, 1), date(2026, 1, 2))


@pytest.mark.asyncio
async def test_query_builds_an_encoded_cube_for_every_granularity(tmp_path):
    service = await _enabled_service(tmp_path)
    await service.record_turn(**_event(invocation_id="1", total=1.25, recorded_at=datetime(2026, 11, 10, 8, 0)))
    await service.record_turn(**_event(invocation_id="2", total=0.75, is_partial=True,
                                       recorded_at=datetime(2026, 11, 10, 9, 0)))
    await service.record_turn(**_event(invocation_id="3", total=2.0, user="", agent_id="worker",
                                       recorded_at=datetime(2026, 11, 12, 9, 0)))
    await service.record_turn(**_event(invocation_id="4", total=0.5, provider="codex", cli_type="codex_server",
                                       model="gpt-5.5", recorded_at=datetime(2026, 11, 16, 9, 0)))

    day = await service.query_stats(start_date=date(2026, 11, 10), end_date=date(2026, 11, 16), granularity="auto")
    assert day["granularity"] == "day"
    assert day["range"] == {"start_date": "2026-11-10", "end_date": "2026-11-16"}
    assert day["buckets"] == [f"2026-11-{value}" for value in range(10, 17)]
    dims = day["dimensions"]
    assert set(dims) == {"provider", "bot", "agent", "user", "model", "currency"}
    decoded = sorted(
        (day["buckets"][row[0]], dims["provider"][row[1]], dims["bot"][row[2]], dims["agent"][row[3]],
         dims["user"][row[4]], dims["model"][row[5]], dims["currency"][row[6]], *row[7:])
        for row in day["rows"]
    )
    assert decoded == [
        ("2026-11-10", "claude", "main", "main", "alice", "claude-opus-5-5", "USD", 2.0, 2, 1),
        ("2026-11-12", "claude", "main", "worker", "", "claude-opus-5-5", "USD", 2.0, 1, 0),
        ("2026-11-16", "codex", "main", "main", "alice", "gpt-5.5", "USD", 0.5, 1, 0),
    ]
    assert all(len(row) == 10 for row in day["rows"])

    week = await service.query_stats(start_date=date(2026, 11, 1), end_date=date(2026, 11, 16), granularity="week")
    assert week["buckets"] == ["2026-10-26", "2026-11-02", "2026-11-09", "2026-11-16"]
    assert sorted((week["buckets"][row[0]], row[7], row[8]) for row in week["rows"]) == [
        ("2026-11-09", 2.0, 1), ("2026-11-09", 2.0, 2), ("2026-11-16", 0.5, 1),
    ]

    month = await service.query_stats(start_date=date(2026, 10, 15), end_date=date(2026, 11, 16), granularity="month")
    assert month["buckets"] == ["2026-10-01", "2026-11-01"]
    assert {month["buckets"][row[0]] for row in month["rows"]} == {"2026-11-01"}

    hour = await service.query_stats(start_date=date(2026, 11, 10), end_date=date(2026, 11, 10))
    assert hour["granularity"] == "hour"
    assert len(hour["buckets"]) == 24 and hour["buckets"][0] == "2026-11-10T00"
    assert sorted((hour["buckets"][row[0]], row[7]) for row in hour["rows"]) == [
        ("2026-11-10T08", 1.25), ("2026-11-10T09", 0.75),
    ]


@pytest.mark.asyncio
async def test_query_reports_previous_period_and_top_turns(tmp_path):
    service = await _enabled_service(tmp_path)
    for index in range(12):
        await service.record_turn(**_event(invocation_id=f"c{index}", total=float(index),
                                           recorded_at=datetime(2026, 11, 16, 9, index)))
    await service.record_turn(**_event(invocation_id="x", total=7.5, provider="codex", cli_type="codex_server",
                                       recorded_at=datetime(2026, 11, 15, 9, 0)))
    await service.record_turn(**_event(invocation_id="old1", total=1.5, recorded_at=datetime(2026, 11, 9, 9, 0)))
    await service.record_turn(**_event(invocation_id="old2", total=2.5, recorded_at=datetime(2026, 11, 3, 9, 0)))
    await service.record_turn(**_event(invocation_id="older", total=9.0, recorded_at=datetime(2026, 11, 2, 9, 0)))

    stats = await service.query_stats(start_date=date(2026, 11, 10), end_date=date(2026, 11, 16))

    assert stats["previous_period"] == {
        "start_date": "2026-11-03",
        "end_date": "2026-11-09",
        "totals": [{"provider": "claude", "currency": "USD", "amount": 4.0, "turns": 2}],
    }
    top = stats["top_turns"]
    assert [turn["amount"] for turn in top] == [11.0, 10.0, 9.0, 8.0, 7.5, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0]
    assert sum(turn["provider"] == "claude" for turn in top) == 10
    assert top[0]["recorded_at"].startswith("2026-11-16T09:11:00")
    assert set(top[0]) == {"provider", "recorded_at", "bot", "agent", "user", "model", "currency", "amount",
                           "is_partial", "conversation_id", "turn_id"}
    assert stats["available_range"] == {"first_date": "2026-11-02", "last_date": "2026-11-16"}


@pytest.mark.asyncio
async def test_query_cache_is_reused_until_a_write(tmp_path):
    service = await _enabled_service(tmp_path)
    query = Mock(wraps=service._store.query_cube)
    service._store.query_cube = query
    params = {"start_date": date(2026, 11, 10), "end_date": date(2026, 11, 16)}

    first = await service.query_stats(**params)
    assert await service.query_stats(**params) == first
    assert query.call_count == 1

    await service.record_turn(**_event())
    refreshed = await service.query_stats(**params)
    assert query.call_count == 2
    assert [row[7] for row in refreshed["rows"]] == [1.0]


@pytest.mark.asyncio
async def test_cost_stats_routes_require_admin_and_validate_input(tmp_path):
    service = CostStatsService(db_path=tmp_path / "cost.sqlite3")
    server = SimpleNamespace(cost_stats_service=service, _with_capability=AsyncMock())
    app = web.Application(middlewares=[error_middleware])
    cost_stats_routes.register(app, server)

    async with TestClient(TestServer(app)) as client:
        for body, code in (
            ({"provider": "codex", "enabled": "true"}, "invalid_enabled"),
            ({"provider": "gemini", "enabled": True}, "invalid_provider"),
            ([], "invalid_json"),
        ):
            response = await client.patch("/api/admin/cost-stats/config", json=body)
            assert response.status == 400
            assert (await response.json())["error"]["code"] == code
        for params, code in (
            ({"start_date": "2026-11-10"}, "invalid_date_range"),
            ({"start_date": "2026-11-17", "end_date": "2026-11-10"}, "invalid_date_range"),
            ({"granularity": "year"}, "invalid_granularity"),
        ):
            response = await client.get("/api/admin/cost-stats/stats", params=params)
            assert response.status == 400
            assert (await response.json())["error"]["code"] == code

        response = await client.patch("/api/admin/cost-stats/config", json={"provider": "claude", "enabled": True})
        assert response.status == 200
        config = (await response.json())["data"]
        assert config["enabled"] == {"claude": True, "codex": False}
        assert set(config) == {"enabled", "time_basis", "available_range"}

        response = await client.get(
            "/api/admin/cost-stats/stats",
            params={"start_date": "2026-11-11", "end_date": "2026-11-17", "granularity": "day"},
        )
        assert response.status == 200
        stats = (await response.json())["data"]
        assert set(stats) == {"range", "granularity", "enabled", "time_basis", "available_range", "buckets",
                              "dimensions", "rows", "previous_period", "top_turns"}
        assert stats["dimensions"]["provider"] == ["claude", "codex"]

    assert all(call.args[1] == CAP_ADMIN_OPS for call in server._with_capability.await_args_list)
    assert server._with_capability.await_count == 8

    server._with_capability = AsyncMock(side_effect=WebApiError(403, "forbidden", "需要管理员权限"))
    async with TestClient(TestServer(app)) as client:
        for method, url in (("GET", "/api/admin/cost-stats/config"), ("GET", "/api/admin/cost-stats/stats"),
                            ("PATCH", "/api/admin/cost-stats/config")):
            response = await client.request(method, url, json={"provider": "codex", "enabled": True})
            assert response.status == 403
    assert (await service.config_snapshot())["enabled"]["codex"] is False
