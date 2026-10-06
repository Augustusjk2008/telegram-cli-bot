import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.codex_server.client import CodexServerUnknownOutcome
from bot.codex_server.voice import (
    VoiceError,
    VoiceEvents,
    VoiceLease,
    VoiceLeaseRegistry,
    validate_message,
    voice_capability,
)


class FakeRuntime:
    def __init__(self, *, owner=(1, 2, "main"), conversation="conversation"):
        self.request = SimpleNamespace(
            owner_key=owner,
            conversation_id=conversation,
            experimental_api=True,
        )
        self.thread_id = "thread-1"
        self.active = False
        self.alive = True
        self.voice_events = VoiceEvents()
        self.voice_lease = None
        self.start_realtime = AsyncMock(return_value={})
        self.stop_realtime = AsyncMock(return_value={})

    def subscribe_voice(self):
        return self.voice_events.subscribe()

    def unsubscribe_voice(self, queue):
        self.voice_events.unsubscribe(queue)


async def wait_for_cleanup(lease: VoiceLease) -> None:
    for _ in range(100):
        if not lease.cleanup_pending:
            return
        await asyncio.sleep(0)
    pytest.fail("voice lease cleanup did not complete")


def test_voice_capability_is_default_off_and_scope_checked():
    assert voice_capability(enabled=False, cli_type="codex_server", execution_mode="cli", can_send=True) == {
        "enabled": False,
        "reason": "disabled",
    }
    assert voice_capability(enabled=True, cli_type="codex", execution_mode="cli", can_send=True)["reason"] == "unsupported_cli"
    assert voice_capability(enabled=True, cli_type="codex_server", execution_mode="cli", can_send=False)["enabled"] is False
    assert voice_capability(enabled=True, cli_type="codex_server", execution_mode="cli", can_send=True)["enabled"] is True


def test_voice_message_validates_sdp_and_does_not_accept_client_bindings():
    seen = set()
    assert validate_message({"id": "one", "op": "start", "sdp": "v=0\r\n"}, seen)["op"] == "start"
    with pytest.raises(VoiceError, match="已处理"):
        validate_message({"id": "one", "op": "summary"}, seen)
    with pytest.raises(VoiceError, match="大小"):
        validate_message({"id": "two", "op": "start", "sdp": "v=0" + "a" * 128_000}, seen)
    with pytest.raises(VoiceError, match="字段"):
        validate_message({"id": "three", "op": "summary", "thread_id": "other"}, seen)


def test_voice_lease_conflict_and_session_isolation():
    registry = VoiceLeaseRegistry()
    first = registry.acquire((1, 2, "main", "conversation"), ("account-a", 2))
    with pytest.raises(VoiceError, match="已有语音连接"):
        registry.acquire((1, 2, "main", "conversation"), ("account-b", 2))
    second = registry.acquire((1, 3, "main", "conversation"), ("account-b", 3))
    third = registry.acquire((1, 2, "other", "conversation"), ("account-b", 2))
    assert len({first.connection_id, second.connection_id, third.connection_id}) == 3


@pytest.mark.asyncio
async def test_runtime_voice_events_are_bounded_and_stop_is_realtime_only():
    runtime = FakeRuntime()
    lease = VoiceLease((1, 2, "main", "conversation"), ("account", 2))
    queue = runtime.subscribe_voice()
    lease.bind(runtime)
    await lease.start("v=0\r\n")
    started = {"method": "thread/realtime/started", "params": {
        "threadId": "thread-1", "realtimeSessionId": "realtime-1"}}
    sdp = {"method": "thread/realtime/sdp", "params": {
        "threadId": "thread-1", "sdp": "v=0 answer"}}
    runtime.voice_events.packet(started, "thread-1")
    lease.observe(started)
    runtime.voice_events.packet(sdp, "thread-1")
    lease.observe(sdp)
    messages = [await asyncio.wait_for(queue.get(), 1) for _ in range(5)]
    assert any(item["type"] == "voice.sdp" for item in messages)
    assert lease.state == "active"

    stopping = asyncio.create_task(lease.stop_voice(timeout=1))
    await asyncio.sleep(0)
    closed = {"method": "thread/realtime/closed", "params": {
        "threadId": "thread-1", "realtimeSessionId": "realtime-1"}}
    runtime.voice_events.packet(closed, "thread-1")
    lease.observe(closed)
    await stopping
    assert lease.state == "closed"
    assert runtime.stop_realtime.await_count == 1


@pytest.mark.asyncio
async def test_unknown_stop_result_is_not_retried():
    runtime = FakeRuntime()
    runtime.stop_realtime.side_effect = CodexServerUnknownOutcome("unknown")
    registry = VoiceLeaseRegistry()
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")
    await lease.stop_voice(timeout=.01)
    await lease.stop_voice(timeout=.01)
    assert lease.state == "unknown"
    assert runtime.stop_realtime.await_count == 1
    assert not registry.owner_busy((1, 2, "main"))


