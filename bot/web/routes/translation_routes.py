"""全局与 Bot 聊天翻译设置，复用现有鉴权。"""

from __future__ import annotations

import asyncio
import hashlib

from aiohttp import web

from bot.web.api_common import WebApiError, get_profile_or_raise
from bot.web.async_chat_store import run_chat_store_io
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_CHAT_SEND, CAP_VIEW_CHAT_HISTORY
from bot.web.translation_config import PROMPT_TARGET_LANGUAGE, TranslationConfigError
from bot.web.translation_service import TranslationService, get_translation_service


def register(app: web.Application, server, *, service: TranslationService | None = None) -> None:
    translation_service = service if service is not None else get_translation_service()

    async def get_config(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        return web.json_response({"ok": True, "data": translation_service.config_store.get_public_config()})

    async def patch_config(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        body = await server._parse_json(request)
        try:
            data = translation_service.config_store.update(body)
        except TranslationConfigError as exc:
            raise WebApiError(exc.status, exc.code, exc.message) from None
        return web.json_response({"ok": True, "data": data})

    app.router.add_get("/api/admin/chat-translation/config", get_config)
    app.router.add_patch("/api/admin/chat-translation/config", patch_config)

    def bot_config(alias, auth):
        profile = get_profile_or_raise(server.manager, alias)
        config = translation_service.config_store.get_config()
        return {
            "enabled": profile.chat_translation_enabled,
            "global_translate_user_enabled": config.translate_user_enabled,
            "global_translate_assistant_enabled": config.translate_assistant_enabled,
            "can_edit": server._is_local_admin(auth) or auth.role == "member",
        }

    async def get_bot_config(request: web.Request) -> web.Response:
        auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        return web.json_response({"ok": True, "data": bot_config(server._manager_alias(request), auth)})

    async def patch_bot_config(request: web.Request) -> web.Response:
        auth = await server._with_bot_config_access(request)
        alias = server._manager_alias(request)
        get_profile_or_raise(server.manager, alias)
        body = await server._parse_json(request)
        if not isinstance(body, dict) or set(body) != {"enabled"} or not isinstance(body["enabled"], bool):
            raise WebApiError(400, "invalid_translation_config", "仅支持布尔值 enabled")
        await server.manager.set_bot_chat_translation(alias, body["enabled"])
        return web.json_response({"ok": True, "data": bot_config(alias, auth)})

    app.router.add_get("/api/bots/{alias}/chat-translation", get_bot_config)
    app.router.add_patch("/api/bots/{alias}/chat-translation", patch_bot_config)

    async def retry_answer(request: web.Request) -> web.Response:
        from bot.web.api_service import get_answer_translation_retry_target

        auth = await server._with_capability(request, CAP_CHAT_SEND)
        alias = server._manager_alias(request)
        profile = get_profile_or_raise(server.manager, alias)
        config = translation_service.config_store.get_config()
        if not profile.chat_translation_enabled or not config.translate_assistant_enabled or not config.configured:
            raise WebApiError(409, "translation_unavailable", "回答翻译当前不可用")
        message_id = request.match_info["message_id"]
        agent_id = server._request_agent_id(request)
        if agent_id != "main":
            raise WebApiError(404, "message_not_found", "未找到对应回答")
        user_id = server._chat_user_id(auth)
        history, message = await run_chat_store_io(
            get_answer_translation_retry_target, server.manager, alias, user_id, message_id,
            agent_id=agent_id, execution_mode=server._request_execution_mode(request, include_body=False),
            write_key=f"{alias}:{user_id}:{agent_id}",
        )
        if message is None:
            raise WebApiError(404, "message_not_found", "未找到对应回答")
        if message["role"] != "assistant" or message["state"] != "done" or (message.get("translation") or {}).get("status") != "failed":
            raise WebApiError(409, "translation_not_failed", "仅可重试翻译失败的最终回答")
        text = message["content"]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        async def update(translation: dict) -> bool:
            return await asyncio.to_thread(
                history.update_message_translation, message_id, source_digest=digest,
                translation=translation, retry_failed_answer=True,
            )

        if not translation_service.submit_answer(text=text, config=config, message_id=message_id, update=update, retry=True):
            raise WebApiError(409, "translation_busy", "翻译任务暂时无法启动，请稍后重试")
        return web.json_response({"ok": True, "data": {
            "status": "pending", "target_language": PROMPT_TARGET_LANGUAGE, "source_digest": digest,
        }})

    app.router.add_post("/api/bots/{alias}/history/{message_id}/translation/retry", retry_answer)
