from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.notification_service import ChatNotificationService
from bot.web.pushplus_client import PushPlusClient
from bot.web.server import WebApiServer


@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(temp_dir),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


class FakeTunnelService:
    def __init__(self, public_url: str = "") -> None:
        self.public_url = public_url

    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "manual" if self.public_url else "disabled",
            "status": "running" if self.public_url else "stopped",
            "source": "manual_config" if self.public_url else "disabled",
            "public_url": self.public_url,
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


class FakePushPlus:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, title: str, content: str, *, topic: str | None = None) -> bool:
        self.calls.append({"title": title, "content": content, "topic": topic})
        return True


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_pushplus_client_disabled_is_noop() -> None:
    client = PushPlusClient(enabled=False, token="", api_url="http://127.0.0.1:1/send")

    ok = await client.send("标题", "内容")

    assert ok is False


@pytest.mark.asyncio
async def test_pushplus_client_posts_expected_payload() -> None:
    captured: list[dict[str, Any]] = []

    async def handle(request: web.Request) -> web.Response:
        captured.append(await request.json())
        return web.json_response({"code": 200, "msg": "ok"})

    app = web.Application()
    app.router.add_post("/send", handle)

    async with TestServer(app) as server:
        client = PushPlusClient(
            enabled=True,
            token="push-token",
            topic="default-topic",
            template="markdown",
            channel="wechat",
            api_url=str(server.make_url("/send")),
            timeout_seconds=2,
        )

        ok = await client.send("聊天已完成", "### 内容", topic="override-topic")

    assert ok is True
    assert captured == [
        {
            "token": "push-token",
            "title": "聊天已完成",
            "content": "### 内容",
            "topic": "override-topic",
            "template": "markdown",
            "channel": "wechat",
        }
    ]


@pytest.mark.asyncio
async def test_notification_service_sends_ws_and_skips_pushplus() -> None:
    pushplus = FakePushPlus()
    service = ChatNotificationService(pushplus=pushplus, enabled=True)
    ws = FakeWebSocket()
    service.register(account_id="alice", user_id=1001, username="alice", ws=ws)

    await service.notify_chat_completed(
        account_id="alice",
        user_id=1001,
        bot_alias="main",
        agent_id="main",
        conversation_id="conv-1",
        message_id="msg-1",
        status="success",
        preview="完成内容",
        elapsed_seconds=3,
    )
    await service.drain_push_tasks()

    assert len(ws.sent) == 1
    event = ws.sent[0]
    assert event["type"] == "chat_completed"
    assert event["botAlias"] == "main"
    assert event["conversationId"] == "conv-1"
    assert event["status"] == "success"
    assert event["preview"] == "完成内容"
    assert event["elapsedSeconds"] == 3
    assert pushplus.calls == []


@pytest.mark.asyncio
async def test_notification_service_offline_uses_pushplus_once_per_dedupe_key() -> None:
    pushplus = FakePushPlus()
    service = ChatNotificationService(pushplus=pushplus, enabled=True)

    for _ in range(2):
        await service.notify_chat_completed(
            account_id="alice",
            user_id=1001,
            bot_alias="main",
            agent_id="main",
            conversation_id="conv-1",
            message_id="msg-1",
            status="success",
            preview="完成内容",
            elapsed_seconds=3,
        )
    await service.drain_push_tasks()

    assert len(pushplus.calls) == 1
    assert pushplus.calls[0]["title"] == "聊天已完成"
    assert "- Bot: main" in pushplus.calls[0]["content"]
    assert "完成内容" in pushplus.calls[0]["content"]
    assert "打开聊天" not in pushplus.calls[0]["content"]


@pytest.mark.asyncio
async def test_notification_service_pushplus_includes_chat_link_when_url_present() -> None:
    pushplus = FakePushPlus()
    service = ChatNotificationService(pushplus=pushplus, enabled=True)

    await service.notify_chat_completed(
        account_id="alice",
        user_id=1001,
        bot_alias="main",
        agent_id="main",
        conversation_id="conv-1",
        message_id="msg-1",
        status="success",
        preview="完成内容",
        elapsed_seconds=3,
        url="https://demo.trycloudflare.com/bots/main/chat?conversation_id=conv-1",
    )
    await service.drain_push_tasks()

    assert "[打开聊天](https://demo.trycloudflare.com/bots/main/chat?conversation_id=conv-1)" in pushplus.calls[0]["content"]


