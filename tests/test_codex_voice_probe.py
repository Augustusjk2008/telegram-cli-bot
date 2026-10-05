import asyncio
import json

import pytest
import pytest_asyncio

from bot.codex_server.client import CodexServerError
from scripts.codex_voice_probe import M0_REQUIRED_CHECKS, VoiceProbe, sanitize


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
async def test_validation_summary_starts_incomplete_and_lists_all_missing(probe):
    summary = probe.validation_summary()

    assert summary["status"] == "incomplete"
    assert summary["missing"] == list(M0_REQUIRED_CHECKS)
    assert summary["checks"] == {name: False for name in M0_REQUIRED_CHECKS}
    assert summary["observed"] == {name: 0 for name in M0_REQUIRED_CHECKS}


@pytest.mark.asyncio
async def test_validation_summary_passes_only_after_representative_events(probe):
    events = [
        ("app-server", "thread/realtime/started", {
            "threadId": "thread-1", "realtimeSessionId": "voice-1",
        }),
        ("app-server", "thread/realtime/sdp", {
            "threadId": "thread-1", "sdp": "v=0\r\nm=audio 9",
        }),
        ("browser", "media.microphone_acquired", {"audio_tracks": 1}),
        ("browser", "media.remote_track", {"kind": "audio"}),
        ("browser", "media.audio.playing", {"readyState": 4}),
        ("browser", "conversation.item.input_audio_transcription.completed", {
            "threadId": "thread-1", "transcript": "read the fixture",
        }),
        ("app-server", "turn/started", {
            "threadId": "thread-1", "turn": {"id": "turn-voice", "status": "inProgress"},
        }),
        ("app-server", "item/started", {
            "threadId": "thread-1", "item": {"id": "tool-1", "type": "commandExecution"},
        }),
        ("browser", "response.audio_transcript.done", {
            "threadId": "thread-1", "transcript": "I found the result.",
        }),
        ("app-server", "turn/completed", {
            "threadId": "thread-1", "turn": {"id": "turn-voice", "status": "completed"},
        }),
        ("request", "thread/realtime/stop", {"threadId": "thread-1"}),
        ("response", "thread/realtime/stop", {}),
        ("request", "turn/interrupt", {"threadId": "thread-1", "turnId": "turn-voice"}),
        ("response", "turn/interrupt", {}),
        ("response", "thread/read", {
            "thread": {"id": "thread-1", "turns": [{"id": "turn-voice"}]},
        }),
        ("app-server", "thread/realtime/closed", {"threadId": "thread-1"}),
    ]
    for source, name, data in events:
        probe.record(source, name, data)

    summary = probe.validation_summary()

    assert summary["status"] == "passed"
    assert summary["missing"] == []
    assert all(summary["checks"].values())
    assert all(summary["observed"][name] >= 1 for name in M0_REQUIRED_CHECKS)


@pytest.mark.asyncio
async def test_failed_control_responses_do_not_satisfy_m0_acceptance(probe):
    probe.record("app-server", "thread/realtime/started", {
        "threadId": "thread-1", "realtimeSessionId": "voice-1",
    })
    probe.record("request", "thread/realtime/stop", {"threadId": "thread-1"})
    probe.record("response", "thread/realtime/stop", {"error": "rejected"})
    probe.record("request", "turn/interrupt", {"threadId": "thread-1", "turnId": "turn-1"})
    probe.record("response", "turn/interrupt", {"error": "rejected"})

    summary = probe.validation_summary()

    assert summary["checks"]["stop_voice_requested"] is True
    assert summary["checks"]["interrupt_requested"] is True
    assert summary["checks"]["stop_voice_accepted"] is False
    assert summary["checks"]["interrupt_accepted"] is False
    assert summary["status"] == "incomplete"


@pytest.mark.asyncio
async def test_history_from_another_thread_does_not_satisfy_m0_acceptance(probe):
    probe.record("app-server", "thread/realtime/started", {
        "threadId": "thread-1", "realtimeSessionId": "voice-1",
    })
    probe.record("app-server", "turn/started", {
        "threadId": "thread-1", "turn": {"id": "turn-voice", "status": "inProgress"},
    })
    probe.record("response", "thread/read", {
        "thread": {"id": "other-thread", "turns": [{"id": "turn-voice"}]},
    })

    assert probe.validation_summary()["checks"]["history_read"] is False


@pytest.mark.asyncio
async def test_repeated_evidence_events_count_without_breaking_checks(probe):
    event = {"threadId": "thread-1", "realtimeSessionId": "voice-1"}
    probe.record("app-server", "thread/realtime/started", event)
    probe.record("app-server", "thread/realtime/started", event)

    summary = probe.validation_summary()

    assert summary["checks"]["realtime_started"] is True
    assert summary["observed"]["realtime_started"] == 2
    assert summary["status"] == "incomplete"


@pytest.mark.asyncio
async def test_baseline_text_events_do_not_satisfy_voice_task_checks(probe):
    probe.record("app-server", "turn/started", {
        "threadId": "thread-1", "turn": {"id": "turn-text", "status": "inProgress"},
    })
    probe.record("app-server", "item/started", {
        "threadId": "thread-1", "item": {"id": "tool-text", "type": "commandExecution"},
    })
    probe.record("app-server", "turn/completed", {
        "threadId": "thread-1", "turn": {"id": "turn-text", "status": "completed"},
    })

    summary = probe.validation_summary()

    assert summary["status"] == "incomplete"
    assert not summary["checks"]["turn_started"]
    assert not summary["checks"]["tool_execution"]
    assert not summary["checks"]["turn_completed"]


@pytest.mark.asyncio
async def test_summary_command_is_read_only(probe):
    before = list(probe.client.calls)

    result = await probe.command({"op": "summary"})

    assert result == probe.validation_summary()
    assert probe.client.calls == before


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
async def test_start_voice_selects_avas_compatible_v3(probe):
    probe.ready = True
    await probe.command({"op": "start_voice", "sdp": "v=0\r\n"})
    method, params = probe.client.calls[-1]
    assert method == "thread/realtime/start"
    assert params["version"] == "v3"
    assert params["transport"]["type"] == "webrtc"


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
