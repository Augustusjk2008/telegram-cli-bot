from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bot.native_agent.pi_rpc_client import PiRpcClient
from bot.native_agent.pi_session_runtime import (
    PiSessionRuntime,
    PiSessionRuntimeRegistry,
    PiSessionRuntimeRequest,
    PiSessionRuntimeState,
)
from bot.native_agent.pi_session_store import PiSessionStore, pi_session_key
from bot.native_agent.service import NativeAgentService


_TEST_TIMEOUT_SECONDS = 1.0


class _FakeClient:
    def __init__(self) -> None:
        self.process = SimpleNamespace(poll=lambda: None)
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1

    async def kill(self) -> None:
        self.close_count += 1

    async def events(self):
        if False:
            yield {}


class _EventClient(_FakeClient):
    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        error: BaseException | None = None,
        wait_after_events: bool = False,
    ) -> None:
        super().__init__()
        self._events = list(events)
        self._error = error
        self._wait_after_events = wait_after_events
        self._release = asyncio.Event()

    async def close(self) -> None:
        await super().close()
        self._release.set()

    async def kill(self) -> None:
        await super().kill()
        self._release.set()

    async def events(self):
        for event in self._events:
            yield event
        if self._error is not None:
            raise self._error
        if self._wait_after_events:
            await self._release.wait()


class _GatedEventClient(_FakeClient):
    def __init__(self, remaining_events: list[dict[str, Any]]) -> None:
        super().__init__()
        self._remaining_events = list(remaining_events)
        self.release = asyncio.Event()

    async def close(self) -> None:
        await super().close()
        self.release.set()

    async def kill(self) -> None:
        await super().kill()
        self.release.set()

    async def events(self):
        yield {"type": "message_start", "message": {"role": "assistant"}}
        await self.release.wait()
        for event in self._remaining_events:
            yield event


def _request(tmp_path: Path) -> PiSessionRuntimeRequest:
    return PiSessionRuntimeRequest(
        runtime_key="runtime-key",
        owner_key="owner-key",
        conversation_id="conversation",
        cwd=str(tmp_path),
        command="pi",
    )


def _runtime(index: int, tmp_path: Path) -> PiSessionRuntime:
    return PiSessionRuntime(
        client=_FakeClient(),
        state=PiSessionRuntimeState(
            pi_runtime_id=f"runtime-{index}",
            runtime_key=f"key-{index}",
            owner_key=f"owner-{index}",
            conversation_id=f"conversation-{index}",
            cwd=str(tmp_path),
            command="pi",
        ),
    )


def _runtime_with_client(client: _FakeClient, tmp_path: Path) -> PiSessionRuntime:
    return PiSessionRuntime(
        client=client,
        state=PiSessionRuntimeState(
            pi_runtime_id="runtime-stream",
            runtime_key="key-stream",
            owner_key="owner-stream",
            conversation_id="conversation-stream",
            cwd=str(tmp_path),
            command="pi",
        ),
    )


async def _collect_events(runtime: PiSessionRuntime) -> list[dict[str, Any]]:
    return [event async for event in runtime.events()]


@pytest.mark.asyncio
async def test_reader_finishes_when_slow_consumer_fills_queue_and_keeps_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        4,
    )
    terminal_event = {"type": "turn_end", "message": {"finishReason": "stop"}}
    client = _EventClient(
        [
            *[
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": str(index)},
                }
                for index in range(12)
            ],
            terminal_event,
        ]
    )
    runtime = _runtime_with_client(client, tmp_path)
    runtime._ensure_reader()

    try:
        assert runtime._reader_task is not None
        await asyncio.wait_for(asyncio.shield(runtime._reader_task), timeout=_TEST_TIMEOUT_SECONDS)
        collected = await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()

    assert terminal_event in collected
    assert runtime.diagnostics()["stream_queue_events"] <= 4


