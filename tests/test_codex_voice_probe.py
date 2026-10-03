import asyncio
import json

import pytest
import pytest_asyncio

from bot.codex_server.client import CodexServerError
from scripts.codex_voice_probe import VoiceProbe, sanitize


class FakeClient:
    def __init__(self):
        self.alive = True
        self._sequence = 0
        self.calls = []
        self.incoming = asyncio.Queue()

    async def request(self, method, params, **kwargs):
        self._sequence += 1
        self.calls.append((method, params))
        if method == "turn/start":
            return {"turn": {"id": "turn-1", "status": "inProgress"}}
        return {}

    async def events(self):
        while self.alive:
            yield await self.incoming.get()

    async def close(self):
        self.alive = False


@pytest_asyncio.fixture
async def probe(tmp_path):
    client = FakeClient()
    result = VoiceProbe(client, tmp_path, tmp_path / "events.jsonl")
    result.thread_id = "thread-1"
    yield result
    await result.close()


def test_sanitize_filters_credentials_media_and_sdp():
    value = sanitize({
        "authorization": "Bearer secret-token",
        "client_secret": "secret",
        "audio": "AAAA",
        "sdp": "v=0\r\na=ice-ufrag:secret",
        "text": "keep this caption",
    })
    assert value["authorization"] == "[redacted]"
    assert value["client_secret"] == "[redacted]"
    assert value["audio"] == "[redacted]"
    assert value["sdp"] == "[redacted]"
    assert value["text"] == "keep this caption"


@pytest.mark.asyncio
async def test_event_recording_keeps_correlation_and_drops_sdp(probe):
    entry = probe.record("app-server", "thread/realtime/sdp", {
        "threadId": "thread-1", "realtimeSessionId": "voice-1", "sdp": "v=0\r\na=ice-pwd:secret",
    })
    assert entry["thread_id"] == "thread-1"
    assert entry["realtime_session_id"] == "voice-1"
    assert entry["data"]["sdp"] == "[redacted]"
    saved = json.loads((probe.log_path).read_text(encoding="utf-8"))
    assert saved["data"]["sdp"] == "[redacted]"


@pytest.mark.asyncio
async def test_text_submission_is_single_and_transcript_does_not_resubmit(probe):
    await probe.command({"op": "text", "text": "read the fixture"})
    assert [method for method, _ in probe.client.calls] == ["turn/start"]

    queue = asyncio.Queue()
    probe.subscribers.add(queue)
    await probe.client.incoming.put({"method": "thread/realtime/transcript/done", "params": {
        "threadId": "thread-1", "role": "user", "text": "a caption only",
    }})
    await asyncio.wait_for(queue.get(), 1)
    await asyncio.sleep(0)
    assert [method for method, _ in probe.client.calls] == ["turn/start"]


@pytest.mark.asyncio
async def test_stop_voice_and_interrupt_use_different_operations(probe):
    probe.ready = True
    probe.voice_state = "started"
    await probe.command({"op": "stop_voice"})
    assert probe.client.calls[-1][0] == "thread/realtime/stop"
    assert all(method != "turn/interrupt" for method, _ in probe.client.calls)

    probe.active_turn_id = "turn-1"
    await probe.command({"op": "interrupt"})
    assert probe.client.calls[-1] == ("turn/interrupt", {"threadId": "thread-1", "turnId": "turn-1"})


@pytest.mark.asyncio
async def test_unknown_text_request_is_not_retried(probe):
    async def fail(method, params, **kwargs):
        probe.client._sequence += 1
        probe.client.calls.append((method, params))
        probe.client.alive = False
        raise CodexServerError("app-server turn/start 超时；请求结果未知，不会重发")

    probe.client.request = fail
    with pytest.raises(CodexServerError, match="不会重发"):
        await probe.command({"op": "text", "text": "submit once"})
    assert [method for method, _ in probe.client.calls] == ["turn/start"]
    assert probe.task_state == "unknown"
