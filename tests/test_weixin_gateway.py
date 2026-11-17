from __future__ import annotations

import asyncio

import pytest

from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import api_service
from bot.weixin.gateway import WeixinGateway
from bot.weixin.state import WeixinState


class FakeWeixinClient:
    token = "secret"
    account_id = "bot@im.bot"

    def __init__(self):
        self.messages = []

    async def send_message(self, peer_id, text, *, context_token=""):
        self.messages.append((peer_id, text, context_token))
        return {"ret": 0}

    async def close(self):
        return None


class FakeHost:
    def __init__(self, *, refusal: str = "") -> None:
        self.refusal = refusal
        self.restart_requests = 0
        self.status = {
            "version": "9.9.9",
            "pid": 4321,
            "uptime_seconds": 3700,
            "busy_reason": "",
            "exposure": {
                "mode": "fixed_public_forward",
                "status": "running",
                "public_url": "https://hub.example/node/n1",
                "heartbeat_status": "online",
                "heartbeat_last_at": "2026-11-15T12:00:00Z",
            },
        }

    async def host_status(self):
        return self.status

    def host_restart_refusal(self):
        return self.refusal

    def request_host_restart(self):
        self.restart_requests += 1
        return self.refusal


def make_message(message_id="1", text="to dev hello", *, peer_id="peer-1", message_type=1, group=False):
    return {
        "message_id": message_id,
        "from_user_id": peer_id,
        "message_type": message_type,
        "is_group": group,
        "context_token": "ctx-1",
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


@pytest.fixture
def gateway(tmp_path):
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        str(tmp_path / "managed_bots.json"),
    )
    manager.managed_profiles["dev"] = BotProfile(
        alias="dev", cli_type="codex", cli_path="codex", working_dir=str(tmp_path),
    )
    state = WeixinState(tmp_path / "weixin.sqlite3", "bot@im.bot")
    instance = WeixinGateway(manager, FakeWeixinClient(), state, {"peer-1"}, account_id="bot@im.bot")
    yield instance
    asyncio.get_event_loop().run_until_complete(instance.stop()) if False else None


@pytest.mark.asyncio
async def test_only_allowlisted_private_text_reaches_shared_chat(gateway, monkeypatch):
    events = [{
        "type": "done", "turn_id": "turn-1", "assistant_message_id": "assistant-1",
        "message": {"id": "assistant-1", "conversation_id": "conversation-1", "content": "answer", "meta": {"completion_state": "completed"}},
    }]
    calls = []

    async def stream(*args, **kwargs):
        calls.append((args, kwargs))
        for event in events:
            yield event

    monkeypatch.setattr(api_service, "stream_chat", stream)
    assert gateway.receive_update(make_message(peer_id="other")) is None
    assert gateway.receive_update(make_message(message_id="2", group=True)) is None
    assert gateway.receive_update(make_message(message_id="3", message_type=2)) is None
    task = gateway.receive_update(make_message(message_id="4"))
    await task
    assert len(calls) == 1
    assert calls[0][0] == (gateway.manager, "dev", chat_session_user_id(None), "hello")
    assert calls[0][1]["source_channel"] == "weixin"
    assert gateway.client.messages[0][0] == "peer-1"
    assert gateway.client.messages[0][2] == "ctx-1"
    assert gateway.state.get_message("4")["status"] == "completed"
    assert gateway.receive_update(make_message(message_id="4")) is None
    await gateway.stop()


@pytest.mark.asyncio
async def test_control_commands_create_new_conversation_and_do_not_start_agent(gateway, monkeypatch):
    calls = []

    async def stream(*args, **kwargs):
        calls.append((args, kwargs))
        if False:
            yield {}

    monkeypatch.setattr(api_service, "stream_chat", stream)
    task = gateway.receive_update(make_message(text="to dev /new"))
    await task
    assert calls == []
    binding = gateway.state.get_binding("peer-1")
    assert binding["alias"] == "dev"
    assert binding["conversation_id"]
    assert "已新建并切换会话" in gateway.client.messages[-1][1]
    await gateway.stop()


@pytest.mark.asyncio
async def test_host_restart_requires_weixin_confirmation(gateway):
    host = FakeHost()
    gateway.host = host

    task = gateway.receive_update(make_message(message_id="host-1", text="/host"))
    await task
    host_status_messages = "\n".join(text for _, text, _ in gateway.client.messages)
    assert "宿主状态" in host_status_messages
    assert "/host restart" in host_status_messages

    task = gateway.receive_update(make_message(message_id="host-2", text="/host restart"))
    await task
    assert host.restart_requests == 0
    assert "确认重启后端" in gateway.client.messages[-1][1]

    task = gateway.receive_update(make_message(message_id="host-3", text="/host restart confirm"))
    await task
    assert host.restart_requests == 1
    assert "已请求重启后端" in gateway.client.messages[-1][1]
    await gateway.stop()


@pytest.mark.asyncio
async def test_host_restart_confirmation_expires(gateway):
    host = FakeHost()
    gateway.host = host
    gateway._host_restart_confirmations["peer-1"] = 0.0

    task = gateway.receive_update(make_message(message_id="host-expired", text="/host restart confirm"))
    await task

    assert host.restart_requests == 0
    assert "没有待确认的重启请求" in gateway.client.messages[-1][1]
    await gateway.stop()