@pytest.mark.asyncio
async def test_reader_error_survives_full_queue_and_reaches_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        4,
    )
    expected_error = RuntimeError("pi reader failed")
    client = _EventClient(
        [
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": str(index)},
            }
            for index in range(12)
        ],
        error=expected_error,
    )
    runtime = _runtime_with_client(client, tmp_path)
    runtime._ensure_reader()

    try:
        assert runtime._reader_task is not None
        await asyncio.wait_for(asyncio.shield(runtime._reader_task), timeout=_TEST_TIMEOUT_SECONDS)
        with pytest.raises(RuntimeError, match="pi reader failed"):
            await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_duplicate_done_events_do_not_evict_error_before_eof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        3,
    )
    error_event = {"type": "extension_error", "error": "extension failed"}
    client = _EventClient(
        [
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "partial"},
            },
            error_event,
            {"type": "turn_end"},
            {"type": "agent_end"},
        ]
    )
    runtime = _runtime_with_client(client, tmp_path)
    runtime._ensure_reader()

    try:
        assert runtime._reader_task is not None
        await asyncio.wait_for(asyncio.shield(runtime._reader_task), timeout=_TEST_TIMEOUT_SECONDS)
        collected = await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()

    assert error_event in collected
    assert any(event.get("type") in {"turn_end", "agent_end"} for event in collected)


@pytest.mark.asyncio
async def test_permission_event_survives_queue_pressure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        4,
    )
    permission_event = {
        "type": "extension_ui_request",
        "request_id": "permission-1",
        "method": "confirm",
    }
    client = _EventClient(
        [
            {"type": "message_start", "message": {"role": "assistant"}},
            {"type": "tool_execution_start", "toolCallId": "tool-1"},
            {"type": "tool_execution_end", "toolCallId": "tool-1"},
            permission_event,
            {"type": "session_state", "sessionId": "session-1"},
            {"type": "turn_end"},
        ]
    )
    runtime = _runtime_with_client(client, tmp_path)
    runtime._ensure_reader()

    try:
        assert runtime._reader_task is not None
        await asyncio.wait_for(asyncio.shield(runtime._reader_task), timeout=_TEST_TIMEOUT_SECONDS)
        collected = await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()

    assert permission_event in collected
    assert any(event.get("sessionId") == "session-1" for event in collected)


@pytest.mark.asyncio
async def test_close_replaces_queued_increment_with_eof_for_later_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        4,
    )
    client = _EventClient(
        [
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": str(index)},
            }
            for index in range(12)
        ],
        wait_after_events=True,
    )
    runtime = _runtime_with_client(client, tmp_path)
    runtime._ensure_reader()

    try:
        while runtime.diagnostics()["stream_queue_events"] == 0:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.wait_for(runtime.close(), timeout=_TEST_TIMEOUT_SECONDS)
        collected = await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()

    assert len(collected) < 4


@pytest.mark.asyncio
async def test_cancelled_consumer_releases_slot_and_later_consumer_reaches_eof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS",
        4,
    )
    terminal_event = {"type": "agent_end"}
    client = _GatedEventClient(
        [
            *[
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": str(index)},
                }
                for index in range(12)
            ],
            terminal_event,
        ]
    )
    runtime = _runtime_with_client(client, tmp_path)
    first_stream = runtime.events()
    iterator = first_stream.__aiter__()
    try:
        await asyncio.wait_for(iterator.__anext__(), timeout=_TEST_TIMEOUT_SECONDS)
        consumer_task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        consumer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer_task
        assert runtime.diagnostics()["active_consumers"] == 0

        client.release.set()
        assert runtime._reader_task is not None
        await asyncio.wait_for(asyncio.shield(runtime._reader_task), timeout=_TEST_TIMEOUT_SECONDS)
        collected = await asyncio.wait_for(_collect_events(runtime), timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        await runtime.close()

    assert terminal_event in collected


@pytest.mark.asyncio
async def test_registry_singleflights_concurrent_open_for_same_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    starts = 0

    async def fake_start(_request: Any) -> _FakeClient:
        nonlocal starts
        starts += 1
        await asyncio.sleep(0.03)
        return _FakeClient()

    monkeypatch.setattr(PiRpcClient, "start", fake_start)
    registry = PiSessionRuntimeRegistry()

    first, second = await asyncio.gather(
        registry.open_or_create(_request(tmp_path)),
        registry.open_or_create(_request(tmp_path)),
    )

    assert first is second
    assert starts == 1
    await registry.shutdown()


@pytest.mark.asyncio
async def test_registry_max_count_eviction_excludes_already_expired_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_IDLE_TTL_SECONDS",
        60.0,
    )
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_MAX_COUNT",
        32,
    )
    registry = PiSessionRuntimeRegistry()
    runtimes = [_runtime(index, tmp_path) for index in range(36)]
    for runtime in runtimes[:2]:
        runtime.last_used_at = time.monotonic() - 120
    for runtime in runtimes[2:]:
        runtime.last_used_at = time.monotonic()
    registry._by_key = {
        runtime.state.runtime_key: runtime
        for runtime in runtimes
    }
    registry._by_runtime_id = {
        runtime.runtime_id: runtime
        for runtime in runtimes
    }

    evicted = await registry.evict_idle()

    assert evicted == 4
    assert len(registry._by_runtime_id) == 32
    await registry.shutdown()


