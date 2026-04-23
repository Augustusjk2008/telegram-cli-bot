"""aiohttp Web API 服务器。"""

from __future__ import annotations

import asyncio
import getpass
import ipaddress
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
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
from bot.debug.service import DebugService
from bot.manager import MultiBotManager
from bot.platform.runtime import get_default_shell
from bot.platform.terminal import create_shell_process
from bot.updater import (
    check_for_updates,
    download_latest_update,
    get_update_status,
    set_update_enabled,
)
from .auth_store import (
    AuthStoreError,
    CAP_ADMIN_OPS,
    CAP_CHAT_SEND,
    CAP_DEBUG_EXEC,
    CAP_GIT_OPS,
    CAP_MANAGE_CLI_PARAMS,
    CAP_MANAGE_REGISTER_CODES,
    CAP_MUTATE_BROWSE_STATE,
    CAP_READ_FILE_CONTENT,
    CAP_RUN_PLUGINS,
    CAP_RUN_SCRIPTS,
    CAP_TERMINAL_EXEC,
    CAP_VIEW_BOTS,
    CAP_VIEW_BOT_STATUS,
    CAP_VIEW_CHAT_HISTORY,
    CAP_VIEW_CHAT_TRACE,
    CAP_VIEW_FILE_TREE,
    CAP_VIEW_PLUGINS,
    CAP_WRITE_FILES,
    LOCAL_ADMIN_CAPABILITIES,
    MEMBER_CAPABILITIES,
    ROLE_GUEST,
    WebAuthSession,
    WebAuthStore,
)
from .tunnel_service import TunnelService
from .api_service import (
    approve_assistant_proposal,
    apply_assistant_upgrade,
    AuthContext,
    _require_capability,
    WebApiError,
    add_managed_bot,
    build_bot_summary,
    change_working_directory,
    create_directory,
    create_text_file,
    delete_path,
    dispose_plugin_view,
    execute_shell_command,
    get_plugin_view_window,
    get_directory_listing,
    get_file_metadata,
    get_history,
    get_history_trace,
    get_overview,
    list_avatar_assets,
    list_assistant_proposals,
    get_cli_params_payload,
    get_processing_sessions,
    get_working_directory,
    kill_user_process,
    list_bots,
    list_assistant_cron_jobs,
    list_assistant_cron_runs,
    list_plugins,
    open_plugin_view,
    list_system_scripts,
    read_file_content,
    rename_path,
    remove_managed_bot,
    reject_assistant_proposal,
    reset_user_session,
    reset_cli_params,
    run_chat,
    run_assistant_cron_job_now,
    render_plugin_view,
    run_system_script,
    resolve_plugin_file_target,
    save_chat_attachment,
    save_uploaded_file,
    start_managed_bot,
    stop_managed_bot,
    stream_system_script,
    stream_update_download,
    stream_chat,
    create_assistant_cron_job,
    delete_chat_attachment,
    delete_assistant_cron_job,
    update_cli_params,
    update_assistant_cron_job,
    update_bot_avatar,
    update_bot_cli,
    update_plugin,
    rename_managed_bot,
    update_bot_workdir,
    write_file_content,
)
from .git_service import (
    commit_git_changes,
    discard_all_git_changes,
    discard_git_paths,
    fetch_git_remote,
    get_git_diff,
    get_git_overview,
    get_git_tree_status,
    init_git_repository,
    pop_git_stash,
    pull_git_remote,
    push_git_remote,
    stage_git_paths,
    stash_git_changes,
    unstage_git_paths,
)
from .workspace_search_service import (
    build_file_outline,
    quick_open_files,
    search_workspace_text,
)
from .workspace_definition_service import resolve_workspace_definition

logger = logging.getLogger(__name__)
# 给浏览器留出响应落地时间，避免服务重启过快导致前端请求悬挂。
RESTART_RESPONSE_DELAY_SECONDS = 1.0
_TERMINAL_OUTPUT_EOF = object()
_CLIENT_DISCONNECT_ERRORS = (
    ClientConnectionResetError,
    ConnectionResetError,
    BrokenPipeError,
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_AUTH_STORE = WebAuthStore(
    users_path=_REPO_ROOT / ".web_users.json",
    register_codes_path=_REPO_ROOT / ".web_register_codes.json",
)


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))
    response.enable_compression()
    return response


def _serialize_file_version_fields(data: dict[str, Any]) -> dict[str, Any]:
    if "last_modified_ns" not in data:
        return data
    return {
        **data,
        "last_modified_ns": str(data["last_modified_ns"]),
    }


def _error_response(exc: WebApiError) -> web.Response:
    return _json(
        {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "data": exc.data,
            },
        },
        status=exc.status,
    )


def _auth_error(exc: AuthStoreError) -> WebApiError:
    return WebApiError(exc.status, exc.code, exc.message, exc.data)


