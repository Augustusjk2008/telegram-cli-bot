"""HTTP long-polling Weixin gateway backed by the shared Web chat service."""

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
from bot.telegram.ui import (
    configuration_text,
    conversation_label,
    help_text,
    parse_config_text,
    parse_target_text,
    status_text,
)

from .client import (
    WeixinApiError,
    WeixinClient,
    WeixinError,
    WeixinSessionExpiredError,
)
from .notifications import WeixinCompletionNotifier, format_weixin_result, split_weixin_text
from .state import WeixinState

logger = logging.getLogger(__name__)
_POLL_MAX_BACKOFF = 30.0
_TOKEN_USERS: set[str] = set()
_ACTIVE_GATEWAYS: dict[str, "WeixinGateway"] = {}


class WeixinTokenInUseError(WeixinError):
    def __init__(self) -> None:
        super().__init__("token_lock", retryable=False)


def _take_token_lock(token: str) -> None:
    key = str(token or "").strip()
    if not key:
        raise ValueError("WEIXIN_TOKEN 不能为空")
    if key in _TOKEN_USERS:
        raise WeixinTokenInUseError()
    _TOKEN_USERS.add(key)


def _release_token_lock(token: str) -> None:
    _TOKEN_USERS.discard(str(token or "").strip())


def _message_id(message: dict[str, Any]) -> str:
    for key in ("message_id", "msg_id", "id"):
        value = message.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _peer_id(message: dict[str, Any]) -> str:
    for key in ("from_user_id", "sender_id", "user_id", "peer_id"):
        value = message.get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("user_id")
        if value is not None and str(value).strip():
            return str(value).strip()
    sender = message.get("from")
    if isinstance(sender, dict):
        return str(sender.get("id") or sender.get("user_id") or "").strip()
    return ""


def _is_group_message(message: dict[str, Any], peer_id: str) -> bool:
    if message.get("is_group") is True or message.get("group_id") or message.get("room_id"):
        return True
    kind = str(message.get("chat_type") or message.get("conversation_type") or "").strip().lower()
    if kind in {"group", "群聊", "room", "chatroom"}:
        return True
    lowered = str(peer_id or "").lower()
    return any(marker in lowered for marker in ("@chatroom", "@im.group", "@group"))


def _text_from_message(message: dict[str, Any]) -> str | None:
    direct = message.get("text")
    if isinstance(direct, str) and direct.strip():
        return direct
    items = message.get("item_list") or message.get("items") or []
    if not isinstance(items, list):
        return None
    texts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if str(item_type) not in {"1", "text", "TEXT"}:
            continue
        text_item = item.get("text_item") or item.get("textItem") or {}
        value = text_item.get("text") if isinstance(text_item, dict) else item.get("text")
        if isinstance(value, str) and value:
            texts.append(value)
    return "\n".join(texts) if texts else None


