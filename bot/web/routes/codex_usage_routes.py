"""Codex provider daily usage administration routes."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from aiohttp import web

from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.routes.app_keys import SERVER_APP_KEY


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9]\d*$")
_MAX_PROVIDER_KEYS = 100
_MAX_PROVIDER_KEY_LENGTH = 256
_DEFAULT_DAILY_PAGE = 1
_DEFAULT_DAILY_PAGE_SIZE = 10
_MAX_DAILY_PAGE_SIZE = 100


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


def _provider_keys(request: web.Request) -> list[str]:
    values = [str(item or "").strip() for item in request.query.getall("provider", [])]
    if len(values) > _MAX_PROVIDER_KEYS:
        raise WebApiError(400, "invalid_provider", "provider 数量不能超过 100")
    if any(not item or len(item) > _MAX_PROVIDER_KEY_LENGTH for item in values):
        raise WebApiError(400, "invalid_provider", "provider 参数无效")
    return list(dict.fromkeys(values))


def _daily_pagination(request: web.Request) -> tuple[int, int]:
    def _positive_integer(name: str, *, default: int, maximum: int | None = None) -> int:
        raw_value = request.query.get(name)
        if raw_value is None:
            return default
        value = str(raw_value).strip()
        if not _POSITIVE_INTEGER_RE.fullmatch(value):
            raise WebApiError(400, "invalid_daily_pagination", f"{name} 必须是正整数")
        try:
            parsed = int(value)
        except ValueError as exc:
            raise WebApiError(400, "invalid_daily_pagination", f"{name} 必须是正整数") from exc
        if maximum is not None and parsed > maximum:
            raise WebApiError(
                400,
                "invalid_daily_pagination",
                f"{name} 不能超过 {maximum}",
            )
        return parsed

    return (
        _positive_integer("daily_page", default=_DEFAULT_DAILY_PAGE),
        _positive_integer(
            "daily_page_size",
            default=_DEFAULT_DAILY_PAGE_SIZE,
            maximum=_MAX_DAILY_PAGE_SIZE,
        ),
    )


async def get_config(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    return _json({"ok": True, "data": await server.codex_usage_service.config_snapshot()})


async def patch_config(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    payload = await _json_object(request)
    enabled = payload.get("enabled")
    if type(enabled) is not bool:
        raise WebApiError(400, "invalid_enabled", "enabled 必须是 JSON boolean")
    return _json({"ok": True, "data": await server.codex_usage_service.update_enabled(enabled)})


async def get_stats(request: web.Request) -> web.Response:
    server = _server(request)
    await server._with_capability(request, CAP_ADMIN_OPS)
    start_date, end_date = _date_range(request)
    provider_keys = _provider_keys(request)
    daily_page, daily_page_size = _daily_pagination(request)
    try:
        data = await server.codex_usage_service.query_stats(
            start_date=start_date,
            end_date=end_date,
            provider_keys=provider_keys,
            daily_page=daily_page,
            daily_page_size=daily_page_size,
        )
    except ValueError as exc:
        raise WebApiError(400, "invalid_provider", str(exc)) from exc
    return _json({"ok": True, "data": data})


def register(app: web.Application, server) -> None:
    app[SERVER_APP_KEY] = server
    app.router.add_get("/api/admin/codex-usage/config", get_config)
    app.router.add_patch("/api/admin/codex-usage/config", patch_config)
    app.router.add_get("/api/admin/codex-usage/stats", get_stats)
