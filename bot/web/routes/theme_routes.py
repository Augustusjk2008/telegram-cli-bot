"""Account-owned theme routes using the host authentication context."""

from __future__ import annotations

import asyncio

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import ROLE_GUEST
from bot.web.routes.app_keys import SERVER_APP_KEY
from bot.web.theme_store import ThemeStoreError


async def _dispatch(request: web.Request, operation: str) -> web.Response:
    server = request.app[SERVER_APP_KEY]
    auth = await server._with_auth(request)
    expected_account = request.headers.get("X-UI-Account-ID", "")
    if expected_account and expected_account != auth.account_id:
        raise WebApiError(409, "theme_account_changed", "登录账户已在其他页面切换，请刷新页面后管理主题")
    guest = auth.role == ROLE_GUEST or auth.account_id == "guest"
    try:
        if operation == "list":
            data = await asyncio.to_thread(server.theme_store.list_for_account, auth.account_id, guest=guest)
        else:
            if guest:
                raise WebApiError(403, "theme_readonly", "请登录正式账户后管理个人主题")
            payload = await server._parse_json(request)
            method = getattr(server.theme_store, operation)
            args = [auth.account_id]
            if operation in {"update", "delete"}:
                args.append(request.match_info["theme_id"])
            data = await asyncio.to_thread(method, *args, payload)
    except ThemeStoreError as exc:
        raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc
    return web.json_response({"ok": True, "data": {**data, "accountId": auth.account_id}})


async def get_themes(request: web.Request) -> web.Response:
    return await _dispatch(request, "list")


async def post_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "create")


async def patch_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "update")


async def delete_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "delete")


async def patch_selection(request: web.Request) -> web.Response:
    return await _dispatch(request, "select")


def register(app: web.Application, server) -> None:
    app[SERVER_APP_KEY] = server
    app.router.add_get("/api/ui/themes", get_themes)
    app.router.add_post("/api/ui/themes", post_theme)
    app.router.add_patch("/api/ui/themes/{theme_id}", patch_theme)
    app.router.add_delete("/api/ui/themes/{theme_id}", delete_theme)
    app.router.add_patch("/api/ui/theme-selection", patch_selection)
