"""Transfer bridge aiohttp routes."""

from __future__ import annotations

import json
import os
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.transfer_service import TransferServiceError

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Response ↔ Chat API 转接器</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; }
    main { max-width: 920px; margin: 0 auto; padding: 40px 20px; }
    h1 { color: #38bdf8; }
    code { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 2px 6px; color: #7dd3fc; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 20px; margin-top: 18px; }
  </style>
</head>
<body>
  <main>
    <h1>Response ↔ Chat API 转接器</h1>
    <p>本页面用于调试项目内置 OpenAI-compatible transfer bridge。</p>
    <div class="card">
      <p>Responses endpoint：<code>/v1/responses</code></p>
      <p>Chat Completions endpoint：<code>/v1/chat/completions</code></p>
      <p>状态 API：<code>/api/transfer/status</code></p>
    </div>
  </main>
</body>
</html>
"""


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _server(request: web.Request):
    return request.app["server"]


def _is_loopback_value(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"127.0.0.1", "::1", "localhost"} or text.startswith("127.")


def _is_loopback_request(request: web.Request) -> bool:
    if any(str(request.headers.get(name, "")).strip() for name in ("Forwarded", "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP")):
        return False
    host = str(request.headers.get("Host", "")).split(":", 1)[0].strip()
    if host and not _is_loopback_value(host):
        return False
    if _is_loopback_value(request.remote):
        return True
    transport = request.transport
    if transport is None:
        return False
    peername = transport.get_extra_info("peername")
    if isinstance(peername, tuple) and peername:
        return _is_loopback_value(peername[0])
    return _is_loopback_value(peername)


def _require_transfer_access(request: web.Request) -> None:
    expected = os.environ.get("TRANSFER_ACCESS_TOKEN", "").strip()
    if expected:
        actual = request.headers.get("X-TCB-Transfer-Token", "").strip()
        if actual != expected:
            raise WebApiError(401, "transfer_unauthorized", "Transfer token 无效")
        return
    if not _is_loopback_request(request):
        raise WebApiError(403, "transfer_loopback_required", "Transfer bridge 默认仅允许本机访问")


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise WebApiError(400, "invalid_json", "请求体不是合法 JSON") from exc
    if not isinstance(body, dict):
        raise WebApiError(400, "invalid_json", "请求体必须是 JSON 对象")
    return body


def _transfer_error(exc: TransferServiceError) -> WebApiError:
    return WebApiError(exc.status, exc.code, exc.message)


async def create_response(request: web.Request) -> web.StreamResponse | web.Response:
    _require_transfer_access(request)
    server = _server(request)
    try:
        result = await server.transfer_service.create_response(await _read_json(request))
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    if result.stream is None:
        return _json(result.data or {}, status=result.status)
    response = web.StreamResponse(status=result.status, headers=result.headers)
    response.content_type = "text/event-stream"
    await response.prepare(request)
    async for event in result.stream:
        chunk = json.dumps(event, ensure_ascii=False)
        await response.write(f"event: {event.get('type', 'message')}\ndata: {chunk}\n\n".encode("utf-8"))
    await response.write_eof()
    return response


async def proxy_chat_completions(request: web.Request) -> web.StreamResponse | web.Response:
    _require_transfer_access(request)
    server = _server(request)
    try:
        result = await server.transfer_service.proxy_chat_completions(await _read_json(request))
    except TransferServiceError as exc:
        raise _transfer_error(exc) from exc
    if result.stream is not None:
        response = web.StreamResponse(status=result.status, headers=result.headers)
        response.content_type = "text/event-stream"
        await response.prepare(request)
        async for event in result.stream:
            if event.get("type") == "__done__":
                await response.write(b"data: [DONE]\n\n")
                continue
            chunk = json.dumps(event, ensure_ascii=False)
            await response.write(f"data: {chunk}\n\n".encode("utf-8"))
        await response.write_eof()
        return response
    return _json(result.data or {}, status=result.status)


async def get_response(request: web.Request) -> web.Response:
    _require_transfer_access(request)
    response_id = str(request.match_info.get("response_id") or "")
    raise WebApiError(404, "response_not_found", f"Response not found: {response_id}")


async def delete_response(request: web.Request) -> web.Response:
    _require_transfer_access(request)
    response_id = str(request.match_info.get("response_id") or "")
    return _json({"id": response_id, "object": "response.deleted", "deleted": True})


async def health(request: web.Request) -> web.Response:
    service = _server(request).transfer_service
    return _json({"ok": True, "data": {"status": service.get_status()["status"], "enabled": service.config.enabled}})


async def status(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_auth(request)
    return _json({"ok": True, "data": server.transfer_service.get_status(base_path=server._web_base_path())})


async def page(request: web.Request) -> web.Response:
    return web.Response(text=HTML_PAGE, content_type="text/html")


async def reset(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    return _json({"ok": True, "data": server.transfer_service.reset_stats()})


async def config(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    data = server.transfer_service.update_config(await _read_json(request))
    return _json({"ok": True, "data": data})


def register(app: web.Application, server) -> None:
    app["server"] = server
    app.router.add_post("/v1/responses", create_response)
    app.router.add_post("/responses", create_response)
    app.router.add_get("/v1/responses/{response_id}", get_response)
    app.router.add_get("/responses/{response_id}", get_response)
    app.router.add_delete("/v1/responses/{response_id}", delete_response)
    app.router.add_delete("/responses/{response_id}", delete_response)
    app.router.add_post("/v1/chat/completions", proxy_chat_completions)
    app.router.add_post("/chat/completions", proxy_chat_completions)
    app.router.add_get("/api/transfer/health", health)
    app.router.add_get("/api/transfer/status", status)
    app.router.add_get("/api/transfer/page", page)
    app.router.add_post("/api/admin/transfer/reset", reset)
    app.router.add_patch("/api/admin/transfer/config", config)