@pytest.mark.asyncio
async def test_notification_service_expired_ws_falls_back_to_pushplus() -> None:
    now = 100.0
    pushplus = FakePushPlus()
    service = ChatNotificationService(
        pushplus=pushplus,
        enabled=True,
        heartbeat_ttl_seconds=10,
        now=lambda: now,
    )
    ws = FakeWebSocket()
    service.register(account_id="alice", user_id=1001, username="alice", ws=ws)
    now = 111.0

    await service.notify_chat_completed(
        account_id="alice",
        user_id=1001,
        bot_alias="main",
        agent_id="main",
        conversation_id="conv-2",
        message_id="msg-2",
        status="success",
        preview="离线内容",
        elapsed_seconds=2,
    )
    await service.drain_push_tasks()

    assert ws.sent == []
    assert len(pushplus.calls) == 1


@pytest.mark.asyncio
async def test_notifications_websocket_requires_auth(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with pytest.raises(WSServerHandshakeError):
                await client.ws_connect("/api/notifications/ws")

            ws = await client.ws_connect("/api/notifications/ws?token=secret")
            hello = await ws.receive_json()
            await ws.send_json({"type": "heartbeat"})
            ack = await ws.receive_json()
            await ws.close()

    assert hello["type"] == "hello"
    assert ack["type"] == "heartbeat_ack"


@pytest.mark.asyncio
async def test_notification_settings_returns_pushplus_status_without_token(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    server = WebApiServer(web_manager)
    server._notification_service.pushplus.enabled = True
    server._notification_service.pushplus.token = "secret-token"
    server._notification_service.pushplus.topic = "team"
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/notifications/settings")
            payload = await resp.json()

    assert resp.status == 200
    assert payload["ok"] is True
    assert payload["data"] == {
        "chat_completion_notify_enabled": True,
        "pushplus_enabled": True,
        "pushplus_configured": True,
        "pushplus_topic_configured": True,
    }
    assert "secret-token" not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_pushplus_test_endpoint_sends_configured_push(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    pushplus = FakePushPlus()
    pushplus.enabled = True
    pushplus.token = "secret-token"
    server = WebApiServer(web_manager)
    server._notification_service.pushplus = pushplus
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/notifications/pushplus/test")
            payload = await resp.json()

    assert resp.status == 200
    assert payload["ok"] is True
    assert payload["data"] == {"sent": True}
    assert pushplus.calls == [{
        "title": "PushPlus 测试推送",
        "content": "### PushPlus 测试推送\n\n如果你收到这条消息，说明 PushPlus 已可用。",
        "topic": None,
    }]


@pytest.mark.asyncio
async def test_pushplus_test_endpoint_rejects_disabled_pushplus(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    pushplus = FakePushPlus()
    pushplus.enabled = False
    pushplus.token = "secret-token"
    server = WebApiServer(web_manager)
    server._notification_service.pushplus = pushplus
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/notifications/pushplus/test")
            payload = await resp.json()

    assert resp.status == 409
    assert payload["ok"] is False
    assert payload["error"]["code"] == "pushplus_disabled"
    assert pushplus.calls == []


@pytest.mark.asyncio
async def test_post_chat_notifies_after_success(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_run_chat(_manager, _alias, _user_id, _message, **_kwargs):
        return {
            "output": "回复内容",
            "elapsed_seconds": 4,
            "message": {
                "id": "msg-1",
                "role": "assistant",
                "content": "回复内容",
                "state": "done",
                "meta": {"completion_state": "completed"},
            },
            "session": {"active_conversation_id": "conv-1"},
        }

    server = WebApiServer(web_manager)
    server._notification_service.notify_chat_completed = AsyncMock()
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.run_chat", fake_run_chat):
                resp = await client.post("/api/bots/main/chat", json={"message": "hi"})
            await asyncio.gather(*list(server._notification_tasks), return_exceptions=True)

    assert resp.status == 200
    server._notification_service.notify_chat_completed.assert_awaited_once()
    kwargs = server._notification_service.notify_chat_completed.await_args.kwargs
    assert kwargs["account_id"] == "local-admin"
    assert kwargs["bot_alias"] == "main"
    assert kwargs["conversation_id"] == "conv-1"
    assert kwargs["message_id"] == "msg-1"
    assert kwargs["status"] == "success"
    assert kwargs["preview"] == "回复内容"
    assert kwargs["elapsed_seconds"] == 4
    assert kwargs["url"] == ""


@pytest.mark.asyncio
async def test_post_chat_notification_url_uses_public_tunnel_url(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_run_chat(_manager, _alias, _user_id, _message, **_kwargs):
        return {
            "output": "回复内容",
            "elapsed_seconds": 4,
            "message": {
                "id": "msg-1",
                "content": "回复内容",
                "meta": {"completion_state": "completed"},
            },
            "session": {"active_conversation_id": "conv 1"},
        }

    server = WebApiServer(
        web_manager,
        tunnel_service=FakeTunnelService("https://demo.trycloudflare.com/"),
    )
    server._notification_service.notify_chat_completed = AsyncMock()
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.run_chat", fake_run_chat):
                resp = await client.post("/api/bots/main/chat", json={"message": "hi"})
            await asyncio.gather(*list(server._notification_tasks), return_exceptions=True)

    assert resp.status == 200
    kwargs = server._notification_service.notify_chat_completed.await_args.kwargs
    assert kwargs["url"] == "https://demo.trycloudflare.com/bots/main/chat?conversation_id=conv+1"


@pytest.mark.asyncio
async def test_post_chat_stream_notifies_after_client_disconnect(web_manager: MultiBotManager) -> None:
    server = WebApiServer(web_manager)
    request = MagicMock()
    request.query = {}
    consumed: list[str] = []

    async def fake_stream_chat(_manager, alias, _user_id, _message, **_kwargs):
        for event in [
            {"type": "meta", "alias": alias},
            {"type": "status", "elapsed_seconds": 1},
            {
                "type": "done",
                "output": "ok",
                "elapsed_seconds": 2,
                "message": {
                    "id": "msg-2",
                    "content": "ok",
                    "state": "done",
                    "meta": {"completion_state": "completed"},
                },
                "session": {"active_conversation_id": "conv-2"},
            },
        ]:
            consumed.append(event["type"])
            yield event

    class FakeStreamResponse:
        def __init__(self, *args, **kwargs) -> None:
            self.write_calls = 0

        async def prepare(self, req) -> None:
            return None

        async def write(self, data) -> None:
            self.write_calls += 1
            if self.write_calls == 2:
                raise ClientConnectionResetError("closing")

        async def write_eof(self) -> None:
            raise AssertionError("write_eof should not run after disconnect")

    server._notification_service.notify_chat_completed = AsyncMock()
    auth = AuthContext(user_id=1001, token_used=False, account_id="local-admin", username="127.0.0.1")

    with patch.object(server, "_with_capability", AsyncMock(return_value=auth)), \
         patch.object(server, "_manager_alias", return_value="main"), \
         patch.object(server, "_parse_json", AsyncMock(return_value={"message": "hi"})), \
         patch("bot.web.server.stream_chat", fake_stream_chat), \
         patch("bot.web.server.web.StreamResponse", FakeStreamResponse):
        await server.post_chat_stream(request)  # type: ignore[arg-type]
    await asyncio.gather(*list(server._notification_tasks), return_exceptions=True)

    assert consumed == ["meta", "status", "done"]
    server._notification_service.notify_chat_completed.assert_awaited_once()
    kwargs = server._notification_service.notify_chat_completed.await_args.kwargs
    assert kwargs["conversation_id"] == "conv-2"
    assert kwargs["message_id"] == "msg-2"
    assert kwargs["status"] == "success"
