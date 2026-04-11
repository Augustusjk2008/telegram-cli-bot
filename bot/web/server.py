"""aiohttp Web API 服务器。"""

from __future__ import annotations

import asyncio
import json
import html
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, WSCloseCode, web
from aiohttp.client_exceptions import ClientConnectionResetError

from bot.app_settings import get_git_proxy_settings, update_git_proxy_port
from bot.config import (
    ALLOWED_USER_IDS,
    WEB_ALLOWED_ORIGINS,
    WEB_API_TOKEN,
    WEB_DEFAULT_USER_ID,
    WEB_HOST,
    WEB_PORT,
    WEB_PUBLIC_URL,
    WEB_TUNNEL_AUTOSTART,
    WEB_TUNNEL_CLOUDFLARED_PATH,
    WEB_TUNNEL_MODE,
    WEB_TUNNEL_STATE_FILE,
    request_restart,
)
from bot.manager import MultiBotManager
from bot.handlers.tui_server import create_shell_process
from bot.platform.runtime import get_default_shell
from .tunnel_service import TunnelService
from .api_service import (
    approve_assistant_proposal,
    apply_assistant_upgrade,
    AuthContext,
    WebApiError,
    add_managed_bot,
    build_bot_summary,
    change_working_directory,
    create_directory,
    delete_path,
    execute_shell_command,
    get_directory_listing,
    get_file_metadata,
    get_history,
    get_overview,
    list_assistant_proposals,
    get_cli_params_payload,
    get_processing_sessions,
    get_working_directory,
    kill_user_process,
    list_bots,
    list_system_scripts,
    read_file_content,
    remove_managed_bot,
    reject_assistant_proposal,
    reset_user_session,
    reset_cli_params,
    run_chat,
    run_system_script,
    save_uploaded_file,
    start_managed_bot,
    stop_managed_bot,
    stream_system_script,
    stream_chat,
    update_cli_params,
    update_bot_cli,
    rename_managed_bot,
    update_bot_workdir,
)
from .git_service import (
    commit_git_changes,
    fetch_git_remote,
    get_git_diff,
    get_git_overview,
    init_git_repository,
    pop_git_stash,
    pull_git_remote,
    push_git_remote,
    stage_git_paths,
    stash_git_changes,
    unstage_git_paths,
)

logger = logging.getLogger(__name__)
# 给浏览器留出响应落地时间，避免服务重启过快导致前端请求悬挂。
RESTART_RESPONSE_DELAY_SECONDS = 1.0
_TERMINAL_OUTPUT_EOF = object()


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def _error_response(exc: WebApiError) -> web.Response:
    return _json({"ok": False, "error": {"code": exc.code, "message": exc.message}}, status=exc.status)


def _normalize_origin(origin: str) -> str:
    return origin.rstrip("/")


