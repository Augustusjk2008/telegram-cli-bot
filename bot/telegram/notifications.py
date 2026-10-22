"""Durable Telegram notifications for shared-chat final replies."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bot import config

from .client import TelegramClient, TelegramError
from .state import NAVIGATION_TTL, TelegramState
from .ui import format_broadcast_preview, format_result

logger = logging.getLogger(__name__)
_DELIVERY_MAX_BACKOFF = 60.0


@dataclass(frozen=True)
class TelegramCompletionNotification:
    alias: str
    agent_id: str = "main"
    conversation_id: str = ""
    turn_id: str = ""
    assistant_message_id: str = ""
    content: str = ""
    completion_state: str = "completed"
    context_usage: dict[str, Any] | None = None
    source_chat_id: int | None = None


CompletionNotification = TelegramCompletionNotification

_ACTIVE_NOTIFIERS: dict[str, "TelegramCompletionNotifier"] = {}


def register_completion_notifier(notifier: "TelegramCompletionNotifier") -> None:
    _ACTIVE_NOTIFIERS[str(notifier.bot_id)] = notifier


def unregister_completion_notifier(
    notifier: "TelegramCompletionNotifier | None" = None,
    *,
    bot_id: str | None = None,
) -> None:
    key = str(bot_id or getattr(notifier, "bot_id", "") or "")
    if not key:
        return
    current = _ACTIVE_NOTIFIERS.get(key)
    if notifier is None or current is notifier:
        _ACTIVE_NOTIFIERS.pop(key, None)


def get_active_completion_notifier(bot_id: str | None = None) -> "TelegramCompletionNotifier | None":
    if bot_id:
        return _ACTIVE_NOTIFIERS.get(str(bot_id))
    if not _ACTIVE_NOTIFIERS:
        return None
    return _ACTIVE_NOTIFIERS[next(reversed(_ACTIVE_NOTIFIERS))]


class TelegramDeliveryService:
    """Shared segmented Telegram delivery and retry behavior."""

    @staticmethod
    async def deliver_parts(
        client: TelegramClient,
        record: dict[str, Any],
        parts: list[dict[str, Any]],
        *,
        mark_sent: Callable[[int, int], None],
        mark_failed: Callable[[int, str, float], None],
        schedule_retry: Callable[[float], None],
        retry_delay: Callable[[int, TelegramError], float],
        log_label: str,
    ) -> dict[str, Any] | None:
        last_message: dict[str, Any] | None = None
        for part in parts:
            if part.get("status") == "sent":
                continue
            due = float(part.get("retry_at") or 0)
            if not math.isfinite(due):
                return last_message
            if due > time.time():
                schedule_retry(due - time.time())
                return last_message
            index = int(part["part_index"])
            markup = record.get("reply_markup") if index == len(parts) - 1 else None
            try:
                options = {"parse_mode": record["parse_mode"]} if record.get("parse_mode") else {}
                last_message = await client.send_message(
                    int(record["chat_id"]),
                    str(part["text"]),
                    reply_markup=markup,
                    **options,
                )
                message_id = last_message.get("message_id") if isinstance(last_message, dict) else None
                if type(message_id) is not int:
                    raise TelegramError("sendMessage")
                mark_sent(index, message_id)
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                if exc.retryable:
                    delay = retry_delay(int(part.get("attempts") or 0) + 1, exc)
                    mark_failed(index, str(exc), time.time() + delay)
                    schedule_retry(delay)
                else:
                    mark_failed(index, str(exc), float("inf"))
                logger.warning(
                    "Telegram %s投递失败 key=%s part=%s (%s)",
                    log_label,
                    record.get("notification_key") or record.get("delivery_id") or "",
                    index,
                    type(exc).__name__,
                )
                return last_message
            except Exception as exc:
                retryable = isinstance(exc, (ConnectionError, TimeoutError)) or bool(
                    getattr(exc, "retryable", False)
                )
                if retryable:
                    delay = min(_DELIVERY_MAX_BACKOFF, 2 ** min(int(part.get("attempts") or 0), 6))
                    mark_failed(index, str(exc), time.time() + delay)
                    schedule_retry(delay)
                else:
                    mark_failed(index, str(exc), float("inf"))
                logger.warning(
                    "Telegram %s投递失败 key=%s part=%s (%s)",
                    log_label,
                    record.get("notification_key") or record.get("delivery_id") or "",
                    index,
                    type(exc).__name__,
                )
                return last_message
        return last_message


class TelegramCompletionNotifier:
    """Resolve and durably deliver one final reply to Telegram recipients."""

    def __init__(
        self,
        state: TelegramState,
        client: TelegramClient,
        allowed_user_ids: set[int] | frozenset[int] | list[int],
        *,
        chat_url: Callable[[str, str], str] | None = None,
        broadcast_enabled: bool | None = None,
        schedule_task: Callable[..., asyncio.Task] | None = None,
        markup_factory: Callable[[int, int, str, str], dict[str, Any]] | None = None,
    ):
        self.state = state
        self.client = client
        self.bot_id = str(state.bot_id)
        self.allowed_user_ids = frozenset(int(item) for item in allowed_user_ids)
        self.chat_url = chat_url
        self.broadcast_enabled = broadcast_enabled
        self._schedule_task = schedule_task
        self._markup_factory = markup_factory
        self._retry_tasks: dict[str, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()

    @property
    def is_broadcast_enabled(self) -> bool:
        if self.broadcast_enabled is not None:
            return bool(self.broadcast_enabled)
        return bool(getattr(config, "TELEGRAM_BROADCAST_COMPLETIONS", False))

    async def close(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._retry_tasks.clear()
        self._tasks.clear()

    def _schedule(self, coroutine, *, name: str | None = None) -> asyncio.Task:
        if self._schedule_task is not None:
            return self._schedule_task(coroutine, name=name)
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _schedule_retry(self, notification_key: str, delay: float) -> None:
        existing = self._retry_tasks.get(notification_key)
        current = asyncio.current_task()
        if existing is not None and existing is not current and not existing.done():
            return
        if existing is current:
            self._retry_tasks.pop(notification_key, None)

        async def retry() -> None:
            await asyncio.sleep(max(0.0, delay))
            await self._deliver_persisted(notification_key)

        task = self._schedule(retry(), name=f"telegram-completion-{notification_key}")
        self._retry_tasks[notification_key] = task

    @staticmethod
    def _retry_delay(attempts: int, error: TelegramError) -> float:
        if error.retry_after > 0:
            return float(error.retry_after)
        return min(_DELIVERY_MAX_BACKOFF, 2 ** min(max(attempts - 1, 0), 6))

    def _bound_records(self, completion: TelegramCompletionNotification) -> list[dict[str, Any]]:
        return self.state.list_bound_chats(
            completion.alias,
            completion.agent_id,
            completion.conversation_id,
        )

    def _recipients(
        self,
        completion: TelegramCompletionNotification,
    ) -> list[tuple[int, int, bool, dict[str, Any] | None]]:
        bound_records = self._bound_records(completion)
        bound_by_chat: dict[int, dict[str, Any]] = {}
        for record in bound_records:
            try:
                chat_id = int(record["chat_id"])
                telegram_user_id = int(record.get("telegram_user_id") or chat_id)
            except (TypeError, ValueError):
                continue
            if completion.source_chat_id is not None and chat_id == int(completion.source_chat_id):
                continue
            if self.allowed_user_ids and telegram_user_id not in self.allowed_user_ids and chat_id not in self.allowed_user_ids:
                continue
            bound_by_chat[chat_id] = record

        if not self.is_broadcast_enabled:
            return [
                (chat_id, int(record.get("telegram_user_id") or chat_id), True, record)
                for chat_id, record in sorted(bound_by_chat.items())
            ]

        recipients: list[tuple[int, int, bool, dict[str, Any] | None]] = []
        for user_id in sorted(self.allowed_user_ids):
            chat_id = int(user_id)
            if completion.source_chat_id is not None and chat_id == int(completion.source_chat_id):
                continue
            record = bound_by_chat.get(chat_id)
            recipients.append((chat_id, user_id, record is not None, record))
        return recipients

    def _local_button(
        self,
        label: str,
        action: str,
        user_id: int,
        chat_id: int,
        alias: str,
        conversation_id: str,
    ) -> dict[str, str]:
        token = self.state.new_interaction(
            action,
            user_id,
            chat_id,
            alias,
            conversation_id,
            ttl=NAVIGATION_TTL,
        )
        return {"text": label, "callback_data": token}

    def _local_markup(
        self,
        user_id: int,
        chat_id: int,
        alias: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        if self._markup_factory is not None:
            return self._markup_factory(user_id, chat_id, alias, conversation_id)
        web_url = self.chat_url(alias, conversation_id) if self.chat_url else ""
        web_button = (
            {"text": "打开 Web", "url": web_url}
            if web_url
            else self._local_button("打开 Web（需配置公网地址）", "web", user_id, chat_id, alias, conversation_id)
        )
        return {
            "inline_keyboard": [[
                self._local_button("继续聊", "prompt", user_id, chat_id, alias, conversation_id),
                self._local_button("新会话", "new", user_id, chat_id, alias, conversation_id),
            ], [web_button]],
        }

    async def notify_completion(
        self,
        completion: TelegramCompletionNotification | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if completion is None:
            if "bot_alias" in kwargs and "alias" not in kwargs:
                kwargs["alias"] = kwargs.pop("bot_alias")
            if "final_text" in kwargs and "content" not in kwargs:
                kwargs["content"] = kwargs.pop("final_text")
            if "telegram_origin_chat_id" in kwargs and "source_chat_id" not in kwargs:
                kwargs["source_chat_id"] = kwargs.pop("telegram_origin_chat_id")
            completion = TelegramCompletionNotification(**kwargs)
        if not completion.turn_id:
            logger.warning(
                "跳过缺少 turn_id 的 Telegram 最终回复 alias=%s",
                completion.alias,
            )
            return []
        notification_ids: list[str] = []
        for chat_id, telegram_user_id, bound, record in self._recipients(completion):
            shared_user_id = int(record.get("shared_user_id") or telegram_user_id) if record else telegram_user_id
            key = f"{completion.turn_id}:{chat_id}"
            existing = self.state.get_completion_notification(key)
            if existing is not None:
                notification_ids.append(key)
                try:
                    await self._deliver_persisted(key)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive boundary
                    logger.warning(
                        "Telegram 最终回复投递失败 notification_key=%s (%s)",
                        key,
                        type(exc).__name__,
                    )
                continue
            markup = (
                self._local_markup(
                    telegram_user_id,
                    chat_id,
                    completion.alias,
                    completion.conversation_id,
                )
                if bound and completion.conversation_id
                else None
            )
            parts = format_result(completion.alias, completion.content, completion.context_usage)
            full_parts = None
            preview = (
                format_broadcast_preview(completion.alias, completion.content)
                if self.is_broadcast_enabled and completion.source_chat_id is None else None
            )
            if preview is not None:
                full_parts, parts = parts, [preview]
                token = self.state.new_interaction(
                    "expand", telegram_user_id, chat_id, completion.alias, completion.conversation_id,
                    control={"notification_key": key},
                )
                rows = (markup or {}).get("inline_keyboard", [])
                markup = {"inline_keyboard": [[{"text": "展开全文", "callback_data": token}], *rows]}
            notification_id = self.state.create_completion_notification(
                key,
                chat_id,
                completion.alias,
                parts,
                telegram_user_id=telegram_user_id,
                shared_user_id=shared_user_id,
                agent_id=completion.agent_id,
                conversation_id=completion.conversation_id,
                turn_id=completion.turn_id,
                assistant_message_id=completion.assistant_message_id,
                reply_markup=markup,
                parse_mode="HTML",
                full_parts=full_parts,
            )
            notification_ids.append(notification_id)
            try:
                await self._deliver_persisted(notification_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.warning(
                    "Telegram 最终回复投递失败 notification_key=%s (%s)",
                    notification_id,
                    type(exc).__name__,
                )
        return notification_ids

    async def notify(self, completion: TelegramCompletionNotification | None = None, **kwargs: Any) -> list[str]:
        return await self.notify_completion(completion, **kwargs)

    async def _deliver_persisted(self, notification_key: str) -> dict[str, Any] | None:
        try:
            notification = self.state.get_completion_notification(notification_key)
            if notification is None or notification.get("status") == "sent":
                return None
            parts = notification.get("part_records") or self.state.get_completion_notification_parts(notification_key)
            return await TelegramDeliveryService.deliver_parts(
                self.client,
                notification,
                parts,
                mark_sent=lambda index, message_id: self.state.mark_completion_notification_part_sent(
                    notification_key,
                    index,
                    message_id,
                ),
                mark_failed=lambda index, error, retry_at: self.state.mark_completion_notification_part_failed(
                    notification_key,
                    index,
                    error,
                    retry_at=retry_at,
                ),
                schedule_retry=lambda delay: self._schedule_retry(notification_key, delay),
                retry_delay=self._retry_delay,
                log_label="最终回复",
            )
        finally:
            task = self._retry_tasks.get(notification_key)
            if task is asyncio.current_task():
                self._retry_tasks.pop(notification_key, None)

    async def recover(self) -> None:
        try:
            records = self.state.list_incomplete_completion_notifications()
            for record in records:
                retry_at = float(record.get("retry_at") or 0)
                if not math.isfinite(retry_at):
                    continue
                delay = max(0.0, retry_at - time.time())
                if delay <= 0:
                    await self._deliver_persisted(str(record["notification_key"]))
                else:
                    self._schedule_retry(str(record["notification_key"]), delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram 最终回复恢复失败 (%s)", type(exc).__name__)


TelegramNotificationService = TelegramCompletionNotifier
TelegramFinalReplyNotifier = TelegramCompletionNotifier
get_telegram_completion_notifier = get_active_completion_notifier
register_telegram_completion_notifier = register_completion_notifier
unregister_telegram_completion_notifier = unregister_completion_notifier

