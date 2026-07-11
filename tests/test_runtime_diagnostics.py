from __future__ import annotations

import asyncio
import json

import pytest

from bot.web.runtime_diagnostics import LoopLagTracker, RuntimeDiagnosticsRegistry
from bot.web.server import WebApiServer


@pytest.mark.asyncio
async def test_runtime_diagnostics_registry_is_versioned_and_provider_failures_are_isolated() -> None:
    registry = RuntimeDiagnosticsRegistry()
    tracker = LoopLagTracker(max_samples=8, threshold_ms=5)
    tracker.observe(1.0)
    tracker.observe(10.0)
    registry.register("healthy", lambda: {"items": 2, "bytes": 10})
    registry.register("broken", lambda: 1 / 0)
    registry.register("loop_lag", tracker.diagnostics)

    snapshot = registry.snapshot()

    assert snapshot["schema_version"] == 1
    assert snapshot["components"]["healthy"] == {"items": 2, "bytes": 10}
    assert snapshot["components"]["broken"]["available"] is False
    assert snapshot["components"]["loop_lag"]["current_ms"] == 10.0
    assert snapshot["components"]["loop_lag"]["over_threshold_count"] == 1
    assert snapshot["process"]["asyncio_tasks"] >= 1


def test_loop_lag_tracker_keeps_bounded_percentile_samples() -> None:
    tracker = LoopLagTracker(max_samples=4, threshold_ms=100)
    for value in (1, 2, 3, 4, 1000):
        tracker.observe(value)

    data = tracker.diagnostics()

    assert data["sample_count"] == 4
    assert data["max_ms"] == 1000.0
    assert data["p50_ms"] >= 3.0


@pytest.mark.asyncio
async def test_admin_runtime_diagnostics_keeps_migration_fields_and_adds_runtime(monkeypatch) -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765)

    async def allow(_request, _capability):
        return object()

    monkeypatch.setattr(server, "_with_capability", allow)
    monkeypatch.setattr("bot.web.server.migration_diagnostics", lambda _root: {"migration": "kept"})

    response = await server.admin_runtime_diagnostics(object())
    payload = json.loads(response.text)

    assert payload["data"]["migration"] == "kept"
    assert payload["data"]["runtime"]["schema_version"] == 1
    assert "terminal" in payload["data"]["runtime"]["components"]
