from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from aiohttp import web

from bot.config import PUSHPLUS_PREVIEW_CHARS
from bot.web.pushplus_client import PushPlusClient

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class NotificationConnection:
    account_id: str
    user_id: int
    username: str
    ws: web.WebSocketResponse
    connected_at: float
    last_seen_at: float
    presence: dict[str, Any] = field(default_factory=dict)


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

    def register(
        self,
        *,
        account_id: str,
        user_id: int,
        username: str,
        ws: web.WebSocketResponse,
    ) -> NotificationConnection:
        now = self._now()
        connection = NotificationConnection(
            account_id=str(account_id or "legacy-default"),
            user_id=int(user_id),
            username=str(username or ""),
            ws=ws,
            connected_at=now,
            last_seen_at=now,
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
            else:
                stale.append(connection)
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
            "completedAt": datetime.now(UTC).isoformat(),
            "url": str(url or ""),
        }
        if elapsed_seconds is not None:
            try:
                event["elapsedSeconds"] = round(float(elapsed_seconds), 1)
            except (TypeError, ValueError):
                pass
        return event

    def _build_push_content(self, event: dict[str, Any]) -> str:
        lines = [
            f"### {event.get('title') or '聊天已完成'}",
            "",
            f"- Bot: {event.get('botAlias') or ''}",
            f"- Agent: {event.get('agentId') or 'main'}",
            f"- 状态: {event.get('status') or 'success'}",
        ]
        if "elapsedSeconds" in event:
            lines.append(f"- 耗时: {event.get('elapsedSeconds')}s")
        preview = str(event.get("preview") or "").strip()
        if preview:
            lines.extend(["", "预览:", preview])
        url = str(event.get("url") or "").strip()
        if url:
            lines.extend(["", f"[打开聊天]({url})"])
        return "\n".join(lines)

    async def _send_pushplus(self, event: dict[str, Any]) -> None:
        if self.pushplus is None:
            return
        try:
            await self.pushplus.send(
                str(event.get("title") or "聊天已完成"),
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
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        key = dedupe_key or ":".join(
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
        )
        delivered = 0
        failed: list[NotificationConnection] = []
        for connection in self._active_connections(account_id):
            try:
                await connection.ws.send_json(event)
                delivered += 1
            except Exception as exc:
                logger.warning("通知 WebSocket 投递失败 account=%s error=%s", account_id, exc)
                failed.append(connection)
        for connection in failed:
            self.unregister(connection)
        if delivered == 0:
            self._schedule_pushplus(event)
        return event

    async def close(self) -> None:
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
