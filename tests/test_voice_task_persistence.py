from types import SimpleNamespace

import pytest

from bot.codex_server.voice import VoiceEvents
from bot.models import UserSession
from bot.web.chat_store import ChatTurnHandle
from bot.web.voice_task_persistence import VoiceTaskPersistence


class FakeService:
    def __init__(self):
        self.handle = ChatTurnHandle("conversation", "local-turn", "user-message", "assistant-message")
        self.events = []
        self.completed = []

    def ensure_voice_turn(self, session, **_kwargs):
        return self.handle

    def record_voice_event(self, handle, event):
        self.events.append((handle, dict(event)))
        return True

    def complete_voice_turn(self, handle, **kwargs):
        self.completed.append((handle, dict(kwargs)))
        return {"id": handle.assistant_message_id}


def _session():
    session = UserSession(1, "main", 2, "C:/workspace")
    session.persist_hook = lambda _session: None
    return session


@pytest.mark.asyncio
async def test_voice_task_persistence_is_runtime_owned_and_terminal_is_idempotent():
    runtime = SimpleNamespace(thread_id="thread-1", voice_lease=None, voice_events=VoiceEvents())
    queue = runtime.voice_events.subscribe()
    service = FakeService()
    coordinator = VoiceTaskPersistence(
        service,
        SimpleNamespace(alias="main"),
        _session(),
        "conversation",
        runtime,
    )

    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "hello"},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "codex-turn",
    }})
    await coordinator.observe({"method": "item/userMessage/delta", "params": {
        "threadId": "thread-1", "turnId": "codex-turn", "itemId": "user-item", "delta": "hello",
        "item": {"id": "user-item", "type": "userMessage"},
    }})
    await coordinator.observe({"method": "item/agentMessage/delta", "params": {
        "threadId": "thread-1", "turnId": "codex-turn", "itemId": "assistant-item", "delta": "hi",
        "item": {"id": "assistant-item", "type": "agentMessage"},
    }})
    terminal = {"method": "turn/completed", "params": {
        "threadId": "thread-1", "turnId": "codex-turn", "turn": {"id": "codex-turn", "status": "completed"},
    }}
    await coordinator.observe(terminal)
    await coordinator.observe(terminal)

    assert len(service.events) == 4
    assert len(service.completed) == 1
    assert service.completed[0][1]["completion_state"] == "completed"
    assert service.completed[0][1]["content"] == "hi"
    assert coordinator.state == "completed"
    assert coordinator.transcript_state == "saved"
    assert coordinator.session.is_processing is False
    packets = []
    while not queue.empty():
        packets.append(queue.get_nowait())
    assert any(packet.get("type") == "voice.task" and packet.get("state") == "completed" for packet in packets)


@pytest.mark.asyncio
async def test_unknown_runtime_close_keeps_unknown_state():
    runtime = SimpleNamespace(thread_id="thread-1", voice_lease=None, voice_events=VoiceEvents())
    service = FakeService()
    coordinator = VoiceTaskPersistence(
        service,
        SimpleNamespace(alias="main"),
        _session(),
        "conversation",
        runtime,
    )
    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "hello"},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "codex-turn",
    }})
    await coordinator.close()
    assert coordinator.state == "unknown"
    assert service.completed[0][1]["completion_state"] == "unknown"
    await coordinator.close()
    assert len(service.completed) == 1


@pytest.mark.asyncio
async def test_realtime_captions_do_not_overwrite_delegated_chat_messages():
    runtime = SimpleNamespace(thread_id="thread-1", voice_lease=None, voice_events=VoiceEvents())
    service = FakeService()
    coordinator = VoiceTaskPersistence(
        service,
        SimpleNamespace(alias="main"),
        _session(),
        "conversation",
        runtime,
    )

    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "what model"},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "codex-turn",
    }})
    await coordinator.observe({"method": "item/started", "params": {
        "threadId": "thread-1", "turnId": "codex-turn", "itemId": "user-item",
        "item": {"id": "user-item", "type": "userMessage", "content": [{
            "type": "text",
            "text": "<realtime_delegation><input>what model</input><transcript_delta>assistant: hi</transcript_delta></realtime_delegation>",
        }]},
    }})
    await coordinator.observe({"method": "item/agentMessage/delta", "params": {
        "threadId": "thread-1", "turnId": "codex-turn", "itemId": "assistant-item", "delta": "GPT-6",
        "item": {"id": "assistant-item", "type": "agentMessage"},
    }})
    await coordinator.observe({"method": "thread/realtime/item/started", "params": {
        "threadId": "thread-1", "item": {
            "id": "speech-item", "type": "transcriptSegment", "role": "assistant", "text": "",
        },
    }})
    await coordinator.observe({"method": "thread/realtime/item/transcript/delta", "params": {
        "threadId": "thread-1", "itemId": "speech-item", "delta": "GPT-6",
    }})
    await coordinator.observe({"method": "thread/realtime/transcript/delta", "params": {
        "threadId": "thread-1", "role": "assistant", "delta": "GPT-6",
    }})

    transcript_events = [event for _handle, event in service.events if event.get("transcript_text")]
    assert [(event["role"], event["transcript_text"]) for event in transcript_events] == [
        ("user", "what model"),
        ("assistant", "GPT-6"),
    ]


@pytest.mark.asyncio
async def test_unbound_late_item_does_not_enter_new_voice_turn():
    runtime = SimpleNamespace(thread_id="thread-1", voice_lease=None, voice_events=VoiceEvents())
    service = FakeService()
    coordinator = VoiceTaskPersistence(
        service,
        SimpleNamespace(alias="main"),
        _session(),
        "conversation",
        runtime,
    )

    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "first"},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "turn-1",
    }})
    await coordinator.observe({"method": "turn/completed", "params": {
        "threadId": "thread-1", "turnId": "turn-1", "turn": {"id": "turn-1", "status": "completed"},
    }})
    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "second"},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "turn-2",
    }})
    before = len(service.events)
    await coordinator.observe({"method": "item/agentMessage/delta", "params": {
        "threadId": "thread-1", "itemId": "late-item", "delta": "old response",
        "item": {"id": "late-item", "type": "agentMessage"},
    }})

    assert len(service.events) == before


@pytest.mark.asyncio
async def test_non_voice_turn_events_do_not_create_a_persisted_task():
    runtime = SimpleNamespace(thread_id="thread-1", voice_lease=None, voice_events=VoiceEvents())
    service = FakeService()
    coordinator = VoiceTaskPersistence(
        service,
        SimpleNamespace(alias="main"),
        _session(),
        "conversation",
        runtime,
    )

    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "text-turn",
    }})
    await coordinator.observe({"method": "item/userMessage/delta", "params": {
        "threadId": "thread-1", "turnId": "text-turn", "itemId": "text-item", "delta": "hello",
        "item": {"id": "text-item", "type": "userMessage"},
    }})
    await coordinator.observe({"method": "thread/realtime/itemAdded", "params": {
        "threadId": "thread-1", "item": {"type": "handoff_request", "input_transcript": "   "},
    }})
    await coordinator.observe({"method": "turn/started", "params": {
        "threadId": "thread-1", "turnId": "empty-voice-turn",
    }})

    assert coordinator.handle is None
    assert coordinator.state == "idle"
    assert service.events == []
    assert service.completed == []
