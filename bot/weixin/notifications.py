"""Durable final-reply delivery for Weixin private chats."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from bot.channel_notifications import (
    CompletionNotification,
    register_channel_notifier,
    unregister_channel_notifier,
)
from bot.telegram.ui import context_left

from .client import WeixinError
from .state import WeixinState

logger = logging.getLogger(__name__)
MAX_MESSAGE_LENGTH = 2000
MAX_BACKOFF_SECONDS = 60.0


def split_weixin_text(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text without changing Markdown or emitting empty messages."""
    value = str(text or "")
    if not value:
        return [""]
    return [value[index:index + limit] for index in range(0, len(value), max(1, limit))]


def format_weixin_result(alias: str, content: str, usage: dict[str, Any] | None = None) -> list[str]:
    body = str(content or "").strip() or "任务已完成，没有文本答复。"
    text = f"[{str(alias or '').strip()}]\n\n{body}\n\ncontext left: {context_left(usage)}"
    return split_weixin_text(text)


class WeixinCompletionNotifier:
    """Resolve persisted bindings and deliver each final reply exactly once."""

    def __init__(
        self,
        state: WeixinState,
        client: Any,
        allowed_user_ids: set[str] | frozenset[str] | list[str],
        *,
        schedule_task: Any | None = None,
        account_id: str = "",
    ) -> None:
        self.state = state
        self.client = client
        self.allowed_user_ids = frozenset(str(item).strip() for item in allowed_user_ids if str(item).strip())
        self.account_id = str(account_id or getattr(client, "account_id", "") or "").strip()
        self._schedule_task = schedule_task
        self._retry_tasks: dict[str, asyncio.Task[Any]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    def register(self) -> None:
        register_channel_notifier("weixin", self, key=self.account_id or "default")

    def unregister(self) -> None:
        unregister_channel_notifier("weixin", self, key=self.account_id or "default")

    def _schedule(self, coroutine, *, name: str) -> asyncio.Task[Any]:
        if self._schedule_task is not None:
            return self._schedule_task(coroutine, name=name)
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _schedule_retry(self, delivery_id: str, delay: float) -> None:
        existing = self._retry_tasks.get(delivery_id)
        current = asyncio.current_task()
        if existing is not None and existing is not current and not existing.done():
            return
        if existing is current:
            self._retry_tasks.pop(delivery_id, None)

        async def retry() -> None:
            await asyncio.sleep(max(0.0, delay))
            await self._deliver_persisted(delivery_id)

        self._retry_tasks[delivery_id] = self._schedule(retry(), name=f"weixin-delivery-{delivery_id}")

    @staticmethod
    def _retry_delay(attempts: int, error: Any) -> float:
        try:
            retry_after = float(getattr(error, "retry_after", 0) or 0)
        except (TypeError, ValueError):
            retry_after = 0
        return retry_after or min(MAX_BACKOFF_SECONDS, 2 ** min(max(attempts - 1, 0), 6))

    async def close(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._retry_tasks.clear()

    def _notification_key(self, completion: CompletionNotification, peer_id: str) -> str:
        identity = str(
            completion.terminal_at
            or completion.endless_completion_token
            or completion.endless_group_id
            or completion.turn_id
        ).strip()
        return f"completion:{completion.turn_id}:{peer_id}:{identity}"

    def _recipient_bindings(self, completion: CompletionNotification) -> list[dict[str, Any]]:
        records = self.state.list_bound_peers(
            completion.alias,
            completion.agent_id,
            completion.conversation_id,
        )
        result: list[dict[str, Any]] = []
        for record in records:
            peer_id = str(record.get("peer_id") or "").strip()
            if not peer_id or (self.allowed_user_ids and peer_id not in self.allowed_user_ids):
                continue
            if completion.source_channel == "weixin" and peer_id == str(completion.source_external_id or "").strip():
                continue
            result.append(record)
        return result

    async def notify_completion(self, completion: CompletionNotification, **_kwargs: Any) -> list[str]:
        if not completion.turn_id:
            return []
        identifiers: list[str] = []
        for record in self._recipient_bindings(completion):
            peer_id = str(record.get("peer_id") or "").strip()
            key = self._notification_key(completion, peer_id)
            identifiers.append(key)
            if self.state.get_delivery(key) is None:
                parts = format_weixin_result(completion.alias, completion.content, completion.context_usage)
                self.state.create_delivery(
                    key,
                    peer_id,
                    parts,
                    alias=completion.alias,
                    agent_id=completion.agent_id,
                    conversation_id=completion.conversation_id,
                    turn_id=completion.turn_id,
                    assistant_message_id=completion.assistant_message_id,
                )
            try:
                await self._deliver_persisted(key)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - delivery boundary
                logger.warning("微信最终回复投递失败 key=%s (%s)", key, type(exc).__name__)
        return identifiers

    async def deliver_direct(
        self,
        peer_id: str,
        parts: list[str],
        *,
        delivery_id: str,
        alias: str = "",
        conversation_id: str = "",
        turn_id: str = "",
        assistant_message_id: str = "",
    ) -> None:
        if self.state.get_delivery(delivery_id) is None:
            self.state.create_delivery(
                delivery_id,
                peer_id,
                parts,
                alias=alias,
                conversation_id=conversation_id,
                turn_id=turn_id,
                assistant_message_id=assistant_message_id,
            )
        await self._deliver_persisted(delivery_id)

    async def _deliver_persisted(self, delivery_id: str) -> None:
        try:
            record = self.state.get_delivery(delivery_id)
            if record is None or record.get("status") == "sent":
                return
            peer_id = str(record.get("peer_id") or "").strip()
            parts = record.get("part_records") or []
            for part in parts:
                if part.get("status") == "sent":
                    continue
                due = float(part.get("retry_at") or 0)
                if math.isfinite(due) and due > time.time():
                    self._schedule_retry(delivery_id, due - time.time())
                    return
                try:
                    response = await self.client.send_message(
                        peer_id,
                        str(part.get("text") or ""),
                        context_token=self.state.get_context_token(peer_id),
                    )
                    if isinstance(response, dict):
                        next_token = response.get("context_token") or response.get("contextToken")
                        if isinstance(next_token, str) and next_token.strip():
                            self.state.set_context_token(peer_id, next_token)
                    self.state.mark_delivery_part_sent(delivery_id, int(part.get("part_index") or 0))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    retryable = bool(getattr(exc, "retryable", False)) or isinstance(exc, (ConnectionError, TimeoutError))
                    attempts = int(part.get("attempts") or 0) + 1
                    delay = self._retry_delay(attempts, exc)
                    self.state.mark_delivery_part_failed(
                        delivery_id,
                        int(part.get("part_index") or 0),
                        type(exc).__name__,
                        retry_at=time.time() + delay if retryable else float("inf"),
                    )
                    if retryable:
                        self._schedule_retry(delivery_id, delay)
                    logger.warning("微信消息投递失败 key=%s part=%s (%s)", delivery_id, part.get("part_index"), type(exc).__name__)
                    return
        finally:
            task = self._retry_tasks.get(delivery_id)
            if task is asyncio.current_task():
                self._retry_tasks.pop(delivery_id, None)

    async def recover(self) -> None:
        for record in self.state.list_incomplete_deliveries():
            delivery_id = str(record.get("delivery_id") or "")
            retry_at = float(record.get("retry_at") or 0)
            if retry_at > time.time() and math.isfinite(retry_at):
                self._schedule_retry(delivery_id, retry_at - time.time())
            else:
                await self._deliver_persisted(delivery_id)


__all__ = ["MAX_MESSAGE_LENGTH", "WeixinCompletionNotifier", "format_weixin_result", "split_weixin_text"]
