"""Announcement routes."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _server(request: web.Request):
    return request.app["server"]


async def _parse_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise WebApiError(400, "invalid_json", "请求体不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise WebApiError(400, "invalid_json", "请求体必须是 JSON 对象")
    return payload


async def get_announcements(request: web.Request) -> web.Response:
    server = _server(request)
    session = await server._with_auth(request)
    return _json({"ok": True, "data": server.announcement_store.list_for_user(session.account_id)})


async def post_announcements_seen(request: web.Request) -> web.Response:
    server = _server(request)
    session = await server._with_auth(request)
    payload = await _parse_json(request)
    latest_id = str(payload.get("latest_id") or payload.get("latestId") or "").strip()
    try:
        data = server.announcement_store.mark_seen(session.account_id, latest_id)
    except ValueError as exc:
        raise WebApiError(400, "invalid_announcement", str(exc)) from exc
    return _json({"ok": True, "data": data})


async def post_admin_announcement(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    payload = await _parse_json(request)
    try:
        data = server.announcement_store.upsert_item(payload)
    except ValueError as exc:
        raise WebApiError(400, "invalid_announcement", str(exc)) from exc
    return _json({"ok": True, "data": data})


async def delete_admin_announcement(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    item_id = str(request.match_info["item_id"] or "").strip()
    return _json({"ok": True, "data": {"deleted": server.announcement_store.delete_item(item_id)}})


def register(app: web.Application, server) -> None:
    app["server"] = server
    app.router.add_get("/api/announcements", get_announcements)
    app.router.add_post("/api/announcements/seen", post_announcements_seen)
    app.router.add_post("/api/admin/announcements", post_admin_announcement)
    app.router.add_delete("/api/admin/announcements/{item_id}", delete_admin_announcement)
