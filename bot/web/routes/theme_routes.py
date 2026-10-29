"""Global theme routes with public login previews and authenticated mutations."""

from __future__ import annotations

import asyncio

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import ROLE_GUEST
from bot.web.routes.app_keys import SERVER_APP_KEY
from bot.web.theme_asset_store import ThemeAssetStoreError
from bot.web.theme_store import ThemeStoreError


async def _dispatch(request: web.Request, operation: str) -> web.Response:
    server = request.app[SERVER_APP_KEY]
    auth = None if operation == "public_list" else await server._with_auth(request)
    try:
        if operation in {"list", "public_list"}:
            data = await asyncio.to_thread(server.theme_store.list_library)
        else:
            if auth.role == ROLE_GUEST or auth.account_id == "guest":
                raise WebApiError(403, "theme_readonly", "请登录正式账户后管理主题")
            payload = await server._parse_json(request)
            method = getattr(server.theme_store, operation)
            args = []
            if operation in {"update", "delete"}:
                args.append(request.match_info["theme_id"])
            data = await asyncio.to_thread(method, *args, payload)
    except ThemeStoreError as exc:
        raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc
    return web.json_response({"ok": True, "data": data})


async def get_themes(request: web.Request) -> web.Response:
    return await _dispatch(request, "list")


async def get_public_themes(request: web.Request) -> web.Response:
    return await _dispatch(request, "public_list")


async def post_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "create")


async def post_import(request: web.Request) -> web.Response:
    return await _dispatch(request, "import_themes")


async def patch_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "update")


async def delete_theme(request: web.Request) -> web.Response:
    return await _dispatch(request, "delete")


async def patch_selection(request: web.Request) -> web.Response:
    return await _dispatch(request, "select")


async def post_asset(request: web.Request) -> web.Response:
    server = request.app[SERVER_APP_KEY]
    auth = await server._with_auth(request)
    if auth.role == ROLE_GUEST or auth.account_id == "guest":
        raise WebApiError(403, "theme_readonly", "请登录正式账户后管理主题")
    try:
        mime_type = ""
        data: bytes | None = None
        if request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file":
                raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
            mime_type = str(field.headers.get("Content-Type") or "")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = await field.read_chunk(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 4 * 1024 * 1024:
                    raise WebApiError(413, "theme_asset_too_large", "单张插画不能超过 4 MiB")
                chunks.append(chunk)
            data = b"".join(chunks)
        else:
            body = await server._parse_json(request)
            mime_type = str(body.get("mimeType") or "")
            encoded = body.get("data")
            if not isinstance(encoded, str) or not encoded.startswith("data:"):
                raise WebApiError(400, "invalid_theme_asset", "上传插画数据无效")
            import base64
            _, payload = encoded.split(",", 1)
            data = base64.b64decode(payload, validate=True)
        descriptor = await asyncio.to_thread(server.theme_store.asset_store.store, data or b"", mime_type or None)
    except WebApiError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise WebApiError(400, "invalid_theme_asset", "上传插画数据无效") from exc
    except ThemeAssetStoreError as exc:
        raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc
    return web.json_response({"ok": True, "data": descriptor})


async def get_asset(request: web.Request) -> web.Response:
    server = request.app[SERVER_APP_KEY]
    try:
        data, mime_type = await asyncio.to_thread(server.theme_store.asset_store.read, request.match_info["asset_id"])
    except ThemeAssetStoreError as exc:
        raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc
    return web.Response(body=data, content_type=mime_type.split("/", 1)[1], headers={"Cache-Control": "public, max-age=31536000, immutable"})


def register(app: web.Application, server) -> None:
    app[SERVER_APP_KEY] = server
    app.router.add_get("/api/public/ui/themes", get_public_themes)
    app.router.add_get("/api/ui/themes", get_themes)
    app.router.add_post("/api/ui/themes", post_theme)
    app.router.add_post("/api/ui/themes/import", post_import)
    app.router.add_patch("/api/ui/themes/{theme_id}", patch_theme)
    app.router.add_delete("/api/ui/themes/{theme_id}", delete_theme)
    app.router.add_patch("/api/ui/theme-selection", patch_selection)
    app.router.add_post("/api/ui/theme-assets", post_asset)
    app.router.add_get("/api/ui/theme-assets/{asset_id}", get_asset)
