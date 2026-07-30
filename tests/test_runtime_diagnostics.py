from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.language_server.manager import LanguageServerRuntime, LanguageServerRuntimeKey
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
    assert "language_servers" in payload["data"]["runtime"]["components"]


@pytest.mark.asyncio
async def test_admin_runtime_diagnostics_projects_language_servers_to_a_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理诊断可保留运行态计数，但不能把 LSP 传输内容直接发给浏览器。"""

    class LeakingLanguageServerManager:
        def diagnostics(self) -> dict[str, object]:
            return {
                "enabled": True,
                "runtime_count": 1,
                "pending_count": 2,
                "open_document_count": 1,
                "restart_count": 3,
                "crash_count": 4,
                "state_counts": {"degraded": 1},
                "runtimes": [
                    {
                        "key": {
                            "workspace_root": "/private/lsp-workspace/customer/main.py",
                        },
                        "stderr_tail": ["LSP_STDERR_SECRET_DO_NOT_LEAK"],
                        "last_error": "LSP_SOURCE_SNIPPET_SECRET_DO_NOT_LEAK",
                        "recent_errors": ["LSP_RECENT_ERROR_SECRET_DO_NOT_LEAK"],
                    }
                ],
                "recent_errors": ["LSP_MANAGER_ERROR_SECRET_DO_NOT_LEAK"],
            }

    server = WebApiServer(
        object(),
        host="127.0.0.1",
        port=8765,
        language_server_manager=LeakingLanguageServerManager(),
    )

    async def allow(_request, _capability):
        return object()

    monkeypatch.setattr(server, "_with_capability", allow)
    monkeypatch.setattr("bot.web.server.migration_diagnostics", lambda _root: {})
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/admin/runtime-diagnostics")
            raw_payload = await response.text()
            payload = json.loads(raw_payload)

    assert response.status == 200, payload
    language_servers = payload["data"]["runtime"]["components"]["language_servers"]
    assert language_servers["runtime_count"] == 1
    assert language_servers["pending_count"] == 2
    assert language_servers["open_document_count"] == 1
    assert language_servers["state_counts"] == {"degraded": 1}
    for secret in (
        "LSP_STDERR_SECRET_DO_NOT_LEAK",
        "LSP_SOURCE_SNIPPET_SECRET_DO_NOT_LEAK",
        "LSP_RECENT_ERROR_SECRET_DO_NOT_LEAK",
        "LSP_MANAGER_ERROR_SECRET_DO_NOT_LEAK",
        "/private/lsp-workspace/customer/main.py",
    ):
        assert secret not in raw_payload


def test_language_server_runtime_diagnostics_exposes_operational_health_fields(tmp_path) -> None:
    runtime = LanguageServerRuntime(
        LanguageServerRuntimeKey("main", 1, tmp_path.resolve(), "pyright"),
        ("fake-pyright",),
        request_timeout=1,
    )

    diagnostics = runtime.diagnostics()

    assert diagnostics["state"] == "stopped"
    assert diagnostics["pid"] is None
    assert diagnostics["pending_count"] == 0
    assert diagnostics["open_document_count"] == 0
    assert isinstance(diagnostics["stderr_tail"], list)
    assert isinstance(diagnostics["recent_errors"], list)
    assert diagnostics["restart_count"] == 0
    assert diagnostics["crash_count"] == 0
