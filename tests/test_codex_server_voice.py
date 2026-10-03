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
    lease = VoiceLease((1, 2, "main", "conversation"), ("account", 2))
    lease.bind(runtime)
    await lease.start("v=0\r\n")
    await lease.stop_voice(timeout=.01)
    await lease.stop_voice(timeout=.01)
    assert lease.state == "unknown"
    assert runtime.stop_realtime.await_count == 1
