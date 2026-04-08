"""aiohttp Web API 服务器。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.config import (
    ALLOWED_USER_IDS,
    WEB_ALLOWED_ORIGINS,
    WEB_API_TOKEN,
    WEB_DEFAULT_USER_ID,
    WEB_HOST,
    WEB_PORT,
    request_restart,
)
from bot.manager import MultiBotManager
from .api_service import (
    AuthContext,
    WebApiError,
    add_managed_bot,
    add_memory,
    build_bot_summary,
    change_working_directory,
    clear_memories,
    delete_memory,
    execute_shell_command,
    get_directory_listing,
    get_file_metadata,
    get_history,
    get_memory_tool_stats,
    get_overview,
    get_processing_sessions,
    get_working_directory,
    kill_user_process,
    list_bots,
    list_memories,
    list_system_scripts,
    read_file_content,
    remove_managed_bot,
    reset_user_session,
    run_chat,
    run_system_script,
    save_uploaded_file,
    search_memories,
    start_managed_bot,
    stop_managed_bot,
    stream_chat,
    update_bot_cli,
    update_bot_workdir,
)

logger = logging.getLogger(__name__)


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def _error_response(exc: WebApiError) -> web.Response:
    return _json({"ok": False, "error": {"code": exc.code, "message": exc.message}}, status=exc.status)


def _normalize_origin(origin: str) -> str:
    return origin.rstrip("/")


def _format_sse(event_type: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except WebApiError as exc:
        return _error_response(exc)
    except web.HTTPException:
        raise
    except Exception as exc:
        logger.exception("Web API 未处理异常: %s", exc)
        return _json(
            {"ok": False, "error": {"code": "internal_error", "message": str(exc)}},
            status=500,
        )


@web.middleware
async def cors_middleware(request: web.Request, handler):
    # 处理 OPTIONS 预检请求
    if request.method == "OPTIONS":
        response = web.Response(status=204)
        origin = request.headers.get("Origin", "")
        normalized = {_normalize_origin(item) for item in WEB_ALLOWED_ORIGINS}
        if "*" in normalized:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
        elif origin and _normalize_origin(origin) in normalized:
            response.headers["Access-Control-Allow-Origin"] = origin
        
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Token, X-User-Id"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
    
    response = await handler(request)

    origin = request.headers.get("Origin", "")
    normalized = {_normalize_origin(item) for item in WEB_ALLOWED_ORIGINS}
    if "*" in normalized and origin:
        response.headers["Access-Control-Allow-Origin"] = origin
    elif origin and _normalize_origin(origin) in normalized:
        response.headers["Access-Control-Allow-Origin"] = origin
    elif not origin and "*" in normalized:
        response.headers["Access-Control-Allow-Origin"] = "*"

    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Token, X-User-Id"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


class WebApiServer:
    """可嵌入现有进程的 Web API 服务器。"""

    def __init__(self, manager: MultiBotManager):
        self.manager = manager
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def _auth_context(self, request: web.Request) -> AuthContext:
        raw_token = ""
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            raw_token = auth_header[7:].strip()
        if not raw_token:
            raw_token = request.headers.get("X-API-Token", "").strip()
        if WEB_API_TOKEN and raw_token != WEB_API_TOKEN:
            raise WebApiError(401, "unauthorized", "访问令牌无效")

        raw_user_id = request.headers.get("X-User-Id", "").strip() or request.query.get("user_id", "").strip()
        if raw_user_id:
            try:
                user_id = int(raw_user_id)
            except ValueError as exc:
                raise WebApiError(400, "invalid_user_id", "X-User-Id 必须是整数") from exc
        else:
            user_id = WEB_DEFAULT_USER_ID

        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            raise WebApiError(403, "forbidden", f"用户 {user_id} 未授权")

        return AuthContext(user_id=user_id, token_used=bool(raw_token))

    async def _parse_json(self, request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except json.JSONDecodeError as exc:
            raise WebApiError(400, "invalid_json", "请求体不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise WebApiError(400, "invalid_json", "请求体必须是 JSON 对象")
        return data

    async def _with_auth(self, request: web.Request) -> AuthContext:
        auth = self._auth_context(request)
        request["auth"] = auth
        return auth

    def _manager_alias(self, request: web.Request) -> str:
        alias = request.match_info.get("alias", "").strip().lower()
        if not alias:
            raise WebApiError(400, "missing_alias", "缺少 Bot 别名")
        return alias

    async def health(self, request: web.Request) -> web.Response:
        return _json(
            {
                "ok": True,
                "service": "telegram-cli-bridge-web",
                "web_enabled": True,
                "telegram_running": bool(self.manager.applications),
                "host": WEB_HOST,
                "port": WEB_PORT,
            }
        )

    async def auth_me(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json(
            {
                "ok": True,
                "data": {
                    "user_id": auth.user_id,
                    "token_protected": bool(WEB_API_TOKEN),
                    "allowed_user_ids": ALLOWED_USER_IDS,
                },
            }
        )

    async def get_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json({"ok": True, "data": list_bots(self.manager, auth.user_id)})

    async def get_bot_overview(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_overview(self.manager, alias, auth.user_id)})

    async def post_chat(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await run_chat(self.manager, alias, auth.user_id, body.get("message", ""))
        return _json({"ok": True, "data": data})

    async def post_chat_stream(self, request: web.Request) -> web.StreamResponse:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        async for event in stream_chat(self.manager, alias, auth.user_id, body.get("message", "")):
            await response.write(_format_sse(event["type"], event))

        await response.write_eof()
        return response

    async def post_exec(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await execute_shell_command(self.manager, alias, auth.user_id, body.get("command", ""))
        return _json({"ok": True, "data": data})

    async def get_pwd(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_working_directory(self.manager, alias, auth.user_id)})

    async def get_ls(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_directory_listing(self.manager, alias, auth.user_id)})

    async def post_cd(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = change_working_directory(self.manager, alias, auth.user_id, body.get("path", ""))
        return _json({"ok": True, "data": data})

    async def post_reset(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": reset_user_session(self.manager, alias, auth.user_id)})

    async def post_kill(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": kill_user_process(self.manager, alias, auth.user_id)})

    async def get_history_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        return _json({"ok": True, "data": get_history(self.manager, alias, auth.user_id, limit=limit)})

    async def upload_file(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
        filename = field.filename or ""
        data = await field.read(decode=False)
        result = save_uploaded_file(self.manager, alias, auth.user_id, filename, data)
        return _json({"ok": True, "data": result})

    async def download_file(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        filename = request.query.get("filename", "")
        metadata = get_file_metadata(self.manager, alias, auth.user_id, filename)
        return web.FileResponse(
            path=metadata["path"],
            headers={"Content-Disposition": f'attachment; filename="{metadata["filename"]}"'},
        )

    async def read_file(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        filename = request.query.get("filename", "")
        mode = request.query.get("mode", "cat")
        lines = int(request.query.get("lines", "20"))
        data = read_file_content(self.manager, alias, auth.user_id, filename, mode=mode, lines=lines)
        return _json({"ok": True, "data": data})

    async def get_memories(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json({"ok": True, "data": list_memories(auth.user_id)})

    async def post_memory(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        body = await self._parse_json(request)
        data = add_memory(
            auth.user_id,
            body.get("content", ""),
            category=body.get("category", "other"),
            tags=body.get("tags", []),
        )
        return _json({"ok": True, "data": data})

    async def search_memory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        keyword = request.query.get("keyword", "")
        category = request.query.get("category") or None
        limit = int(request.query.get("limit", "10"))
        data = search_memories(auth.user_id, keyword=keyword, category=category, limit=limit)
        return _json({"ok": True, "data": data})

    async def delete_memory_view(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        memory_id = request.match_info.get("memory_id", "")
        return _json({"ok": True, "data": delete_memory(memory_id)})

    async def clear_memory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json({"ok": True, "data": clear_memories(auth.user_id)})

    async def tool_stats(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        return _json({"ok": True, "data": get_memory_tool_stats()})

    async def admin_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json({"ok": True, "data": list_bots(self.manager, auth.user_id)})
    
    async def admin_scripts(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        return _json({"ok": True, "data": list_system_scripts()})

    async def admin_run_script(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        body = await self._parse_json(request)
        data = await run_system_script(body.get("script_name", ""))
        return _json({"ok": True, "data": data})

    async def admin_processing(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_processing_sessions(alias)})

    async def admin_add_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        body = await self._parse_json(request)
        data = await add_managed_bot(
            self.manager,
            alias=body.get("alias", ""),
            token=body.get("token", ""),
            bot_mode=body.get("bot_mode", "cli"),
            cli_type=body.get("cli_type"),
            cli_path=body.get("cli_path"),
            working_dir=body.get("working_dir"),
        )
        return _json({"ok": True, "data": data})

    async def admin_remove_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await remove_managed_bot(self.manager, alias)})

    async def admin_start_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await start_managed_bot(self.manager, alias)})

    async def admin_stop_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await stop_managed_bot(self.manager, alias)})

    async def admin_update_cli(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_cli(
            self.manager,
            alias=alias,
            cli_type=body.get("cli_type", ""),
            cli_path=body.get("cli_path", ""),
        )
        return _json({"ok": True, "data": data})

    async def admin_update_workdir(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_workdir(self.manager, alias, body.get("working_dir", ""))
        return _json({"ok": True, "data": data})

    async def admin_restart(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        request_restart()
        return _json({"ok": True, "data": {"restart_requested": True}})

    async def admin_single_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": {"bot": build_bot_summary(self.manager, alias)}})

    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[cors_middleware, error_middleware], client_max_size=25 * 1024 * 1024)
        app.router.add_get("/api/health", self.health)
        app.router.add_get("/api/auth/me", self.auth_me)
        app.router.add_get("/api/bots", self.get_bots)
        app.router.add_get("/api/bots/{alias}", self.get_bot_overview)
        app.router.add_post("/api/bots/{alias}/chat", self.post_chat)
        app.router.add_post("/api/bots/{alias}/chat/stream", self.post_chat_stream)
        app.router.add_post("/api/bots/{alias}/exec", self.post_exec)
        app.router.add_get("/api/bots/{alias}/pwd", self.get_pwd)
        app.router.add_get("/api/bots/{alias}/ls", self.get_ls)
        app.router.add_post("/api/bots/{alias}/cd", self.post_cd)
        app.router.add_post("/api/bots/{alias}/reset", self.post_reset)
        app.router.add_post("/api/bots/{alias}/kill", self.post_kill)
        app.router.add_get("/api/bots/{alias}/history", self.get_history_view)
        app.router.add_post("/api/bots/{alias}/files/upload", self.upload_file)
        app.router.add_get("/api/bots/{alias}/files/download", self.download_file)
        app.router.add_get("/api/bots/{alias}/files/read", self.read_file)
        app.router.add_get("/api/memory", self.get_memories)
        app.router.add_post("/api/memory", self.post_memory)
        app.router.add_get("/api/memory/search", self.search_memory_view)
        app.router.add_delete("/api/memory/{memory_id}", self.delete_memory_view)
        app.router.add_delete("/api/memory", self.clear_memory_view)
        app.router.add_get("/api/tool-stats", self.tool_stats)
        app.router.add_get("/api/admin/bots", self.admin_bots)
        app.router.add_get("/api/admin/scripts", self.admin_scripts)
        app.router.add_post("/api/admin/scripts/run", self.admin_run_script)
        app.router.add_get("/api/admin/bots/{alias}/processing", self.admin_processing)
        app.router.add_post("/api/admin/bots", self.admin_add_bot)
        app.router.add_get("/api/admin/bots/{alias}", self.admin_single_bot)
        app.router.add_delete("/api/admin/bots/{alias}", self.admin_remove_bot)
        app.router.add_post("/api/admin/bots/{alias}/start", self.admin_start_bot)
        app.router.add_post("/api/admin/bots/{alias}/stop", self.admin_stop_bot)
        app.router.add_patch("/api/admin/bots/{alias}/cli", self.admin_update_cli)
        app.router.add_patch("/api/admin/bots/{alias}/workdir", self.admin_update_workdir)
        app.router.add_post("/api/admin/restart", self.admin_restart)
        
        # Add static file serving for frontend when dist exists
        assets_dir = Path(self._get_static_dir("assets"))
        if assets_dir.exists():
            app.router.add_static("/assets", path=str(assets_dir), name="assets")
        app.router.add_get("/{tail:.*}", self.serve_index, name="index")
        return app
    
    def _get_static_dir(self, subdir=None):
        """Get static directory path."""
        script_dir = Path(__file__).resolve().parent.parent.parent
        static_dir = script_dir / "front" / "dist"
        if subdir:
            static_dir = static_dir / subdir
        return str(static_dir)
    
    async def serve_index(self, request):
        """Serve index.html for SPA routes."""
        index_path = Path(self._get_static_dir()) / "index.html"
        if index_path.exists():
            return web.FileResponse(str(index_path))
        return web.Response(text="Not found", status=404)

    async def start(self):
        if self._runner is not None:
            return
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=WEB_HOST, port=WEB_PORT)
        await self._site.start()
        logger.info(
            "Web API 已启动: http://%s:%s (token=%s, allowed_origins=%s)",
            WEB_HOST,
            WEB_PORT,
            "已配置" if WEB_API_TOKEN else "未配置",
            ",".join(WEB_ALLOWED_ORIGINS),
        )

    async def stop(self):
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        logger.info("Web API 已停止")