def _extract_auth_token(request: web.Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (
        request.headers.get("X-API-Token", "").strip()
        or request.query.get("token", "").strip()
    )


def _is_loopback_value(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    if ":" in text and text.count(":") == 1:
        host, _, port = text.partition(":")
        if port.isdigit():
            text = host
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return text.lower() == "localhost"


_FORWARDED_CLIENT_IP_HEADER_NAMES = (
    "Forwarded",
    "X-Forwarded-For",
    "X-Real-IP",
    "CF-Connecting-IP",
    "True-Client-IP",
)


def _has_forwarded_client_headers(request: web.Request) -> bool:
    return any(str(request.headers.get(name, "")).strip() for name in _FORWARDED_CLIENT_IP_HEADER_NAMES)


def _request_targets_non_loopback_host(request: web.Request) -> bool:
    host = str(request.headers.get("Host", "")).strip()
    return bool(host) and not _is_loopback_value(host)


def _is_loopback_request(request: web.Request) -> bool:
    if _has_forwarded_client_headers(request):
        return False
    if _request_targets_non_loopback_host(request):
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


def _serialize_auth_context(auth: AuthContext, *, token: str = "") -> dict[str, Any]:
    payload = {
        "user_id": auth.user_id,
        "account_id": auth.account_id,
        "username": auth.username,
        "role": auth.role,
        "capabilities": sorted(auth.capabilities),
        "current_bot_alias": "",
        "current_path": "",
        "is_logged_in": True,
        "token_protected": bool(WEB_API_TOKEN),
        "allowed_user_ids": ALLOWED_USER_IDS,
    }
    if token:
        payload["token"] = token
    return payload


def _serialize_auth_session(session: WebAuthSession) -> dict[str, Any]:
    auth = AuthContext(
        user_id=WEB_DEFAULT_USER_ID,
        token_used=True,
        account_id=session.account.account_id,
        username=session.account.username,
        role=session.account.role,
        capabilities=set(session.capabilities),
    )
    return _serialize_auth_context(auth, token=session.token)


def _parse_optional_int(value: object, *, field_name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise WebApiError(400, "invalid_request", f"{field_name} 必须是整数") from exc


def _normalize_origin(origin: str) -> str:
    return origin.rstrip("/")


def _format_sse(event_type: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


def _get_total_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            memory_status = _MemoryStatusEx()
            memory_status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
                return int(memory_status.ullTotalPhys)

        if hasattr(os, "sysconf"):
            page_size = os.sysconf("SC_PAGE_SIZE")
            page_count = os.sysconf("SC_PHYS_PAGES")
            if isinstance(page_size, int) and isinstance(page_count, int) and page_size > 0 and page_count > 0:
                return int(page_size * page_count)
    except (AttributeError, OSError, TypeError, ValueError):
        return None

    return None


def _format_memory_label(total_memory_bytes: int | None) -> str:
    if not total_memory_bytes or total_memory_bytes <= 0:
        return "内存未知"

    total_gb = total_memory_bytes / (1024 ** 3)
    rounded = round(total_gb, 1)
    if abs(rounded - round(rounded)) < 0.05:
        return f"{int(round(rounded))} GB 内存"
    return f"{rounded:.1f} GB 内存"


def _build_public_host_info() -> dict[str, str]:
    username = (
        str(os.environ.get("USERNAME") or "").strip()
        or str(os.environ.get("USER") or "").strip()
    )
    if not username:
        try:
            username = getpass.getuser().strip()
        except Exception:
            username = ""

    system = str(platform.system() or "").strip() or "未知系统"
    release = str(platform.release() or "").strip()
    operating_system = " ".join(part for part in [system, release] if part).strip() or system

    hardware_platform = str(platform.machine() or "").strip() or "未知平台"
    logical_cores = os.cpu_count()
    hardware_spec_parts: list[str] = []
    if isinstance(logical_cores, int) and logical_cores > 0:
        hardware_spec_parts.append(f"{logical_cores} 逻辑核心")
    hardware_spec_parts.append(_format_memory_label(_get_total_memory_bytes()))

    return {
        "username": username or "未知用户",
        "operating_system": operating_system,
        "hardware_platform": hardware_platform,
        "hardware_spec": " · ".join(part for part in hardware_spec_parts if part) or "规格未知",
    }


class _TerminalOutputPump:
    """用 daemon 线程读取终端输出，避免阻塞读把主进程退出卡住。"""

    def __init__(self, process: Any, *, flush_interval_ms: int = 8, max_chunk_bytes: int = 65536):
        self._process = process
        self._queue: asyncio.Queue[bytes | object] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._flush_interval = max(flush_interval_ms, 0) / 1000
        self._max_chunk_bytes = max(max_chunk_bytes, 1)

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
        pending = bytearray()
        last_flush_at = time.monotonic()
        try:
            while not self._stop_event.is_set():
                try:
                    data = self._process.read(timeout=20)
                except Exception as exc:
                    logger.debug("终端输出读取结束 pid=%s: %s", getattr(self._process, "pid", "unknown"), exc)
                    break

                if data:
                    if isinstance(data, str):
                        data = data.encode("utf-8", errors="replace")
                    pending.extend(data)
                    now = time.monotonic()
                    if len(pending) >= self._max_chunk_bytes or now - last_flush_at >= self._flush_interval:
                        self._put(bytes(pending))
                        pending.clear()
                        last_flush_at = now
                    continue

                if pending:
                    self._put(bytes(pending))
                    pending.clear()
                    last_flush_at = time.monotonic()

                try:
                    if not self._process.isalive():
                        break
                except Exception:
                    break

                self._stop_event.wait(0.01)
        finally:
            if pending:
                self._put(bytes(pending))
            self._put(_TERMINAL_OUTPUT_EOF)


def _parse_terminal_size(payload: dict[str, Any]) -> tuple[int, int] | None:
    try:
        cols = int(payload.get("cols") or 0)
        rows = int(payload.get("rows") or 0)
    except (TypeError, ValueError):
        return None

    if cols < 2 or rows < 2:
        return None
    return cols, rows


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

    def __init__(
        self,
        manager: MultiBotManager,
        *,
        host: str | None = None,
        port: int | None = None,
        tunnel_service: TunnelService | None = None,
    ):
        self.manager = manager
        self._host = str(host or WEB_HOST or "").strip() or "0.0.0.0"
        self._port = int(port if port is not None else WEB_PORT)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._update_task: asyncio.Task[None] | None = None
        self._terminal_sockets: set[web.WebSocketResponse] = set()
        self._terminal_tasks: set[asyncio.Task[Any]] = set()
        self._debug_service = DebugService(manager)
        self._debug_sockets: set[web.WebSocketResponse] = set()
        self._debug_tasks: set[asyncio.Task[Any]] = set()
        self._tunnel_service = tunnel_service or TunnelService(
            host=self._host,
            port=self._port,
            mode=WEB_TUNNEL_MODE,
            autostart=WEB_TUNNEL_AUTOSTART,
            public_url=WEB_PUBLIC_URL,
            cloudflared_path=WEB_TUNNEL_CLOUDFLARED_PATH,
            state_file=WEB_TUNNEL_STATE_FILE,
        )

    def _auth_context(self, request: web.Request) -> AuthContext:
        raw_token = _extract_auth_token(request)
        if raw_token:
            session = _WEB_AUTH_STORE.get_session(raw_token)
            if session is not None:
                return self._session_auth_context(session)
            if _is_loopback_request(request):
                return self._local_admin_auth_context()
            if WEB_API_TOKEN and raw_token == WEB_API_TOKEN:
                return self._legacy_auth_context(request, token_used=True)
            raise WebApiError(401, "unauthorized", "访问令牌无效")

        if _is_loopback_request(request):
            return self._local_admin_auth_context()
        if WEB_API_TOKEN:
            raise WebApiError(401, "unauthorized", "访问令牌无效")
        if _WEB_AUTH_STORE.can_bootstrap_without_auth():
            return self._legacy_auth_context(request, token_used=False, username="bootstrap")
        raise WebApiError(401, "unauthorized", "请先登录")

    def _legacy_user_id(self, request: web.Request) -> int:
        raw_user_id = request.headers.get("X-User-Id", "").strip() or request.query.get("user_id", "").strip()
        if not raw_user_id:
            return WEB_DEFAULT_USER_ID
        try:
            return int(raw_user_id)
        except ValueError as exc:
            raise WebApiError(400, "invalid_user_id", "X-User-Id 必须是整数") from exc

    def _ensure_allowed_user_id(self, user_id: int) -> None:
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            raise WebApiError(403, "forbidden", f"用户 {user_id} 未授权")

    def _legacy_auth_context(
        self,
        request: web.Request,
        *,
        token_used: bool,
        username: str = "legacy",
    ) -> AuthContext:
        user_id = self._legacy_user_id(request)
        self._ensure_allowed_user_id(user_id)
        return AuthContext(
            user_id=user_id,
            token_used=token_used,
            account_id="legacy-default",
            username=username,
            role="member",
            capabilities=set(MEMBER_CAPABILITIES),
        )

    def _session_auth_context(self, session: WebAuthSession) -> AuthContext:
        self._ensure_allowed_user_id(WEB_DEFAULT_USER_ID)
        return AuthContext(
            user_id=WEB_DEFAULT_USER_ID,
            token_used=True,
            account_id=session.account.account_id,
            username=session.account.username,
            role=session.account.role,
            capabilities=set(session.capabilities),
        )

    def _local_admin_auth_context(self) -> AuthContext:
        self._ensure_allowed_user_id(WEB_DEFAULT_USER_ID)
        return AuthContext(
            user_id=WEB_DEFAULT_USER_ID,
            token_used=False,
            account_id="local-admin",
            username="127.0.0.1",
            role="member",
            capabilities=set(LOCAL_ADMIN_CAPABILITIES),
        )

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

    async def _with_capability(self, request: web.Request, capability: str) -> AuthContext:
        auth = await self._with_auth(request)
        _require_capability(auth, capability)
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

    def _build_public_url_qr_text(self, public_url: str) -> str:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(public_url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        return "\n".join("".join("██" if cell else "  " for cell in row) for row in matrix)

    def _print_public_url_qr(self, public_url: str) -> bool:
        value = str(public_url or "").strip()
        if not value:
            return False

        try:
            print(f"[INFO] Quick tunnel URL: {value}")
            print(self._build_public_url_qr_text(value))
            return True
        except Exception as exc:
            logger.warning("打印 quick tunnel 二维码失败: %s", exc)
            print(f"[INFO] Quick tunnel URL: {value}")
            return False

    async def _notify_tunnel_public_url(self, snapshot: dict[str, Any], *, reason: str) -> bool:
        if snapshot.get("status") != "running":
            return False
        if snapshot.get("source") != "quick_tunnel":
            return False

        public_url = str(snapshot.get("public_url") or "").strip()
        if not public_url:
            return False

        copied = self._copy_text_to_clipboard(public_url)
        if copied:
            logger.info("已复制 Web 公网地址到剪贴板 reason=%s url=%s", reason, public_url)
        qr_printed = self._print_public_url_qr(public_url)
        return copied or qr_printed

    async def health(self, request: web.Request) -> web.Response:
        return _json(
            {
                "ok": True,
                "service": "telegram-cli-bridge-web",
                "web_enabled": True,
                "host": self._host,
                "port": self._port,
                "host_info": _build_public_host_info(),
            }
        )

    async def auth_me(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        return _json({"ok": True, "data": _serialize_auth_context(auth, token=_extract_auth_token(request))})

    async def auth_login(self, request: web.Request) -> web.Response:
        if _is_loopback_request(request):
            return _json({"ok": True, "data": _serialize_auth_context(self._local_admin_auth_context())})
        body = await self._parse_json(request)
        try:
            session = _WEB_AUTH_STORE.login_member(
                str(body.get("username", "")),
                str(body.get("password", "")),
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": _serialize_auth_session(session)})

    async def auth_register(self, request: web.Request) -> web.Response:
        if _is_loopback_request(request):
            return _json({"ok": True, "data": _serialize_auth_context(self._local_admin_auth_context())})
        body = await self._parse_json(request)
        try:
            session = _WEB_AUTH_STORE.register_member(
                str(body.get("username", "")),
                str(body.get("password", "")),
                str(body.get("register_code", "")),
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": _serialize_auth_session(session)})

    async def auth_guest(self, request: web.Request) -> web.Response:
        session = _WEB_AUTH_STORE.create_guest_session()
        return _json({"ok": True, "data": _serialize_auth_session(session)})

    async def auth_logout(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        raw_token = _extract_auth_token(request)
        if raw_token and _WEB_AUTH_STORE.get_session(raw_token) is not None:
            _WEB_AUTH_STORE.delete_session(raw_token)
        return _json({"ok": True, "data": {"username": auth.username}})

    async def admin_register_codes(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        return _json({"ok": True, "data": _WEB_AUTH_STORE.list_register_codes()})

    async def admin_register_code_create(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        body = await self._parse_json(request)
        try:
            data = _WEB_AUTH_STORE.create_register_code(
                created_by=auth.username,
                max_uses=int(body.get("max_uses", 1)),
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": data})

    async def admin_register_code_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        body = await self._parse_json(request)
        try:
            data = _WEB_AUTH_STORE.update_register_code(
                request.match_info["code_id"],
                max_uses_delta=_parse_optional_int(body.get("max_uses_delta"), field_name="max_uses_delta"),
                disabled=body.get("disabled") if "disabled" in body else None,
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": data})

    async def admin_register_code_delete(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        try:
            _WEB_AUTH_STORE.delete_register_code(request.match_info["code_id"])
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": {"deleted": True}})

    async def get_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_BOTS)
        return _json({"ok": True, "data": list_bots(self.manager, auth.user_id)})

    async def get_plugins(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_PLUGINS)
        refresh = str(request.query.get("refresh", "")).lower() in {"1", "true", "yes"}
        return _json({"ok": True, "data": await list_plugins(self.manager, auth, refresh=refresh)})

    async def patch_plugin(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await update_plugin(self.manager, auth, plugin_id, dict(body or {}))})

    async def get_bot_overview(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_BOT_STATUS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_overview(self.manager, alias, auth.user_id)})

    async def post_chat(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await run_chat(self.manager, alias, auth.user_id, body.get("message", ""))
        return _json({"ok": True, "data": data})

    async def post_chat_stream(self, request: web.Request) -> web.StreamResponse:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
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
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await execute_shell_command(self.manager, alias, auth.user_id, body.get("command", ""))
        return _json({"ok": True, "data": data})

    async def terminal_ws(self, request: web.Request) -> web.WebSocketResponse:
        await self._with_capability(request, CAP_TERMINAL_EXEC)
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
            initial_size = _parse_terminal_size(init_data)
            process = create_shell_process(
                shell_type,
                cwd,
                use_pty=not force_no_pty,
                cols=initial_size[0] if initial_size else None,
                rows=initial_size[1] if initial_size else None,
            )
            try:
                await ws.send_json({"pty_mode": process.is_pty})
            except _CLIENT_DISCONNECT_ERRORS:
                logger.info("终端 WebSocket 客户端在初始化完成前断开: cwd=%s shell=%s", cwd, shell_type)
                return ws
            loop = asyncio.get_running_loop()
            output_pump = _TerminalOutputPump(process)
            output_pump.start(loop)

            async def forward_output() -> None:
                while True:
                    data = await output_pump.read()
                    if data is _TERMINAL_OUTPUT_EOF:
                        break
                    try:
                        await ws.send_bytes(data)
                    except _CLIENT_DISCONNECT_ERRORS:
                        logger.info("终端 WebSocket 客户端已断开，停止转发输出: cwd=%s shell=%s", cwd, shell_type)
                        break

            async def forward_input() -> None:
                while not ws.closed:
                    transport = request.transport
                    if transport is None or transport.is_closing():
                        break
                    message = await ws.receive()
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
                            if isinstance(payload, dict):
                                if payload.get("type") == "ping":
                                    continue
                                if payload.get("type") == "resize":
                                    resize = getattr(process, "resize", None)
                                    size = _parse_terminal_size(payload)
                                    if callable(resize) and size is not None:
                                        resize(*size)
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
        auth = await self._with_capability(request, CAP_VIEW_FILE_TREE)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_working_directory(self.manager, alias, auth.user_id)})

    async def get_ls(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_FILE_TREE)
        alias = self._manager_alias(request)
        target_path = request.query.get("path") or None
        if auth.role == ROLE_GUEST:
            base_dir = get_working_directory(self.manager, alias, auth.user_id)["working_dir"]
            data = get_directory_listing(
                self.manager,
                alias,
                auth.user_id,
                path=target_path,
                base_dir=base_dir,
                restrict_to_base_dir=True,
            )
            return _json({"ok": True, "data": data})
        return _json({"ok": True, "data": get_directory_listing(self.manager, alias, auth.user_id, path=target_path)})

    async def get_workspace_quick_open(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = get_working_directory(self.manager, alias, auth.user_id)["working_dir"]
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", "50"))
        return _json({"ok": True, "data": quick_open_files(workspace, query, limit=limit)})

    async def get_workspace_search(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = get_working_directory(self.manager, alias, auth.user_id)["working_dir"]
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", "100"))
        return _json({"ok": True, "data": search_workspace_text(workspace, query, limit=limit)})

    async def get_workspace_outline(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = get_working_directory(self.manager, alias, auth.user_id)["working_dir"]
        path = request.query.get("path", "")
        return _json({"ok": True, "data": build_file_outline(workspace, path)})

    async def post_workspace_resolve_definition(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        workspace = get_working_directory(self.manager, alias, auth.user_id)["working_dir"]
        data = resolve_workspace_definition(
            workspace,
            str(body.get("path", "")),
            line=int(body.get("line") or 1),
            column=int(body.get("column") or 1),
            symbol=str(body.get("symbol", "")),
        )
        return _json({"ok": True, "data": data})

    async def post_cd(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MUTATE_BROWSE_STATE)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = change_working_directory(self.manager, alias, auth.user_id, body.get("path", ""))
        return _json({"ok": True, "data": data})

    async def post_reset(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": reset_user_session(self.manager, alias, auth.user_id)})

    async def post_kill(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": kill_user_process(self.manager, alias, auth.user_id)})

    async def get_cli_params(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_CLI_PARAMS)
        alias = self._manager_alias(request)
        cli_type = request.query.get("cli_type") or None
        return _json({"ok": True, "data": get_cli_params_payload(self.manager, alias, cli_type)})

    async def patch_cli_params(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_CLI_PARAMS)
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
        await self._with_capability(request, CAP_MANAGE_CLI_PARAMS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        data = await reset_cli_params(self.manager, alias, body.get("cli_type"))
        return _json({"ok": True, "data": data})

    async def get_history_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        return _json({"ok": True, "data": get_history(self.manager, alias, auth.user_id, limit=limit)})

    async def get_debug_profile(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await self._debug_service.get_profile(alias, auth.user_id)})

    async def get_debug_state(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await self._debug_service.get_state(alias, auth.user_id)})

    async def patch_debug_profile_overrides(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        return _json({"ok": True, "data": await self._debug_service.patch_profile_overrides(alias, auth.user_id, body)})

    async def post_debug_launch(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        return _json({"ok": True, "data": await self._debug_service.launch(alias, auth.user_id, body)})

    async def post_debug_stop(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await self._debug_service.stop(alias, auth.user_id)})

    async def post_debug_command(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        action = str(body.get("action") or body.get("command") or body.get("type") or "").strip()
        payload = body.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {
            key: value
            for key, value in body.items()
            if key not in {"action", "command", "type"}
        }
        return _json({"ok": True, "data": await self._debug_service.command(alias, auth.user_id, action, payload_dict)})

    async def post_debug_breakpoints(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        return _json({"ok": True, "data": await self._debug_service.set_breakpoints(alias, auth.user_id, body)})

    async def post_debug_evaluate(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        return _json({"ok": True, "data": await self._debug_service.evaluate(alias, auth.user_id, body)})

    async def debug_ws(self, request: web.Request) -> web.WebSocketResponse:
        auth = await self._with_capability(request, CAP_DEBUG_EXEC)
        alias = str(request.query.get("alias") or "").strip().lower()
        if not alias:
            raise WebApiError(400, "missing_alias", "缺少 Bot 别名")
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        queue = await self._debug_service.subscribe(alias, auth.user_id)
        current_task = asyncio.current_task()
        self._debug_sockets.add(ws)
        if current_task is not None:
            self._debug_tasks.add(current_task)

        async def sender() -> None:
            initial_state = await self._debug_service.get_state(alias, auth.user_id)
            await ws.send_json({"type": "state", "payload": initial_state})
            while True:
                event = await queue.get()
                await ws.send_json(event)

        sender_task = asyncio.create_task(sender())
        try:
            async for message in ws:
                if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    break
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(message.data or "{}")
                except json.JSONDecodeError:
                    await ws.send_json(
                        {
                            "type": "error",
                            "payload": {
                                "code": "invalid_json",
                                "message": "调试消息不是合法 JSON",
                            },
                        }
                    )
                    continue
                if not isinstance(payload, dict):
                    await ws.send_json(
                        {
                            "type": "error",
                            "payload": {
                                "code": "invalid_json",
                                "message": "调试消息必须是对象",
                            },
                        }
                    )
                    continue
                await self._debug_service.handle_ws_message(alias, auth.user_id, payload)
        finally:
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)
            await self._debug_service.unsubscribe(alias, auth.user_id, queue)
            self._debug_sockets.discard(ws)
            if current_task is not None:
                self._debug_tasks.discard(current_task)
        return ws

    async def get_history_trace_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_TRACE)
        alias = self._manager_alias(request)
        message_id = request.match_info.get("message_id", "")
        return _json({"ok": True, "data": get_history_trace(self.manager, alias, auth.user_id, message_id)})

    async def get_git_overview_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_git_overview(self.manager, alias, auth.user_id)})

    async def get_git_tree_status_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_git_tree_status(self.manager, alias, auth.user_id)})

    async def post_git_init(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": init_git_repository(self.manager, alias, auth.user_id)})

    async def get_git_diff_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        path = request.query.get("path", "")
        staged = request.query.get("staged", "").strip().lower() in {"1", "true", "yes"}
        return _json({"ok": True, "data": get_git_diff(self.manager, alias, auth.user_id, path, staged=staged)})

    async def post_git_stage(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = stage_git_paths(self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已暂存所选文件", "overview": overview}})

    async def post_git_unstage(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = unstage_git_paths(self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已取消暂存所选文件", "overview": overview}})

    async def post_git_discard(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = discard_git_paths(self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已丢弃所选文件改动", "overview": overview}})

    async def post_git_discard_all(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = discard_all_git_changes(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已丢弃全部改动", "overview": overview}})

    async def post_git_commit(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = commit_git_changes(self.manager, alias, auth.user_id, body.get("message", ""))
        return _json({"ok": True, "data": {"message": "已创建提交", "overview": overview}})

    async def post_git_fetch(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = fetch_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已抓取远端更新", "overview": overview}})

    async def post_git_pull(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = pull_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已拉取远端更新", "overview": overview}})

    async def post_git_push(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = push_git_remote(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已推送本地提交", "overview": overview}})

    async def post_git_stash(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = stash_git_changes(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已暂存当前工作区", "overview": overview}})

    async def post_git_stash_pop(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = pop_git_stash(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已恢复最近一次暂存", "overview": overview}})

    async def upload_file(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
        filename = field.filename or ""
        data = await field.read(decode=False)
        result = save_uploaded_file(self.manager, alias, auth.user_id, filename, data)
        return _json({"ok": True, "data": result})

    async def upload_chat_attachment(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
        filename = field.filename or ""
        data = await field.read(decode=False)
        result = save_chat_attachment(self.manager, alias, auth.user_id, filename, data)
        return _json({"ok": True, "data": result})

    async def delete_chat_attachment_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        result = delete_chat_attachment(self.manager, alias, auth.user_id, body.get("saved_path", ""))
        return _json({"ok": True, "data": result})

    async def create_directory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = create_directory(
            self.manager,
            alias,
            auth.user_id,
            body.get("name", ""),
            parent_path=body.get("parent_path"),
        )
        return _json({"ok": True, "data": data})

    async def write_file_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = write_file_content(
            self.manager,
            alias,
            auth.user_id,
            body.get("path", ""),
            body.get("content", ""),
            expected_mtime_ns=body.get("expected_mtime_ns"),
        )
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def create_text_file_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = create_text_file(
            self.manager,
            alias,
            auth.user_id,
            body.get("filename", ""),
            body.get("content", ""),
            parent_path=body.get("parent_path"),
        )
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def rename_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = rename_path(self.manager, alias, auth.user_id, body.get("path", ""), body.get("new_name", ""))
        return _json({"ok": True, "data": data})

    async def delete_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = delete_path(self.manager, alias, auth.user_id, body.get("path", ""))
        return _json({"ok": True, "data": data})

    async def download_file(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        filename = request.query.get("filename", "")
        metadata = get_file_metadata(self.manager, alias, auth.user_id, filename)
        return web.FileResponse(
            path=metadata["path"],
            headers={"Content-Disposition": f'attachment; filename="{metadata["filename"]}"'},
        )

    async def read_file(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        filename = request.query.get("filename", "")
        mode = request.query.get("mode", "cat")
        lines = int(request.query.get("lines", "20"))
        data = read_file_content(self.manager, alias, auth.user_id, filename, mode=mode, lines=lines)
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def resolve_file_plugin_target(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_PLUGINS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = resolve_plugin_file_target(self.manager, alias, auth, str(body.get("path", "")))
        return _json({"ok": True, "data": data})

    async def post_render_plugin_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        view_id = request.match_info.get("view_id", "").strip()
        body = await self._parse_json(request)
        input_payload = dict(body.get("input") or {})
        data = await render_plugin_view(self.manager, alias, auth, plugin_id, view_id, input_payload)
        return _json({"ok": True, "data": data})

    async def post_open_plugin_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        view_id = request.match_info.get("view_id", "").strip()
        body = await self._parse_json(request)
        input_payload = dict(body.get("input") or {})
        data = await open_plugin_view(self.manager, alias, auth, plugin_id, view_id, input_payload)
        return _json({"ok": True, "data": data})

    async def post_plugin_view_window(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        session_id = request.match_info.get("session_id", "").strip()
        body = await self._parse_json(request)
        request_payload = dict(body or {})
        data = await get_plugin_view_window(self.manager, alias, auth, plugin_id, session_id, request_payload)
        return _json({"ok": True, "data": data})

    async def delete_plugin_view_session(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        session_id = request.match_info.get("session_id", "").strip()
        data = await dispose_plugin_view(self.manager, alias, auth, plugin_id, session_id)
        return _json({"ok": True, "data": data})

    async def admin_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": list_bots(self.manager, auth.user_id)})
    
    async def bot_scripts(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_SCRIPTS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": list_system_scripts(self.manager, alias, auth.user_id)})

    async def bot_run_script(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_SCRIPTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await run_system_script(self.manager, alias, auth.user_id, body.get("script_name", ""))
        return _json({"ok": True, "data": data})

    async def bot_run_script_stream(self, request: web.Request) -> web.StreamResponse:
        auth = await self._with_capability(request, CAP_RUN_SCRIPTS)
        alias = self._manager_alias(request)
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
        async for event in stream_system_script(self.manager, alias, auth.user_id, script_name):
            if client_disconnected:
                continue
            try:
                await response.write(_format_sse(event["type"], event))
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                client_disconnected = True
                logger.info("系统功能 SSE 客户端已断开，继续在后台执行: alias=%s script=%s", alias, script_name)

        if not client_disconnected:
            try:
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                logger.info("系统功能 SSE 客户端在结束前断开: alias=%s script=%s", alias, script_name)
        return response

    async def admin_processing(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_processing_sessions(alias)})

    async def admin_add_bot(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        data = await add_managed_bot(
            self.manager,
            alias=body.get("alias", ""),
            bot_mode=body.get("bot_mode", "cli"),
            cli_type=body.get("cli_type"),
            cli_path=body.get("cli_path"),
            working_dir=body.get("working_dir"),
            avatar_name=body.get("avatar_name"),
        )
        return _json({"ok": True, "data": data})

    async def admin_list_avatar_assets(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": list_avatar_assets()})

    async def admin_remove_bot(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await remove_managed_bot(self.manager, alias)})

    async def admin_start_bot(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await start_managed_bot(self.manager, alias)})

    async def admin_stop_bot(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": await stop_managed_bot(self.manager, alias)})

    async def admin_update_cli(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
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
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await rename_managed_bot(self.manager, alias, str(body.get("new_alias", "")))
        return _json({"ok": True, "data": data})

    async def admin_update_workdir(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_workdir(
            self.manager,
            alias,
            body.get("working_dir", ""),
            auth.user_id,
            force_reset=bool(body.get("force_reset")),
        )
        return _json({"ok": True, "data": data})

    async def admin_update_avatar(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_avatar(self.manager, alias, body.get("avatar_name"), auth.user_id)
        return _json({"ok": True, "data": data})

    async def admin_get_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": get_git_proxy_settings()})

    async def admin_patch_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        try:
            data = update_git_proxy_port(body.get("port", ""))
        except ValueError as exc:
            raise WebApiError(400, "invalid_git_proxy_port", str(exc)) from exc
        return _json({"ok": True, "data": data})

    async def admin_get_update(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": get_update_status()})

    async def admin_patch_update(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": set_update_enabled(bool(body.get("update_enabled", True)))})

    async def admin_update_check(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        data = await asyncio.to_thread(check_for_updates)
        return _json({"ok": True, "data": data})

    async def admin_update_download(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        repo_root = Path(__file__).resolve().parents[2]
        data = await asyncio.to_thread(download_latest_update, repo_root)
        return _json({"ok": True, "data": data})

    async def admin_update_download_stream(self, request: web.Request) -> web.StreamResponse:
        await self._with_capability(request, CAP_ADMIN_OPS)
        await self._parse_json(request)

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
        async for event in stream_update_download():
            if client_disconnected:
                continue
            try:
                await response.write(_format_sse(event["type"], event))
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                client_disconnected = True
                logger.info("更新下载 SSE 客户端已断开，继续在后台下载")

        if not client_disconnected:
            try:
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                logger.info("更新下载 SSE 客户端在结束前断开")
        return response

    async def admin_restart(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        self._schedule_restart_request()
        return _json({"ok": True, "data": {"restart_requested": True}})

    async def admin_tunnel(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": self._tunnel_service.snapshot()})

    async def admin_tunnel_start(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        snapshot = await self._tunnel_service.start()
        await self._notify_tunnel_public_url(snapshot, reason="manual_tunnel_start")
        return _json({"ok": True, "data": snapshot})

    async def admin_tunnel_stop(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": await self._tunnel_service.stop()})

    async def admin_tunnel_restart(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        snapshot = await self._tunnel_service.restart()
        await self._notify_tunnel_public_url(snapshot, reason="manual_tunnel_restart")
        return _json({"ok": True, "data": snapshot})

    async def admin_single_bot(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": {"bot": build_bot_summary(self.manager, alias)}})

    async def admin_assistant_proposals(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        status = request.query.get("status") or None
        return _json({"ok": True, "data": list_assistant_proposals(self.manager, alias, status=status)})

    async def admin_assistant_proposal_approve(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
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
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
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
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        proposal_id = request.match_info["proposal_id"]
        data = await apply_assistant_upgrade(self.manager, alias, proposal_id)
        return _json({"ok": True, "data": data})

    async def admin_assistant_cron_jobs(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": list_assistant_cron_jobs(self.manager, alias)})

    async def admin_assistant_cron_job_create(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await create_assistant_cron_job(self.manager, alias, body)
        return _json({"ok": True, "data": data})

    async def admin_assistant_cron_job_update(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        job_id = request.match_info["job_id"]
        body = await self._parse_json(request)
        data = await update_assistant_cron_job(self.manager, alias, job_id, body)
        return _json({"ok": True, "data": data})

    async def admin_assistant_cron_job_delete(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        job_id = request.match_info["job_id"]
        data = await delete_assistant_cron_job(self.manager, alias, job_id)
        return _json({"ok": True, "data": data})

    async def admin_assistant_cron_job_run(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        job_id = request.match_info["job_id"]
        data = await run_assistant_cron_job_now(self.manager, alias, job_id)
        return _json({"ok": True, "data": data})

    async def admin_assistant_cron_job_runs(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        job_id = request.match_info["job_id"]
        limit = request.query.get("limit", "").strip()
        if limit:
            try:
                resolved_limit = int(limit)
            except ValueError as exc:
                raise WebApiError(400, "invalid_limit", "limit 必须是整数") from exc
        else:
            resolved_limit = 20
        data = list_assistant_cron_runs(self.manager, alias, job_id, limit=resolved_limit)
        return _json({"ok": True, "data": data})

    async def _auto_refresh_update_status(self) -> None:
        status = get_update_status()
        if not status.get("update_enabled"):
            return
        try:
            checked_status = await asyncio.to_thread(check_for_updates)
            latest_version = str(checked_status.get("last_available_version") or "").strip()
            current_version = str(checked_status.get("current_version") or "").strip()
            pending_version = str(
                checked_status.get("pending_update_version")
                or status.get("pending_update_version")
                or ""
            ).strip()
            if latest_version and latest_version != current_version and latest_version != pending_version:
                repo_root = Path(__file__).resolve().parents[2]
                logger.info("检测到新版本 %s，开始后台下载更新包", latest_version)
                await asyncio.to_thread(download_latest_update, repo_root)
        except Exception as exc:
            logger.warning("自动后台下载更新失败: %s", exc)

    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[cors_middleware, error_middleware], client_max_size=25 * 1024 * 1024)
        app.router.add_get("/api/health", self.health)
        app.router.add_get("/api/auth/me", self.auth_me)
        app.router.add_post("/api/auth/login", self.auth_login)
        app.router.add_post("/api/auth/register", self.auth_register)
        app.router.add_post("/api/auth/guest", self.auth_guest)
        app.router.add_post("/api/auth/logout", self.auth_logout)
        app.router.add_get("/api/admin/register-codes", self.admin_register_codes)
        app.router.add_post("/api/admin/register-codes", self.admin_register_code_create)
        app.router.add_patch("/api/admin/register-codes/{code_id}", self.admin_register_code_patch)
        app.router.add_delete("/api/admin/register-codes/{code_id}", self.admin_register_code_delete)
        app.router.add_get("/api/bots", self.get_bots)
        app.router.add_get("/api/plugins", self.get_plugins)
        app.router.add_patch("/api/plugins/{plugin_id}", self.patch_plugin)
        app.router.add_get("/api/bots/{alias}", self.get_bot_overview)
        app.router.add_post("/api/bots/{alias}/chat", self.post_chat)
        app.router.add_post("/api/bots/{alias}/chat/stream", self.post_chat_stream)
        app.router.add_post("/api/bots/{alias}/exec", self.post_exec)
        app.router.add_get("/api/bots/{alias}/debug/profile", self.get_debug_profile)
        app.router.add_patch("/api/bots/{alias}/debug/profile", self.patch_debug_profile_overrides)
        app.router.add_patch("/api/bots/{alias}/debug/profile-overrides", self.patch_debug_profile_overrides)
        app.router.add_get("/api/bots/{alias}/debug/state", self.get_debug_state)
        app.router.add_post("/api/bots/{alias}/debug/launch", self.post_debug_launch)
        app.router.add_post("/api/bots/{alias}/debug/stop", self.post_debug_stop)
        app.router.add_post("/api/bots/{alias}/debug/command", self.post_debug_command)
        app.router.add_post("/api/bots/{alias}/debug/control", self.post_debug_command)
        app.router.add_post("/api/bots/{alias}/debug/breakpoints", self.post_debug_breakpoints)
        app.router.add_post("/api/bots/{alias}/debug/evaluate", self.post_debug_evaluate)
        app.router.add_get("/debug/ws", self.debug_ws)
        app.router.add_get("/terminal/ws", self.terminal_ws)
        app.router.add_get("/api/bots/{alias}/pwd", self.get_pwd)
        app.router.add_get("/api/bots/{alias}/ls", self.get_ls)
        app.router.add_get("/api/bots/{alias}/workspace/quick-open", self.get_workspace_quick_open)
        app.router.add_get("/api/bots/{alias}/workspace/search", self.get_workspace_search)
        app.router.add_get("/api/bots/{alias}/workspace/outline", self.get_workspace_outline)
        app.router.add_post("/api/bots/{alias}/workspace/resolve-definition", self.post_workspace_resolve_definition)
        app.router.add_post("/api/bots/{alias}/cd", self.post_cd)
        app.router.add_post("/api/bots/{alias}/reset", self.post_reset)
        app.router.add_post("/api/bots/{alias}/kill", self.post_kill)
        app.router.add_get("/api/bots/{alias}/cli-params", self.get_cli_params)
        app.router.add_patch("/api/bots/{alias}/cli-params", self.patch_cli_params)
        app.router.add_post("/api/bots/{alias}/cli-params/reset", self.post_cli_params_reset)
        app.router.add_get("/api/bots/{alias}/history", self.get_history_view)
        app.router.add_get("/api/bots/{alias}/history/{message_id}/trace", self.get_history_trace_view)
        app.router.add_get("/api/bots/{alias}/git", self.get_git_overview_view)
        app.router.add_get("/api/bots/{alias}/git/tree-status", self.get_git_tree_status_view)
        app.router.add_post("/api/bots/{alias}/git/init", self.post_git_init)
        app.router.add_get("/api/bots/{alias}/git/diff", self.get_git_diff_view)
        app.router.add_post("/api/bots/{alias}/git/stage", self.post_git_stage)
        app.router.add_post("/api/bots/{alias}/git/unstage", self.post_git_unstage)
        app.router.add_post("/api/bots/{alias}/git/discard", self.post_git_discard)
        app.router.add_post("/api/bots/{alias}/git/discard-all", self.post_git_discard_all)
        app.router.add_post("/api/bots/{alias}/git/commit", self.post_git_commit)
        app.router.add_post("/api/bots/{alias}/git/fetch", self.post_git_fetch)
        app.router.add_post("/api/bots/{alias}/git/pull", self.post_git_pull)
        app.router.add_post("/api/bots/{alias}/git/push", self.post_git_push)
        app.router.add_post("/api/bots/{alias}/git/stash", self.post_git_stash)
        app.router.add_post("/api/bots/{alias}/git/stash/pop", self.post_git_stash_pop)
        app.router.add_post("/api/bots/{alias}/files/upload", self.upload_file)
        app.router.add_post("/api/bots/{alias}/chat/attachments", self.upload_chat_attachment)
        app.router.add_post("/api/bots/{alias}/chat/attachments/delete", self.delete_chat_attachment_view)
        app.router.add_post("/api/bots/{alias}/files/mkdir", self.create_directory_view)
        app.router.add_post("/api/bots/{alias}/files/write", self.write_file_view)
        app.router.add_post("/api/bots/{alias}/files/create", self.create_text_file_view)
        app.router.add_post("/api/bots/{alias}/files/rename", self.rename_path_view)
        app.router.add_post("/api/bots/{alias}/files/delete", self.delete_path_view)
        app.router.add_get("/api/bots/{alias}/files/download", self.download_file)
        app.router.add_get("/api/bots/{alias}/files/read", self.read_file)
        app.router.add_post("/api/bots/{alias}/plugins/resolve-file-target", self.resolve_file_plugin_target)
        app.router.add_post("/api/bots/{alias}/plugins/{plugin_id}/views/{view_id}/render", self.post_render_plugin_view)
        app.router.add_post("/api/bots/{alias}/plugins/{plugin_id}/views/{view_id}/open", self.post_open_plugin_view)
        app.router.add_post("/api/bots/{alias}/plugins/{plugin_id}/sessions/{session_id}/window", self.post_plugin_view_window)
        app.router.add_delete("/api/bots/{alias}/plugins/{plugin_id}/sessions/{session_id}", self.delete_plugin_view_session)
        app.router.add_get("/api/bots/{alias}/scripts", self.bot_scripts)
        app.router.add_post("/api/bots/{alias}/scripts/run/stream", self.bot_run_script_stream)
        app.router.add_post("/api/bots/{alias}/scripts/run", self.bot_run_script)
        app.router.add_get("/api/admin/bots", self.admin_bots)
        app.router.add_get("/api/admin/assets/avatars", self.admin_list_avatar_assets)
        app.router.add_get("/api/admin/bots/{alias}/processing", self.admin_processing)
        app.router.add_post("/api/admin/bots", self.admin_add_bot)
        app.router.add_get("/api/admin/bots/{alias}", self.admin_single_bot)
        app.router.add_delete("/api/admin/bots/{alias}", self.admin_remove_bot)
        app.router.add_post("/api/admin/bots/{alias}/start", self.admin_start_bot)
        app.router.add_post("/api/admin/bots/{alias}/stop", self.admin_stop_bot)
        app.router.add_patch("/api/admin/bots/{alias}/cli", self.admin_update_cli)
        app.router.add_patch("/api/admin/bots/{alias}/alias", self.admin_rename_bot)
        app.router.add_patch("/api/admin/bots/{alias}/workdir", self.admin_update_workdir)
        app.router.add_patch("/api/admin/bots/{alias}/avatar", self.admin_update_avatar)
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
        app.router.add_get("/api/admin/bots/{alias}/assistant/cron/jobs", self.admin_assistant_cron_jobs)
        app.router.add_post("/api/admin/bots/{alias}/assistant/cron/jobs", self.admin_assistant_cron_job_create)
        app.router.add_patch(
            "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}",
            self.admin_assistant_cron_job_update,
        )
        app.router.add_delete(
            "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}",
            self.admin_assistant_cron_job_delete,
        )
        app.router.add_post(
            "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/run",
            self.admin_assistant_cron_job_run,
        )
        app.router.add_get(
            "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/runs",
            self.admin_assistant_cron_job_runs,
        )
        app.router.add_get("/api/admin/git-proxy", self.admin_get_git_proxy)
        app.router.add_patch("/api/admin/git-proxy", self.admin_patch_git_proxy)
        app.router.add_get("/api/admin/update", self.admin_get_update)
        app.router.add_patch("/api/admin/update", self.admin_patch_update)
        app.router.add_post("/api/admin/update/check", self.admin_update_check)
        app.router.add_post("/api/admin/update/download", self.admin_update_download)
        app.router.add_post("/api/admin/update/download/stream", self.admin_update_download_stream)
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
            response = web.FileResponse(str(index_path))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        return web.Response(text="Not found", status=404)

    async def start(self):
        if self._runner is not None:
            return
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        if get_update_status().get("update_enabled"):
            self._update_task = asyncio.create_task(self._auto_refresh_update_status())
        if self._tunnel_service.should_autostart():
            tunnel_snapshot = await self._tunnel_service.start()
            await self._notify_tunnel_public_url(tunnel_snapshot, reason="web_server_start")
            logger.info("Web tunnel 状态: %s %s", tunnel_snapshot.get("status"), tunnel_snapshot.get("public_url") or "")
        local_url = TunnelService._build_local_url(self._host, self._port)
        logger.info(
            "Web API 已启动: %s (token=%s, allowed_origins=%s)",
            local_url,
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
        if self._update_task is not None:
            self._update_task.cancel()
            await asyncio.gather(self._update_task, return_exceptions=True)
            self._update_task = None
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
        debug_tasks = list(self._debug_tasks)
        self._debug_tasks.clear()
        for task in debug_tasks:
            task.cancel()
        if debug_tasks:
            await asyncio.gather(*debug_tasks, return_exceptions=True)
        debug_sockets = list(self._debug_sockets)
        self._debug_sockets.clear()
        for ws in debug_sockets:
            try:
                await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
            except Exception:
                pass
        await self._debug_service.shutdown()
        plugin_service = getattr(self.manager, "plugin_service", None)
        if plugin_service is not None:
            await plugin_service.shutdown()
        if preserve_tunnel:
            self._tunnel_service.preserve_for_restart()
        else:
            await self._tunnel_service.stop()
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        logger.info("Web API 已停止")