@pytest.mark.asyncio
async def test_registry_rejects_new_runtime_when_all_capacity_is_protected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_MAX_COUNT",
        2,
    )
    starts = 0

    async def fake_start(_request: Any) -> _FakeClient:
        nonlocal starts
        starts += 1
        return _FakeClient()

    monkeypatch.setattr(PiRpcClient, "start", fake_start)
    registry = PiSessionRuntimeRegistry()
    runtimes = [_runtime(index, tmp_path) for index in range(2)]
    for runtime in runtimes:
        runtime.state.processing = True
    registry._by_key = {
        runtime.state.runtime_key: runtime
        for runtime in runtimes
    }
    registry._by_runtime_id = {
        runtime.runtime_id: runtime
        for runtime in runtimes
    }

    with pytest.raises(RuntimeError, match="Pi runtime 数量已达上限"):
        await registry.open_or_create(
            PiSessionRuntimeRequest(
                runtime_key="new-runtime",
                owner_key="new-owner",
                conversation_id="new-conversation",
                cwd=str(tmp_path),
                command="pi",
            )
        )

    assert starts == 0
    assert len(registry._by_runtime_id) == 2
    await registry.shutdown()


@pytest.mark.asyncio
async def test_registry_reuses_existing_runtime_at_capacity_without_evicting_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.native_agent.pi_session_runtime.PI_RUNTIME_MAX_COUNT", 2)
    registry = PiSessionRuntimeRegistry()
    first = _runtime(0, tmp_path)
    second = _runtime(1, tmp_path)
    first.state.runtime_key = "runtime-key"
    first.state.owner_key = "owner-key"
    first.state.conversation_id = "conversation"
    registry._by_key = {first.state.runtime_key: first, second.state.runtime_key: second}
    registry._by_runtime_id = {first.runtime_id: first, second.runtime_id: second}

    reused = await registry.open_or_create(_request(tmp_path))

    assert reused is first
    assert first.client.close_count == 0
    assert len(registry._by_runtime_id) == 2
    await registry.shutdown()


@pytest.mark.asyncio
async def test_native_service_persists_runtime_before_eviction(tmp_path: Path) -> None:
    service = NativeAgentService()
    service._pi_session_store = PiSessionStore(tmp_path / "pi-sessions.json")
    runtime = PiSessionRuntime(
        client=_FakeClient(),
        state=PiSessionRuntimeState(
            pi_runtime_id="runtime-persist",
            runtime_key="1:2:conversation",
            owner_key="1:2",
            conversation_id="conversation",
            cwd=str(tmp_path),
            command="pi",
            native_session_id="pi-session",
            workspace_history_head="workspace-head",
            linear_index=7,
        ),
    )

    await service._persist_runtime_before_close(runtime)

    record = service._pi_session_store.get(
        pi_session_key(
            cwd=str(tmp_path),
            bot_id=1,
            user_id=2,
            conversation_id="conversation",
        )
    )
    assert record is not None
    assert record.pi_session_id == "pi-session"
    assert record.workspace_history_head == "workspace-head"
    assert record.linear_index == 7


@pytest.mark.asyncio
async def test_registry_shutdown_persists_and_closes_each_runtime_once(tmp_path: Path) -> None:
    persisted: list[str] = []
    release_persistence = asyncio.Event()

    async def persist(runtime: PiSessionRuntime) -> None:
        persisted.append(runtime.runtime_id)
        await release_persistence.wait()

    registry = PiSessionRuntimeRegistry(before_runtime_close=persist)
    runtimes = [_runtime(index, tmp_path) for index in range(3)]
    registry._by_key = {runtime.state.runtime_key: runtime for runtime in runtimes}
    registry._by_runtime_id = {runtime.runtime_id: runtime for runtime in runtimes}

    shutdown_task = asyncio.create_task(registry.shutdown())
    while not persisted:
        await asyncio.sleep(0)

    assert registry.diagnostics()["runtime_count"] == 0
    release_persistence.set()
    report = await shutdown_task

    assert sorted(persisted) == ["runtime-0", "runtime-1", "runtime-2"]
    assert [runtime.client.close_count for runtime in runtimes] == [1, 1, 1]
    assert report == {
        "requested": 3,
        "persisted": 3,
        "closed": 3,
        "failed": 0,
        "timed_out": 0,
        "lock_timed_out": False,
        "start_tasks_cancelled": 0,
    }


