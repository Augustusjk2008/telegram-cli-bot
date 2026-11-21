from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import chat_sync_events
from bot.web.chat_history_service import StreamingPersistenceBuffer
from bot.web.chat_sync_events import (
    CHAT_SYNC_REASON_CONVERSATION,
    CHAT_SYNC_REASON_PROGRESS,
    CHAT_SYNC_REASON_TURN_FINISHED,
    publish_chat_sync,
    set_chat_sync_publisher,
)
from bot.web.notification_service import ChatNotificationService
from bot.web.permission_store import BotPermissionStore
from bot.web.server import WebApiServer


class _Socket:
    closed = False

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, event: dict) -> None:
        self.sent.append(event)


def _service(**kwargs) -> ChatNotificationService:
    return ChatNotificationService(chat_sync_settle_seconds=0.0, **kwargs)


async def _settle(service: ChatNotificationService, seconds: float = 0.02) -> None:
    await asyncio.sleep(seconds)
    await service.drain_chat_sync()


@pytest.fixture(autouse=True)
def _no_publisher():
    previous = set_chat_sync_publisher(None)
    yield
    set_chat_sync_publisher(previous)


@pytest.mark.asyncio
async def test_chat_sync_reaches_only_connections_that_may_view_the_bot() -> None:
    service = _service()
    allowed, denied, unscoped = _Socket(), _Socket(), _Socket()
    service.register(account_id="alice", user_id=1, username="alice", ws=allowed, can_view_bot=lambda alias: alias == "main")
    service.register(account_id="bob", user_id=2, username="bob", ws=denied, can_view_bot=lambda alias: alias == "other")
    service.register(account_id="carol", user_id=3, username="carol", ws=unscoped)

    service.queue_chat_sync("Main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await _settle(service)

    assert allowed.sent == [{"type": "chat_sync", "botAlias": "main", "agentId": "main", "reason": "turn_finished"}]
    assert denied.sent == [] and unscoped.sent == []
    await service.close()


@pytest.mark.asyncio
async def test_progress_hints_are_coalesced_and_rate_limited_per_session() -> None:
    service = _service(chat_sync_min_interval_seconds=0.2)
    socket = _Socket()
    service.register(account_id="alice", user_id=1, username="alice", ws=socket, can_view_bot=lambda _alias: True)

    for _ in range(5):
        service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)
    await _settle(service)
    assert len(socket.sent) == 1

    # More progress inside the interval is held back, then delivered once.
    for _ in range(5):
        service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)
    service.queue_chat_sync("main", "worker", CHAT_SYNC_REASON_PROGRESS)
    await _settle(service)
    assert [(event["agentId"], event["reason"]) for event in socket.sent] == [("main", "progress"), ("worker", "progress")]
    await _settle(service, 0.25)
    assert [event["agentId"] for event in socket.sent] == ["main", "worker", "main"]
    await service.close()


@pytest.mark.asyncio
async def test_lifecycle_hint_is_not_delayed_behind_rate_limited_progress() -> None:
    service = _service(chat_sync_min_interval_seconds=30.0)
    socket = _Socket()
    service.register(account_id="alice", user_id=1, username="alice", ws=socket, can_view_bot=lambda _alias: True)

    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)
    await _settle(service)
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)
    await _settle(service)

    # The pending progress hint is folded into the prompt lifecycle hint.
    assert [event["reason"] for event in socket.sent] == ["progress", "turn_finished"]
    await service.close()


@pytest.mark.asyncio
async def test_revoked_bot_access_stops_hints_after_the_cache_expires() -> None:
    access = {"main": True}
    service = _service(bot_access_ttl_seconds=0.0)
    socket = _Socket()
    service.register(account_id="alice", user_id=1, username="alice", ws=socket, can_view_bot=lambda alias: access[alias])

    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_CONVERSATION)
    await _settle(service)
    access["main"] = False
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_CONVERSATION)
    await _settle(service)

    assert len(socket.sent) == 1
    await service.close()


@pytest.mark.asyncio
async def test_hints_do_not_depend_on_the_presence_heartbeat_window() -> None:
    clock = {"now": 1000.0}
    service = ChatNotificationService(chat_sync_settle_seconds=0.0, heartbeat_ttl_seconds=75.0, now=lambda: clock["now"])
    socket = _Socket()
    connection = service.register(
        account_id="alice", user_id=1, username="alice", ws=socket, can_view_bot=lambda _alias: True,
    )

    # A page with frozen timers stops sending heartbeats, but its socket is still open
    # and it keeps polling slowly, so it must still receive hints.
    clock["now"] += 600.0
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await _settle(service)
    assert len(socket.sent) == 1

    # A completion notice skips the page as not present, without dropping its open socket.
    notice = await service.notify_chat_completed(account_id="alice", user_id=1, bot_alias="main", message_id="m1")
    assert notice is not None and [event["type"] for event in socket.sent] == ["chat_sync"]
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await _settle(service)
    assert len(socket.sent) == 2
    # Once it reports back it is present again for completion notices as well.
    service.heartbeat(connection)
    await service.notify_chat_completed(account_id="alice", user_id=1, bot_alias="main", message_id="m2")
    assert [event["type"] for event in socket.sent] == ["chat_sync", "chat_sync", "chat_completed"]

    # A closed socket leaves the registry and a late heartbeat does not bring it back.
    socket.closed = True
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await _settle(service)
    service.heartbeat(connection)
    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await _settle(service)
    assert len(socket.sent) == 3
    await service.drain_push_tasks()
    await service.close()


