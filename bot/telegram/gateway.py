"""Long polling and final-only delivery through the shared chat service."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from bot import config
from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.runtime_paths import get_app_data_root
from bot.web import api_service
from bot.web.api_common import WebApiError

from .client import TelegramClient
from .state import CONFIRM_TTL, NAVIGATION_TTL, REPLY_TTL, TelegramState
from .ui import SHORTCUTS, conversation_label, force_reply, format_result, help_text, parse_target_text, reply_keyboard, split_text, status_text

logger = logging.getLogger(__name__)
_UNBOUND = object()
_REFRESH = "此操作已失效，请通过底部“智能体”刷新面板后重试。"


class TelegramGateway:
    def __init__(
        self, manager: MultiBotManager, client: TelegramClient, state: TelegramState,
        allowed_user_ids: set[int],
        *, chat_url: Callable[[str, str], str] | None = None,
    ):
        self.manager = manager
        self.client = client
        self.state = state
        self.allowed_user_ids = frozenset(allowed_user_ids)
        self.chat_url = chat_url
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
        callback = update.get("callback_query") or {}
        message = (callback.get("message") or {}) if callback else (update.get("message") or {})
        sender = (callback if callback else message).get("from") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        user_id = user_id if type(user_id) is int else None
        chat_id = chat_id if type(chat_id) is int else None
        if not self.state.claim(update_id, user_id=user_id, chat_id=chat_id):
            return self._schedule(self._ack(callback)) if callback else None
        if (
            chat.get("type") != "private" or chat_id is None
            or user_id not in self.allowed_user_ids or sender.get("is_bot")
        ):
            self.state.update(update_id, status="ignored")
            return self._schedule(self._ack(callback)) if callback else None
        if callback:
            message = {"chat": chat, "from": sender}
        return self._schedule(self._handle(update_id, message, callback))

    def _schedule(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    async def _ack(self, callback: dict[str, Any]) -> None:
        if not isinstance(callback.get("id"), str):
            return
        try:
            await self.client.answer_callback_query(callback["id"])
        except Exception as exc:
            logger.warning("Telegram 回调应答失败 (%s)", type(exc).__name__)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Telegram 更新处理失败 (%s)", type(task.exception()).__name__)

    def _aliases(self) -> list[str]:
        profiles = [self.manager.main_profile, *self.manager.managed_profiles.values()]
        return sorted(profile.alias for profile in profiles if profile.enabled and not profile.archived)

    async def _deliver(
        self, update_id: int, chat_id: int, parts: list[str],
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        sent = None
        try:
            for index, part in enumerate(parts):
                options = {"reply_markup": reply_markup} if reply_markup is not None and index == len(parts) - 1 else {}
                sent = await self.client.send_message(chat_id, part, **options)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.update(update_id, delivery_status="failed")
            logger.warning("Telegram 结果投递失败 update_id=%s (%s)", update_id, type(exc).__name__)
        else:
            self.state.update(update_id, delivery_status="sent")
            return sent
        return None

    def _require_target(self, alias: str) -> None:
        if alias not in self._aliases():
            raise WebApiError(404, "telegram_target_unavailable", f"智能体 {alias} 不可用，请刷新智能体列表。")

    def _conversation(self, alias: str, user_id: int) -> str | None:
        self._require_target(alias)
        _, _, session = api_service.get_chat_session_for_alias(self.manager, alias, chat_session_user_id(user_id), "main")
        return session.active_conversation_id or None

    def _button(
        self, label: str, action: str, user_id: int, chat_id: int, alias: str,
        conversation_id: str | None, *, ttl: int = NAVIGATION_TTL, control: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        token = self.state.new_interaction(action, user_id, chat_id, alias, conversation_id, ttl=ttl, control=control)
        return {"text": label, "callback_data": token}

    def _web_button(self, user_id: int, chat_id: int, alias: str, conversation_id: str | None) -> dict[str, str]:
        url = self.chat_url(alias, conversation_id or "") if self.chat_url else ""
        if url:
            return {"text": "打开 Web", "url": url}
        return self._button("打开 Web（需配置公网地址）", "web", user_id, chat_id, alias, conversation_id)

    def _result_markup(self, user_id: int, chat_id: int, alias: str, conversation_id: str) -> dict[str, Any]:
        return {"inline_keyboard": [[
            self._button("继续聊", "prompt", user_id, chat_id, alias, conversation_id),
            self._button("新会话", "new", user_id, chat_id, alias, conversation_id),
        ], [self._web_button(user_id, chat_id, alias, conversation_id)]]}

    async def _targets(self, update_id: int, user_id: int, chat_id: int) -> None:
        buttons = [[self._button(alias, "select", user_id, chat_id, alias, None)] for alias in self._aliases()]
        await self._deliver(update_id, chat_id, ["请选择操作的智能体：" if buttons else "暂无已启用的智能体。"],
                            {"inline_keyboard": buttons} if buttons else reply_keyboard())

    async def _panel(self, update_id: int, user_id: int, chat_id: int, alias: str) -> None:
        conversation_id = self._conversation(alias, user_id)
        rows = [[self._button(label, action, user_id, chat_id, alias, conversation_id)
                 for label, action in pair] for pair in (
                     (("发消息", "prompt"), ("新会话", "new")),
                     (("状态", "status"), ("停止任务", "stop")),
                 )]
        rows.append([self._web_button(user_id, chat_id, alias, conversation_id)])
        await self._deliver(update_id, chat_id, [f"[{alias}] 当前操作目标\n会话：{conversation_label(conversation_id)}"],
                            {"inline_keyboard": rows})

    async def _help(self, update_id: int, user_id: int, chat_id: int) -> None:
        await self._deliver(update_id, chat_id, split_text(help_text(self._aliases())), reply_keyboard())
        alias = self.state.selected_target(user_id, chat_id)
        if alias in self._aliases():
            await self._panel(update_id, user_id, chat_id, alias)
        else:
            await self._targets(update_id, user_id, chat_id)

    async def _prompt(
        self, update_id: int, user_id: int, chat_id: int, alias: str, conversation_id: str | None,
    ) -> None:
        token = self.state.new_interaction("reply", user_id, chat_id, alias, conversation_id, ttl=REPLY_TTL)
        sent = await self._deliver(update_id, chat_id, [
            f"[{alias}] 请回复此消息输入正文。\n会话：{conversation_label(conversation_id)}\n"
            "本提示 30 分钟内有效，回复中的命令文字也会作为正文发送。"
        ], force_reply())
        if sent is not None and type(sent.get("message_id")) is int:
            self.state.bind_reply(token, sent["message_id"])
        else:
            self.state.finish_interaction(token, "回复提示投递失败，请刷新面板。", status="failed")

    def _check_interaction(self, record: dict[str, Any] | None, user_id: int, chat_id: int) -> dict[str, Any]:
        if (record is None or record["user_id"] != user_id or record["chat_id"] != chat_id
                or record["expires_at"] <= time.time()):
            raise WebApiError(409, "telegram_interaction_expired", _REFRESH)
        self._require_target(record["alias"])
        return record

    def _check_conversation(self, record: dict[str, Any], user_id: int) -> None:
        if self._conversation(record["alias"], user_id) != record["conversation_id"]:
            raise WebApiError(409, "telegram_conversation_changed", _REFRESH)

    async def _control(
        self, update_id: int, sender: dict[str, Any], chat_id: int, action: str,
        alias: str, conversation_id: str | None,
    ) -> None:
        if action == "prompt":
            await self._prompt(update_id, sender["id"], chat_id, alias, conversation_id)
        elif action == "new":
            confirm = self._button("确认新建会话", "create_confirm", sender["id"], chat_id, alias,
                                   conversation_id, ttl=CONFIRM_TTL)
            await self._deliver(update_id, chat_id, [
                f"[{alias}] 确认新建并切换会话？\n当前会话：{conversation_label(conversation_id)}\n"
                "旧历史会保留，发送正文后才启动模型。本确认 5 分钟内有效。"
            ], {"inline_keyboard": [[confirm]]})
        elif action in {"status", "stop"}:
            snapshot = await api_service.get_conversation_control_snapshot(
                self.manager, alias, chat_session_user_id(sender["id"]), agent_id="main",
            )
            if snapshot["conversation_id"] != conversation_id:
                raise WebApiError(409, "telegram_conversation_changed", _REFRESH)
            summary = status_text(alias, snapshot)
            if action == "status":
                await self._deliver(update_id, chat_id, split_text(summary),
                                    {"inline_keyboard": [[self._web_button(sender["id"], chat_id, alias, conversation_id)]]})
            elif snapshot["phase"] == "idle":
                await self._deliver(update_id, chat_id, [f"[{alias}] 当前没有运行中的任务。"])
            else:
                task_ids = snapshot.get("cluster_task_ids") or []
                if task_ids:
                    scope = ("将停止本次主任务，并取消" if snapshot.get("execution_id") else "将取消")
                    scope += f"这 {len(task_ids)} 个运行中或排队的子任务。\n子任务：" + ", ".join(task_ids)
                else:
                    scope = "将停止本次任务。"
                confirm = self._button("确认停止任务", "stop_confirm", sender["id"], chat_id, alias,
                                       conversation_id, ttl=CONFIRM_TTL, control=snapshot)
                await self._deliver(update_id, chat_id, split_text(
                    f"{summary}\n\n{scope}\n任务或子任务范围变化后需重新确认。本确认 5 分钟内有效。"
                ), {"inline_keyboard": [[confirm]]})
        elif action == "web":
            await self._deliver(update_id, chat_id, [f"[{alias}] 请在 Web 配置公网访问地址，然后刷新面板打开会话。"])
        else:
            raise WebApiError(409, "telegram_control_unavailable", _REFRESH)

    async def _confirm(self, update_id: int, record: dict[str, Any], user_id: int, chat_id: int) -> None:
        alias = record["alias"]
        options = {"agent_id": "main", "expected_conversation_id": record["conversation_id"]}
        if record["action"] == "create_confirm":
            created = await api_service.create_conversation(
                self.manager, alias, chat_session_user_id(user_id), follow_current_conversation=True, **options,
            )
            conversation_id = created["conversation"]["id"]
            self.state.update(update_id, conversation_id=conversation_id)
            result = f"[{alias}] 已新建并切换会话，旧历史已保留。\n会话：{conversation_id}\n点击“继续聊”发送正文开始对话。"
            markup = self._result_markup(user_id, chat_id, alias, conversation_id)
        else:
            stopped = await api_service.kill_user_process(
                self.manager, alias, chat_session_user_id(user_id), expected_control=record["control"], **options,
            )
            result = f"[{alias}] {stopped['message']}"
            markup = reply_keyboard()
        # Record the side effect before attempting Telegram delivery.
        self.state.finish_interaction(record["token"], result)
        self.state.update(update_id, status="completed", alias=alias)
        await self._deliver(update_id, chat_id, split_text(result), markup)

    async def _handle(self, update_id: int, message: dict[str, Any], callback: dict[str, Any] | None = None) -> None:
        chat_id = message["chat"]["id"]
        sender = message["from"]
        user_id = sender["id"]
        alias = ""
        claimed_token = ""
        try:
            if callback:
                await self._ack(callback)
                token = callback.get("data")
                record = self._check_interaction(self.state.get_interaction(token) if isinstance(token, str) else None, user_id, chat_id)
                alias = record["alias"]
                action = record["action"]
                if action in {"create_confirm", "stop_confirm"}:
                    if not self.state.claim_interaction(record["token"], user_id, chat_id):
                        previous = self.state.get_interaction(record["token"])
                        await self._deliver(update_id, chat_id, split_text(previous["result"] or f"[{alias}] 操作正在处理中，请稍候。"))
                        self.state.update(update_id, status="handled", alias=alias)
                        return
                    claimed_token = record["token"]
                    self.state.update(update_id, status="running", alias=alias)
                    await self._confirm(update_id, record, user_id, chat_id)
                    return
                elif action == "select":
                    self.state.select_target(user_id, chat_id, alias)
                    await self._panel(update_id, user_id, chat_id, alias)
                else:
                    self._check_conversation(record, user_id)
                    await self._control(update_id, sender, chat_id, action, alias, record["conversation_id"])
                self.state.update(update_id, status="handled", alias=alias)
                return
            text = message.get("text")
            reply = message.get("reply_to_message") or {}
            if type(reply.get("message_id")) is int:
                record = self._check_interaction(self.state.get_reply(chat_id, reply["message_id"]), user_id, chat_id)
                alias = record["alias"]
                self._check_conversation(record, user_id)
                if not isinstance(text, str) or not text.strip():
                    await self._deliver(update_id, chat_id, [f"[{alias}] 请回复文本正文。"])
                    self.state.update(update_id, status="handled")
                    return
                if not self.state.claim_interaction(record["token"], user_id, chat_id):
                    raise WebApiError(409, "telegram_reply_consumed", "此回复提示已使用或正在处理，请刷新面板后重新点击“发消息”。")
                claimed_token = record["token"]
                await self._send_text(update_id, chat_id, alias, text, sender, expected_conversation_id=record["conversation_id"])
                self.state.finish_interaction(claimed_token, "回复已处理，请使用最终答复下的“继续聊”。")
                return
            action = SHORTCUTS.get(text) if isinstance(text, str) else None
            if text in ("/start", "/help") or action == "help":
                await self._help(update_id, user_id, chat_id)
                self.state.update(update_id, status="handled")
                return
            if action:
                alias = self.state.selected_target(user_id, chat_id) or ""
                if action == "targets" or alias not in self._aliases():
                    await self._targets(update_id, user_id, chat_id)
                else:
                    await self._control(update_id, sender, chat_id, action, alias, self._conversation(alias, user_id))
                self.state.update(update_id, status="handled")
                return
            route = parse_target_text(text) if isinstance(text, str) else None
            if route is None:
                self.state.update(update_id, status="handled")
                await self._help(update_id, user_id, chat_id)
                return
            alias, body = route
            if alias not in self._aliases():
                self.state.update(update_id, alias=alias, status="rejected")
                await self._deliver(update_id, chat_id, split_text(f"智能体 {alias} 不可用。\n\n{help_text(self._aliases())}"))
                return
            if body.strip() == "/new":
                self.state.update(update_id, alias=alias, status="running")
                result = await api_service.create_conversation(
                    self.manager, alias, chat_session_user_id(user_id),
                    agent_id="main", follow_current_conversation=True,
                )
                self.state.update(update_id, status="completed", conversation_id=result["conversation"]["id"])
                await self._deliver(update_id, chat_id, [f"[{alias}] 已新建并切换会话，旧历史已保留。\n发送 to {alias} <正文> 开始对话。"])
                return
            await self._send_text(update_id, chat_id, alias, body, sender)
        except asyncio.CancelledError:
            record = self.state.get(update_id)
            if record and record["status"] == "running":
                self.state.update(update_id, status="interrupted")
            if claimed_token:
                self.state.finish_interaction(claimed_token, "操作已中断，请在 Web 查看历史后刷新面板。", status="interrupted")
            raise
        except Exception as exc:
            rejected = isinstance(exc, WebApiError) and exc.status < 500
            self.state.update(update_id, status="rejected" if rejected else "failed")
            logger.warning("Telegram 执行失败 update_id=%s (%s)", update_id, type(exc).__name__)
            detail = exc.message if isinstance(exc, WebApiError) else "执行失败，请在 Web 查看任务和历史。"
            if claimed_token:
                self.state.finish_interaction(claimed_token, detail, status="failed")
            await self._deliver(update_id, chat_id, split_text(f"[{alias}] {detail}"))

    async def _send_text(
        self, update_id: int, chat_id: int, alias: str, body: str, sender: dict[str, Any],
        *, expected_conversation_id: Any = _UNBOUND,
    ) -> None:
        self._require_target(alias)
        self.state.update(update_id, alias=alias, status="running")
        parts, status = await self._execute(update_id, alias, body, sender, expected_conversation_id=expected_conversation_id)
        self.state.update(update_id, status=status)
        conversation_id = (self.state.get(update_id) or {}).get("conversation_id")
        markup = self._result_markup(sender["id"], chat_id, alias, conversation_id) if conversation_id else None
        await self._deliver(update_id, chat_id, parts, markup)

    async def _execute(
        self, update_id: int, alias: str, body: str, sender: dict[str, Any],
        *, expected_conversation_id: Any = _UNBOUND,
    ) -> tuple[list[str], str]:
        shared_user_id = chat_session_user_id(sender["id"])
        _profile, _agent, session = api_service.get_chat_session_for_alias(self.manager, alias, shared_user_id, "main")
        store = api_service._get_chat_store(session)
        bindings: dict[str, str] = {}
        terminal: dict[str, Any] | None = None
        expected = {"expected_conversation_id": expected_conversation_id} if expected_conversation_id is not _UNBOUND else {}
        events = api_service.stream_chat(
            self.manager, alias, shared_user_id, body,
            agent_id="main", follow_current_conversation=True, include_trace=False,
            protocol="ag-ui",
            actor={"user_id": sender["id"], "username": sender.get("username") or sender.get("first_name") or "Telegram"},
            **expected,
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
        if terminal.get("code") == "session_busy":
            return split_text(f"[{alias}] {terminal['message']}"), "rejected"

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


async def start_telegram_gateway(
    manager: MultiBotManager, *, chat_url: Callable[[str, str], str] | None = None,
) -> TelegramGateway | None:
    if not config.TELEGRAM_ENABLED:
        return None
    if not config.TELEGRAM_ALLOWED_USER_IDS or not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram 接入已关闭：请配置 Token 和数字用户 ID 白名单")
        return None
    try:
        client = TelegramClient(config.TELEGRAM_BOT_TOKEN)
        state = TelegramState(get_app_data_root() / "telegram" / "state.sqlite3", client.bot_id)
        gateway = TelegramGateway(manager, client, state, set(config.TELEGRAM_ALLOWED_USER_IDS), chat_url=chat_url)
        gateway.start()
        return gateway
    except Exception as exc:
        logger.warning("Telegram 接入启动失败 (%s)", type(exc).__name__)
        return None