@pytest.mark.asyncio
async def test_disconnect_keeps_runtime_binding_until_realtime_closed():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry()
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")

    disconnecting = asyncio.create_task(lease.disconnect())
    await asyncio.sleep(0)
    assert runtime.voice_lease is lease
    closed = {"method": "thread/realtime/closed", "params": {
        "threadId": "thread-1", "realtimeSessionId": "realtime-1"}}
    lease.realtime_session_id = "realtime-1"
    lease.observe(closed)
    await disconnecting

    assert lease.state == "closed"
    assert runtime.voice_lease is None
    assert not registry.owner_busy((1, 2, "main"))


def test_detached_lease_expires_and_does_not_block_reacquire():
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.last_activity -= 1
    assert not registry.owner_busy((1, 2, "main"))
    replacement = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    assert replacement is not lease


@pytest.mark.asyncio
async def test_expired_cleanup_stops_only_its_owned_realtime_and_releases_binding():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")

    async def stop_realtime():
        lease.observe({"method": "thread/realtime/closed", "params": {
            "realtimeSessionId": "realtime-1"}})
        return {}

    runtime.stop_realtime.side_effect = stop_realtime
    lease.last_activity -= 1
    assert registry.owner_busy((1, 2, "main"))
    await wait_for_cleanup(lease)

    assert runtime.stop_realtime.await_count == 1
    assert runtime.voice_lease is None
    assert lease.key not in registry._leases
    assert not registry.owner_busy((1, 2, "main"))


@pytest.mark.asyncio
async def test_pending_cleanup_rejects_reusing_the_runtime_until_it_finishes():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")
    gate = asyncio.Event()

    async def stop_realtime():
        await gate.wait()
        lease.observe({"method": "thread/realtime/closed", "params": {
            "realtimeSessionId": "realtime-1"}})
        return {}

    runtime.stop_realtime.side_effect = stop_realtime
    lease.last_activity -= 1
    registry._prune()
    with pytest.raises(VoiceError, match="正在清理") as acquire_error:
        registry.acquire(lease.key, ("account", 2))
    assert acquire_error.value.code == "voice_cleanup_pending"
    replacement = VoiceLease(lease.key, ("account", 2), _registry=registry)
    with pytest.raises(VoiceError, match="正在清理") as exc_info:
        replacement.bind(runtime)
    assert exc_info.value.code == "voice_cleanup_pending"
    registry.release(replacement)

    gate.set()
    await wait_for_cleanup(lease)
    replacement = registry.acquire(lease.key, ("account", 2))
    replacement.bind(runtime)
    assert runtime.voice_lease is replacement


@pytest.mark.asyncio
async def test_replaced_runtime_binding_prevents_old_cleanup_stop():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")
    lease.last_activity -= 1
    registry._prune()

    replacement = VoiceLease(lease.key, ("account", 2), _registry=registry)
    runtime.voice_lease = replacement
    runtime.voice_lease_generation = replacement.connection_id
    await wait_for_cleanup(lease)

    assert runtime.stop_realtime.await_count == 0
    assert runtime.voice_lease is replacement
    registry.release(replacement)


@pytest.mark.asyncio
async def test_cleanup_completion_allows_runtime_reacquire():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    lease.last_activity -= 1
    registry._prune()

    await wait_for_cleanup(lease)
    replacement = registry.acquire(lease.key, ("account", 2))
    replacement.bind(runtime)
    assert runtime.voice_lease is replacement


@pytest.mark.asyncio
async def test_expired_cleanup_retains_active_voice_task_protection():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry(ttl=.01)
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    runtime.voice_task_active = True
    lease.last_activity -= 1
    registry._prune()

    assert registry._tasks[(1, 2, "main")] is runtime
    assert runtime.stop_realtime.await_count == 0
    assert registry.owner_busy((1, 2, "main"))

    runtime.voice_task_active = False
    registry._prune()
    await wait_for_cleanup(lease)
    assert (1, 2, "main") not in registry._tasks
    assert runtime.stop_realtime.await_count == 0
    assert runtime.voice_lease is None


@pytest.mark.asyncio
async def test_closed_lease_clears_binding_while_retaining_active_task_protection():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry()
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    runtime.voice_task_active = True
    lease.state = "closed"
    lease.detach()

    assert runtime.voice_lease is None
    assert registry.owner_busy((1, 2, "main"))

    runtime.voice_task_active = False
    replacement = registry.acquire(lease.key, ("account", 2))
    replacement.bind(runtime)
    assert runtime.voice_lease is replacement


@pytest.mark.asyncio
async def test_repeated_release_disconnect_and_runtime_close_are_idempotent():
    runtime = FakeRuntime()
    registry = VoiceLeaseRegistry()
    lease = registry.acquire((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")

    async def stop_realtime():
        lease.observe({"method": "thread/realtime/closed", "params": {}})
        return {}

    runtime.stop_realtime.side_effect = stop_realtime
    await lease.disconnect()
    await lease.disconnect()
    registry.release(lease)
    registry.release(lease)
    lease.observe({"method": "runtime/closed", "params": {}})
    lease.observe({"method": "runtime/closed", "params": {}})

    assert runtime.stop_realtime.await_count == 1
    assert runtime.voice_lease is None
    assert not registry.owner_busy((1, 2, "main"))
