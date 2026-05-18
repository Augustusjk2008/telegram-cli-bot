from __future__ import annotations

import json
from typing import Any

from aiohttp import WSMsgType, web

from bot.web.auth_store import CAP_ADMIN_OPS, CAP_CHAT_SEND, CAP_VIEW_CHAT_HISTORY
from bot.web.lan_chat_types import LanChatError


def _json(data: object, status: int = 200) -> web.Response:
    response = web.json_response({"ok": True, "data": data}, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _lan_error_response(exc: LanChatError) -> web.HTTPException:
    body = json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False)
    if exc.status == 401:
        return web.HTTPUnauthorized(text=body, content_type="application/json")
    if exc.status == 403:
        return web.HTTPForbidden(text=body, content_type="application/json")
    if exc.status == 404:
        return web.HTTPNotFound(text=body, content_type="application/json")
    if exc.status == 503:
        return web.HTTPServiceUnavailable(text=body, content_type="application/json")
    return web.HTTPBadRequest(text=body, content_type="application/json")


def _raise_lan_error(exc: LanChatError) -> None:
    raise _lan_error_response(exc)


async def get_admin_config(request: web.Request) -> web.Response:
    server = request.app["server"]
    await server._with_capability(request, CAP_ADMIN_OPS)
    return _json(server.lan_chat_service.public_config())


async def patch_admin_config(request: web.Request) -> web.Response:
    server = request.app["server"]
    await server._with_capability(request, CAP_ADMIN_OPS)
    payload = await server._parse_json(request)
    try:
        return _json(server.lan_chat_service.update_config(payload))
    except LanChatError as exc:
        _raise_lan_error(exc)


async def get_status(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
    return _json(server.lan_chat_service.status_for_user(auth))


async def get_conversations(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
    user = server.lan_chat_service.local_user(auth)
    return _json({"items": server.lan_chat_service.list_conversations(user)})


async def post_private_conversation(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_CHAT_SEND)
    payload = await server._parse_json(request)
    target_room_user_id = str(payload.get("target_room_user_id") or "")
    user = server.lan_chat_service.local_user(auth)
    try:
        return _json(server.lan_chat_service.ensure_dm(user.room_user_id, target_room_user_id))
    except LanChatError as exc:
        _raise_lan_error(exc)


async def get_messages(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
    user = server.lan_chat_service.local_user(auth)
    try:
        after_seq = int(request.query.get("after_seq") or 0)
        limit = int(request.query.get("limit") or 50)
    except ValueError as exc:
        raise web.HTTPBadRequest(text='{"ok":false,"error":{"code":"invalid_lan_chat_query","message":"查询参数无效"}}') from exc
    try:
        return _json(
            {
                "items": server.lan_chat_service.list_messages(
                    user,
                    request.match_info["conversation_id"],
                    after_seq=after_seq,
                    limit=limit,
                )
            }
        )
    except LanChatError as exc:
        _raise_lan_error(exc)


async def post_message(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_CHAT_SEND)
    payload = await server._parse_json(request)
    user = server.lan_chat_service.local_user(auth)
    try:
        message = await server.lan_chat_service.send_message(
            user,
            request.match_info["conversation_id"],
            payload.get("text"),
        )
        return _json(message)
    except LanChatError as exc:
        _raise_lan_error(exc)


async def post_read(request: web.Request) -> web.Response:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
    payload = await server._parse_json(request)
    user = server.lan_chat_service.local_user(auth)
    try:
        return _json(server.lan_chat_service.mark_read(user, request.match_info["conversation_id"], int(payload.get("seq") or 0)))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text='{"ok":false,"error":{"code":"invalid_lan_chat_read","message":"已读位置无效"}}') from exc
    except LanChatError as exc:
        _raise_lan_error(exc)


async def browser_ws(request: web.Request) -> web.WebSocketResponse:
    server = request.app["server"]
    auth = await server._with_capability(request, CAP_VIEW_CHAT_HISTORY)
    user = server.lan_chat_service.local_user(auth)
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    service = server.lan_chat_service
    service.add_browser_socket(ws, user.room_user_id)
    await ws.send_json({"type": "snapshot", "status": service.status_for_user(auth)})
    try:
        async for message in ws:
            if message.type == WSMsgType.ERROR:
                break
    finally:
        if service.remove_browser_socket(ws):
            await service.broadcast_event({"type": "presence_updated"})
    return ws


def _require_node_key(request: web.Request) -> None:
    server = request.app["server"]
    expected = str(server.lan_chat_service.config().get("room_key") or "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or provided != expected:
        body = json.dumps(
            {"ok": False, "error": {"code": "lan_chat_node_unauthorized", "message": "联机聊天节点未授权"}},
            ensure_ascii=False,
        )
        raise web.HTTPUnauthorized(text=body, content_type="application/json")


async def post_node_message(request: web.Request) -> web.Response:
    _require_node_key(request)
    server = request.app["server"]
    payload = await server._parse_json(request)
    try:
        message = server.lan_chat_service.append_node_message(
            request.match_info["conversation_id"],
            payload["sender"] if isinstance(payload.get("sender"), dict) else {},
            payload.get("text"),
        )
        await server.lan_chat_service.broadcast_event({"type": "message_created", "message": message})
        return _json(message)
    except (KeyError, LanChatError) as exc:
        if isinstance(exc, LanChatError):
            _raise_lan_error(exc)
        _raise_lan_error(LanChatError(400, "invalid_lan_chat_node_payload", "节点消息无效"))


async def node_ws(request: web.Request) -> web.WebSocketResponse:
    _require_node_key(request)
    server = request.app["server"]
    instance_id = str(request.headers.get("X-Lan-Chat-Instance-Id") or request.query.get("instance_id") or "").strip()
    if not instance_id:
        raise web.HTTPBadRequest(text='{"ok":false,"error":{"code":"invalid_lan_chat_node","message":"节点无效"}}')
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    service = server.lan_chat_service
    service.add_node_socket(instance_id, ws)
    await ws.send_json({"type": "snapshot", "status": {"mode": service.config().get("mode"), "connected": True}})
    try:
        async for message in ws:
            if message.type == WSMsgType.ERROR:
                break
    finally:
        service.remove_node_socket(instance_id, ws)
    return ws


def register(app: web.Application, server) -> None:
    if "server" not in app:
        app["server"] = server
    app.router.add_get("/api/admin/lan-chat/config", get_admin_config)
    app.router.add_patch("/api/admin/lan-chat/config", patch_admin_config)
    app.router.add_get("/api/lan-chat/status", get_status)
    app.router.add_get("/api/lan-chat/conversations", get_conversations)
    app.router.add_post("/api/lan-chat/private-conversations", post_private_conversation)
    app.router.add_get("/api/lan-chat/conversations/{conversation_id}/messages", get_messages)
    app.router.add_post("/api/lan-chat/conversations/{conversation_id}/messages", post_message)
    app.router.add_post("/api/lan-chat/conversations/{conversation_id}/read", post_read)
    app.router.add_get("/lan-chat/ws", browser_ws)
    app.router.add_post("/api/internal/lan-chat/node/conversations/{conversation_id}/messages", post_node_message)
    app.router.add_get("/lan-chat/node/ws", node_ws)
