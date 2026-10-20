"""Long polling and final-only delivery through the shared chat service."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot import config
from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.runtime_paths import get_app_data_root
from bot.web import api_service
from bot.web.api_common import WebApiError

from .client import TelegramClient
from .state import TelegramState
from .ui import format_result, help_text, parse_target_text, split_text

logger = logging.getLogger(__name__)


class TelegramGateway:
    def __init__(
        self, manager: MultiBotManager, client: TelegramClient, state: TelegramState,
        allowed_user_ids: set[int],
    ):
        self.manager = manager
        self.client = client
        self.state = state
        self.allowed_user_ids = frozenset(allowed_user_ids)
        self._poll_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        if self._poll_task is None and self.allowed_user_ids:
            self._poll_task = asyncio.create_task(self._poll(), name="telegram-poll")

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self.client.close()
        finally:
            self.state.close()

    async def _poll(self) -> None:
        offset = self.state.next_offset()
        while True:
            try:
                updates = await self.client.get_updates(offset)
                for update in updates:
                    self.receive_update(update)
                    # Claims are committed before acknowledging updates to Telegram.
                    if type(update.get("update_id")) is int:
                        offset = update["update_id"] + 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram 轮询失败，稍后重试 (%s)", type(exc).__name__)
                await asyncio.sleep(5)

    def receive_update(self, update: dict[str, Any]) -> asyncio.Task | None:
        update_id = update.get("update_id")
        if type(update_id) is not int:
            return None
        message = update.get("message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        user_id = user_id if type(user_id) is int else None
        chat_id = chat_id if type(chat_id) is int else None
        if not self.state.claim(update_id, user_id=user_id, chat_id=chat_id):
            return None
        if (
            chat.get("type") != "private" or chat_id is None
            or user_id not in self.allowed_user_ids or sender.get("is_bot")
        ):
            self.state.update(update_id, status="ignored")
            return None
        task = asyncio.create_task(self._handle(update_id, message), name=f"telegram-update-{update_id}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Telegram 更新处理失败 (%s)", type(task.exception()).__name__)

    def _aliases(self) -> list[str]:
        profiles = [self.manager.main_profile, *self.manager.managed_profiles.values()]
        return sorted(profile.alias for profile in profiles if profile.enabled and not profile.archived)

    async def _deliver(self, update_id: int, chat_id: int, parts: list[str]) -> None:
        try:
            for part in parts:
                await self.client.send_message(chat_id, part)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.update(update_id, delivery_status="failed")
            logger.warning("Telegram 结果投递失败 update_id=%s (%s)", update_id, type(exc).__name__)
        else:
            self.state.update(update_id, delivery_status="sent")

    async def _handle(self, update_id: int, message: dict[str, Any]) -> None:
        chat_id = message["chat"]["id"]
        alias = ""
        try:
            text = message.get("text")
            route = parse_target_text(text) if isinstance(text, str) else None
            if route is None:
                self.state.update(update_id, status="handled")
                await self._deliver(update_id, chat_id, split_text(help_text(self._aliases())))
                return
            alias, body = route
            if alias not in self._aliases():
                self.state.update(update_id, alias=alias, status="rejected")
                await self._deliver(update_id, chat_id, split_text(f"智能体 {alias} 不可用。\n\n{help_text(self._aliases())}"))
                return
            if body.strip() == "/new":
                self.state.update(update_id, alias=alias, status="rejected")
                await self._deliver(update_id, chat_id, [f"[{alias}] 请在 Web 中新建会话。"])
                return
            self.state.update(update_id, alias=alias, status="running")
            parts, status = await self._execute(update_id, alias, body, message["from"])
            self.state.update(update_id, status=status)
            await self._deliver(update_id, chat_id, parts)
        except asyncio.CancelledError:
            record = self.state.get(update_id)
            if record and record["status"] == "running":
                self.state.update(update_id, status="interrupted")
            raise
        except Exception as exc:
            self.state.update(update_id, status="failed")
            logger.warning("Telegram 执行失败 update_id=%s (%s)", update_id, type(exc).__name__)
            detail = exc.message if isinstance(exc, WebApiError) else "执行失败，请在 Web 查看任务和历史。"
            await self._deliver(update_id, chat_id, format_result(alias, detail, None))

    async def _execute(
        self, update_id: int, alias: str, body: str, sender: dict[str, Any],
    ) -> tuple[list[str], str]:
        shared_user_id = chat_session_user_id(sender["id"])
        profile, _agent, session = api_service.get_chat_session_for_alias(self.manager, alias, shared_user_id, "main")
        store = api_service._get_chat_store(session)
        with session._lock:
            conversation_id = session.active_conversation_id or ""
        execution_mode = profile.default_execution_mode
        if conversation_id:
            conversation = store.get_conversation(conversation_id)
            execution_mode = api_service._conversation_execution_mode(conversation)
        bindings: dict[str, str] = {}
        terminal: dict[str, Any] | None = None
        events = api_service.stream_chat(
            self.manager, alias, shared_user_id, body,
            agent_id="main", execution_mode=execution_mode, include_trace=False,
            protocol="ag-ui" if execution_mode == "native_agent" else "",
            actor={"user_id": sender["id"], "username": sender.get("username") or sender.get("first_name") or "Telegram"},
        )
        try:
            async for event in events:
                # Native AG-UI events are followed by the service's terminal done/error.
                # Preview, trace and AG-UI deltas never trigger Telegram messages.
                if event.get("type") not in {"meta", "status", "done", "error"}:
                    continue
                event_message = event.get("message") if isinstance(event.get("message"), dict) else {}
                snapshot = event.get("session") if isinstance(event.get("session"), dict) else {}
                ids = {
                    "turn_id": str(event.get("turn_id") or event_message.get("turn_id") or ""),
                    "assistant_message_id": str(event.get("assistant_message_id") or event_message.get("id") or ""),
                    "conversation_id": str(event.get("conversation_id") or event_message.get("conversation_id") or snapshot.get("active_conversation_id") or ""),
                }
                if any(bindings.get(key) and ids[key] and bindings[key] != ids[key] for key in ids):
                    continue
                changed = {key: value for key, value in ids.items() if value and bindings.get(key) != value}
                if changed:
                    bindings.update(changed)
                    self.state.update(update_id, **changed)
                if event["type"] in {"done", "error"}:
                    terminal = event
        finally:
            await events.aclose()
        if terminal is None:
            return format_result(alias, "执行结束，但未收到最终结果。请在 Web 查看历史。", None), "failed"

        final_message = terminal.get("message") if isinstance(terminal.get("message"), dict) else {}
        meta = final_message.get("meta") or {}
        usage = meta.get("context_usage") or terminal.get("context_usage")
        if not usage and bindings.get("assistant_message_id"):
            try:
                stored = store.get_message(bindings["assistant_message_id"])
                if stored.get("turn_id") == bindings.get("turn_id") and stored.get("conversation_id") == bindings.get("conversation_id"):
                    usage = (stored.get("meta") or {}).get("context_usage")
            except KeyError:
                pass
        completion = meta.get("completion_state") or ""
        failed = terminal["type"] == "error" or completion in {"error", "failed"} or final_message.get("state") == "error" or terminal.get("returncode", 0) != 0
        content = str(final_message.get("content") or terminal.get("output") or "")
        if completion == "cancelled":
            content = content or "任务已停止。"
        elif failed:
            detail = content or (terminal.get("message") if isinstance(terminal.get("message"), str) else "") or "请在 Web 查看任务详情。"
            content = f"执行失败：{detail}"
        return format_result(alias, content, usage), "failed" if failed else "completed"


async def start_telegram_gateway(manager: MultiBotManager) -> TelegramGateway | None:
    if not config.TELEGRAM_ENABLED:
        return None
    if not config.TELEGRAM_ALLOWED_USER_IDS or not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram 接入已关闭：请配置 Token 和数字用户 ID 白名单")
        return None
    try:
        client = TelegramClient(config.TELEGRAM_BOT_TOKEN)
        state = TelegramState(get_app_data_root() / "telegram" / "state.sqlite3", client.bot_id)
        gateway = TelegramGateway(manager, client, state, set(config.TELEGRAM_ALLOWED_USER_IDS))
        gateway.start()
        return gateway
    except Exception as exc:
        logger.warning("Telegram 接入启动失败 (%s)", type(exc).__name__)
        return None