class WeixinGateway:
    def __init__(
        self,
        manager: MultiBotManager,
        client: Any,
        state: WeixinState,
        allowed_user_ids: set[str] | frozenset[str] | list[str],
        *,
        account_id: str = "",
        host: Any | None = None,
    ) -> None:
        self.manager = manager
        self.client = client
        self.state = state
        self.allowed_user_ids = frozenset(str(item).strip() for item in allowed_user_ids if str(item).strip())
        self.account_id = str(account_id or getattr(client, "account_id", "") or "").strip()
        self.host = host
        self._poll_task: asyncio.Task[Any] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._running = False
        self._token = str(getattr(client, "token", "") or "")
        self.completion_notifier = WeixinCompletionNotifier(
            state,
            client,
            self.allowed_user_ids,
            schedule_task=self._schedule,
            account_id=self.account_id,
        )

    def start(self) -> None:
        if self._poll_task is None:
            _take_token_lock(self._token)
            self._running = True
            self.state.set_gateway_status("starting")
            self.completion_notifier.register()
            _ACTIVE_GATEWAYS[self.account_id or "default"] = self
            self._poll_task = asyncio.create_task(self._poll(), name="weixin-poll")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await self.completion_notifier.close()
        self.completion_notifier.unregister()
        if _ACTIVE_GATEWAYS.get(self.account_id or "default") is self:
            _ACTIVE_GATEWAYS.pop(self.account_id or "default", None)
        _release_token_lock(self._token)
        self.state.set_gateway_status("stopped")
        try:
            await self.client.close()
        finally:
            self.state.close()

    def _schedule(self, coroutine, *, name: str | None = None) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("微信消息处理失败 (%s)", type(task.exception()).__name__)

    async def _poll(self) -> None:
        try:
            await self._recover_state()
            failures = 0
            while self._running:
                try:
                    result = await self.client.get_updates(self.state.get_updates_buf())
                    failures = 0
                    self.state.set_gateway_status("connected")
                    if isinstance(result, list):
                        messages = result
                        next_cursor = self.state.get_updates_buf()
                    else:
                        payload = result if isinstance(result, dict) else {}
                        messages = payload.get("msgs") or payload.get("messages") or []
                        next_cursor = payload.get("get_updates_buf") or payload.get("sync_buf") or self.state.get_updates_buf()
                    for raw_message in messages if isinstance(messages, list) else []:
                        if isinstance(raw_message, dict):
                            self.receive_update(raw_message)
                    if isinstance(next_cursor, str) and next_cursor != self.state.get_updates_buf():
                        # Claim message IDs before advancing the cursor so a
                        # process interruption cannot skip an unclaimed batch.
                        self.state.set_updates_buf(next_cursor)
                except asyncio.CancelledError:
                    raise
                except WeixinSessionExpiredError:
                    self.state.set_gateway_status("needs_relogin", detail="session_expired")
                    logger.warning("微信 iLink 会话已过期，需要重新扫码")
                    break
                except WeixinError as exc:
                    failures += 1
                    delay = min(_POLL_MAX_BACKOFF, exc.retry_after or 2 ** min(failures - 1, 5))
                    self.state.set_gateway_status("error", detail=type(exc).__name__)
                    logger.warning("微信长轮询失败，将在 %s 秒后重试 (%s)", delay, type(exc).__name__)
                    await asyncio.sleep(delay)
                except Exception as exc:
                    failures += 1
                    delay = min(_POLL_MAX_BACKOFF, 2 ** min(failures - 1, 5))
                    self.state.set_gateway_status("error", detail=type(exc).__name__)
                    logger.warning("微信长轮询失败，将在 %s 秒后重试 (%s)", delay, type(exc).__name__)
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

    async def _recover_state(self) -> None:
        try:
            await self.completion_notifier.recover()
            self.state.set_gateway_status("connected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("微信状态恢复失败 (%s)", type(exc).__name__)

    def receive_update(self, update: dict[str, Any]) -> asyncio.Task[Any] | None:
        message = update.get("message") if isinstance(update.get("message"), dict) else update.get("msg")
        if not isinstance(message, dict):
            message = update
        message_id = _message_id(message)
        if not message_id:
            return None
        peer_id = _peer_id(message)
        if not self.state.claim_message(message_id, peer_id=peer_id):
            return None
        message_type = str(message.get("message_type") or message.get("type") or "1").lower()
        if message_type in {"2", "bot", "assistant"} or (self.account_id and peer_id == self.account_id):
            self.state.update_message(message_id, status="ignored")
            return None
        if _is_group_message(message, peer_id):
            self.state.update_message(message_id, status="ignored")
            return None
        if not peer_id or (self.allowed_user_ids and peer_id not in self.allowed_user_ids):
            self.state.update_message(message_id, status="ignored")
            return None
        context_token = message.get("context_token") or message.get("contextToken")
        if isinstance(context_token, str) and context_token.strip():
            self.state.set_context_token(peer_id, context_token)
        text = _text_from_message(message)
        if not text or not text.strip():
            self.state.update_message(message_id, status="ignored")
            return None
        task = self._schedule(self._handle_message(message_id, peer_id, text, message), name=f"weixin-message-{message_id}")
        return task

    def _aliases(self) -> list[str]:
        profiles = [self.manager.main_profile, *self.manager.managed_profiles.values()]
        return sorted(profile.alias for profile in profiles if profile.enabled and not profile.archived)

    def _require_target(self, alias: str) -> None:
        if alias not in self._aliases():
            raise WebApiError(404, "weixin_target_unavailable", f"智能体 {alias} 不可用，请发送 /help 刷新列表。")

    def _conversation(self, alias: str) -> str:
        self._require_target(alias)
        _, _, session = api_service.get_chat_session_for_alias(
            self.manager, alias, chat_session_user_id(None), "main"
        )
        return str(session.active_conversation_id or "")

    async def _configuration(self, alias: str) -> dict[str, Any]:
        self._require_target(alias)
        profile = self.manager.get_profile(alias)
        payload = await asyncio.to_thread(api_service.get_cli_params_payload, self.manager, alias, profile.cli_type)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
        schema = payload.get("schema") if isinstance(payload.get("schema"), dict) else {}
        cli_type = str(payload.get("cli_type") or profile.cli_type or "cli")
        reasoning_key = "effort" if cli_type in {"claude", "antigravity"} else "reasoning_effort"
        model_schema = schema.get("model") if isinstance(schema.get("model"), dict) else {}
        reasoning_schema = schema.get(reasoning_key) if isinstance(schema.get(reasoning_key), dict) else {}
        return {
            "execution_mode": "cli",
            "cli_type": cli_type,
            "reasoning_key": reasoning_key,
            "model": str(params.get("model") or "none").strip(),
            "reasoning_effort": str(params.get(reasoning_key) or defaults.get(reasoning_key) or "").strip(),
            "model_options": [{"value": str(item).strip(), "label": str(item).strip()} for item in model_schema.get("enum", []) if str(item).strip()],
            "reasoning_options": [str(item).strip() for item in reasoning_schema.get("enum", []) if str(item).strip()],
            "cluster_enabled": bool((await asyncio.to_thread(api_service.get_cluster_status, self.manager, alias)).get("enabled")),
        }

    async def _send(self, message_id: str, peer_id: str, parts: list[str], *, alias: str = "", status: str = "handled") -> None:
        delivery_id = f"control:{message_id}:{len(parts)}"
        await self.completion_notifier.deliver_direct(
            peer_id,
            [chunk for part in parts for chunk in split_weixin_text(part)],
            delivery_id=delivery_id,
            alias=alias,
            conversation_id=self._conversation(alias) if alias else "",
        )
        self.state.update_message(message_id, status=status, delivery_status="sent", alias=alias)

    async def _help(self, message_id: str, peer_id: str) -> None:
        await self._send(message_id, peer_id, [help_text(self._aliases())])

    async def _apply_configuration(self, alias: str, setting: str, value: str) -> str:
        configuration = await self._configuration(alias)
        normalized = str(value or "").strip()
        if setting == "cluster":
            if normalized.lower() in {"on", "true", "1", "开启", "打开"}:
                enabled = True
            elif normalized.lower() in {"off", "false", "0", "关闭"}:
                enabled = False
            else:
                raise WebApiError(400, "invalid_weixin_cluster_value", "集群开关只能填写 on 或 off。")
            cluster = self.manager.get_profile(alias).cluster.to_dict()
            cluster["enabled"] = enabled
            await api_service.update_cluster_config(self.manager, alias, cluster)
            return f"集群已{'开启' if enabled else '关闭'}。"
        if setting == "model":
            await api_service.update_cli_params(self.manager, alias, configuration["cli_type"], "model", normalized)
            return f"模型已设置为：{normalized}。"
        if setting == "reasoning":
            await api_service.update_cli_params(self.manager, alias, configuration["cli_type"], configuration["reasoning_key"], normalized)
            return f"思考强度已设置为：{normalized}。"
        raise WebApiError(400, "invalid_weixin_config_setting", "配置项只能是 model、reasoning 或 cluster。")

    async def _handle_config(self, message_id: str, peer_id: str, command: tuple[str | None, str | None, str | None], *, forced_alias: str | None = None) -> None:
        command_alias, setting, value = command
        binding = self.state.get_binding(peer_id)
        alias = (forced_alias or command_alias or (binding or {}).get("alias") or "").strip().lower()
        if command_alias and forced_alias and command_alias != forced_alias:
            raise WebApiError(409, "weixin_config_target_mismatch", "配置命令的智能体和当前 to 目标不一致。")
        if not alias:
            await self._send(message_id, peer_id, ["请指定智能体，例如：/config dev"], status="handled")
            return
        self._require_target(alias)
        if setting is None:
            await self._send(message_id, peer_id, [configuration_text(alias, await self._configuration(alias))], alias=alias)
            return
        if not value:
            raise WebApiError(400, "missing_weixin_config_value", f"请填写 {setting} 的值。")
        result = await self._apply_configuration(alias, setting, value)
        await self._send(message_id, peer_id, [f"[{alias}] {result}"], alias=alias)

    async def _handle_status(self, message_id: str, peer_id: str) -> None:
        binding = self.state.get_binding(peer_id)
        alias = str((binding or {}).get("alias") or "").strip().lower()
        if not alias:
            await self._help(message_id, peer_id)
            return
        snapshot = await api_service.get_conversation_control_snapshot(
            self.manager, alias, chat_session_user_id(None), agent_id="main"
        )
        await self._send(message_id, peer_id, [status_text(alias, snapshot)], alias=alias)

    async def _handle_stop(self, message_id: str, peer_id: str) -> None:
        binding = self.state.get_binding(peer_id)
        alias = str((binding or {}).get("alias") or "").strip().lower()
        if not alias:
            await self._help(message_id, peer_id)
            return
        snapshot = await api_service.get_conversation_control_snapshot(
            self.manager, alias, chat_session_user_id(None), agent_id="main"
        )
        if snapshot.get("phase") == "idle":
            await self._send(message_id, peer_id, [f"[{alias}] 当前没有运行中的任务。"], alias=alias)
            return
        result = await api_service.kill_user_process(
            self.manager,
            alias,
            chat_session_user_id(None),
            agent_id="main",
            expected_conversation_id=snapshot.get("conversation_id") or None,
        )
        await self._send(message_id, peer_id, [f"[{alias}] {result.get('message') or '任务已停止。'}"], alias=alias)

    async def _handle_new(self, message_id: str, peer_id: str, alias: str) -> None:
        self._require_target(alias)
        result = await api_service.create_conversation(
            self.manager,
            alias,
            chat_session_user_id(None),
            agent_id="main",
            follow_current_conversation=True,
        )
        conversation_id = str(result["conversation"]["id"])
        self.state.bind_conversation(
            peer_id=peer_id,
            alias=alias,
            agent_id="main",
            conversation_id=conversation_id,
            shared_user_id=chat_session_user_id(None),
            actor_id=peer_id,
        )
        self.state.update_message(message_id, alias=alias, conversation_id=conversation_id, status="completed")
        await self._send(message_id, peer_id, [f"[{alias}] 已新建并切换会话，旧历史已保留。\n会话：{conversation_id}\n发送 to {alias} <正文> 开始对话。"], alias=alias)

    async def _execute(self, message_id: str, peer_id: str, alias: str, body: str) -> None:
        self._require_target(alias)
        self.state.update_message(message_id, alias=alias, status="running")
        binding = self.state.get_binding(peer_id, alias)
        expected = str((binding or {}).get("conversation_id") or "").strip() or None
        kwargs: dict[str, Any] = {
            "agent_id": "main",
            "follow_current_conversation": True,
            "include_trace": False,
            "actor": {"user_id": peer_id, "username": peer_id, "channel": "weixin"},
            "source_channel": "weixin",
            "source_external_id": peer_id,
        }
        if expected:
            kwargs["expected_conversation_id"] = expected
        events = api_service.stream_chat(
            self.manager,
            alias,
            chat_session_user_id(None),
            body,
            **kwargs,
        )
        bindings: dict[str, str] = {}
        terminal: dict[str, Any] | None = None
        try:
            async for event in events:
                if event.get("type") not in {"meta", "status", "done", "error"}:
                    continue
                message = event.get("message") if isinstance(event.get("message"), dict) else {}
                session = event.get("session") if isinstance(event.get("session"), dict) else {}
                ids = {
                    "turn_id": str(event.get("turn_id") or message.get("turn_id") or ""),
                    "assistant_message_id": str(event.get("assistant_message_id") or message.get("id") or ""),
                    "conversation_id": str(event.get("conversation_id") or message.get("conversation_id") or session.get("active_conversation_id") or ""),
                }
                if any(bindings.get(key) and ids[key] and bindings[key] != ids[key] for key in ids):
                    continue
                bindings.update({key: value for key, value in ids.items() if value})
                self.state.update_message(message_id, **{key: value for key, value in ids.items() if value})
                if ids["conversation_id"]:
                    self.state.bind_conversation(
                        peer_id=peer_id,
                        alias=alias,
                        agent_id="main",
                        conversation_id=ids["conversation_id"],
                        shared_user_id=chat_session_user_id(None),
                        actor_id=peer_id,
                    )
                if event.get("type") in {"done", "error"}:
                    terminal = event
        finally:
            await events.aclose()
        if terminal is None:
            content = "执行结束，但未收到最终结果。请在 Web 查看历史。"
            status = "failed"
            usage = None
        else:
            message = terminal.get("message") if isinstance(terminal.get("message"), dict) else {}
            meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
            usage = meta.get("context_usage") or terminal.get("context_usage")
            completion = str(meta.get("completion_state") or terminal.get("completion_state") or "")
            failed = terminal.get("type") == "error" or completion in {"error", "failed"} or message.get("state") == "error" or terminal.get("returncode", 0) not in {0, None}
            content = str(message.get("content") or terminal.get("output") or "")
            if completion in {"cancelled", "canceled"}:
                content = content or "任务已停止。"
            elif failed:
                content = f"执行失败：{content or terminal.get('message') or '请在 Web 查看任务详情。'}"
            status = "failed" if failed else "completed"
        parts = format_weixin_result(alias, content, usage)
        delivery_id = f"direct:{message_id}:{bindings.get('turn_id') or 'result'}"
        await self.completion_notifier.deliver_direct(
            peer_id,
            parts,
            delivery_id=delivery_id,
            alias=alias,
            conversation_id=bindings.get("conversation_id", ""),
            turn_id=bindings.get("turn_id", ""),
            assistant_message_id=bindings.get("assistant_message_id", ""),
        )
        self.state.update_message(message_id, status=status, delivery_status="sent")

    async def _handle_message(self, message_id: str, peer_id: str, text: str, message: dict[str, Any]) -> None:
        alias = ""
        try:
            normalized = text.strip()
            lowered = normalized.lower()
            if lowered in {"/start", "/help"}:
                await self._help(message_id, peer_id)
                return
            if lowered == "/status":
                await self._handle_status(message_id, peer_id)
                return
            if lowered == "/stop":
                await self._handle_stop(message_id, peer_id)
                return
            config_command = parse_config_text(normalized)
            if config_command is not None:
                await self._handle_config(message_id, peer_id, config_command)
                return
            route = parse_target_text(text)
            if route is None:
                await self._help(message_id, peer_id)
                return
            alias, body = route
            self._require_target(alias)
            body_config = parse_config_text(body)
            if body_config is not None:
                await self._handle_config(message_id, peer_id, body_config, forced_alias=alias)
                return
            if body.strip() == "/new":
                await self._handle_new(message_id, peer_id, alias)
                return
            await self._execute(message_id, peer_id, alias, body)
        except asyncio.CancelledError:
            self.state.update_message(message_id, status="interrupted")
            raise
        except Exception as exc:
            rejected = isinstance(exc, WebApiError) and exc.status < 500
            self.state.update_message(message_id, status="rejected" if rejected else "failed", alias=alias)
            detail = exc.message if isinstance(exc, WebApiError) else "执行失败，请在 Web 查看历史。"
            await self._send(message_id, peer_id, [f"[{alias}] {detail}" if alias else detail], alias=alias, status="rejected" if rejected else "failed")


async def start_weixin_gateway(
    manager: MultiBotManager,
    *,
    chat_url: Callable[[str, str], str] | None = None,
    host: Any | None = None,
) -> WeixinGateway | None:
    del chat_url  # Kept parallel to Telegram's launcher for host integration compatibility.
    if not getattr(config, "WEIXIN_ENABLED", False):
        return None
    account_id = str(getattr(config, "WEIXIN_ACCOUNT_ID", "") or "").strip()
    token = str(getattr(config, "WEIXIN_TOKEN", "") or "").strip()
    allowed = set(getattr(config, "WEIXIN_ALLOWED_USER_IDS", set()) or set())
    if not account_id or not token or not allowed:
        logger.warning("微信接入已关闭：请配置账号 ID、Token 和私聊用户 ID 白名单")
        return None
    try:
        client = WeixinClient(token, account_id=account_id, base_url=getattr(config, "WEIXIN_BASE_URL", ""))
        state = WeixinState(get_app_data_root() / "weixin" / "state.sqlite3", account_id)
        gateway = WeixinGateway(manager, client, state, allowed, account_id=account_id, host=host)
        gateway.start()
        return gateway
    except Exception as exc:
        logger.warning("微信接入启动失败 (%s)", type(exc).__name__)
        return None


def get_active_weixin_gateway(account_id: str | None = None) -> WeixinGateway | None:
    if account_id:
        return _ACTIVE_GATEWAYS.get(str(account_id))
    if not _ACTIVE_GATEWAYS:
        return None
    return _ACTIVE_GATEWAYS[next(reversed(_ACTIVE_GATEWAYS))]


__all__ = [
    "WeixinGateway",
    "WeixinTokenInUseError",
    "get_active_weixin_gateway",
    "start_weixin_gateway",
]
