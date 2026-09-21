"""全局与 Bot 聊天翻译设置，复用现有鉴权。"""

from __future__ import annotations

from aiohttp import web

from bot.web.api_common import WebApiError, get_profile_or_raise
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_VIEW_CHAT_HISTORY
from bot.web.translation_config import TranslationConfigError
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
