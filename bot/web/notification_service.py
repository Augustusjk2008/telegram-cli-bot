from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from bot.config import PUSHPLUS_PREVIEW_CHARS
from bot.web.chat_sync_events import (
    CHAT_SYNC_REASON_CLUSTER,
    CHAT_SYNC_REASON_CONVERSATION,
    CHAT_SYNC_REASON_PROGRESS,
    CHAT_SYNC_REASON_TURN_FINISHED,
    CHAT_SYNC_REASON_TURN_STARTED,
)
from bot.web.pushplus_client import PushPlusClient

logger = logging.getLogger(__name__)
_CLIENT_DISCONNECT_ERRORS = (
    ClientConnectionResetError,
    ConnectionResetError,
    BrokenPipeError,
)

# Feature names announced in the socket's hello message.
NOTIFICATION_FEATURE_CHAT_SYNC = "chat_sync"
# Later reasons win when several hints for one session are coalesced.
_CHAT_SYNC_REASON_PRIORITY = {
    CHAT_SYNC_REASON_PROGRESS: 1,
    CHAT_SYNC_REASON_CLUSTER: 2,
    CHAT_SYNC_REASON_CONVERSATION: 3,
    CHAT_SYNC_REASON_TURN_STARTED: 4,
    CHAT_SYNC_REASON_TURN_FINISHED: 5,
}
_CHAT_SYNC_LIFECYCLE_REASONS = frozenset({
    CHAT_SYNC_REASON_CONVERSATION,
    CHAT_SYNC_REASON_TURN_STARTED,
    CHAT_SYNC_REASON_TURN_FINISHED,
})


@dataclass(eq=False)
class NotificationConnection:
    account_id: str
    user_id: int
    username: str
    ws: web.WebSocketResponse
    connected_at: float
    last_seen_at: float
    presence: dict[str, Any] = field(default_factory=dict)
    # Decides which Bots this account may see; chat sync hints are only sent for those.
    can_view_bot: Callable[[str], bool] | None = None
    bot_access_cache: dict[str, tuple[bool, float]] = field(default_factory=dict)