@pytest.mark.asyncio
async def test_registry_slow_start_does_not_hold_lock_and_shutdown_cancels_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started = asyncio.Event()

    async def slow_start(_request: Any) -> _FakeClient:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(PiRpcClient, "start", slow_start)
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS",
        0.1,
    )
    registry = PiSessionRuntimeRegistry()
    open_task = asyncio.create_task(registry.open_or_create(_request(tmp_path)))
    await asyncio.wait_for(started.wait(), timeout=1)

    try:
        assert await asyncio.wait_for(registry.evict_idle(), timeout=0.05) == 0
        report = await asyncio.wait_for(registry.shutdown(), timeout=0.5)

        assert report["lock_timed_out"] is False
        assert report["start_tasks_cancelled"] == 1
        assert registry.diagnostics()["runtime_count"] == 0
        with pytest.raises(asyncio.CancelledError):
            await open_task
    finally:
        if not open_task.done():
            open_task.cancel()
        await asyncio.gather(open_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_registry_shutdown_deadline_includes_lock_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS",
        0.05,
    )
    registry = PiSessionRuntimeRegistry()
    await registry._lock.acquire()
    try:
        started_at = time.monotonic()
        try:
            report = await asyncio.wait_for(registry.shutdown(), timeout=0.2)
        except asyncio.TimeoutError:
            pytest.fail("shutdown 未将 registry 锁等待计入总 deadline")
        elapsed = time.monotonic() - started_at
    finally:
        registry._lock.release()

    assert elapsed < 0.2
    assert report["lock_timed_out"] is True
    assert report["timed_out"] == 1


@pytest.mark.asyncio
async def test_registry_shutdown_reports_slow_close_as_timeout_not_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class SlowCloseClient(_FakeClient):
        async def close(self) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(
        "bot.native_agent.pi_session_runtime.PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS",
        0.05,
    )
    runtime = _runtime(0, tmp_path)
    runtime.client = SlowCloseClient()
    registry = PiSessionRuntimeRegistry()
    registry._by_key = {runtime.state.runtime_key: runtime}
    registry._by_runtime_id = {runtime.runtime_id: runtime}

    report = await asyncio.wait_for(registry.shutdown(), timeout=0.2)

    assert report["requested"] == 1
    assert report["timed_out"] == 1
    assert report["failed"] == 0
    assert report["closed"] == 0


@pytest.mark.asyncio
async def test_same_owner_different_runtime_starts_are_serialized_and_capacity_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.native_agent.pi_session_runtime.PI_RUNTIME_MAX_COUNT", 1)
    releases = [asyncio.Event(), asyncio.Event()]
    started_count = 0
    clients: list[_FakeClient] = []

    async def controlled_start(_request: Any) -> _FakeClient:
        nonlocal started_count
        index = started_count
        started_count += 1
        client = _FakeClient()
        clients.append(client)
        await releases[index].wait()
        return client

    monkeypatch.setattr(PiRpcClient, "start", controlled_start)
    registry = PiSessionRuntimeRegistry()
    first_request = PiSessionRuntimeRequest(
        runtime_key="runtime-a",
        owner_key="owner-shared",
        conversation_id="conversation-a",
        cwd=str(tmp_path),
        command="pi",
    )
    second_request = PiSessionRuntimeRequest(
        runtime_key="runtime-b",
        owner_key="owner-shared",
        conversation_id="conversation-b",
        cwd=str(tmp_path),
        command="pi",
    )

    first_task = asyncio.create_task(registry.open_or_create(first_request))
    while started_count < 1:
        await asyncio.sleep(0)
    second_task = asyncio.create_task(registry.open_or_create(second_request))
    await asyncio.sleep(0.05)
    assert started_count == 1
    assert registry.diagnostics()["runtime_count"] == 0

    releases[0].set()
    first_runtime = await first_task
    while started_count < 2:
        await asyncio.sleep(0)
    assert len(registry._by_runtime_id) <= 1
    releases[1].set()
    second_runtime = await second_task

    assert len(registry._by_runtime_id) == 1
    assert registry.get_by_runtime_id(second_runtime.runtime_id) is second_runtime
    assert first_runtime.client.close_count == 1
    await registry.shutdown()