@pytest.mark.asyncio
async def test_a_congested_socket_does_not_delay_hints_for_other_pages() -> None:
    service = _service()
    service.chat_sync_send_timeout_seconds = 0.05

    class _StuckSocket(_Socket):
        async def send_json(self, event: dict) -> None:
            await asyncio.sleep(3600)

    stuck, healthy = _StuckSocket(), _Socket()
    service.register(account_id="alice", user_id=1, username="alice", ws=stuck, can_view_bot=lambda _alias: True)
    service.register(account_id="bob", user_id=2, username="bob", ws=healthy, can_view_bot=lambda _alias: True)

    service.queue_chat_sync("main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
    await asyncio.sleep(0.02)
    assert len(healthy.sent) == 1
    await _settle(service, 0.1)
    # The slow socket only lost that hint; it is still registered for the next one.
    assert service._connections.keys() == {"alice", "bob"}
    await service.close()


def test_publish_without_a_publisher_is_a_no_op_and_failures_never_propagate() -> None:
    publish_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)

    def broken(_alias: str, _agent_id: str, _reason: str) -> None:
        raise RuntimeError("socket layer down")

    set_chat_sync_publisher(broken)
    publish_chat_sync("main", "main", CHAT_SYNC_REASON_PROGRESS)

    received: list[tuple[str, str, str]] = []
    set_chat_sync_publisher(lambda alias, agent_id, reason: received.append((alias, agent_id, reason)))
    publish_chat_sync(" Main ", "", CHAT_SYNC_REASON_PROGRESS)
    publish_chat_sync("", "main", CHAT_SYNC_REASON_PROGRESS)
    assert received == [("main", "main", "progress")]


@pytest.mark.asyncio
async def test_persisted_preview_reports_progress_from_the_flush_thread() -> None:
    reported: list[str] = []
    stored: list[str] = []

    class _History:
        def replace_assistant_preview(self, _handle, preview: str) -> None:
            stored.append(preview)

        def append_trace_events(self, _handle, _events) -> None:
            stored.append("trace")

    buffer = StreamingPersistenceBuffer(
        _History(),
        object(),
        loop=asyncio.get_running_loop(),
        on_preview_persisted=lambda: reported.append(threading.current_thread().name),
    )
    buffer.queue_trace({"kind": "commentary", "summary": "只有过程"})
    await buffer.close()
    assert stored == ["trace"] and reported == []

    buffer.queue_preview("正文预览")
    await buffer.close()
    assert stored == ["trace", "正文预览"] and len(reported) == 1


class _DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    def snapshot(self) -> dict[str, object]:
        return {"mode": "disabled", "status": "stopped", "source": "disabled", "public_url": "",
                "local_url": "http://127.0.0.1:8765", "last_error": "", "pid": None}


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    return WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=_DummyTunnelService())


async def _next_event(ws, event_type: str) -> dict:
    while True:
        payload = await asyncio.wait_for(ws.receive_json(), timeout=5)
        if payload.get("type") == event_type:
            return payload


@pytest.mark.asyncio
async def test_notification_socket_announces_chat_sync_and_forwards_hints_from_worker_threads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    server._notification_service.chat_sync_settle_seconds = 0.0

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            await client.post("/api/auth/guest")
            origin = str(test_server.make_url("/")).rstrip("/")

            # Without the publisher installed, clients must keep their polling cadence.
            async with client.ws_connect("/api/notifications/ws", headers={"Origin": origin}) as ws:
                assert "features" not in await _next_event(ws, "hello")

            server._enable_chat_sync()
            try:
                async with client.ws_connect("/api/notifications/ws", headers={"Origin": origin}) as ws:
                    hello = await _next_event(ws, "hello")
                    assert hello["features"] == ["chat_sync"]

                    # Store writes and CLI readers run on worker threads.
                    await asyncio.to_thread(publish_chat_sync, "main", "main", CHAT_SYNC_REASON_TURN_FINISHED)
                    event = await _next_event(ws, "chat_sync")
                    assert event == {"type": "chat_sync", "botAlias": "main", "agentId": "main", "reason": "turn_finished"}

                    # Guests only see the main Bot; hints for other Bots are not sent to them.
                    publish_chat_sync("team2", "main", CHAT_SYNC_REASON_TURN_FINISHED)
                    publish_chat_sync("main", "worker", CHAT_SYNC_REASON_TURN_FINISHED)
                    event = await _next_event(ws, "chat_sync")
                    assert (event["botAlias"], event["agentId"]) == ("main", "worker")
            finally:
                chat_sync_events.clear_chat_sync_publisher(server._publish_chat_sync)
                server._chat_sync_loop = None
    assert chat_sync_events._publisher is None
