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
