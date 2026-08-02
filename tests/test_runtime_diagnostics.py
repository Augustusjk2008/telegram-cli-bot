from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.language_server.manager import LanguageServerRuntime, LanguageServerRuntimeKey
from bot.web import runtime_diagnostics
from bot.web import server as web_server
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


def test_event_loop_stall_watchdog_reports_once_per_stall_and_rearms_after_heartbeat() -> None:
    watchdog_type = getattr(runtime_diagnostics, "EventLoopStallWatchdog", None)
    assert watchdog_type is not None, "需要独立于 asyncio 事件循环的卡顿 watchdog"

    reports: list[dict[str, object]] = []
    reported = threading.Event()

    def capture(report: dict[str, object]) -> None:
        reports.append(report)
        reported.set()

    watchdog = watchdog_type(
        threshold_ms=40,
        poll_interval_ms=5,
        on_stall=capture,
    )
    watchdog.start(loop_thread_id=threading.get_ident())
    try:
        assert reported.wait(0.5), "watchdog 应在线程中检测到停止心跳"
        assert len(reports) == 1
        assert reports[0]["stall_ms"] >= 40
        assert "test_event_loop_stall_watchdog" in str(reports[0]["stack"])

        time.sleep(0.1)
        assert len(reports) == 1, "同一次卡顿不能重复刷屏"

        reported.clear()
        watchdog.beat()
        assert reported.wait(0.5), "恢复心跳后，下一次卡顿应再次告警"
        assert len(reports) == 2
    finally:
        watchdog.stop()

    reported.clear()
    time.sleep(0.06)
    assert not reported.is_set(), "stop 后 watchdog 不应继续告警"


def test_event_loop_stall_watchdog_restart_cannot_revive_previous_worker() -> None:
    baseline_threads = set(threading.enumerate())
    first_worker_entered = threading.Event()
    release_first_worker = threading.Event()
    state_lock = threading.Lock()
    block_first_worker = True

    def enabled() -> bool:
        nonlocal block_first_worker
        if threading.current_thread().name != "event-loop-stall-watchdog":
            return True
        with state_lock:
            should_block = block_first_worker
            block_first_worker = False
        if should_block:
            first_worker_entered.set()
            release_first_worker.wait(0.5)
        return True

    watchdog = runtime_diagnostics.EventLoopStallWatchdog(
        threshold_ms=10_000,
        poll_interval_ms=5,
        on_stall=lambda _report: None,
        enabled=enabled,
    )
    watchdog.start(loop_thread_id=threading.get_ident())
    try:
        assert first_worker_entered.wait(0.5)
        watchdog.stop()
        watchdog.start(loop_thread_id=threading.get_ident())
        release_first_worker.set()
        time.sleep(0.05)

        active_workers = [
            thread
            for thread in threading.enumerate()
            if thread not in baseline_threads and thread.name == "event-loop-stall-watchdog"
        ]
        assert len(active_workers) == 1, "旧 run 的 worker 不得因新 run 清除 stop event 而复活"
    finally:
        release_first_worker.set()
        watchdog.stop()
        watchdog.join(1.0)


def test_web_server_watchdog_timeout_includes_the_heartbeat_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_server, "diag_loop_lag_ms", lambda: 1000)

    server = WebApiServer(object(), host="127.0.0.1", port=8765)

    diagnostics = server._loop_stall_watchdog.diagnostics()
    assert diagnostics["threshold_ms"] == 2000.0


@pytest.mark.asyncio
async def test_web_loop_lag_watcher_beats_stall_watchdog_before_sleep() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765)
    heartbeat = asyncio.Event()

    class FakeWatchdog:
        def beat(self) -> None:
            heartbeat.set()

    server._loop_stall_watchdog = FakeWatchdog()
    task = asyncio.create_task(server._watch_loop_lag())
    try:
        try:
            await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        except TimeoutError:
            pass
        assert heartbeat.is_set(), "loop watcher 必须在首次 sleep 前打心跳"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_web_server_stall_watchdog_helpers_start_and_stop_without_blocking_loop() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765)
    events: list[tuple[str, object]] = []

    class FakeWatchdog:
        def start(self, *, loop_thread_id: int) -> None:
            events.append(("start", loop_thread_id))

        def stop(self) -> None:
            events.append(("stop", None))

        def join(self, timeout: float | None = None) -> None:
            events.append(("join", timeout))

    server._loop_stall_watchdog = FakeWatchdog()
    start_watchdog = getattr(server, "_start_loop_stall_watchdog", None)
    stop_watchdog = getattr(server, "_stop_loop_stall_watchdog", None)
    assert callable(start_watchdog)
    assert callable(stop_watchdog)

    start_watchdog()
    await stop_watchdog()

    assert events[0] == ("start", threading.get_ident())
    assert events[1:] == [("stop", None), ("join", 1.0)]


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