def _format_sse(event_type: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


class _TerminalOutputPump:
    """用 daemon 线程读取终端输出，避免阻塞读把主进程退出卡住。"""

    def __init__(self, process: Any):
        self._process = process
        self._queue: asyncio.Queue[bytes | object] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None:
            return

        self._loop = loop
        self._thread = threading.Thread(
            target=self._run,
            name=f"terminal-output-{getattr(self._process, 'pid', 'unknown')}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    async def read(self) -> bytes | object:
        return await self._queue.get()

    def _put(self, item: bytes | object) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # 事件循环正在关闭时无需再投递。
            return

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    data = self._process.read(timeout=100)
                except Exception as exc:
                    logger.debug("终端输出读取结束 pid=%s: %s", getattr(self._process, "pid", "unknown"), exc)
                    break

                if data:
                    if isinstance(data, str):
                        data = data.encode("utf-8", errors="replace")
                    self._put(data)
                    continue

                try:
                    if not self._process.isalive():
                        break
                except Exception:
                    break

                self._stop_event.wait(0.02)
        finally:
            self._put(_TERMINAL_OUTPUT_EOF)


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
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class WebApiServer:
    """可嵌入现有进程的 Web API 服务器。"""

    def __init__(self, manager: MultiBotManager, tunnel_service: TunnelService | None = None):
        self.manager = manager
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._terminal_sockets: set[web.WebSocketResponse] = set()
        self._terminal_tasks: set[asyncio.Task[Any]] = set()
        self._tunnel_service = tunnel_service or TunnelService(
            host=WEB_HOST,
            port=WEB_PORT,
            mode=WEB_TUNNEL_MODE,
            autostart=WEB_TUNNEL_AUTOSTART,
            public_url=WEB_PUBLIC_URL,
            cloudflared_path=WEB_TUNNEL_CLOUDFLARED_PATH,
            state_file=WEB_TUNNEL_STATE_FILE,
        )

    def _auth_context(self, request: web.Request) -> AuthContext:
        raw_token = ""
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            raw_token = auth_header[7:].strip()
        if not raw_token:
            raw_token = request.headers.get("X-API-Token", "").strip()
        if not raw_token:
            raw_token = request.query.get("token", "").strip()
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

    def _schedule_restart_request(self) -> None:
        if self._restart_task is not None and not self._restart_task.done():
            return

        async def delayed_restart() -> None:
            try:
                await asyncio.sleep(RESTART_RESPONSE_DELAY_SECONDS)
                request_restart()
            except asyncio.CancelledError:
                return

        self._restart_task = asyncio.create_task(delayed_restart())

    def _manager_alias(self, request: web.Request) -> str:
        alias = request.match_info.get("alias", "").strip().lower()
        if not alias:
            raise WebApiError(400, "missing_alias", "缺少 Bot 别名")
        return alias

    def _copy_text_to_clipboard(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False

        commands: list[list[str]] = []
        if os.name == "nt":
            commands.append(["clip"])
        elif sys.platform == "darwin":
            commands.append(["pbcopy"])
        else:
            commands.extend(
                [
                    ["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"],
                ]
            )

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        for command in commands:
            try:
                subprocess.run(
                    command,
                    input=value,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                    creationflags=creationflags,
                )
                return True
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.warning("复制 Web 公网地址到剪贴板失败 command=%s: %s", command[0], exc)
                return False

        logger.warning("复制 Web 公网地址到剪贴板失败: 未找到可用的剪贴板命令")
        return False

    async def _notify_tunnel_public_url(self, snapshot: dict[str, Any], *, reason: str) -> bool:
        if snapshot.get("status") != "running":
            return False
        if snapshot.get("source") != "quick_tunnel":
            return False

        public_url = str(snapshot.get("public_url") or "").strip()
        if not public_url:
            return False

        self._copy_text_to_clipboard(public_url)

        main_app = self.manager.applications.get(self.manager.main_profile.alias)
        if main_app is None or not ALLOWED_USER_IDS:
            return False

        text = (
            "🌐 <b>Web 公网地址已就绪</b>\n\n"
            f"来源: <code>{html.escape(reason)}</code>\n"
            f"公网地址: <code>{html.escape(public_url)}</code>\n"
            f"本地地址: <code>{html.escape(str(snapshot.get('local_url') or ''))}</code>"
        )

        sent_any = False
        for user_id in ALLOWED_USER_IDS:
            try:
                await main_app.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                )
                sent_any = True
            except Exception as exc:
                logger.info("发送 Web 公网地址通知失败(已忽略) user_id=%s: %s", user_id, exc)

        return sent_any

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

        client_disconnected = False
        async for event in stream_chat(self.manager, alias, auth.user_id, body.get("message", "")):
            if client_disconnected:
                continue
            try:
                await response.write(_format_sse(event["type"], event))
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                client_disconnected = True
                logger.info(
                    "Web SSE 客户端已断开，继续在后台完成任务: alias=%s user_id=%s",
                    alias,
                    auth.user_id,
                )

        if not client_disconnected:
            try:
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                logger.info(
                    "Web SSE 客户端在结束前断开: alias=%s user_id=%s",
                    alias,
                    auth.user_id,
                )
        return response

    async def post_exec(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await execute_shell_command(self.manager, alias, auth.user_id, body.get("command", ""))
        return _json({"ok": True, "data": data})

    async def terminal_ws(self, request: web.Request) -> web.WebSocketResponse:
        await self._with_auth(request)
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self._terminal_sockets.add(ws)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._terminal_tasks.add(current_task)

        process = None
        output_pump: _TerminalOutputPump | None = None
        tasks: list[asyncio.Task[Any]] = []
        try:
            init_message = await ws.receive()
            init_data: dict[str, Any] = {}
            if init_message.type == WSMsgType.TEXT:
                try:
                    parsed = json.loads(init_message.data or "{}")
                    if isinstance(parsed, dict):
                        init_data = parsed
                except json.JSONDecodeError:
                    init_data = {}

            default_shell = get_default_shell()
            shell_type = str(init_data.get("shell") or request.query.get("shell") or default_shell).strip() or default_shell
            if shell_type == "auto":
                shell_type = default_shell
            raw_cwd = str(init_data.get("cwd") or request.query.get("cwd") or os.getcwd()).strip() or os.getcwd()
            cwd = os.path.abspath(os.path.expanduser(raw_cwd))
            if not os.path.isdir(cwd):
                cwd = os.getcwd()

            force_no_pty = bool(init_data.get("no_pty", False))
            process = create_shell_process(shell_type, cwd, use_pty=not force_no_pty)
            await ws.send_json({"pty_mode": process.is_pty})
            loop = asyncio.get_running_loop()
            output_pump = _TerminalOutputPump(process)
            output_pump.start(loop)

            async def forward_output() -> None:
                while True:
                    data = await output_pump.read()
                    if data is _TERMINAL_OUTPUT_EOF:
                        break
                    await ws.send_bytes(data)

            async def forward_input() -> None:
                while not ws.closed:
                    transport = request.transport
                    if transport is None or transport.is_closing():
                        break
                    try:
                        message = await asyncio.wait_for(ws.receive(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    if message.type == WSMsgType.BINARY:
                        process.write(message.data)
                        continue

                    if message.type == WSMsgType.TEXT:
                        text = message.data or ""
                        if text.startswith("{"):
                            try:
                                payload = json.loads(text)
                            except json.JSONDecodeError:
                                payload = None
                            if isinstance(payload, dict) and payload.get("type") in {"resize", "ping"}:
                                continue
                        process.write(text.encode("utf-8"))
                        await asyncio.sleep(0)
                        continue

                    if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break

            tasks = [
                asyncio.create_task(forward_output()),
                asyncio.create_task(forward_input()),
            ]
            output_task, input_task = tasks
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

            if output_task in done and output_task.exception() is not None:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
                output_task.result()
            else:
                await input_task
                if not output_task.done():
                    output_task.cancel()
                await asyncio.gather(output_task, return_exceptions=True)
        except Exception as exc:
            logger.exception("终端 WebSocket 处理失败: %s", exc)
            if not ws.closed:
                try:
                    await ws.send_json({"error": str(exc)})
                except Exception:
                    pass
        finally:
            self._terminal_sockets.discard(ws)
            if current_task is not None:
                self._terminal_tasks.discard(current_task)
            if output_pump is not None:
                output_pump.stop()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.close()
                except Exception:
                    pass

        return ws

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

    async def get_cli_params(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        cli_type = request.query.get("cli_type") or None
        return _json({"ok": True, "data": get_cli_params_payload(self.manager, alias, cli_type)})

    async def patch_cli_params(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_cli_params(
            self.manager,
            alias=alias,
            cli_type=body.get("cli_type"),
            key=str(body.get("key", "")),
            value=body.get("value"),
        )
        return _json({"ok": True, "data": data})

    async def post_cli_params_reset(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        data = await reset_cli_params(self.manager, alias, body.get("cli_type"))
        return _json({"ok": True, "data": data})

    async def get_history_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        return _json({"ok": True, "data": get_history(self.manager, alias, auth.user_id, limit=limit)})

    async def get_git_overview_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_git_overview(self.manager, alias, auth.user_id)})

    async def post_git_init(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": init_git_repository(self.manager, alias, auth.user_id)})

    async def get_git_diff_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        path = request.query.get("path", "")
        staged = request.query.get("staged", "").strip().lower() in {"1", "true", "yes"}
        return _json({"ok": True, "data": get_git_diff(self.manager, alias, auth.user_id, path, staged=staged)})

    async def post_git_stage(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = stage_git_paths(self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已暂存所选文件", "overview": overview}})

    async def post_git_unstage(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = unstage_git_paths(self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已取消暂存所选文件", "overview": overview}})

    async def post_git_commit(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = commit_git_changes(self.manager, alias, auth.user_id, body.get("message", ""))
        return _json({"ok": True, "data": {"message": "已创建提交", "overview": overview}})

    async def post_git_fetch(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        overview = fetch_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已抓取远端更新", "overview": overview}})

    async def post_git_pull(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        overview = pull_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已拉取远端更新", "overview": overview}})

    async def post_git_push(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        overview = push_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已推送本地提交", "overview": overview}})

    async def post_git_stash(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        overview = stash_git_changes(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已暂存当前工作区", "overview": overview}})

    async def post_git_stash_pop(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        overview = pop_git_stash(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已恢复最近一次暂存", "overview": overview}})

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

    async def create_directory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = create_directory(self.manager, alias, auth.user_id, body.get("name", ""))
        return _json({"ok": True, "data": data})

    async def delete_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = delete_path(self.manager, alias, auth.user_id, body.get("path", ""))
        return _json({"ok": True, "data": data})

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

    async def admin_run_script_stream(self, request: web.Request) -> web.StreamResponse:
        await self._with_auth(request)
        body = await self._parse_json(request)
        script_name = str(body.get("script_name", ""))

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        client_disconnected = False
        async for event in stream_system_script(script_name):
            if client_disconnected:
                continue
            try:
                await response.write(_format_sse(event["type"], event))
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                client_disconnected = True
                logger.info("系统脚本 SSE 客户端已断开，继续在后台执行: script=%s", script_name)

        if not client_disconnected:
            try:
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                logger.info("系统脚本 SSE 客户端在结束前断开: script=%s", script_name)
        return response

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

    async def admin_rename_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await rename_managed_bot(self.manager, alias, str(body.get("new_alias", "")))
        return _json({"ok": True, "data": data})

    async def admin_update_workdir(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_workdir(self.manager, alias, body.get("working_dir", ""), auth.user_id)
        return _json({"ok": True, "data": data})

    async def admin_get_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        return _json({"ok": True, "data": get_git_proxy_settings()})

    async def admin_patch_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        body = await self._parse_json(request)
        try:
            data = update_git_proxy_port(body.get("port", ""))
        except ValueError as exc:
            raise WebApiError(400, "invalid_git_proxy_port", str(exc)) from exc
        return _json({"ok": True, "data": data})

    async def admin_restart(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        self._schedule_restart_request()
        return _json({"ok": True, "data": {"restart_requested": True}})

    async def admin_tunnel(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        return _json({"ok": True, "data": self._tunnel_service.snapshot()})

    async def admin_tunnel_start(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        snapshot = await self._tunnel_service.start()
        await self._notify_tunnel_public_url(snapshot, reason="manual_tunnel_start")
        return _json({"ok": True, "data": snapshot})

    async def admin_tunnel_stop(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        return _json({"ok": True, "data": await self._tunnel_service.stop()})

    async def admin_tunnel_restart(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        snapshot = await self._tunnel_service.restart()
        await self._notify_tunnel_public_url(snapshot, reason="manual_tunnel_restart")
        return _json({"ok": True, "data": snapshot})

    async def admin_single_bot(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": {"bot": build_bot_summary(self.manager, alias)}})

    async def admin_assistant_proposals(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        status = request.query.get("status") or None
        return _json({"ok": True, "data": list_assistant_proposals(self.manager, alias, status=status)})

    async def admin_assistant_proposal_approve(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        proposal_id = request.match_info["proposal_id"]
        data = await approve_assistant_proposal(
            self.manager,
            alias,
            proposal_id,
            reviewer=str(auth.user_id),
        )
        return _json({"ok": True, "data": data})

    async def admin_assistant_proposal_reject(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        proposal_id = request.match_info["proposal_id"]
        data = await reject_assistant_proposal(
            self.manager,
            alias,
            proposal_id,
            reviewer=str(auth.user_id),
        )
        return _json({"ok": True, "data": data})

    async def admin_assistant_upgrade_apply(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        alias = self._manager_alias(request)
        proposal_id = request.match_info["proposal_id"]
        data = await apply_assistant_upgrade(self.manager, alias, proposal_id)
        return _json({"ok": True, "data": data})

    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[cors_middleware, error_middleware], client_max_size=25 * 1024 * 1024)
        app.router.add_get("/api/health", self.health)
        app.router.add_get("/api/auth/me", self.auth_me)
        app.router.add_get("/api/bots", self.get_bots)
        app.router.add_get("/api/bots/{alias}", self.get_bot_overview)
        app.router.add_post("/api/bots/{alias}/chat", self.post_chat)
        app.router.add_post("/api/bots/{alias}/chat/stream", self.post_chat_stream)
        app.router.add_post("/api/bots/{alias}/exec", self.post_exec)
        app.router.add_get("/terminal/ws", self.terminal_ws)
        app.router.add_get("/api/bots/{alias}/pwd", self.get_pwd)
        app.router.add_get("/api/bots/{alias}/ls", self.get_ls)
        app.router.add_post("/api/bots/{alias}/cd", self.post_cd)
        app.router.add_post("/api/bots/{alias}/reset", self.post_reset)
        app.router.add_post("/api/bots/{alias}/kill", self.post_kill)
        app.router.add_get("/api/bots/{alias}/cli-params", self.get_cli_params)
        app.router.add_patch("/api/bots/{alias}/cli-params", self.patch_cli_params)
        app.router.add_post("/api/bots/{alias}/cli-params/reset", self.post_cli_params_reset)
        app.router.add_get("/api/bots/{alias}/history", self.get_history_view)
        app.router.add_get("/api/bots/{alias}/git", self.get_git_overview_view)
        app.router.add_post("/api/bots/{alias}/git/init", self.post_git_init)
        app.router.add_get("/api/bots/{alias}/git/diff", self.get_git_diff_view)
        app.router.add_post("/api/bots/{alias}/git/stage", self.post_git_stage)
        app.router.add_post("/api/bots/{alias}/git/unstage", self.post_git_unstage)
        app.router.add_post("/api/bots/{alias}/git/commit", self.post_git_commit)
        app.router.add_post("/api/bots/{alias}/git/fetch", self.post_git_fetch)
        app.router.add_post("/api/bots/{alias}/git/pull", self.post_git_pull)
        app.router.add_post("/api/bots/{alias}/git/push", self.post_git_push)
        app.router.add_post("/api/bots/{alias}/git/stash", self.post_git_stash)
        app.router.add_post("/api/bots/{alias}/git/stash/pop", self.post_git_stash_pop)
        app.router.add_post("/api/bots/{alias}/files/upload", self.upload_file)
        app.router.add_post("/api/bots/{alias}/files/mkdir", self.create_directory_view)
        app.router.add_post("/api/bots/{alias}/files/delete", self.delete_path_view)
        app.router.add_get("/api/bots/{alias}/files/download", self.download_file)
        app.router.add_get("/api/bots/{alias}/files/read", self.read_file)
        app.router.add_get("/api/admin/bots", self.admin_bots)
        app.router.add_get("/api/admin/scripts", self.admin_scripts)
        app.router.add_post("/api/admin/scripts/run/stream", self.admin_run_script_stream)
        app.router.add_post("/api/admin/scripts/run", self.admin_run_script)
        app.router.add_get("/api/admin/bots/{alias}/processing", self.admin_processing)
        app.router.add_post("/api/admin/bots", self.admin_add_bot)
        app.router.add_get("/api/admin/bots/{alias}", self.admin_single_bot)
        app.router.add_delete("/api/admin/bots/{alias}", self.admin_remove_bot)
        app.router.add_post("/api/admin/bots/{alias}/start", self.admin_start_bot)
        app.router.add_post("/api/admin/bots/{alias}/stop", self.admin_stop_bot)
        app.router.add_patch("/api/admin/bots/{alias}/cli", self.admin_update_cli)
        app.router.add_patch("/api/admin/bots/{alias}/alias", self.admin_rename_bot)
        app.router.add_patch("/api/admin/bots/{alias}/workdir", self.admin_update_workdir)
        app.router.add_get("/api/admin/bots/{alias}/assistant/proposals", self.admin_assistant_proposals)
        app.router.add_post(
            "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/approve",
            self.admin_assistant_proposal_approve,
        )
        app.router.add_post(
            "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/reject",
            self.admin_assistant_proposal_reject,
        )
        app.router.add_post(
            "/api/admin/bots/{alias}/assistant/upgrades/{proposal_id}/apply",
            self.admin_assistant_upgrade_apply,
        )
        app.router.add_get("/api/admin/git-proxy", self.admin_get_git_proxy)
        app.router.add_patch("/api/admin/git-proxy", self.admin_patch_git_proxy)
        app.router.add_post("/api/admin/restart", self.admin_restart)
        app.router.add_get("/api/admin/tunnel", self.admin_tunnel)
        app.router.add_post("/api/admin/tunnel/start", self.admin_tunnel_start)
        app.router.add_post("/api/admin/tunnel/stop", self.admin_tunnel_stop)
        app.router.add_post("/api/admin/tunnel/restart", self.admin_tunnel_restart)
        
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
        if self._tunnel_service.should_autostart():
            tunnel_snapshot = await self._tunnel_service.start()
            await self._notify_tunnel_public_url(tunnel_snapshot, reason="web_server_start")
            logger.info("Web tunnel 状态: %s %s", tunnel_snapshot.get("status"), tunnel_snapshot.get("public_url") or "")
        logger.info(
            "Web API 已启动: http://%s:%s (token=%s, allowed_origins=%s)",
            WEB_HOST,
            WEB_PORT,
            "已配置" if WEB_API_TOKEN else "未配置",
            ",".join(WEB_ALLOWED_ORIGINS),
        )

    async def stop(self, *, preserve_tunnel: bool = False):
        if self._runner is None:
            return
        if self._restart_task is not None and not self._restart_task.done():
            self._restart_task.cancel()
        if self._restart_task is not None:
            await asyncio.gather(self._restart_task, return_exceptions=True)
            self._restart_task = None
        terminal_tasks = list(self._terminal_tasks)
        self._terminal_tasks.clear()
        for task in terminal_tasks:
            task.cancel()
        if terminal_tasks:
            await asyncio.gather(*terminal_tasks, return_exceptions=True)
        terminal_sockets = list(self._terminal_sockets)
        self._terminal_sockets.clear()
        for ws in terminal_sockets:
            try:
                await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
            except Exception:
                pass
        if preserve_tunnel:
            self._tunnel_service.preserve_for_restart()
        else:
            await self._tunnel_service.stop()
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        logger.info("Web API 已停止")
