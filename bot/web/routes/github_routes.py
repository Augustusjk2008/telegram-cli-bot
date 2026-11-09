"""GitHub account and repository routes, scoped to the signed-in Web account."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_GIT_OPS
from bot.web.routes.app_keys import SERVER_APP_KEY


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


async def _context(request: web.Request):
    server = request.app[SERVER_APP_KEY]
    auth = await server._with_capability(request, CAP_GIT_OPS)
    return server, auth


async def get_account(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    return _json({"ok": True, "data": await server.github_service.account_status(auth.account_id)})


async def connect_with_token(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    body = await server._parse_json(request)
    data = await server.github_service.connect_with_token(auth.account_id, body.get("token"))
    return _json({"ok": True, "data": data})


async def disconnect(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    return _json({"ok": True, "data": await server.github_service.disconnect(auth.account_id)})


async def start_device_flow(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    return _json({"ok": True, "data": await server.github_service.start_device_flow(auth.account_id)})


async def poll_device_flow(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    data = await server.github_service.poll_device_flow(auth.account_id, request.match_info.get("flow_id", ""))
    return _json({"ok": True, "data": data})


async def list_repositories(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    data = await server.github_service.list_repositories(auth.account_id, page=request.query.get("page", "1"))
    return _json({"ok": True, "data": data})


async def list_owners(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    return _json({"ok": True, "data": await server.github_service.list_owners(auth.account_id)})


async def create_repository(request: web.Request) -> web.Response:
    server, auth = await _context(request)
    body = await server._parse_json(request)
    private = body.get("private", True)
    if not isinstance(private, bool):
        raise WebApiError(400, "invalid_request", "private 必须是布尔值")
    data = await server.github_service.create_repository(
        auth.account_id,
        owner=body.get("owner", ""),
        name=body.get("name", ""),
        description=body.get("description", ""),
        private=private,
    )
    return _json({"ok": True, "data": data})


def register(app: web.Application, server) -> None:
    app[SERVER_APP_KEY] = server
    app.router.add_get("/api/github/account", get_account)
    app.router.add_delete("/api/github/account", disconnect)
    app.router.add_post("/api/github/account/token", connect_with_token)
    app.router.add_post("/api/github/device", start_device_flow)
    app.router.add_post("/api/github/device/{flow_id}/poll", poll_device_flow)
    app.router.add_get("/api/github/owners", list_owners)
    app.router.add_get("/api/github/repos", list_repositories)
    app.router.add_post("/api/github/repos", create_repository)
