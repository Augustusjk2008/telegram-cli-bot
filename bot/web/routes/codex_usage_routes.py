"""Quota administration routes for the supported usage providers."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from typing import Any

from aiohttp import web

from bot.codex_usage.transfer import SampleDocumentError
from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.routes.app_keys import SERVER_APP_KEY


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _server(request: web.Request):
    return request.app[SERVER_APP_KEY]


async def _json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise WebApiError(400, "invalid_json", "请求体不是合法 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise WebApiError(400, "invalid_json", "请求体必须是 JSON 对象")
    return payload


def _date_range(request: web.Request) -> tuple[date | None, date | None]:
    raw_start = str(request.query.get("start_date") or "").strip()
    raw_end = str(request.query.get("end_date") or "").strip()
    if bool(raw_start) != bool(raw_end):
        raise WebApiError(400, "invalid_date_range", "必须同时提供开始日期和结束日期")
    if not raw_start:
        return None, None
    if not _DATE_RE.fullmatch(raw_start) or not _DATE_RE.fullmatch(raw_end):
        raise WebApiError(400, "invalid_date_range", "日期必须使用 YYYY-MM-DD 格式")
    try:
        start = date.fromisoformat(raw_start)
        end = date.fromisoformat(raw_end)
    except ValueError as exc:
        raise WebApiError(400, "invalid_date_range", "日期无效") from exc
    if start > end:
        raise WebApiError(400, "invalid_date_range", "开始日期不能晚于结束日期")
    return start, end


async def get_config(request: web.Request) -> web.Response:
    return await _get_config(request, "codex")


async def _get_config(request: web.Request, provider: str) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    return _json({
        "ok": True,
        "data": await server.codex_usage_service.config_snapshot(provider=provider),
    })


async def patch_config(request: web.Request) -> web.Response:
    return await _patch_config(request, "codex")


async def _patch_config(request: web.Request, provider: str) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    payload = await _json_object(request)
    enabled = payload.get("enabled")
    if type(enabled) is not bool:
        raise WebApiError(400, "invalid_enabled", "enabled 必须是 JSON boolean")
    return _json({
        "ok": True,
        "data": await server.codex_usage_service.update_enabled(enabled, provider),
    })


async def get_stats(request: web.Request) -> web.Response:
    return await _get_stats(request, "codex")


async def _get_stats(request: web.Request, provider: str) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    start_date, end_date = _date_range(request)
    data = await server.codex_usage_service.query_stats(
        start_date=start_date,
        end_date=end_date,
        provider=provider,
    )
    return _json({"ok": True, "data": data})


async def get_claude_config(request: web.Request) -> web.Response:
    return await _get_config(request, "claude")


async def patch_claude_config(request: web.Request) -> web.Response:
    return await _patch_config(request, "claude")


async def get_claude_stats(request: web.Request) -> web.Response:
    return await _get_stats(request, "claude")


async def export_samples(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    # Exports follow the queried range instead of dumping the whole history.
    start_date, end_date = _date_range(request)
    if start_date is None or end_date is None:
        raise WebApiError(400, "invalid_date_range", "导出额度样本必须提供开始日期和结束日期")
    data = await server.codex_usage_service.export_samples(start_date=start_date, end_date=end_date)
    # A long history serializes to megabytes; keep that off the event loop.
    body = await asyncio.to_thread(
        json.dumps,
        {"ok": True, "data": data},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    response = web.Response(text=body, content_type="application/json")
    response.enable_compression()
    return response


async def import_samples(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    body = await request.read()
    try:
        document = await asyncio.to_thread(json.loads, body)
    except (RecursionError, ValueError) as exc:
        raise WebApiError(400, "invalid_json", "导入文件不是合法 JSON") from exc
    try:
        data = await server.codex_usage_service.import_samples(document)
    except SampleDocumentError as exc:
        raise WebApiError(400, "invalid_usage_samples", str(exc)) from exc
    return _json({"ok": True, "data": data})


async def delete_imported_samples(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    data = await server.codex_usage_service.delete_imported_samples()
    return _json({"ok": True, "data": data})


def register(app: web.Application, server) -> None:
    app[SERVER_APP_KEY] = server
    app.router.add_get("/api/admin/codex-usage/config", get_config)
    app.router.add_patch("/api/admin/codex-usage/config", patch_config)
    app.router.add_get("/api/admin/codex-usage/stats", get_stats)
    app.router.add_get("/api/admin/claude-usage/config", get_claude_config)
    app.router.add_patch("/api/admin/claude-usage/config", patch_claude_config)
    app.router.add_get("/api/admin/claude-usage/stats", get_claude_stats)
    app.router.add_get("/api/admin/usage-samples/export", export_samples)
    app.router.add_post("/api/admin/usage-samples/import", import_samples)
    app.router.add_delete("/api/admin/usage-samples/imported", delete_imported_samples)
