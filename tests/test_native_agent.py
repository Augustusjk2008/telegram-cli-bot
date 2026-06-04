from __future__ import annotations

from pathlib import Path

import pytest

from bot.models import BotProfile, UserSession
from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.client import NativeAgentClient, NativeAgentServerRef, parse_sse_block
from bot.native_agent.events import is_relevant_event, unwrap_event
from bot.native_agent.service import NativeAgentService
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


def test_parse_sse_block_and_unwrap_global_event():
    raw = parse_sse_block(
        "event: message.part.updated\n"
        'data: {"directory":"/repo","payload":{"type":"message.part.updated","sessionID":"s1","part":{"id":"p1","type":"text","delta":"你好"}}}\n'
    )

    assert raw is not None
    event = unwrap_event(raw)

    assert event is not None
    assert event.type == "message.part.updated"
    assert event.directory == "/repo"
    assert is_relevant_event(event, session_id="s1", cwd="/repo")


def test_native_agent_aggregator_delta_replace_and_removed():
    aggregator = NativeAgentAggregator(user_message_id="u1")

    first = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "delta": "你"}}))
    second = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "delta": "好"}}))
    replace = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "text": "完成"}}))
    removed = aggregator.apply(unwrap_event({"type": "message.part.removed", "sessionID": "s1", "part": {"id": "p1"}}))

    assert first.delta == "你"
    assert second.delta == "好"
    assert replace.snapshot == "完成"
    assert removed.snapshot == ""


def test_native_agent_permission_event_uses_official_properties_shape():
    aggregator = NativeAgentAggregator(user_message_id="u1")
    event = unwrap_event({
        "type": "permission.updated",
        "properties": {
            "id": "perm-1",
            "sessionID": "sess-1",
            "title": "允许读取文件？",
        },
    })

    assert event is not None
    assert is_relevant_event(event, session_id="sess-1", cwd="")
    result = aggregator.apply(event)

    assert result.status == "允许读取文件？"
    assert result.trace[0]["payload"]["id"] == "perm-1"
    assert aggregator.permission_pending["perm-1"]["sessionID"] == "sess-1"


@pytest.mark.asyncio
async def test_native_agent_client_reply_permission_uses_official_permissions_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_request_json(self, method, path, *, json_body=None):
        captured.update({"method": method, "path": path, "json_body": json_body})
        return {"ok": True}

    monkeypatch.setattr(NativeAgentClient, "_request_json", fake_request_json)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))

    await client.reply_permission("sess-1", "perm-1", approved=True)

    assert captured["method"] == "POST"
    assert captured["path"] == "/session/sess-1/permissions/perm-1"
    assert captured["json_body"]["response"] == "once"


@pytest.mark.asyncio
async def test_native_agent_service_stream_persists_done_message(tmp_path: Path):
    class FakeClient:
        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None):
            assert session_id == "sess-1"
            assert text == "你好"
            assert message_id
            return {}

        async def events(self, *, global_events=True):
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "回"},
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "答"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "回答"}]

    class FakeHandle:
        key = "native-key"

        def client(self):
            return FakeClient()

    class FakeManager:
        async def get_server(self, **_kwargs):
            return FakeHandle()

        async def get_existing(self, _key):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "回答"
    assert done["message"]["meta"]["native_source"]["provider"] == "native_agent"
    assert session.native_agent_session_id == "sess-1"
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_native_agent_stream_starts_separate_conversation_from_cli(tmp_path: Path):
    class FakeClient:
        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None):
            return {}

        async def events(self, *, global_events=True):
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "原生"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "原生"}]

    class FakeHandle:
        key = "native-key"

        def client(self):
            return FakeClient()

    class FakeManager:
        async def get_server(self, **_kwargs):
            return FakeHandle()

        async def get_existing(self, _key):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", cli_type="codex", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    cli_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="CLI",
        native_provider="codex",
    )
    history.complete_turn(cli_handle, content="CLI 回复", completion_state="completed", native_session_id="thread-1")
    cli_conversation_id = session.active_conversation_id

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["message"]["meta"]["native_source"]["provider"] == "native_agent"
    assert session.active_conversation_id != cli_conversation_id
    conversations = ChatStore(tmp_path).list_conversations(
        bot_id=1,
        user_id=1001,
        agent_id="main",
        working_dir=str(tmp_path),
        limit=10,
    )
    providers = {item["native_provider"] for item in conversations}
    assert providers == {"codex", "native_agent"}
