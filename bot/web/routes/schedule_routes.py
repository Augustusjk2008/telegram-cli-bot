"""Admin routes for scheduled agent tasks."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from bot.scheduler.service import SchedulerService, get_active_scheduler_service
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_RUN_UNSAFE_CLI


def _ok(data: Any) -> web.Response:
    return web.json_response({"ok": True, "data": data}, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def _service() -> SchedulerService:
    service = get_active_scheduler_service()
    if service is None:
        raise WebApiError(503, "scheduler_unavailable", "定时任务服务未运行")
    return service


def _actor(auth: AuthContext) -> dict[str, Any]:
    return {
        "account_id": auth.account_id,
        "username": auth.username,
        "can_allow_unsafe_cli": CAP_RUN_UNSAFE_CLI in auth.capabilities,
    }


def register(app: web.Application, server) -> None:
    async def list_schedules(request: web.Request) -> web.Response:
        auth = await server._with_capability(request, CAP_ADMIN_OPS)
        return _ok(await _service().overview(can_allow_unsafe_cli=CAP_RUN_UNSAFE_CLI in auth.capabilities))

    async def create_schedule(request: web.Request) -> web.Response:
        auth = await server._with_capability(request, CAP_ADMIN_OPS)
        body = await server._parse_json(request)
        return _ok(await _service().create(body, _actor(auth)))

    async def update_schedule(request: web.Request) -> web.Response:
        auth = await server._with_capability(request, CAP_ADMIN_OPS)
        body = await server._parse_json(request)
        return _ok(await _service().update(request.match_info["schedule_id"], body, _actor(auth)))

    async def delete_schedule(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        return _ok(await _service().delete(request.match_info["schedule_id"]))

    async def run_schedule(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        return _ok(await _service().run_now(request.match_info["schedule_id"]))

    async def list_runs(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        try:
            limit = int(str(request.query.get("limit", "20") or "20"))
        except ValueError:
            raise WebApiError(400, "invalid_request", "limit 必须是整数") from None
        return _ok(await _service().list_runs(request.match_info["schedule_id"], limit))

    async def cancel_run(request: web.Request) -> web.Response:
        await server._with_capability(request, CAP_ADMIN_OPS)
        return _ok(await _service().cancel_run(request.match_info["schedule_id"], request.match_info["run_id"]))

    app.router.add_get("/api/admin/schedules", list_schedules)
    app.router.add_post("/api/admin/schedules", create_schedule)
    app.router.add_patch("/api/admin/schedules/{schedule_id}", update_schedule)
    app.router.add_delete("/api/admin/schedules/{schedule_id}", delete_schedule)
    app.router.add_post("/api/admin/schedules/{schedule_id}/run", run_schedule)
    app.router.add_get("/api/admin/schedules/{schedule_id}/runs", list_runs)
    app.router.add_post("/api/admin/schedules/{schedule_id}/runs/{run_id}/cancel", cancel_run)