class ChatNotificationService:
    def __init__(
        self,
        *,
        pushplus: PushPlusClient | Any | None = None,
        enabled: bool = True,
        heartbeat_ttl_seconds: float = 75.0,
        dedupe_ttl_seconds: float = 600.0,
        preview_chars: int = PUSHPLUS_PREVIEW_CHARS,
        now: Callable[[], float] | None = None,
        chat_sync_min_interval_seconds: float = 1.0,
        chat_sync_settle_seconds: float = 0.05,
        bot_access_ttl_seconds: float = 10.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.pushplus = pushplus
        self.heartbeat_ttl_seconds = max(1.0, float(heartbeat_ttl_seconds or 75.0))
        self.dedupe_ttl_seconds = max(1.0, float(dedupe_ttl_seconds or 600.0))
        self.preview_chars = max(0, int(preview_chars or 0))
        self._now = now or time.monotonic
        self._connections: dict[str, set[NotificationConnection]] = {}
        self._event_seen_at: OrderedDict[str, float] = OrderedDict()
        self._push_tasks: set[asyncio.Task[Any]] = set()
        # Progress hints are limited to one per interval and session; lifecycle hints
        # only wait for the settle delay, which lets the change commit and coalesces bursts.
        self.chat_sync_min_interval_seconds = max(0.0, float(chat_sync_min_interval_seconds))
        self.chat_sync_settle_seconds = max(0.0, float(chat_sync_settle_seconds))
        self.chat_sync_send_timeout_seconds = 10.0
        self.bot_access_ttl_seconds = max(0.0, float(bot_access_ttl_seconds))
        self._chat_sync_pending: dict[tuple[str, str], str] = {}
        self._chat_sync_timers: dict[tuple[str, str], asyncio.TimerHandle] = {}
        self._chat_sync_due_at: dict[tuple[str, str], float] = {}
        self._chat_sync_sent_at: dict[tuple[str, str], float] = {}
        self._chat_sync_tasks: set[asyncio.Task[Any]] = set()

    def register(
        self,
        *,
        account_id: str,
        user_id: int,
        username: str,
        ws: web.WebSocketResponse,
        can_view_bot: Callable[[str], bool] | None = None,
    ) -> NotificationConnection:
        now = self._now()
        connection = NotificationConnection(
            account_id=str(account_id or "legacy-default"),
            user_id=int(user_id),
            username=str(username or ""),
            ws=ws,
            connected_at=now,
            last_seen_at=now,
            can_view_bot=can_view_bot,
        )
        self._connections.setdefault(connection.account_id, set()).add(connection)
        return connection

    def unregister(self, connection: NotificationConnection | None) -> None:
        if connection is None:
            return
        connections = self._connections.get(connection.account_id)
        if not connections:
            return
        connections.discard(connection)
        if not connections:
            self._connections.pop(connection.account_id, None)

    def heartbeat(self, connection: NotificationConnection, presence: dict[str, Any] | None = None) -> None:
        connection.last_seen_at = self._now()
        if isinstance(presence, dict):
            connection.presence = dict(presence)
        # A page whose timers were frozen misses heartbeats and is dropped as stale while its
        # socket stays open; it must count again as soon as it reports back.
        if not bool(getattr(connection.ws, "closed", False)):
            self._connections.setdefault(connection.account_id, set()).add(connection)

    def _is_connection_alive(self, connection: NotificationConnection, now: float) -> bool:
        if bool(getattr(connection.ws, "closed", False)):
            return False
        return now - connection.last_seen_at <= self.heartbeat_ttl_seconds

    def _active_connections(self, account_id: str) -> list[NotificationConnection]:
        now = self._now()
        connections = self._connections.get(str(account_id or ""), set())
        active: list[NotificationConnection] = []
        stale: list[NotificationConnection] = []
        for connection in connections:
            if self._is_connection_alive(connection, now):
                active.append(connection)
            elif bool(getattr(connection.ws, "closed", False)):
                stale.append(connection)
            # An open socket whose page stopped sending heartbeats (frozen timers) is only
            # skipped here: it still receives chat sync hints and counts again once it reports back.
        for connection in stale:
            self.unregister(connection)
        return active

    def _prune_dedupe(self, now: float) -> None:
        while self._event_seen_at:
            _, seen_at = next(iter(self._event_seen_at.items()))
            if now - seen_at <= self.dedupe_ttl_seconds:
                break
            self._event_seen_at.popitem(last=False)

    def _claim_dedupe_key(self, dedupe_key: str) -> bool:
        now = self._now()
        self._prune_dedupe(now)
        if dedupe_key in self._event_seen_at:
            return False
        self._event_seen_at[dedupe_key] = now
        return True

    def _clip_preview(self, preview: str) -> str:
        text = str(preview or "").strip()
        if self.preview_chars <= 0 or len(text) <= self.preview_chars:
            return text
        return text[: self.preview_chars].rstrip() + "..."

    def _build_event(
        self,
        *,
        bot_alias: str,
        agent_id: str,
        conversation_id: str,
        message_id: str,
        status: str,
        preview: str,
        elapsed_seconds: int | float | None,
        url: str,
        dedupe_key: str,
        terminal_at: str,
    ) -> dict[str, Any]:
        normalized_status = "error" if str(status or "").lower() == "error" else "success"
        title = "聊天失败" if normalized_status == "error" else "聊天已完成"
        event: dict[str, Any] = {
            "type": "chat_completed",
            "id": f"ntf_{uuid.uuid4().hex}",
            "dedupeKey": dedupe_key,
            "botAlias": str(bot_alias or ""),
            "agentId": str(agent_id or "main"),
            "conversationId": str(conversation_id or ""),
            "messageId": str(message_id or ""),
            "status": normalized_status,
            "title": title,
            "preview": self._clip_preview(preview),
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "url": str(url or ""),
        }
        if elapsed_seconds is not None:
            try:
                event["elapsedSeconds"] = round(float(elapsed_seconds), 1)
            except (TypeError, ValueError):
                pass
        if str(terminal_at or "").strip():
            event["terminalAt"] = str(terminal_at).strip()
        return event

    def _build_push_title(self, event: dict[str, Any]) -> str:
        bot_alias = str(event.get("botAlias") or "main").strip() or "main"
        status = str(event.get("status") or "success").strip().lower()
        suffix = "聊天失败" if status == "error" else "聊天已完成"
        return f"{bot_alias} 的{suffix}"

    def _build_push_content(self, event: dict[str, Any]) -> str:
        title = self._build_push_title(event)
        lines = [
            f"### {title}",
            "",
            f"- Bot: {event.get('botAlias') or ''}",
            f"- Agent: {event.get('agentId') or 'main'}",
            f"- 状态: {event.get('status') or 'success'}",
        ]
        if "elapsedSeconds" in event:
            lines.append(f"- 耗时: {event.get('elapsedSeconds')}s")
        url = str(event.get("url") or "").strip()
        if url:
            lines.extend(["", f"[打开聊天]({url})"])
        preview = str(event.get("preview") or "").strip()
        if preview:
            lines.extend(["", "预览:", preview])
        return "\n".join(lines)

    async def _send_pushplus(self, event: dict[str, Any]) -> None:
        if self.pushplus is None:
            return
        try:
            await self.pushplus.send(
                self._build_push_title(event),
                self._build_push_content(event),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("PushPlus 通知任务失败: %s", exc)

    def _schedule_pushplus(self, event: dict[str, Any]) -> None:
        task = asyncio.create_task(self._send_pushplus(event))
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    async def drain_push_tasks(self) -> None:
        if self._push_tasks:
            await asyncio.gather(*list(self._push_tasks), return_exceptions=True)

    async def notify_chat_completed(
        self,
        *,
        account_id: str,
        user_id: int,
        bot_alias: str,
        agent_id: str = "main",
        conversation_id: str = "",
        message_id: str = "",
        status: str = "success",
        preview: str = "",
        elapsed_seconds: int | float | None = None,
        url: str = "",
        dedupe_key: str = "",
        terminal_at: str = "",
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        normalized_dedupe_key = str(dedupe_key or "").strip()
        key = normalized_dedupe_key or ":".join(
            [
                str(account_id or ""),
                str(bot_alias or ""),
                str(agent_id or "main"),
                str(conversation_id or ""),
                str(message_id or ""),
                str(status or ""),
            ]
        )
        if not self._claim_dedupe_key(key):
            return None

        event = self._build_event(
            bot_alias=bot_alias,
            agent_id=agent_id,
            conversation_id=conversation_id,
            message_id=message_id,
            status=status,
            preview=preview,
            elapsed_seconds=elapsed_seconds,
            url=url,
            dedupe_key=key,
            terminal_at=terminal_at,
        )
        delivered = 0
        failed: list[NotificationConnection] = []
        for connection in self._active_connections(account_id):
            try:
                await connection.ws.send_json(event)
                delivered += 1
            except _CLIENT_DISCONNECT_ERRORS as exc:
                logger.debug("通知 WebSocket 已断开 account=%s error=%s", account_id, exc)
                failed.append(connection)
            except Exception as exc:
                logger.warning("通知 WebSocket 投递失败 account=%s error=%s", account_id, exc)
                failed.append(connection)
        for connection in failed:
            self.unregister(connection)
        if delivered == 0:
            self._schedule_pushplus(event)
        return event

    def _connection_can_view_bot(self, connection: NotificationConnection, bot_alias: str, now: float) -> bool:
        if connection.can_view_bot is None:
            return False
        cached = connection.bot_access_cache.get(bot_alias)
        if cached is not None and now - cached[1] <= self.bot_access_ttl_seconds:
            return cached[0]
        try:
            allowed = bool(connection.can_view_bot(bot_alias))
        except Exception as exc:
            logger.debug("检查通知连接的 Bot 权限失败 account=%s error=%s", connection.account_id, exc)
            allowed = False
        connection.bot_access_cache[bot_alias] = (allowed, now)
        return allowed

    def queue_chat_sync(self, bot_alias: str, agent_id: str = "main", reason: str = "") -> None:
        """Schedule one coalesced ``chat_sync`` hint for a session. Call on the event loop."""
        alias = str(bot_alias or "").strip().lower()
        if not alias or not self._connections:
            return
        key = (alias, str(agent_id or "main").strip().lower() or "main")
        normalized_reason = str(reason or "")
        pending = self._chat_sync_pending.get(key)
        if pending is None or (
            _CHAT_SYNC_REASON_PRIORITY.get(normalized_reason, 0) >= _CHAT_SYNC_REASON_PRIORITY.get(pending, 0)
        ):
            self._chat_sync_pending[key] = normalized_reason
        loop = asyncio.get_running_loop()
        now = loop.time()
        due_at = now + self.chat_sync_settle_seconds
        if normalized_reason not in _CHAT_SYNC_LIFECYCLE_REASONS:
            due_at = max(due_at, self._chat_sync_sent_at.get(key, float("-inf")) + self.chat_sync_min_interval_seconds)
        timer = self._chat_sync_timers.get(key)
        if timer is not None:
            if due_at >= self._chat_sync_due_at.get(key, float("inf")):
                return
            # A lifecycle hint must not wait behind a rate-limited progress hint.
            timer.cancel()
        self._chat_sync_due_at[key] = due_at
        self._chat_sync_timers[key] = loop.call_later(max(0.0, due_at - now), self._flush_chat_sync, key)

    def _flush_chat_sync(self, key: tuple[str, str]) -> None:
        self._chat_sync_timers.pop(key, None)
        self._chat_sync_due_at.pop(key, None)
        reason = self._chat_sync_pending.pop(key, None)
        if reason is None:
            return
        loop = asyncio.get_running_loop()
        self._chat_sync_sent_at[key] = loop.time()
        if len(self._chat_sync_sent_at) > 512:
            for stale_key in list(self._chat_sync_sent_at)[:256]:
                if stale_key not in self._chat_sync_timers:
                    self._chat_sync_sent_at.pop(stale_key, None)
        event = {"type": "chat_sync", "botAlias": key[0], "agentId": key[1], "reason": reason}
        task = loop.create_task(self._deliver_chat_sync(event))
        self._chat_sync_tasks.add(task)
        task.add_done_callback(self._chat_sync_tasks.discard)

    async def _send_chat_sync(self, connection: NotificationConnection, event: dict[str, Any]) -> bool:
        """Send one hint; False means the socket is gone and should leave the registry."""
        try:
            # One congested socket must not hold back the hint for every other page.
            await asyncio.wait_for(connection.ws.send_json(event), timeout=self.chat_sync_send_timeout_seconds)
        except asyncio.TimeoutError:
            # Still open, only slow: this hint is dropped and the page's fallback poll covers it.
            logger.debug("聊天同步提示投递超时 account=%s", connection.account_id)
        except _CLIENT_DISCONNECT_ERRORS:
            return False
        except Exception as exc:
            logger.debug("聊天同步提示投递失败 account=%s error=%s", connection.account_id, exc)
            return False
        return True

    async def _deliver_chat_sync(self, event: dict[str, Any]) -> int:
        now = self._now()
        # Every open socket gets the hint: the client slows its polling while the socket is
        # open, so the heartbeat presence window used for completion notices does not apply.
        connections = [
            connection
            for account_connections in list(self._connections.values())
            for connection in list(account_connections)
        ]
        closed = [connection for connection in connections if bool(getattr(connection.ws, "closed", False))]
        targets = [
            connection
            for connection in connections
            if not bool(getattr(connection.ws, "closed", False))
            and self._connection_can_view_bot(connection, event["botAlias"], now)
        ]
        results = await asyncio.gather(*(self._send_chat_sync(connection, event) for connection in targets))
        for connection in closed:
            self.unregister(connection)
        for connection, usable in zip(targets, results):
            if not usable:
                self.unregister(connection)
        return sum(1 for usable in results if usable)

    async def drain_chat_sync(self) -> None:
        """Wait for hints that are already being delivered (used by tests)."""
        if self._chat_sync_tasks:
            await asyncio.gather(*list(self._chat_sync_tasks), return_exceptions=True)

    async def close(self) -> None:
        for timer in self._chat_sync_timers.values():
            timer.cancel()
        self._chat_sync_timers.clear()
        self._chat_sync_due_at.clear()
        self._chat_sync_pending.clear()
        sync_tasks = list(self._chat_sync_tasks)
        self._chat_sync_tasks.clear()
        for task in sync_tasks:
            task.cancel()
        if sync_tasks:
            await asyncio.gather(*sync_tasks, return_exceptions=True)
        tasks = list(self._push_tasks)
        self._push_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        connections = [
            connection
            for account_connections in self._connections.values()
            for connection in account_connections
        ]
        self._connections.clear()
        for connection in connections:
            try:
                await connection.ws.close()
            except Exception:
                pass
