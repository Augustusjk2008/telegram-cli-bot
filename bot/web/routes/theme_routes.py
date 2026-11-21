"""Global theme routes with public login previews and authenticated mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import ROLE_GUEST
from bot.web.routes.app_keys import SERVER_APP_KEY
from bot.web.theme_asset_store import ThemeAssetStoreError
from bot.web.theme_store import THEME_READONLY_MESSAGE, ThemeStoreError


def _themes_digest(themes: list[Any]) -> str:
    canonical = json.dumps(themes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _library_response_data(data: Any, known_digest: str) -> Any:
    """Tag the library with a digest of its themes and omit themes the client already holds.

    The theme library is a read-only set of packaged presets, so a client that sends
    the digest it cached only needs the per-account selection and revision back.
    """
    if not isinstance(data, dict) or not isinstance(data.get("themes"), list):
        return data
    digest = _themes_digest(data["themes"])
    result = {**data, "themesDigest": digest}
    if known_digest and known_digest == digest and not result.get("error"):
        result.pop("themes")
        result["themesUnchanged"] = True
    return result


def _json(data: Any) -> web.Response:
    response = web.json_response(
        {"ok": True, "data": data},
        dumps=lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )
    response.enable_compression()
    return response


async def _dispatch(request: web.Request, operation: str) -> web.Response:
    server = request.app[SERVER_APP_KEY]
    auth = None if operation == "public_list" else await server._with_auth(request)
    known_digest = str(request.query.get("themes_digest") or "").strip()
    try:
        if operation in {"list", "public_list"}:
            account_id = None if operation == "public_list" else auth.account_id

            def read_library() -> Any:
                return _library_response_data(server.theme_store.list_library(account_id), known_digest)

            data = await asyncio.to_thread(read_library)
        else:
            if auth.role == ROLE_GUEST or auth.account_id == "guest":
                raise WebApiError(403, "theme_readonly", "请登录正式账户后管理主题")
            if operation in {"create", "import_themes", "update", "delete"}:
                raise WebApiError(403, "theme_readonly", THEME_READONLY_MESSAGE)
            payload = await server._parse_json(request)
            method = getattr(server.theme_store, operation)
            args = []
            if operation in {"update", "delete"}:
                args.append(request.match_info["theme_id"])
            if operation == "select":
                def select_theme() -> Any:
                    return _library_response_data(method(payload, auth.account_id), known_digest)

                data = await asyncio.to_thread(select_theme)
            else:
                data = await asyncio.to_thread(method, *args, payload)
    except ThemeStoreError as exc:
        raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc
    return _json(data)


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
    raise WebApiError(403, "theme_readonly", THEME_READONLY_MESSAGE)


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
