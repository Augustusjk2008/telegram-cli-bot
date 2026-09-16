"""全局聊天翻译管理路由；由 Web 服务注册并提供现有鉴权方法。"""

from __future__ import annotations

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
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
