"""aiohttp Web API 服务器。"""

from __future__ import annotations

import asyncio
import base64
import functools
import getpass
import ipaddress
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
import uuid
import zlib
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from aiohttp.client_exceptions import ClientConnectionResetError
from aiohttp.http import WSCloseCode, WSMsgType
from aiohttp import web
from ag_ui.encoder import EventEncoder

from bot.app_settings import get_git_proxy_settings, update_git_proxy_address
from bot.chat_identity import chat_session_user_id
from bot.config import (
    ALLOWED_USER_IDS,
    CHAT_COMPLETION_NOTIFY_ENABLED,
    PUSHPLUS_API_URL,
    PUSHPLUS_CHANNEL,
    PUSHPLUS_ENABLED,
    PUSHPLUS_PREVIEW_CHARS,
    PUSHPLUS_TEMPLATE,
    PUSHPLUS_TIMEOUT_SECONDS,
    PUSHPLUS_TOKEN,
    PUSHPLUS_TOPIC,
    TCB_HUB_FRPC_AUTOSTART,
    TCB_HUB_FRPC_PATH,
    TCB_HUB_FRPS_PORT,
    TCB_HUB_FRPS_TOKEN,
    TCB_HUB_NODE_TOKEN,
    TCB_NODE_ID,
    WEB_BASE_PATH,
    WEB_ALLOWED_ORIGINS,
    WEB_API_TOKEN,
    WEB_DEFAULT_USER_ID,
    WEB_FIXED_PUBLIC_FORWARD_ENABLED,
    WEB_FIXED_PUBLIC_FORWARD_URL,
    WEB_HOST,
    WEB_PORT,
    WEB_PUBLIC_URL,
    WEB_TERMINAL_SHELL_PATH,
    WEB_TUNNEL_AUTOSTART,
    WEB_TUNNEL_CLOUDFLARED_PATH,
    WEB_TUNNEL_MODE,
    WEB_TUNNEL_STATE_FILE,
    request_restart,
)
from bot.debug.service import DebugService
from bot.manager import MultiBotManager
from bot.models import session_persistence_diagnostics
from bot.native_agent import get_native_agent_service
from bot.native_agent.legacy_migration import (
    LEGACY_EXECUTION_MODE_REMOVED_MESSAGE,
    is_legacy_execution_mode,
)
from bot.platform.runtime import get_default_shell
from bot.runtime_paths import (
    get_announcements_content_path,
    get_announcements_reads_path,
    get_auth_accounts_dir,
    get_auth_register_codes_path,
    get_auth_secret_path,
    get_lan_chat_config_path,
    get_lan_chat_messages_path,
    get_permissions_root,
    get_tunnel_state_path,
)
from bot.session_store import close_session_store, session_store_diagnostics
from bot.updater import (
    check_for_updates,
    download_latest_update,
    get_update_status,
    list_offline_update_packages,
    prepare_offline_update,
    set_update_enabled,
)
from .announcement_store import AnnouncementStore
from .async_chat_store import ChatStoreOverloadedError, chat_store_executor_diagnostics, run_chat_store_io
from .cli_error_stats import collect_cli_error_stats
from .diagnostics import diag_enabled, diag_log_event, diag_log_slow, diag_loop_lag_ms
from .runtime_diagnostics import LoopLagTracker, RuntimeDiagnosticsRegistry
from .env_service import EnvConfigService, EnvValidationError
from .exposure_service import WebExposureService
from .fixed_forward_service import FixedForwardService
from .inline_completion_config import InlineCompletionConfigError, InlineCompletionConfigStore
from .inline_completion_service import InlineCompletionService, InlineCompletionServiceError
from .lan_chat_service import LanChatService
from .notification_service import ChatNotificationService
from .os_open_service import DesktopOpenError, open_directory_in_desktop
from .pushplus_client import PushPlusClient
from .auth_store import (
    AuthStoreError,
    CAP_ADMIN_OPS,
    CAP_CHAT_SEND,
    CAP_DEBUG_EXEC,
    CAP_GIT_OPS,
    CAP_INLINE_COMPLETION,
    CAP_CREATE_WORKDIR_DIRECTORY,
    CAP_MANAGE_BOTS,
    CAP_MANAGE_REGISTER_CODES,
    CAP_MUTATE_BROWSE_STATE,
    CAP_READ_FILE_CONTENT,
    CAP_RUN_PLUGINS,
    CAP_RUN_UNSAFE_CLI,
    CAP_TERMINAL_EXEC,
    CAP_VIEW_BOTS,
    CAP_VIEW_BOT_STATUS,
    CAP_VIEW_CHAT_HISTORY,
    CAP_VIEW_CHAT_TRACE,
    CAP_VIEW_FILE_TREE,
    CAP_VIEW_PLUGINS,
    CAP_WRITE_FILES,
    GUEST_CAPABILITIES,
    LOCAL_ADMIN_CAPABILITIES,
    MEMBER_CAPABILITIES,
    ROLE_GUEST,
    WebAuthSession,
    WebAuthStore,
)
from .permission_store import BotPermissionStore
from .terminal_manager import (
    TERMINAL_CLIENT_EOF,
    TerminalDelivery,
    TerminalLaunchError,
    TerminalNotRunningError,
    TerminalSessionManager,
    encode_terminal_ws_v2,
)
from .transfer_service import TransferService
from .tunnel_service import TunnelService
from .routes import (
    admin_routes,
    announcement_routes,
    auth_routes,
    bot_settings_routes,
    chat_routes,
    cluster_routes,
    debug_routes,
    files_routes,
    git_routes,
    lan_chat_routes,
    plugin_routes,
    terminal_routes,
    transfer_routes,
)
from .api_service import (
    AuthContext,
    _require_capability,
    WebApiError,
    add_managed_bot,
    build_bot_summary,
    change_working_directory,
    create_agent,
    create_conversation,
    delete_all_conversations,
    delete_conversation,
    delete_favorite_answer,
    execute_plan,
    create_directory,
    create_workdir_directory,
    create_text_file,
    copy_path,
    delete_path,
    delete_agent,
    dispose_plugin_view,
    execute_shell_command,
    get_plugin_artifact,
    get_plugin_view_window,
    invoke_plugin_action,
    install_plugin,
    uninstall_plugin,
    get_directory_listing,
    get_file_metadata,
    get_file_browser_directory,
    get_history,
    get_history_delta,
    get_native_agent_history_changes,
    get_native_agent_history_diff,
    get_history_trace,
    rollback_native_agent_history,
    get_native_agent_config_payload,
    get_native_agent_preflight_payload,
    get_native_agent_models_payload,
    get_overview,
    get_cluster_task_status,
    get_terminal_actions_config,
    get_cluster_bundle_schema,
    get_cli_params_payload,
    get_cluster_status,
    get_cluster_templates,
    get_processing_sessions,
    get_working_directory,
    kill_user_process,
    reply_native_agent_permission,
    list_bots,
    list_agents,
    list_conversations,
    list_favorite_answers,
    list_installable_plugins,
    list_plugins,
    open_plugin_view,
    read_file_content,
    rename_path,
    move_path,
    remove_managed_bot,
    remove_managed_bot_with_history,
    reset_user_session,
    reset_cli_params,
    resolve_terminal_action_for_bot,
    run_chat,
    handle_cluster_mcp_tool,
    render_plugin_view,
    resolve_plugin_file_target,
    reveal_directory_tree,
    save_chat_attachment_from_chunks,
    save_uploaded_file_from_chunks,
    save_terminal_actions_config_for_bot,
    start_managed_bot,
    stop_managed_bot,
    stream_update_download,
    stream_chat,
    select_conversation,
    delete_chat_attachment,
    update_cli_params,
    update_cluster_config,
    update_agent,
    update_bot_cli,
    update_bot_execution_config,
    update_global_prompt_presets,
    update_native_agent_config_payload,
    update_bot_native_agent_model,
    update_bot_prompt_presets,
    update_plugin,
    upsert_favorite_answer,
    rename_managed_bot,
    update_bot_workdir,
    write_file_content,
    prepare_cluster_setup,
    preview_cluster_config_bundle,
    preview_cluster_template,
    apply_cluster_config_bundle,
    apply_cluster_template,
    verify_cluster_mcp_request,
)
from bot.migrations.runner import migration_diagnostics
from .git_service import (
    apply_git_stash,
    commit_git_message,
    commit_git_changes,
    create_git_branch,
    discard_all_git_changes,
    discard_git_paths,
    drop_git_stash,
    fetch_git_remote,
    generate_git_smart_commit_message,
    generate_git_commit_message,
    get_git_commit_graph,
    get_git_commit_message_cli_config,
    get_git_diff,
    get_git_identity_config,
    get_git_overview,
    get_git_smart_commit_repo_hint,
    get_git_tree_status,
    git_service_diagnostics,
    init_git_repository,
    list_git_branches,
    list_git_stashes,
    preflight_git_smart_commit,
    pop_git_stash,
    pull_git_remote,
    push_git_remote,
    reset_git_commit_message_cli_config,
    reset_git_branch_to_commit,
    ensure_git_status_snapshot_unchanged,
    stage_all_git_changes,
    stage_git_paths,
    stash_git_changes,
    switch_git_branch,
    unstage_git_paths,
    update_git_commit_message_cli_config,
    update_git_identity_config,
)
from .workspace_search_service import (
    build_file_outline,
    quick_open_files,
    search_workspace_text,
    workspace_search_diagnostics,
)
from .workspace_definition_service import resolve_code_navigation, resolve_workspace_definition

logger = logging.getLogger(__name__)
DEFAULT_TERMINAL_OWNER_ID = "default"
# 给浏览器留出响应落地时间，避免服务重启过快导致前端请求悬挂。
RESTART_RESPONSE_DELAY_SECONDS = 1.0
_TUNNEL_STATUS_REFRESH_TIMEOUT = 1.0
_CLIENT_DISCONNECT_ERRORS = (
    ClientConnectionResetError,
    ConnectionResetError,
    BrokenPipeError,
)
_PUBLIC_RUNTIME_ENV_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>\s*window\.__TCB_PUBLIC_ENV__\s*=\s*.*?;\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
_HEAD_TAG_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_default_auth_store() -> WebAuthStore:
    return WebAuthStore(
        users_path=get_auth_accounts_dir(),
        register_codes_path=get_auth_register_codes_path(),
        secret_path=get_auth_secret_path(),
    )


def _build_default_permission_store() -> BotPermissionStore:
    return BotPermissionStore(get_permissions_root(), legacy_path=_REPO_ROOT / ".web_permissions.json")


def _build_default_announcement_store() -> AnnouncementStore:
    return AnnouncementStore(get_announcements_content_path(), reads_path=get_announcements_reads_path())


def _resolve_tunnel_state_file() -> Path:
    raw_value = str(WEB_TUNNEL_STATE_FILE or "").strip()
    if raw_value:
        raw_path = Path(raw_value).expanduser()
        if raw_path.is_absolute():
            return raw_path
    return get_tunnel_state_path()


_WEB_AUTH_STORE = _build_default_auth_store()
_BOT_PERMISSION_STORE = _build_default_permission_store()
_ANNOUNCEMENT_STORE = _build_default_announcement_store()


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


AUTH_SESSION_COOKIE_NAME = "tcb_web_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_TOKEN_SOURCE_AUTHORIZATION = "authorization"
AUTH_TOKEN_SOURCE_X_API_TOKEN = "x-api-token"
AUTH_TOKEN_SOURCE_QUERY = "query"
AUTH_TOKEN_SOURCE_COOKIE = "cookie"
AUTH_TOKEN_SOURCE_NONE = "none"


@dataclass(frozen=True)
class AuthToken:
    token: str
    source: str = AUTH_TOKEN_SOURCE_NONE


def _extract_auth_token_info(request: web.Request) -> AuthToken:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return AuthToken(auth_header[7:].strip(), AUTH_TOKEN_SOURCE_AUTHORIZATION)
    x_api_token = request.headers.get("X-API-Token", "").strip()
    if x_api_token:
        return AuthToken(x_api_token, AUTH_TOKEN_SOURCE_X_API_TOKEN)
    query_token = request.query.get("token", "").strip()
    if query_token:
        return AuthToken(query_token, AUTH_TOKEN_SOURCE_QUERY)
    cookie_token = request.cookies.get(AUTH_SESSION_COOKIE_NAME, "").strip()
    if cookie_token:
        return AuthToken(cookie_token, AUTH_TOKEN_SOURCE_COOKIE)
    return AuthToken("", AUTH_TOKEN_SOURCE_NONE)


def _extract_auth_token(request: web.Request) -> str:
    return _extract_auth_token_info(request).token


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
        "is_local_admin": auth.is_local_admin,
        "allowed_bots": ["*"] if auth.is_local_admin else sorted(auth.allowed_bot_aliases),
        "owned_bots": ["*"] if auth.is_local_admin else sorted(auth.owned_bot_aliases),
    }
    if token:
        payload["token"] = token
    return payload


def _auth_cookie_path() -> str:
    base_path = str(WEB_BASE_PATH or "").strip()
    if not base_path or base_path == "/":
        return "/"
    return "/" + base_path.strip("/")


def _request_is_secure(request: web.Request) -> bool:
    if request.secure:
        return True
    forwarded_proto = str(request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    return forwarded_proto == "https"


def _set_auth_cookie(request: web.Request, response: web.Response, token: str, *, remember: bool = False) -> None:
    kwargs: dict[str, Any] = {
        "path": _auth_cookie_path(),
        "httponly": True,
        "samesite": "Strict",
        "secure": _request_is_secure(request),
    }
    if remember:
        kwargs["max_age"] = 60 * 60 * 24 * 30
    response.set_cookie(AUTH_SESSION_COOKIE_NAME, token, **kwargs)


def _clear_auth_cookie(request: web.Request, response: web.Response) -> None:
    response.del_cookie(AUTH_SESSION_COOKIE_NAME, path=_auth_cookie_path())


def _session_user_id_for_account(account_id: str, session_user_id: int | None = None) -> int:
    if str(account_id or "").strip() == "local-admin":
        return WEB_DEFAULT_USER_ID
    if isinstance(session_user_id, int) and session_user_id > 0:
        return session_user_id
    seed = zlib.adler32(str(account_id or "web-account").encode("utf-8"))
    return 1_000_000 + int(seed)


def _same_origin_host(origin: str, host: str) -> bool:
    parsed = urlparse(origin)
    origin_host = parsed.netloc or parsed.path
    return bool(origin_host) and origin_host.lower() == str(host or "").strip().lower()


def _forwarded_request_origin(request: web.Request) -> str:
    host = str(
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("X-Original-Host")
        or ""
    ).split(",", 1)[0].strip()
    if not host:
        return ""
    proto = str(
        request.headers.get("X-Forwarded-Proto")
        or request.headers.get("X-Forwarded-Scheme")
        or ""
    ).split(",", 1)[0].strip() or "http"
    return _normalize_origin(f"{proto}://{host}")


def _is_request_origin_allowed(request: web.Request) -> bool:
    origin = str(request.headers.get("Origin") or "").strip()
    if not origin:
        return True
    normalized_allowed = {
        _normalize_origin(item)
        for item in chain(
            WEB_ALLOWED_ORIGINS,
            (_origin_only(WEB_PUBLIC_URL), _origin_only(WEB_FIXED_PUBLIC_FORWARD_URL)),
        )
        if str(item or "").strip()
    }
    normalized_origin = _normalize_origin(origin)
    if "*" in normalized_allowed or normalized_origin in normalized_allowed:
        return True
    return (
        _same_origin_host(origin, request.headers.get("Host", ""))
        or normalized_origin == _forwarded_request_origin(request)
    )


def _cookie_auth_requires_origin(request: web.Request, token_info: AuthToken) -> bool:
    return token_info.source == AUTH_TOKEN_SOURCE_COOKIE and request.method.upper() in UNSAFE_METHODS


def _is_cookie_write_origin_allowed(request: web.Request) -> bool:
    if not str(request.headers.get("Origin") or "").strip():
        return False
    return _is_request_origin_allowed(request)


def _require_auth_cookie_issue_origin(request: web.Request) -> None:
    if str(request.headers.get("Origin") or "").strip() and not _is_request_origin_allowed(request):
        raise WebApiError(403, "csrf_origin_rejected", "请求来源不被允许")


def _is_loopback_auto_auth_allowed(request: web.Request) -> bool:
    return _is_loopback_request(request) and _is_request_origin_allowed(request)


def _iter_field_chunks(field, *, chunk_size: int = 64 * 1024):
    async def iterator():
        while True:
            chunk = await field.read_chunk(size=chunk_size)
            if not chunk:
                break
            yield chunk

    return iterator()

def _serialize_auth_session(session: WebAuthSession, *, include_token: bool = False) -> dict[str, Any]:
    auth = AuthContext(
        user_id=_session_user_id_for_account(session.account.account_id, session.account.session_user_id),
        token_used=True,
        account_id=session.account.account_id,
        username=session.account.username,
        role=session.account.role,
        capabilities=set(session.capabilities),
        allowed_bot_aliases=_BOT_PERMISSION_STORE.allowed_bots_for_account(session.account.account_id),
        owned_bot_aliases=_BOT_PERMISSION_STORE.owned_bot_aliases(session.account.account_id),
        is_local_admin=session.account.account_id == "local-admin",
    )
    return _serialize_auth_context(auth, token=session.token if include_token else "")


def _parse_optional_int(value: object, *, field_name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise WebApiError(400, "invalid_request", f"{field_name} 必须是整数") from exc


def _parse_optional_bool(value: object, *, field_name: str, default: bool = False) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise WebApiError(400, "invalid_request", f"{field_name} 必须是布尔值")
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    raise WebApiError(400, "invalid_request", f"{field_name} 必须是布尔值")


def _normalize_origin(origin: str) -> str:
    return origin.rstrip("/")


def _origin_only(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return str(value or "").strip().rstrip("/")


def _format_sse(event_type: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


def _sse_headers() -> dict[str, str]:
    return {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store, no-cache, must-revalidate, no-transform",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


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
    except ChatStoreOverloadedError as exc:
        return _json(
            {"ok": False, "error": {"code": "chat_store_busy", "message": str(exc)}},
            status=503,
        )
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
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _request_diag_alias(request: web.Request) -> str:
    return str(request.match_info.get("alias") or request.query.get("alias") or "").strip()


def _request_diag_agent(request: web.Request) -> str:
    value = request.match_info.get("agent_id") or request.query.get("agent_id") or request.query.get("agentId")
    return str(value or "").strip() or "main"


def _is_websocket_request(request: web.Request) -> bool:
    return str(request.headers.get("Upgrade") or "").strip().lower() == "websocket"


@web.middleware
async def diag_slow_request_middleware(request: web.Request, handler):
    if not diag_enabled():
        return await handler(request)
    started_at = time.perf_counter()
    status = 500
    try:
        response = await handler(request)
        status = int(getattr(response, "status", 200) or 200)
        return response
    except web.HTTPException as exc:
        status = int(exc.status)
        raise
    finally:
        if not (_is_websocket_request(request) or status == 101):
            elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
            route = getattr(getattr(request, "match_info", None), "route", None)
            route_name = getattr(route, "resource", None)
            diag_log_slow(
                logger,
                "web_request",
                elapsed_ms,
                method=request.method,
                route=getattr(route_name, "canonical", "") or request.path,
                status=status,
                alias=_request_diag_alias(request),
                agent=_request_diag_agent(request),
            )


class WebApiServer:
    """可嵌入现有进程的 Web API 服务器。"""

    def __init__(
        self,
        manager: MultiBotManager,
        *,
        host: str | None = None,
        port: int | None = None,
        tunnel_service: TunnelService | None = None,
        fixed_forward_service: FixedForwardService | None = None,
        instance_id: str | None = None,
    ):
        self.manager = manager
        self._host = str(host or WEB_HOST or "").strip() or "0.0.0.0"
        self._port = int(port if port is not None else WEB_PORT)
        self._instance_id = str(instance_id or "").strip() or uuid.uuid4().hex
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._loop_lag_task: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._update_task: asyncio.Task[None] | None = None
        self._tunnel_ready_task: asyncio.Task[None] | None = None
        self._terminal_sockets: set[web.WebSocketResponse] = set()
        self._terminal_tasks: set[asyncio.Task[Any]] = set()
        self._terminal_manager = TerminalSessionManager()
        self._debug_service = DebugService(manager)
        self._debug_sockets: set[web.WebSocketResponse] = set()
        self._debug_tasks: set[asyncio.Task[Any]] = set()
        self._notification_tasks: set[asyncio.Task[Any]] = set()
        self._notification_service = ChatNotificationService(
            pushplus=PushPlusClient(
                enabled=PUSHPLUS_ENABLED,
                token=PUSHPLUS_TOKEN,
                topic=PUSHPLUS_TOPIC,
                template=PUSHPLUS_TEMPLATE,
                channel=PUSHPLUS_CHANNEL,
                api_url=PUSHPLUS_API_URL,
                timeout_seconds=PUSHPLUS_TIMEOUT_SECONDS,
            ),
            enabled=CHAT_COMPLETION_NOTIFY_ENABLED,
            preview_chars=PUSHPLUS_PREVIEW_CHARS,
        )
        self.announcement_store = _ANNOUNCEMENT_STORE
        self.lan_chat_service = LanChatService(
            repo_root=_REPO_ROOT,
            config_path=get_lan_chat_config_path(),
            messages_path=get_lan_chat_messages_path(),
        )
        self.env_config_service = EnvConfigService(_REPO_ROOT)
        self._git_smart_commit_jobs: dict[str, dict[str, Any]] = {}
        self._git_smart_commit_latest_by_alias: dict[str, str] = {}
        self._git_smart_commit_repo_locks: dict[str, str] = {}
        self._git_smart_commit_task_by_job: dict[str, asyncio.Task[None]] = {}
        self._tunnel_service = tunnel_service or TunnelService(
            host=self._host,
            port=self._port,
            mode=WEB_TUNNEL_MODE,
            autostart=WEB_TUNNEL_AUTOSTART,
            public_url=WEB_PUBLIC_URL,
            cloudflared_path=WEB_TUNNEL_CLOUDFLARED_PATH,
            state_file=str(_resolve_tunnel_state_file()),
            fixed_public_forward_enabled=WEB_FIXED_PUBLIC_FORWARD_ENABLED,
        )
        self._fixed_forward_service = fixed_forward_service or FixedForwardService(
            host=self._host,
            port=self._port,
            enabled=WEB_FIXED_PUBLIC_FORWARD_ENABLED,
            autostart=TCB_HUB_FRPC_AUTOSTART,
            public_url=WEB_FIXED_PUBLIC_FORWARD_URL,
            node_id=TCB_NODE_ID,
            base_path=WEB_BASE_PATH,
            frps_port=TCB_HUB_FRPS_PORT,
            node_token=TCB_HUB_NODE_TOKEN,
            frps_token=TCB_HUB_FRPS_TOKEN,
            frpc_path=TCB_HUB_FRPC_PATH,
            runtime_dir=get_tunnel_state_path().parent / "fixed-forward",
            instance_id=self._instance_id,
        )
        self._exposure_service = WebExposureService(
            tunnel_service=self._tunnel_service,
            fixed_forward_service=self._fixed_forward_service,
            fixed_public_forward_enabled=WEB_FIXED_PUBLIC_FORWARD_ENABLED,
            fixed_public_forward_url=WEB_FIXED_PUBLIC_FORWARD_URL,
            hub_node_token=TCB_HUB_NODE_TOKEN,
            node_id=TCB_NODE_ID,
            base_path=WEB_BASE_PATH,
        )
        self.transfer_service = TransferService(host=self._host, port=self._port)
        self.inline_completion_config_store = InlineCompletionConfigStore()
        self.inline_completion_service = InlineCompletionService(config_store=self.inline_completion_config_store)
        self._loop_lag_tracker = LoopLagTracker(threshold_ms=diag_loop_lag_ms())
        self._runtime_diagnostics = RuntimeDiagnosticsRegistry()
        self._runtime_diagnostics.register("loop_lag", self._loop_lag_tracker.diagnostics)
        self._runtime_diagnostics.register("terminal", self._terminal_manager.diagnostics)
        self._runtime_diagnostics.register("native_agent", get_native_agent_service().diagnostics)
        self._runtime_diagnostics.register("workspace_search", workspace_search_diagnostics)
        self._runtime_diagnostics.register("git", git_service_diagnostics)
        self._runtime_diagnostics.register("chat_store", chat_store_executor_diagnostics)
        self._runtime_diagnostics.register(
            "session_store",
            lambda: {**session_store_diagnostics(), **session_persistence_diagnostics()},
        )
        self._runtime_diagnostics.register("litellm", self.transfer_service.diagnostics)
        plugin_service = getattr(self.manager, "plugin_service", None)
        if plugin_service is not None:
            self._runtime_diagnostics.register("plugins", plugin_service.snapshot_cache_diagnostics)

    def _auth_context(self, request: web.Request) -> AuthContext:
        token_info = _extract_auth_token_info(request)
        raw_token = token_info.token
        if _cookie_auth_requires_origin(request, token_info) and not _is_cookie_write_origin_allowed(request):
            raise WebApiError(403, "csrf_origin_rejected", "请求来源不被允许")
        if raw_token:
            if token_info.source == AUTH_TOKEN_SOURCE_QUERY:
                raise WebApiError(401, "query_token_disabled", "URL token 已禁用")
            session = _WEB_AUTH_STORE.get_session(raw_token)
            if session is not None:
                return self._session_auth_context(session)
            if _is_loopback_auto_auth_allowed(request):
                return self._local_admin_auth_context()
            if token_info.source in {AUTH_TOKEN_SOURCE_AUTHORIZATION, AUTH_TOKEN_SOURCE_X_API_TOKEN} and WEB_API_TOKEN and raw_token == WEB_API_TOKEN:
                return self._legacy_auth_context(request, token_used=True)
            raise WebApiError(401, "unauthorized", "访问令牌无效")

        if _is_loopback_auto_auth_allowed(request):
            return self._local_admin_auth_context()
        if WEB_API_TOKEN:
            raise WebApiError(401, "unauthorized", "访问令牌无效")
        if _WEB_AUTH_STORE.can_bootstrap_without_auth():
            raise WebApiError(401, "setup_required", "请从本机完成初始化")
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
            capabilities=set(LOCAL_ADMIN_CAPABILITIES),
            allowed_bot_aliases=set(),
            owned_bot_aliases=set(),
            is_local_admin=True,
        )

    def _session_auth_context(self, session: WebAuthSession) -> AuthContext:
        if session.account.account_id == "local-admin":
            self._ensure_allowed_user_id(WEB_DEFAULT_USER_ID)
        return AuthContext(
            user_id=_session_user_id_for_account(session.account.account_id, session.account.session_user_id),
            token_used=True,
            account_id=session.account.account_id,
            username=session.account.username,
            role=session.account.role,
            capabilities=set(session.capabilities),
            allowed_bot_aliases=_BOT_PERMISSION_STORE.allowed_bots_for_account(session.account.account_id),
            owned_bot_aliases=_BOT_PERMISSION_STORE.owned_bot_aliases(session.account.account_id),
            is_local_admin=session.account.account_id == "local-admin",
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
            allowed_bot_aliases=set(),
            owned_bot_aliases=set(),
            is_local_admin=True,
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
        raw_alias = request.match_info.get("alias")
        alias = str(raw_alias or "").strip().lower() if isinstance(raw_alias, str) else ""
        if alias:
            auth = self._bot_auth(auth, alias)
            request["auth"] = auth
        if self._allows_readonly_bot_capability(request, capability, auth):
            elevated = auth.with_capabilities({*auth.capabilities, capability})
            request["auth"] = elevated
            return elevated
        _require_capability(auth, capability)
        return auth

    async def _with_any_capability(self, request: web.Request, capabilities: set[str]) -> AuthContext:
        auth = await self._with_auth(request)
        if any(capability in auth.capabilities for capability in capabilities):
            return auth
        raise WebApiError(403, "forbidden", "权限不足")

    async def _with_bot_config_access(self, request: web.Request) -> AuthContext:
        auth = await self._with_auth(request)
        if not self._is_local_admin(auth) and auth.role != "member":
            raise WebApiError(403, "forbidden", "权限不足")
        raw_alias = request.match_info.get("alias")
        alias = str(raw_alias or "").strip().lower() if isinstance(raw_alias, str) else ""
        if alias:
            auth = self._bot_auth(auth, alias)
            request["auth"] = auth
        return auth

    async def _with_cluster_bot_config_access(self, request: web.Request) -> AuthContext:
        return await self._with_bot_config_access(request)

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

    def _normalize_bot_alias(self, alias: str) -> str:
        return str(alias or "").strip().lower()

    def _is_local_admin(self, auth: AuthContext) -> bool:
        return auth.is_local_admin or auth.account_id == "local-admin"

    def _require_websocket_origin(self, request: web.Request) -> None:
        if _is_request_origin_allowed(request):
            return
        logger.warning(
            "WebSocket Origin 不被允许 path=%s origin=%s host=%s forwarded_host=%s forwarded_proto=%s allowed_origins=%s public_url=%s fixed_public_url=%s",
            request.path,
            request.headers.get("Origin", ""),
            request.headers.get("Host", ""),
            request.headers.get("X-Forwarded-Host", ""),
            request.headers.get("X-Forwarded-Proto", ""),
            ",".join(WEB_ALLOWED_ORIGINS),
            WEB_PUBLIC_URL,
            WEB_FIXED_PUBLIC_FORWARD_URL,
        )
        raise web.HTTPForbidden(text="WebSocket Origin 不被允许")

    async def _with_websocket_auth(self, request: web.Request) -> AuthContext:
        token_info = _extract_auth_token_info(request)
        auth = await self._with_auth(request)
        if token_info.source in {AUTH_TOKEN_SOURCE_COOKIE, AUTH_TOKEN_SOURCE_NONE}:
            self._require_websocket_origin(request)
        return auth

    async def _with_websocket_capability(self, request: web.Request, capability: str) -> AuthContext:
        token_info = _extract_auth_token_info(request)
        auth = await self._with_capability(request, capability)
        if token_info.source in {AUTH_TOKEN_SOURCE_COOKIE, AUTH_TOKEN_SOURCE_NONE}:
            self._require_websocket_origin(request)
        return auth

    def _can_operate_bot(self, auth: AuthContext, alias: str) -> bool:
        normalized_alias = self._normalize_bot_alias(alias)
        if auth.role == ROLE_GUEST:
            return normalized_alias == self._normalize_bot_alias(self.manager.main_profile.alias)
        return self._is_local_admin(auth) or _BOT_PERMISSION_STORE.can_operate_bot(auth.account_id, normalized_alias)

    def _bot_auth(self, auth: AuthContext, alias: str) -> AuthContext:
        if self._can_operate_bot(auth, alias):
            return auth
        raise WebApiError(403, "bot_forbidden", "无权访问该 Bot")

    def _allows_readonly_bot_capability(self, request: web.Request, capability: str, auth: AuthContext) -> bool:
        if capability in auth.capabilities:
            return True
        return False

    def _decorate_bot_for_auth(self, auth: AuthContext, item: dict[str, Any]) -> dict[str, Any]:
        alias = self._normalize_bot_alias(str(item.get("alias") or ""))
        can_operate = self._can_operate_bot(auth, alias)
        if can_operate:
            effective = auth
            bot_item = dict(item)
        else:
            effective = auth.with_capabilities(set())
            bot_item = self._redact_bot_summary(item)
        return {
            **bot_item,
            "can_operate": can_operate,
            "effective_capabilities": sorted(effective.capabilities),
            "owner_account_id": _BOT_PERMISSION_STORE.bot_owner(alias),
        }

    def _decorate_bots_for_auth(self, auth: AuthContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._decorate_bot_for_auth(auth, item) for item in items]

    def _redact_bot_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(item)
        for key in (
            "cli_path",
            "working_dir",
            "prompt_presets",
            "global_prompt_presets",
            "cluster",
            "active_cluster_run",
            "agents",
        ):
            redacted.pop(key, None)
        return redacted

    def _authorized_bot_aliases(self, auth: AuthContext) -> set[str]:
        if self._is_local_admin(auth):
            return {self._normalize_bot_alias(self.manager.main_profile.alias), *self.manager.managed_profiles.keys()}
        if auth.role == ROLE_GUEST:
            return {self._normalize_bot_alias(self.manager.main_profile.alias)}
        return {
            alias
            for alias in set(auth.allowed_bot_aliases) | set(auth.owned_bot_aliases)
            if self._normalize_bot_alias(alias)
        }

    def _filter_bots_for_auth(self, auth: AuthContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._is_local_admin(auth):
            return items
        allowed = self._authorized_bot_aliases(auth)
        return [
            item
            for item in items
            if self._normalize_bot_alias(str(item.get("alias") or "")) in allowed
        ]

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

    def _build_git_smart_commit_job(
        self,
        *,
        alias: str,
        user_id: int,
    ) -> dict[str, Any]:
        job_id = f"gsc_{uuid.uuid4().hex}"
        job = {
            "job_id": job_id,
            "alias": alias,
            "user_id": user_id,
            "repo_root": "",
            "status": "queued",
            "phase": "preflight",
            "message": "",
            "overview": None,
            "error": "",
        }
        self._git_smart_commit_jobs[job_id] = job
        self._git_smart_commit_latest_by_alias[alias] = job_id
        return job

    def _git_smart_commit_snapshot(self, job: dict[str, Any]) -> dict[str, Any]:
        overview = job.get("overview")
        return {
            "job_id": str(job.get("job_id") or ""),
            "alias": str(job.get("alias") or ""),
            "user_id": int(job.get("user_id") or 0),
            "status": str(job.get("status") or "queued"),
            "phase": str(job.get("phase") or "preflight"),
            "message": str(job.get("message") or ""),
            "overview": overview if isinstance(overview, dict) and overview else None,
            "error": str(job.get("error") or ""),
        }

    def _set_git_smart_commit_job(
        self,
        job: dict[str, Any],
        *,
        status: str | None = None,
        phase: str | None = None,
        message: str | None = None,
        overview: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status is not None:
            job["status"] = status
        if phase is not None:
            job["phase"] = phase
        if message is not None:
            job["message"] = message
        if overview is not None:
            job["overview"] = overview
        if error is not None:
            job["error"] = error

    def _get_git_smart_commit_job_or_raise(self, alias: str, job_id: str) -> dict[str, Any]:
        job = self._git_smart_commit_jobs.get(job_id)
        if not job or str(job.get("alias") or "") != alias:
            raise WebApiError(404, "git_smart_commit_job_not_found", "未找到智能提交任务")
        return job

    async def _run_git_smart_commit_job(
        self,
        job_id: str,
        *,
        alias: str,
        user_id: int,
    ) -> None:
        job = self._git_smart_commit_jobs.get(job_id)
        if not job:
            return

        repo_root = str(job.get("repo_root") or "")
        try:
            self._set_git_smart_commit_job(job, status="running", phase="preflight", error="")
            _working_dir, repo_root, snapshot = await asyncio.to_thread(
                preflight_git_smart_commit,
                self.manager,
                alias,
                user_id,
            )
            lock_holder = self._git_smart_commit_repo_locks.get(repo_root)
            if lock_holder and lock_holder != job_id:
                raise WebApiError(409, "git_smart_commit_conflict", "当前仓库已有智能提交任务在运行")
            self._git_smart_commit_repo_locks[repo_root] = job_id
            job["repo_root"] = repo_root

            self._set_git_smart_commit_job(job, phase="generating")
            generated = await generate_git_smart_commit_message(
                self.manager,
                alias,
                user_id,
                repo_root=repo_root,
            )
            message = str(generated.get("message") or "").strip()
            self._set_git_smart_commit_job(job, message=message)

            await asyncio.to_thread(ensure_git_status_snapshot_unchanged, repo_root, snapshot)

            self._set_git_smart_commit_job(job, phase="staging")
            await asyncio.to_thread(stage_all_git_changes, repo_root)

            self._set_git_smart_commit_job(job, phase="committing")
            await asyncio.to_thread(commit_git_message, repo_root, message)
            overview = await asyncio.to_thread(get_git_overview, self.manager, alias, user_id)

            self._set_git_smart_commit_job(
                job,
                status="succeeded",
                phase="done",
                overview=overview,
                error="",
            )
        except WebApiError as exc:
            self._set_git_smart_commit_job(job, status="failed", error=exc.message)
        except Exception as exc:
            logger.exception("smart commit job failed: %s", exc)
            self._set_git_smart_commit_job(job, status="failed", error=str(exc) or "智能提交失败")
        finally:
            if repo_root and self._git_smart_commit_repo_locks.get(repo_root) == job_id:
                self._git_smart_commit_repo_locks.pop(repo_root, None)
            self._git_smart_commit_task_by_job.pop(job_id, None)

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

    def _schedule_tunnel_ready_notification(self, snapshot: dict[str, Any], *, reason: str) -> None:
        if snapshot.get("status") not in {"starting", "connected", "verifying_public"}:
            return
        if snapshot.get("source") != "quick_tunnel":
            return
        if not str(snapshot.get("public_url") or "").strip():
            return
        if self._tunnel_ready_task is not None and not self._tunnel_ready_task.done():
            self._tunnel_ready_task.cancel()

        async def wait_and_notify() -> None:
            try:
                ready_snapshot = await self._tunnel_service.wait_until_public_ready()
                await self._notify_tunnel_public_url(ready_snapshot, reason=f"{reason}_ready")
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("等待 Web tunnel 公网地址就绪失败: %s", exc)

        self._tunnel_ready_task = asyncio.create_task(wait_and_notify())

    async def _notify_or_schedule_tunnel_public_url(self, snapshot: dict[str, Any], *, reason: str) -> None:
        if snapshot.get("status") == "running":
            await self._notify_tunnel_public_url(snapshot, reason=reason)
            return
        self._schedule_tunnel_ready_notification(snapshot, reason=reason)

    async def _fresh_tunnel_snapshot(self) -> dict[str, Any]:
        return self._exposure_service.snapshot()

    async def health(self, request: web.Request) -> web.Response:
        return _json(
            {
                "ok": True,
                "service": "telegram-cli-bridge-web",
                "web_enabled": True,
                "host": self._host,
                "port": self._port,
                "instance_id": self._instance_id,
                "node_id": TCB_NODE_ID,
                "base_path": self._web_base_path(),
                "host_info": _build_public_host_info(),
            }
        )

    async def auth_me(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        token_info = _extract_auth_token_info(request)
        include_token = auth.token_used and token_info.source in {AUTH_TOKEN_SOURCE_AUTHORIZATION, AUTH_TOKEN_SOURCE_X_API_TOKEN}
        response = _json({"ok": True, "data": _serialize_auth_context(auth, token=token_info.token if include_token else "")})
        if include_token and _WEB_AUTH_STORE.get_session(token_info.token) is not None:
            _set_auth_cookie(request, response, token_info.token, remember=False)
        return response

    async def auth_login(self, request: web.Request) -> web.Response:
        _require_auth_cookie_issue_origin(request)
        if _is_loopback_auto_auth_allowed(request):
            return _json({"ok": True, "data": _serialize_auth_context(self._local_admin_auth_context())})
        body = await self._parse_json(request)
        try:
            session = _WEB_AUTH_STORE.login_member(
                str(body.get("username", "")),
                str(body.get("password", "")),
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        response = _json({"ok": True, "data": _serialize_auth_session(session)})
        _set_auth_cookie(request, response, session.token, remember=bool(body.get("remember")))
        return response

    async def auth_register(self, request: web.Request) -> web.Response:
        _require_auth_cookie_issue_origin(request)
        body = await self._parse_json(request)
        try:
            session = _WEB_AUTH_STORE.register_member(
                str(body.get("username", "")),
                str(body.get("password", "")),
                str(body.get("register_code", "")),
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        response = _json({"ok": True, "data": _serialize_auth_session(session)})
        _set_auth_cookie(request, response, session.token, remember=bool(body.get("remember")))
        return response

    async def auth_guest(self, request: web.Request) -> web.Response:
        _require_auth_cookie_issue_origin(request)
        session = _WEB_AUTH_STORE.create_guest_session()
        response = _json({"ok": True, "data": _serialize_auth_session(session)})
        _set_auth_cookie(request, response, session.token, remember=False)
        return response

    async def auth_logout(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        raw_token = _extract_auth_token(request)
        if raw_token and _WEB_AUTH_STORE.get_session(raw_token) is not None:
            _WEB_AUTH_STORE.delete_session(raw_token)
        response = _json({"ok": True, "data": {"username": auth.username}})
        _clear_auth_cookie(request, response)
        return response

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

    async def admin_users(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        permission_items = _BOT_PERMISSION_STORE.list_user_permission_summaries()["items"]
        permissions = {item["account_id"]: item for item in permission_items}
        users = []
        for user in _WEB_AUTH_STORE.list_members()["items"]:
            account_id = user["account_id"]
            permission = permissions.get(account_id, {})
            users.append(
                {
                    **user,
                    "allowed_bots": permission.get("allowed_bots", []),
                    "owned_bots": permission.get("owned_bots", []),
                    "owned_bot_count": permission.get("owned_bot_count", 0),
                    "bot_create_limit": permission.get("bot_create_limit", _BOT_PERMISSION_STORE.MEMBER_BOT_LIMIT),
                }
            )
        return _json({"ok": True, "data": {"items": users}})

    async def admin_user_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        body = await self._parse_json(request)
        try:
            user = _WEB_AUTH_STORE.update_member(
                request.match_info["account_id"],
                disabled=body.get("disabled") if "disabled" in body else None,
                capabilities=body.get("capabilities") if isinstance(body.get("capabilities"), list) else None,
            )
        except AuthStoreError as exc:
            raise _auth_error(exc) from exc
        return _json({"ok": True, "data": user})

    async def admin_user_permissions_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_MANAGE_REGISTER_CODES)
        body = await self._parse_json(request)
        allowed_bots = body.get("allowed_bots")
        if not isinstance(allowed_bots, list):
            raise WebApiError(400, "invalid_allowed_bots", "allowed_bots 必须是数组")
        known_aliases = {self.manager.main_profile.alias, *self.manager.managed_profiles.keys()}
        normalized = [str(alias or "").strip().lower() for alias in allowed_bots]
        unknown = sorted(alias for alias in normalized if alias and alias not in known_aliases)
        if unknown:
            raise WebApiError(400, "unknown_bot_alias", "包含不存在的 Bot", {"aliases": unknown})
        data = _BOT_PERMISSION_STORE.set_allowed_bots(request.match_info["account_id"], normalized)
        return _json({"ok": True, "data": data})

    async def get_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_BOTS)
        items = self._filter_bots_for_auth(auth, list_bots(self.manager, auth.user_id))
        return _json({"ok": True, "data": self._decorate_bots_for_auth(auth, items)})

    async def get_plugins(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_PLUGINS)
        refresh = str(request.query.get("refresh", "")).lower() in {"1", "true", "yes"}
        return _json({"ok": True, "data": await list_plugins(self.manager, auth, refresh=refresh)})

    async def get_installable_plugins(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_PLUGINS)
        return _json({"ok": True, "data": await list_installable_plugins(self.manager, auth)})

    async def post_install_plugin(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        body = await self._parse_json(request)
        body["_local_request"] = _is_loopback_request(request)
        return _json({"ok": True, "data": await install_plugin(self.manager, auth, dict(body or {}))})

    async def patch_plugin(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await update_plugin(self.manager, auth, plugin_id, dict(body or {}))})

    async def delete_plugin(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        return _json({"ok": True, "data": await uninstall_plugin(self.manager, auth, plugin_id)})

    async def get_bot_overview(self, request: web.Request) -> web.Response:
        base_auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        auth = self._bot_auth(base_auth, alias)
        _require_capability(auth, CAP_VIEW_BOT_STATUS)
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        data = get_overview(self.manager, alias, auth.user_id, agent_id=agent_id, execution_mode=execution_mode)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(base_auth, data["bot"])}})

    def _request_agent_id(self, request: web.Request, body: dict[str, Any] | None = None) -> str:
        value = request.query.get("agent_id") or request.query.get("agentId")
        if not value and isinstance(body, dict):
            value = body.get("agent_id") or body.get("agentId")
        if not isinstance(value, str):
            return "main"
        return str(value or "main").strip().lower() or "main"

    def _request_execution_mode(
        self,
        request: web.Request,
        body: dict[str, Any] | None = None,
        *,
        include_query: bool = True,
        include_body: bool = True,
    ) -> str:
        value: Any = ""
        if include_body and isinstance(body, dict):
            value = body.get("execution_mode") or body.get("executionMode") or value
        if include_query and not value:
            value = request.query.get("execution_mode") or request.query.get("executionMode") or value
        normalized = str(value or "").strip()
        if is_legacy_execution_mode(normalized):
            raise WebApiError(400, "invalid_execution_mode", LEGACY_EXECUTION_MODE_REMOVED_MESSAGE)
        return normalized

    def _chat_user_id(self, auth: AuthContext) -> int:
        return chat_session_user_id(auth.user_id)

    def _chat_actor(self, auth: AuthContext) -> dict[str, Any]:
        return {
            "user_id": auth.user_id,
            "account_id": auth.account_id,
            "username": auth.username,
        }

    def _decorate_chat_authors(self, data: Any, auth: AuthContext) -> Any:
        if isinstance(data, list):
            return [self._decorate_chat_authors(item, auth) for item in data]
        if not isinstance(data, dict):
            return data
        result = dict(data)
        author = result.get("author")
        if isinstance(author, dict):
            next_author = dict(author)
            if int(next_author.get("user_id") or 0) == int(auth.user_id):
                next_author["is_current_user"] = True
            elif next_author:
                next_author["is_current_user"] = False
            result["author"] = next_author
        for key in ("items", "messages"):
            if isinstance(result.get(key), list):
                result[key] = [self._decorate_chat_authors(item, auth) for item in result[key]]
        message = result.get("message")
        if isinstance(message, dict):
            result["message"] = self._decorate_chat_authors(message, auth)
        return result

    def _public_tunnel_url(self) -> str:
        return self._exposure_service.public_url()

    def _chat_notification_url(self, alias: str, conversation_id: str = "") -> str:
        base_url = self._public_tunnel_url()
        if not base_url:
            return ""
        safe_alias = quote(str(alias or "").strip().lower() or "main", safe="")
        path = f"/bots/{safe_alias}/chat"
        if conversation_id:
            path = f"{path}?{urlencode({'conversation_id': conversation_id})}"
        return f"{base_url}{path}"

    def _extract_chat_notification_payload(
        self,
        *,
        alias: str,
        agent_id: str,
        data: dict[str, Any],
        fallback_status: str = "success",
    ) -> dict[str, Any]:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        session = data.get("session") if isinstance(data.get("session"), dict) else {}
        meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
        completion_state = str(meta.get("completion_state") or "").strip().lower()
        state = str(message.get("state") or "").strip().lower()
        status = "error" if fallback_status == "error" or completion_state in {"error", "failed"} or state == "error" else "success"
        conversation_id = str(
            session.get("active_conversation_id")
            or data.get("conversation_id")
            or data.get("conversationId")
            or message.get("conversation_id")
            or ""
        ).strip()
        message_id = str(message.get("id") or data.get("message_id") or data.get("messageId") or "").strip()
        if not message_id and not conversation_id:
            message_id = str(data.get("id") or data.get("code") or f"event_{uuid.uuid4().hex}")
        preview = str(
            data.get("output")
            or message.get("content")
            or data.get("preview")
            or data.get("message")
            or ""
        ).strip()
        if completion_state == "cancelled":
            status = "cancelled"
        return {
            "bot_alias": alias,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "status": status,
            "preview": preview,
            "elapsed_seconds": data.get("elapsed_seconds"),
            "url": self._chat_notification_url(alias, conversation_id),
        }

    async def _safe_notify_chat_terminal_event(
        self,
        *,
        auth: AuthContext,
        alias: str,
        agent_id: str,
        data: dict[str, Any],
        fallback_status: str = "success",
    ) -> None:
        try:
            payload = self._extract_chat_notification_payload(
                alias=alias,
                agent_id=agent_id,
                data=data,
                fallback_status=fallback_status,
            )
            if payload.get("status") == "cancelled":
                return
            await self._notification_service.notify_chat_completed(
                account_id=auth.account_id,
                user_id=auth.user_id,
                **payload,
            )
        except Exception as exc:
            logger.warning("聊天完成通知失败 alias=%s user_id=%s error=%s", alias, auth.user_id, exc)

    def _schedule_chat_terminal_event(
        self,
        *,
        auth: AuthContext,
        alias: str,
        agent_id: str,
        data: dict[str, Any],
        fallback_status: str = "success",
    ) -> None:
        task = asyncio.create_task(
            self._safe_notify_chat_terminal_event(
                auth=auth,
                alias=alias,
                agent_id=agent_id,
                data=data,
                fallback_status=fallback_status,
            )
        )
        self._notification_tasks.add(task)

        def discard_task(done_task: asyncio.Task[Any]) -> None:
            self._notification_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("聊天完成通知任务失败 alias=%s user_id=%s error=%s", alias, auth.user_id, exc)

        task.add_done_callback(discard_task)

    async def get_agents_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_BOT_STATUS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": list_agents(self.manager, alias, auth.user_id)})

    async def post_agent_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await create_agent(self.manager, alias, dict(body or {}))})

    async def patch_agent_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        agent_id = request.match_info.get("agent_id", "")
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await update_agent(self.manager, alias, agent_id, dict(body or {}))})

    async def delete_agent_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        agent_id = request.match_info.get("agent_id", "")
        return _json({"ok": True, "data": await delete_agent(self.manager, alias, agent_id)})

    async def get_cluster_status_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_VIEW_BOT_STATUS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_cluster_status(self.manager, alias)})

    async def get_cluster_run_tasks_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        run_id = request.match_info.get("run_id", "")
        raw_task_ids = request.query.get("task_ids", "")
        task_ids = [item.strip() for item in raw_task_ids.split(",") if item.strip()] if raw_task_ids else None
        include_output = request.query.get("include_output", "1") not in {"0", "false", "False"}
        include_messages = request.query.get("include_messages", "0") in {"1", "true", "True"}
        try:
            message_limit = int(request.query.get("message_limit", "20"))
        except ValueError:
            message_limit = 20
        data = get_cluster_task_status(
            self.manager,
            alias,
            self._chat_user_id(auth),
            run_id,
            task_ids=task_ids,
            include_output=include_output,
            include_messages=include_messages,
            message_limit=message_limit,
        )
        return _json({"ok": True, "data": data})

    async def post_cluster_setup_prepare(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": prepare_cluster_setup(self.manager, alias)})

    async def post_cluster_config(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await update_cluster_config(self.manager, alias, dict(body or {}))})

    async def get_cluster_templates_view(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_cluster_templates(self.manager, alias)})

    async def get_bot_cluster_schema_view(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        return _json({"ok": True, "data": get_cluster_bundle_schema()})

    async def get_cluster_schema_view(self, request: web.Request) -> web.Response:
        await self._with_any_capability(request, {CAP_MANAGE_BOTS, CAP_ADMIN_OPS})
        return _json({"ok": True, "data": get_cluster_bundle_schema()})

    async def post_cluster_template_preview(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": preview_cluster_template(self.manager, alias, dict(body or {}))})

    async def post_cluster_template_apply(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await apply_cluster_template(self.manager, alias, dict(body or {}))})

    async def post_cluster_bundle_preview(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": preview_cluster_config_bundle(self.manager, alias, dict(body or {}))})

    async def post_cluster_bundle_apply(self, request: web.Request) -> web.Response:
        await self._with_cluster_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": await apply_cluster_config_bundle(self.manager, alias, dict(body or {}))})

    async def cluster_mcp_ping(self, request: web.Request) -> web.Response:
        verify_cluster_mcp_request(request.headers)
        return _json({"ok": True, "data": {"status": "ok"}})

    async def cluster_mcp_tool(self, request: web.Request) -> web.Response:
        verify_cluster_mcp_request(request.headers)
        run_id = request.headers.get("X-TCB-Cluster-Run-Id", "")
        tool_name = request.match_info.get("tool_name", "")
        body = await self._parse_json(request)
        data = await handle_cluster_mcp_tool(self.manager, run_id, tool_name, dict(body or {}))
        return _json({"ok": True, "data": data})

    async def post_chat(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        task_mode = str(body.get("task_mode") or "").strip()
        task_payload = body.get("task_payload")
        visible_text = body.get("visible_text")
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        agent_id = self._request_agent_id(request, body)
        cluster_enabled = bool(body.get("cluster"))
        solo_mode = bool(body.get("solo_mode") or body.get("soloMode"))
        mentions = body.get("mentions") if isinstance(body.get("mentions"), list) else []
        chat_user_id = self._chat_user_id(auth)
        actor = self._chat_actor(auth)
        allow_unsafe_cli = CAP_RUN_UNSAFE_CLI in auth.capabilities
        try:
            if task_mode or isinstance(task_payload, dict) or visible_text is not None:
                data = await run_chat(
                    self.manager,
                    alias,
                    chat_user_id,
                    body.get("message", ""),
                    task_mode=task_mode or "standard",
                    task_payload=dict(task_payload) if isinstance(task_payload, dict) else None,
                    visible_text=str(visible_text) if visible_text is not None else None,
                    agent_id=agent_id,
                    cluster=cluster_enabled,
                    mentions=mentions,
                    execution_mode=execution_mode,
                    solo_mode=solo_mode,
                    actor=actor,
                    allow_unsafe_cli=allow_unsafe_cli,
                )
            else:
                data = await run_chat(
                    self.manager,
                    alias,
                    chat_user_id,
                    body.get("message", ""),
                    agent_id=agent_id,
                    cluster=cluster_enabled,
                    mentions=mentions,
                    execution_mode=execution_mode,
                    solo_mode=solo_mode,
                    actor=actor,
                    allow_unsafe_cli=allow_unsafe_cli,
                )
        except Exception as exc:
            self._schedule_chat_terminal_event(
                auth=auth,
                alias=alias,
                agent_id=agent_id,
                data={"output": str(exc), "elapsed_seconds": 0},
                fallback_status="error",
            )
            raise
        self._schedule_chat_terminal_event(auth=auth, alias=alias, agent_id=agent_id, data=data)
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def post_chat_stream(self, request: web.Request) -> web.StreamResponse:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        task_mode = str(body.get("task_mode") or "").strip()
        task_payload = body.get("task_payload")
        visible_text = body.get("visible_text")
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        protocol = str(request.query.get("protocol") or body.get("protocol") or "").strip()
        agent_id = self._request_agent_id(request, body)
        cluster_enabled = bool(body.get("cluster"))
        solo_mode = bool(body.get("solo_mode") or body.get("soloMode"))
        mentions = body.get("mentions") if isinstance(body.get("mentions"), list) else []
        chat_user_id = self._chat_user_id(auth)
        actor = self._chat_actor(auth)
        wants_ag_ui = protocol.lower() == "ag-ui"
        ag_ui_encoder = EventEncoder() if wants_ag_ui else None
        allow_unsafe_cli = CAP_RUN_UNSAFE_CLI in auth.capabilities
        raw_stream_id = body.get("stream_id", body.get("streamId", ""))
        raw_turn_id = body.get("turn_id", body.get("turnId", ""))
        if not isinstance(raw_stream_id, str) or not isinstance(raw_turn_id, str):
            raise WebApiError(400, "invalid_resume_identity", "恢复 stream_id/turn_id 必须是字符串")
        resume_stream_id = raw_stream_id.strip()
        resume_turn_id = raw_turn_id.strip()
        if len(resume_stream_id) > 128 or len(resume_turn_id) > 128:
            raise WebApiError(400, "invalid_resume_identity", "恢复 stream_id/turn_id 不合法")
        raw_after_sequence = body.get("after_sequence", body.get("afterSequence", 0))
        try:
            if isinstance(raw_after_sequence, bool):
                raise ValueError
            after_sequence = int(raw_after_sequence or 0)
        except (TypeError, ValueError):
            raise WebApiError(400, "invalid_resume_sequence", "恢复 after_sequence 必须是非负整数")
        if after_sequence < 0:
            raise WebApiError(400, "invalid_resume_sequence", "恢复 after_sequence 必须是非负整数")
        if not resume_stream_id and (resume_turn_id or after_sequence):
            raise WebApiError(400, "invalid_resume_identity", "恢复请求缺少 stream_id")
        if resume_stream_id:
            try:
                get_native_agent_service().resume_turn_channel(resume_stream_id, turn_id=resume_turn_id)
            except RuntimeError as exc:
                message = str(exc).strip() or "Pi turn 恢复流不存在或已过期"
                code = "native_turn_stream_mismatch" if "不匹配" in message else "native_turn_stream_expired"
                status = 409 if code.endswith("mismatch") else 410
                raise WebApiError(status, code, message) from exc
        enable_reconnect = bool(body.get("stream_reconnect") or body.get("streamReconnect"))

        response = web.StreamResponse(
            status=200,
            headers=_sse_headers(),
        )
        await response.prepare(request)
        await response.write(b": ready\n\n")

        client_disconnected = False
        stream_kwargs: dict[str, Any] = {
            "protocol": protocol,
            "allow_unsafe_cli": allow_unsafe_cli,
            "resume_stream_id": resume_stream_id,
            "resume_turn_id": resume_turn_id,
            "after_sequence": after_sequence,
            "enable_reconnect": enable_reconnect,
        }
        if execution_mode:
            stream_kwargs["execution_mode"] = execution_mode
        if solo_mode:
            stream_kwargs["solo_mode"] = True
        if agent_id != "main":
            stream_kwargs["agent_id"] = agent_id
        if cluster_enabled:
            stream_kwargs["cluster"] = True
            stream_kwargs["mentions"] = mentions
        if task_mode or isinstance(task_payload, dict) or visible_text is not None:
            stream_kwargs.update({
                "task_mode": task_mode or "standard",
                "task_payload": dict(task_payload) if isinstance(task_payload, dict) else None,
                "visible_text": str(visible_text) if visible_text is not None else None,
            })
        event_stream = stream_chat(
            self.manager,
            alias,
            chat_user_id,
            body.get("message", ""),
            **stream_kwargs,
            actor=actor,
        )
        resumable_stream = False
        try:
            async for event in event_stream:
                resumable_stream = resumable_stream or bool(event.get("stream_id"))
                if wants_ag_ui and str(event.get("type") or "") == "ag_ui":
                    if client_disconnected:
                        continue
                    try:
                        encoded = ag_ui_encoder.encode(event["event"]).encode("utf-8")
                        if event.get("sequence") is not None:
                            encoded = f"id: {int(event['sequence'])}\n".encode("ascii") + encoded
                        await response.write(encoded)
                    except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                        client_disconnected = True
                        logger.info(
                            "Web SSE 客户端已断开，继续在后台完成任务: alias=%s user_id=%s",
                            alias,
                            auth.user_id,
                        )
                        if resumable_stream:
                            break
                    continue
                event = self._decorate_chat_authors(event, auth)
                event_type = str(event.get("type") or "")
                if event_type == "done":
                    self._schedule_chat_terminal_event(
                        auth=auth,
                        alias=alias,
                        agent_id=agent_id,
                        data=event,
                    )
                elif event_type == "error":
                    self._schedule_chat_terminal_event(
                        auth=auth,
                        alias=alias,
                        agent_id=agent_id,
                        data=event,
                        fallback_status="error",
                    )
                if client_disconnected:
                    continue
                try:
                    if not wants_ag_ui:
                        encoded_event = _format_sse(event["type"], event)
                        if event.get("sequence") is not None:
                            encoded_event = f"id: {int(event['sequence'])}\n".encode("ascii") + encoded_event
                        await response.write(encoded_event)
                except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                    client_disconnected = True
                    logger.info(
                        "Web SSE 客户端已断开，继续在后台完成任务: alias=%s user_id=%s",
                        alias,
                        auth.user_id,
                    )
                    if resumable_stream:
                        break
        finally:
            close_event_stream = getattr(event_stream, "aclose", None)
            if callable(close_event_stream):
                await close_event_stream()
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

    def _resolve_terminal_owner_id(self, value: object) -> str:
        owner_id = str(value or "").strip()
        if owner_id:
            return owner_id
        logger.warning("终端请求缺少 owner_id，回退默认 owner=%s", DEFAULT_TERMINAL_OWNER_ID)
        return DEFAULT_TERMINAL_OWNER_ID

    def _resolve_terminal_shell(self, value: object) -> str:
        configured_shell = WEB_TERMINAL_SHELL_PATH.strip()
        if configured_shell:
            return configured_shell
        default_shell = get_default_shell()
        shell_type = str(value or default_shell).strip() or default_shell
        if shell_type == "auto":
            return default_shell
        return shell_type

    def _terminal_launch_error(self, exc: TerminalLaunchError) -> WebApiError:
        message = str(exc).strip() or "终端 shell 启动失败"
        return WebApiError(400, "terminal_launch_failed", message)

    def _request_log_path(self, request: web.Request) -> str:
        return request.path_qs.split("?", 1)[0]

    async def get_terminal_ws_probe(self, request: web.Request) -> web.Response:
        origin_allowed = _is_request_origin_allowed(request)
        token_info = _extract_auth_token_info(request)
        has_token = bool(token_info.token and token_info.source != AUTH_TOKEN_SOURCE_QUERY)
        auth_status = "not_checked"
        auth_error = ""
        try:
            await self._with_capability(request, CAP_TERMINAL_EXEC)
            auth_status = "ok"
        except WebApiError as exc:
            auth_status = f"error:{exc.code}"
            auth_error = exc.message

        upgrade_hint = "not_websocket_probe"
        if str(request.headers.get("Upgrade") or "").lower() == "websocket":
            upgrade_hint = "websocket_upgrade_reached_probe"

        data = {
            "path": self._request_log_path(request),
            "configured_base_path": self._web_base_path(),
            "has_token": has_token,
            "token_source": token_info.source,
            "auth_status": auth_status,
            "auth_error": auth_error,
            "origin_allowed": origin_allowed,
            "origin": request.headers.get("Origin", ""),
            "host": request.headers.get("Host", ""),
            "forwarded_host": request.headers.get("X-Forwarded-Host", ""),
            "forwarded_proto": request.headers.get("X-Forwarded-Proto", ""),
            "upgrade_hint": upgrade_hint,
        }
        logger.info(
            "终端 WebSocket 探针 path=%s auth=%s origin_allowed=%s host=%s origin=%s forwarded_host=%s forwarded_proto=%s",
            data["path"],
            auth_status,
            origin_allowed,
            data["host"],
            data["origin"],
            data["forwarded_host"],
            data["forwarded_proto"],
        )
        return _json({"ok": True, "data": data})

    async def get_terminal_session(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        owner_id = self._resolve_terminal_owner_id(request.query.get("owner_id"))
        data = await self._terminal_manager.get_snapshot(auth.user_id, owner_id)
        return _json({"ok": True, "data": data})

    async def post_terminal_rebuild(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        body = await self._parse_json(request)
        owner_id = self._resolve_terminal_owner_id(body.get("owner_id"))
        shell_type = self._resolve_terminal_shell(body.get("shell"))
        raw_cwd = str(body.get("cwd") or os.getcwd()).strip() or os.getcwd()
        cwd = os.path.abspath(os.path.expanduser(raw_cwd))
        if not os.path.isdir(cwd):
            cwd = os.getcwd()
        size = _parse_terminal_size(body)
        try:
            data = await self._terminal_manager.rebuild(
                auth.user_id,
                owner_id,
                cwd=cwd,
                shell_type=shell_type,
                cols=size[0] if size else None,
                rows=size[1] if size else None,
            )
        except TerminalLaunchError as exc:
            logger.warning("终端启动失败 owner=%s shell=%s cwd=%s: %s", owner_id, shell_type, cwd, exc)
            raise self._terminal_launch_error(exc) from exc
        return _json({"ok": True, "data": data})

    async def post_terminal_close(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        body = await self._parse_json(request)
        owner_id = self._resolve_terminal_owner_id(body.get("owner_id"))
        data = await self._terminal_manager.close(auth.user_id, owner_id)
        return _json({"ok": True, "data": data})

    async def get_terminal_stream(self, request: web.Request) -> web.StreamResponse:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        owner_id = self._resolve_terminal_owner_id(request.query.get("owner_id"))
        from_seq = int(request.query.get("from_seq") or 0)
        protocol_version = 2 if str(request.query.get("protocol") or request.query.get("version") or "1") == "2" else 1
        request_path = self._request_log_path(request)
        logger.info(
            "终端 HTTP stream attach 开始 path=%s user_id=%s owner=%s from_seq=%s",
            request_path,
            auth.user_id,
            owner_id,
            from_seq,
        )
        queue = None
        try:
            queue, snapshot = await self._terminal_manager.attach(
                auth.user_id,
                owner_id,
                from_seq=from_seq,
                protocol_version=protocol_version,
            )
        except TerminalNotRunningError as exc:
            logger.warning(
                "终端 HTTP stream attach 失败，终端未启动 user_id=%s owner=%s path=%s: %s",
                auth.user_id,
                owner_id,
                request_path,
                exc,
            )
            raise WebApiError(409, "terminal_not_running", str(exc)) from exc

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
        try:
            await response.write(
                _format_sse(
                    "ready",
                    {
                        "pty_mode": snapshot.get("pty_mode"),
                        "connection_text": snapshot.get("connection_text"),
                        "last_seq": snapshot.get("last_seq"),
                        "stream_id": snapshot.get("stream_id"),
                        "protocol_version": protocol_version,
                    },
                )
            )
            logger.info(
                "终端 HTTP stream attach 成功 user_id=%s owner=%s pty=%s last_seq=%s",
                auth.user_id,
                owner_id,
                snapshot.get("pty_mode"),
                snapshot.get("last_seq"),
            )
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    await response.write(_format_sse("ping", {"ts": int(time.time())}))
                    continue
                if data is TERMINAL_CLIENT_EOF:
                    await response.write(_format_sse("closed", {"reason": "terminal_closed"}))
                    break
                if isinstance(data, TerminalDelivery):
                    event_name = "closed" if data.kind == "eof" else "gap" if data.kind == "gap" else "output"
                    envelope = {
                        "stream_id": data.stream_id,
                        "kind": data.kind,
                        "sequence": data.sequence,
                        "data": base64.b64encode(data.payload).decode("ascii"),
                        "encoding": "base64",
                        "gap_from": data.gap_from,
                        "gap_to": data.gap_to,
                        "snapshot_required": data.snapshot_required,
                        "reason": data.reason,
                    }
                    await response.write(
                        f"id: {data.sequence}\n".encode("ascii")
                        + _format_sse(event_name, envelope)
                    )
                    continue
                if not isinstance(data, bytes):
                    continue
                await response.write(
                    _format_sse(
                        "output",
                        {
                            "data": base64.b64encode(data).decode("ascii"),
                            "encoding": "base64",
                        },
                    )
                )
        except _CLIENT_DISCONNECT_ERRORS:
            client_disconnected = True
            logger.info("终端 HTTP stream 客户端已断开，停止转发输出: owner=%s", owner_id)
        except Exception as exc:
            logger.exception("终端 HTTP stream 转发失败: owner=%s", owner_id)
            try:
                await response.write(
                    _format_sse(
                        "error",
                        {"code": "terminal_stream_error", "message": str(exc).strip() or "终端流异常"},
                    )
                )
                await response.write(_format_sse("closed", {"reason": "terminal_stream_error"}))
            except _CLIENT_DISCONNECT_ERRORS:
                client_disconnected = True
        finally:
            if queue is not None:
                await self._terminal_manager.detach(auth.user_id, owner_id, queue)
            if not client_disconnected:
                try:
                    await response.write_eof()
                except _CLIENT_DISCONNECT_ERRORS:
                    pass
        return response

    async def post_terminal_input(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        body = await self._parse_json(request)
        owner_id = self._resolve_terminal_owner_id(body.get("owner_id"))
        input_type = str(body.get("type") or "input").strip()
        try:
            if input_type == "resize":
                size = _parse_terminal_size(body)
                if size is not None:
                    await self._terminal_manager.resize(auth.user_id, owner_id, *size)
                return _json({"ok": True, "data": {"accepted": size is not None}})
            data = str(body.get("data") or "").encode("utf-8")
            await self._terminal_manager.write_input(auth.user_id, owner_id, data)
        except TerminalNotRunningError as exc:
            raise WebApiError(409, "terminal_not_running", str(exc)) from exc
        return _json({"ok": True, "data": {"accepted": True}})

    async def get_terminal_actions_config(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        alias = self._manager_alias(request)
        data = get_terminal_actions_config(self.manager, alias, auth)
        return _json({"ok": True, "data": data})

    async def put_terminal_actions_config(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = save_terminal_actions_config_for_bot(self.manager, alias, auth, dict(body or {}))
        return _json({"ok": True, "data": data})

    async def post_run_terminal_action(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_TERMINAL_EXEC)
        alias = self._manager_alias(request)
        action_id = request.match_info.get("action_id", "").strip()
        body = await self._parse_json(request)
        owner_id = self._resolve_terminal_owner_id(body.get("ownerId") or body.get("owner_id"))
        action = resolve_terminal_action_for_bot(
            self.manager,
            alias,
            auth,
            action_id,
            confirmed=bool(body.get("confirmed", False)),
        )
        snapshot = await self._terminal_manager.get_snapshot(auth.user_id, owner_id)
        started_terminal = False
        if not snapshot.get("started"):
            shell_type = self._resolve_terminal_shell(body.get("shell"))
            size = _parse_terminal_size(body)
            try:
                snapshot = await self._terminal_manager.rebuild(
                    auth.user_id,
                    owner_id,
                    cwd=action.resolved_cwd,
                    shell_type=shell_type,
                    cols=size[0] if size else None,
                    rows=size[1] if size else None,
                )
            except TerminalLaunchError as exc:
                logger.warning(
                    "终端快捷命令启动失败 owner=%s action=%s shell=%s cwd=%s: %s",
                    owner_id,
                    action.id,
                    shell_type,
                    action.resolved_cwd,
                    exc,
                )
                raise self._terminal_launch_error(exc) from exc
            started_terminal = True
        await self._terminal_manager.write_input(auth.user_id, owner_id, f"{action.command}\r\n".encode("utf-8"))
        return _json(
            {
                "ok": True,
                "data": {
                    "actionId": action.id,
                    "command": action.command,
                    "cwd": action.resolved_cwd,
                    "startedTerminal": started_terminal,
                    "snapshot": snapshot,
                },
            }
        )

    async def terminal_ws(self, request: web.Request) -> web.WebSocketResponse:
        logger.info(
            "终端 WebSocket 请求到达 path=%s host=%s origin=%s forwarded_host=%s forwarded_proto=%s upgrade=%s has_token=%s remote=%s",
            self._request_log_path(request),
            request.headers.get("Host", ""),
            request.headers.get("Origin", ""),
            request.headers.get("X-Forwarded-Host", ""),
            request.headers.get("X-Forwarded-Proto", ""),
            request.headers.get("Upgrade", ""),
            bool(_extract_auth_token_info(request).token),
            request.remote or "",
        )
        auth = await self._with_websocket_capability(request, CAP_TERMINAL_EXEC)
        request_path = self._request_log_path(request)
        logger.info(
            "终端 WebSocket 鉴权通过 path=%s user_id=%s account=%s capability=%s",
            request_path,
            auth.user_id,
            auth.account_id,
            CAP_TERMINAL_EXEC in auth.capabilities,
        )
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self._terminal_sockets.add(ws)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._terminal_tasks.add(current_task)

        owner_id = ""
        queue = None
        tasks: list[asyncio.Task[Any]] = []
        try:
            try:
                init_message = await asyncio.wait_for(ws.receive(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(
                    "终端 WebSocket 初始化超时 path=%s user_id=%s",
                    request_path,
                    auth.user_id,
                )
                await ws.close(code=WSCloseCode.POLICY_VIOLATION, message=b"terminal init timeout")
                return ws
            if init_message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                logger.info(
                    "终端 WebSocket 初始化前关闭 path=%s user_id=%s type=%s",
                    request_path,
                    auth.user_id,
                    init_message.type,
                )
                return ws
            init_data: dict[str, Any] = {}
            if init_message.type == WSMsgType.TEXT:
                try:
                    parsed = json.loads(init_message.data or "{}")
                    if isinstance(parsed, dict):
                        init_data = parsed
                except json.JSONDecodeError:
                    init_data = {}
            owner_id = self._resolve_terminal_owner_id(init_data.get("owner_id") or request.query.get("owner_id"))
            from_seq = int(init_data.get("from_seq") or request.query.get("from_seq") or 0)
            protocol_version = 2 if int(init_data.get("protocol_version") or init_data.get("version") or 1) >= 2 else 1
            logger.info(
                "终端 WebSocket attach 开始 path=%s user_id=%s owner=%s from_seq=%s",
                request_path,
                auth.user_id,
                owner_id,
                from_seq,
            )
            queue, snapshot = await self._terminal_manager.attach(
                auth.user_id,
                owner_id,
                from_seq=from_seq,
                protocol_version=protocol_version,
            )
            try:
                await ws.send_json({
                    "pty_mode": snapshot.get("pty_mode"),
                    "connection_text": snapshot.get("connection_text"),
                    "stream_id": snapshot.get("stream_id"),
                    "last_seq": snapshot.get("last_seq"),
                    "protocol_version": protocol_version,
                })
            except _CLIENT_DISCONNECT_ERRORS:
                logger.info("终端 WebSocket 客户端在初始化完成前断开: owner=%s", owner_id)
                return ws
            logger.info(
                "终端 WebSocket attach 成功 user_id=%s owner=%s pty=%s last_seq=%s",
                auth.user_id,
                owner_id,
                snapshot.get("pty_mode"),
                snapshot.get("last_seq"),
            )

            async def forward_output() -> None:
                while True:
                    data = await queue.get()
                    if data is TERMINAL_CLIENT_EOF:
                        break
                    try:
                        if isinstance(data, TerminalDelivery):
                            if data.kind in {"gap", "eof"}:
                                await ws.send_json(
                                    {
                                        "type": "closed" if data.kind == "eof" else "gap",
                                        "stream_id": data.stream_id,
                                        "sequence": data.sequence,
                                        "gap_from": data.gap_from,
                                        "gap_to": data.gap_to,
                                        "snapshot_required": data.snapshot_required,
                                        "reason": data.reason,
                                    }
                                )
                            else:
                                await ws.send_bytes(encode_terminal_ws_v2(data))
                        elif isinstance(data, bytes):
                            await ws.send_bytes(data)
                    except _CLIENT_DISCONNECT_ERRORS:
                        logger.info("终端 WebSocket 客户端已断开，停止转发输出: owner=%s", owner_id)
                        break

            async def forward_input() -> None:
                while not ws.closed:
                    transport = request.transport
                    if transport is None or transport.is_closing():
                        break
                    message = await ws.receive()
                    if message.type == WSMsgType.BINARY:
                        await self._terminal_manager.write_input(auth.user_id, owner_id, message.data)
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
                                    size = _parse_terminal_size(payload)
                                    if size is not None:
                                        await self._terminal_manager.resize(auth.user_id, owner_id, *size)
                                    continue
                        await self._terminal_manager.write_input(auth.user_id, owner_id, text.encode("utf-8"))
                        await asyncio.sleep(0)
                        continue

                    if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break

            tasks = [
                asyncio.create_task(forward_output()),
                asyncio.create_task(forward_input()),
            ]
            output_task, input_task = tasks
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if output_task in done and output_task.exception() is not None:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
                output_task.result()
            elif output_task in done:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
                await ws.close(code=WSCloseCode.OK, message=b"terminal closed")
            else:
                await input_task
                if not output_task.done():
                    output_task.cancel()
                await asyncio.gather(output_task, return_exceptions=True)
        except TerminalNotRunningError as exc:
            logger.warning(
                "终端 WebSocket attach 失败，终端未启动 user_id=%s owner=%s path=%s: %s",
                auth.user_id,
                owner_id or request.query.get("owner_id", ""),
                request_path,
                exc,
            )
            if not ws.closed:
                try:
                    await ws.send_json({"error": str(exc)})
                except Exception:
                    pass
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
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if queue is not None and owner_id:
                await self._terminal_manager.detach(auth.user_id, owner_id, queue)

        return ws

    async def notifications_ws(self, request: web.Request) -> web.WebSocketResponse:
        auth = await self._with_websocket_auth(request)
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._notification_tasks.add(current_task)
        connection = self._notification_service.register(
            account_id=auth.account_id,
            user_id=auth.user_id,
            username=auth.username,
            ws=ws,
        )
        try:
            await ws.send_json({
                "type": "hello",
                "accountId": auth.account_id,
                "userId": auth.user_id,
                "username": auth.username,
            })
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break
                    continue
                try:
                    payload = json.loads(message.data or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                message_type = str(payload.get("type") or "").strip()
                if message_type in {"hello", "heartbeat", "presence_update"}:
                    presence = payload.get("presence") if isinstance(payload.get("presence"), dict) else payload
                    self._notification_service.heartbeat(connection, presence)
                    await ws.send_json({"type": "heartbeat_ack"})
        except _CLIENT_DISCONNECT_ERRORS:
            pass
        except Exception as exc:
            logger.warning("通知 WebSocket 处理失败 account=%s error=%s", auth.account_id, exc)
        finally:
            self._notification_service.unregister(connection)
            if current_task is not None:
                self._notification_tasks.discard(current_task)
        return ws

    async def get_notification_settings(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        pushplus = self._notification_service.pushplus
        return _json({
            "ok": True,
            "data": {
                "chat_completion_notify_enabled": self._notification_service.enabled,
                "pushplus_enabled": bool(getattr(pushplus, "enabled", False)),
                "pushplus_configured": bool(str(getattr(pushplus, "token", "") or "").strip()),
                "pushplus_topic_configured": bool(str(getattr(pushplus, "topic", "") or "").strip()),
            },
        })

    async def post_pushplus_test(self, request: web.Request) -> web.Response:
        await self._with_auth(request)
        pushplus = self._notification_service.pushplus
        if not bool(getattr(pushplus, "enabled", False)):
            raise WebApiError(409, "pushplus_disabled", "PushPlus 未启用")
        if not str(getattr(pushplus, "token", "") or "").strip():
            raise WebApiError(409, "pushplus_not_configured", "PushPlus token 未配置")

        public_url = self._public_tunnel_url() or "未配置或未获取"
        content = "\n".join([
            "### PushPlus 测试推送",
            "",
            "如果你收到这条消息，说明 PushPlus 已可用。",
            "",
            f"- 公网网址: {public_url}",
        ])
        sent = await pushplus.send("PushPlus 测试推送", content)
        if not sent:
            raise WebApiError(502, "pushplus_test_failed", "PushPlus 测试推送失败")
        return _json({"ok": True, "data": {"sent": True}})

    async def get_pwd(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_FILE_TREE)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_working_directory(self.manager, alias, self._chat_user_id(auth))})

    async def get_ls(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_FILE_TREE)
        alias = self._manager_alias(request)
        target_path = request.query.get("path") or None
        include_child_counts = str(request.query.get("include_child_counts", "")).strip().lower() in {"1", "true", "yes", "on"}
        if auth.role == ROLE_GUEST:
            base_dir = get_working_directory(self.manager, alias, self._chat_user_id(auth))["working_dir"]
            data = await asyncio.to_thread(
                get_directory_listing,
                self.manager,
                alias,
                self._chat_user_id(auth),
                path=target_path,
                base_dir=base_dir,
                restrict_to_base_dir=True,
                include_child_counts=include_child_counts,
            )
            return _json({"ok": True, "data": data})
        data = await asyncio.to_thread(
            get_directory_listing,
            self.manager,
            alias,
            self._chat_user_id(auth),
            path=target_path,
            include_child_counts=include_child_counts,
        )
        return _json({"ok": True, "data": data})

    def _workspace_file_root(self, alias: str, auth: WebAuthSession) -> str:
        if auth.role == ROLE_GUEST:
            return get_working_directory(self.manager, alias, self._chat_user_id(auth))["working_dir"]
        return get_file_browser_directory(self.manager, alias, self._chat_user_id(auth))["working_dir"]

    async def get_workspace_quick_open(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = self._workspace_file_root(alias, auth)
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", "50"))
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            functools.partial(quick_open_files, workspace, query, limit=limit),
        )
        return _json({"ok": True, "data": data})

    async def get_workspace_search(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = self._workspace_file_root(alias, auth)
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", "100"))
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            functools.partial(search_workspace_text, workspace, query, limit=limit),
        )
        return _json({"ok": True, "data": data})

    async def get_workspace_outline(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        workspace = self._workspace_file_root(alias, auth)
        path = request.query.get("path", "")
        data = await asyncio.to_thread(build_file_outline, workspace, path)
        return _json({"ok": True, "data": data})

    async def post_workspace_resolve_definition(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        workspace = self._workspace_file_root(alias, auth)
        data = await asyncio.to_thread(
            resolve_workspace_definition,
            workspace,
            str(body.get("path", "")),
            line=int(body.get("line") or 1),
            column=int(body.get("column") or 1),
            symbol=str(body.get("symbol", "")),
        )
        return _json({"ok": True, "data": data})

    async def post_workspace_code_navigation_resolve(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        workspace = self._workspace_file_root(alias, auth)
        try:
            data = await asyncio.to_thread(resolve_code_navigation, workspace, body)
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=str(exc)) from exc
        return _json({"ok": True, "data": data})

    async def get_workspace_inline_completion_config(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_INLINE_COMPLETION)
        _require_capability(auth, CAP_READ_FILE_CONTENT)
        return _json({"ok": True, "data": self.inline_completion_config_store.get_public_config()})

    async def post_workspace_inline_completion(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_INLINE_COMPLETION)
        _require_capability(auth, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        workspace = Path(self._workspace_file_root(alias, auth)).expanduser().resolve()
        try:
            data = await self.inline_completion_service.complete(
                account_id=auth.account_id,
                alias=alias,
                workspace_root=workspace,
                request=body,
            )
        except InlineCompletionServiceError as exc:
            raise WebApiError(exc.status, exc.code, exc.message) from exc
        return _json({"ok": True, "data": data})

    async def post_cd(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MUTATE_BROWSE_STATE)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = change_working_directory(self.manager, alias, self._chat_user_id(auth), body.get("path", ""))
        return _json({"ok": True, "data": data})

    async def post_reset(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        return _json({"ok": True, "data": reset_user_session(self.manager, alias, self._chat_user_id(auth), agent_id=agent_id)})

    async def post_kill(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        return _json({
            "ok": True,
            "data": await kill_user_process(
                self.manager,
                alias,
                self._chat_user_id(auth),
                agent_id=agent_id,
                execution_mode=execution_mode,
            ),
        })

    async def post_native_agent_permission_reply(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        permission_id = request.match_info.get("permission_id", "")
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        approved = bool(body.get("approved"))
        if "approved" not in body:
            response_value = str(body.get("response") or body.get("decision") or "").strip().lower()
            approved = response_value in {"allow", "approve", "approved", "yes", "true", "1"}
        data = await reply_native_agent_permission(
            self.manager,
            alias,
            self._chat_user_id(auth),
            permission_id,
            approved=approved,
            message=str(body.get("message") if body.get("message") is not None else body.get("value") or ""),
            agent_id=agent_id,
        )
        return _json({"ok": True, "data": data})

    async def get_cli_params(self, request: web.Request) -> web.Response:
        await self._with_bot_config_access(request)
        alias = self._manager_alias(request)
        cli_type = request.query.get("cli_type") or None
        return _json({"ok": True, "data": get_cli_params_payload(self.manager, alias, cli_type)})

    async def get_native_agent_models(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_VIEW_BOTS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_native_agent_models_payload(self.manager, alias)})

    async def patch_native_agent_model(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_native_agent_model(
            self.manager,
            alias,
            body.get("model", body.get("native_agent_model", body.get("nativeAgentModel"))),
            body.get("reasoning_effort", body.get("reasoningEffort")),
        )
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def patch_cli_params(self, request: web.Request) -> web.Response:
        await self._with_bot_config_access(request)
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
        await self._with_bot_config_access(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        data = await reset_cli_params(self.manager, alias, body.get("cli_type"))
        return _json({"ok": True, "data": data})

    async def get_history_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            get_history,
            self.manager,
            alias,
            chat_user_id,
            limit=limit,
            agent_id=agent_id,
            execution_mode=execution_mode,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def get_history_delta_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        after_id = request.query.get("after_id", "")
        revision = int(request.query.get("revision", "0")) if "revision" in request.query else None
        cursor = request.query.get("cursor", "")
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            get_history_delta,
            self.manager,
            alias,
            chat_user_id,
            after_id,
            limit=limit,
            agent_id=agent_id,
            execution_mode=execution_mode,
            revision=revision,
            cursor=cursor,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def get_conversations_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        limit = int(request.query.get("limit", "50"))
        query = request.query.get("q", "")
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        data = await run_chat_store_io(
            list_conversations,
            self.manager,
            alias,
            self._chat_user_id(auth),
            limit=limit,
            query=query,
            agent_id=agent_id,
            execution_mode=execution_mode,
        )
        return _json({"ok": True, "data": data})

    async def get_favorites_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        query = request.query.get("q", "")
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        data = list_favorite_answers(
            self.manager,
            alias,
            self._chat_user_id(auth),
            agent_id=agent_id,
            execution_mode=execution_mode,
            query=query,
        )
        return _json({"ok": True, "data": data})

    async def post_favorite_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        agent_id = self._request_agent_id(request, body)
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        data = upsert_favorite_answer(
            self.manager,
            alias,
            self._chat_user_id(auth),
            body,
            agent_id=agent_id,
            execution_mode=execution_mode,
        )
        return _json({"ok": True, "data": data})

    async def delete_favorite_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        favorite_id = request.match_info.get("favorite_id", "")
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        data = delete_favorite_answer(
            self.manager,
            alias,
            self._chat_user_id(auth),
            favorite_id,
            agent_id=agent_id,
            execution_mode=execution_mode,
        )
        return _json({"ok": True, "data": data})

    async def post_conversation_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            create_conversation,
            self.manager,
            alias,
            chat_user_id,
            str(body.get("title") or ""),
            agent_id=agent_id,
            execution_mode=execution_mode,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def delete_conversations_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        delete_native = str(request.query.get("delete_native_session", "")).lower() in {"1", "true", "yes", "on"}
        execution_mode = self._request_execution_mode(request, body)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            delete_all_conversations,
            self.manager,
            alias,
            chat_user_id,
            agent_id=agent_id,
            execution_mode=execution_mode,
            delete_native_session=delete_native,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def post_plan_execute_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        agent_id = self._request_agent_id(request, body)
        data = execute_plan(
            self.manager,
            alias,
            self._chat_user_id(auth),
            str(body.get("content") or ""),
            title=str(body.get("title") or ""),
            agent_id=agent_id,
            execution_mode=self._request_execution_mode(request, body, include_query=False),
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def post_conversation_select_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        conversation_id = request.match_info.get("conversation_id", "")
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        execution_mode = self._request_execution_mode(request, body, include_query=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            select_conversation,
            self.manager,
            alias,
            chat_user_id,
            conversation_id,
            agent_id=agent_id,
            execution_mode=execution_mode,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

    async def delete_conversation_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        conversation_id = request.match_info.get("conversation_id", "")
        agent_id = self._request_agent_id(request)
        delete_native = str(request.query.get("delete_native_session", "")).lower() in {"1", "true", "yes", "on"}
        execution_mode = self._request_execution_mode(request, include_body=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            delete_conversation,
            self.manager,
            alias,
            chat_user_id,
            conversation_id,
            agent_id=agent_id,
            delete_native_session=delete_native,
            execution_mode=execution_mode,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": self._decorate_chat_authors(data, auth)})

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
        auth = await self._with_websocket_capability(request, CAP_DEBUG_EXEC)
        alias = str(request.query.get("alias") or "").strip().lower()
        if not alias:
            raise WebApiError(400, "missing_alias", "缺少 Bot 别名")
        auth = self._bot_auth(auth, alias)
        request["auth"] = auth
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
        agent_id = self._request_agent_id(request)
        execution_mode = self._request_execution_mode(request, include_body=False)
        chat_user_id = self._chat_user_id(auth)
        data = await run_chat_store_io(
            get_history_trace,
            self.manager,
            alias,
            chat_user_id,
            message_id,
            agent_id=agent_id,
            execution_mode=execution_mode,
            write_key=f"{alias}:{chat_user_id}:{agent_id}",
        )
        return _json({"ok": True, "data": data})

    async def get_native_agent_history_changes_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        agent_id = self._request_agent_id(request)
        data = get_native_agent_history_changes(
            self.manager,
            alias,
            self._chat_user_id(auth),
            conversation_id=str(request.query.get("conversation_id") or request.query.get("conversationId") or ""),
            turn_id=str(request.query.get("turn_id") or request.query.get("turnId") or ""),
            agent_id=agent_id,
        )
        return _json({"ok": True, "data": data})

    async def get_native_agent_history_diff_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_CHAT_HISTORY)
        alias = self._manager_alias(request)
        agent_id = self._request_agent_id(request)
        data = get_native_agent_history_diff(
            self.manager,
            alias,
            self._chat_user_id(auth),
            conversation_id=str(request.query.get("conversation_id") or request.query.get("conversationId") or ""),
            turn_id=str(request.query.get("turn_id") or request.query.get("turnId") or ""),
            path=str(request.query.get("path") or ""),
            agent_id=agent_id,
        )
        return _json({"ok": True, "data": data})

    async def post_native_agent_history_rollback_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request) if (request.content_length or 0) > 0 else {}
        agent_id = self._request_agent_id(request, body)
        data = await rollback_native_agent_history(
            self.manager,
            alias,
            self._chat_user_id(auth),
            conversation_id=str(body.get("conversation_id") or body.get("conversationId") or ""),
            target_turn_id=str(body.get("target_turn_id") or body.get("targetTurnId") or ""),
            agent_id=agent_id,
        )
        return _json({"ok": True, "data": data})

    async def get_git_overview_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(get_git_overview, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def get_git_commit_graph_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(
            get_git_commit_graph,
            self.manager,
            alias,
            auth.user_id,
            request.query.get("scope", "all"),
            request.query.get("limit", ""),
            request.query.get("cursor", ""),
        )
        return _json({"ok": True, "data": data})

    async def get_git_tree_status_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(get_git_tree_status, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def get_git_branches_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(list_git_branches, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def post_git_branch_create(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await asyncio.to_thread(
            create_git_branch,
            self.manager,
            alias,
            auth.user_id,
            str(body.get("name") or ""),
            str(body.get("start_point") or body.get("startPoint") or ""),
        )
        return _json({"ok": True, "data": data})

    async def post_git_branch_switch(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await asyncio.to_thread(switch_git_branch, self.manager, alias, auth.user_id, str(body.get("name") or ""))
        return _json({"ok": True, "data": data})

    async def post_git_branch_reset(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await asyncio.to_thread(
            reset_git_branch_to_commit,
            self.manager,
            alias,
            auth.user_id,
            str(body.get("commit") or ""),
            str(body.get("mode") or "mixed"),
        )
        return _json({"ok": True, "data": data})

    async def get_git_stashes_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(list_git_stashes, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def post_git_stash_apply(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(apply_git_stash, self.manager, alias, auth.user_id, str(body.get("ref") or ""))
        return _json({"ok": True, "data": {"message": "已应用 stash", "overview": overview}})

    async def post_git_stash_drop(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(drop_git_stash, self.manager, alias, auth.user_id, str(body.get("ref") or ""))
        return _json({"ok": True, "data": {"message": "已删除 stash", "overview": overview}})

    async def get_git_identity_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(get_git_identity_config, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def get_git_commit_message_config_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_git_commit_message_cli_config(self.manager, alias)})

    async def patch_git_commit_message_config_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_git_commit_message_cli_config(
            self.manager,
            alias,
            cli_type=body.get("cli_type"),
            cli_path=body.get("cli_path"),
            params=body.get("params"),
            key=body.get("key"),
            value=body.get("value"),
        )
        return _json({"ok": True, "data": data})

    async def post_git_commit_message_config_reset_view(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await reset_git_commit_message_cli_config(self.manager, alias)
        return _json({"ok": True, "data": data})

    async def post_git_commit_message_generate_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await generate_git_commit_message(self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def post_git_smart_commit(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        _working_dir, repo_root = await asyncio.to_thread(get_git_smart_commit_repo_hint, self.manager, alias)
        if repo_root and self._git_smart_commit_repo_locks.get(repo_root):
            raise WebApiError(409, "git_smart_commit_conflict", "当前仓库已有智能提交任务在运行")

        job = self._build_git_smart_commit_job(alias=alias, user_id=auth.user_id)
        if repo_root:
            job["repo_root"] = repo_root
            self._git_smart_commit_repo_locks[repo_root] = str(job["job_id"])
        task = asyncio.create_task(
            self._run_git_smart_commit_job(
                str(job["job_id"]),
                alias=alias,
                user_id=auth.user_id,
            )
        )
        self._git_smart_commit_task_by_job[str(job["job_id"])] = task
        return _json({"ok": True, "data": self._git_smart_commit_snapshot(job)})

    async def get_git_smart_commit_active(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        _ = auth
        job_id = self._git_smart_commit_latest_by_alias.get(alias)
        if not job_id:
            return _json({"ok": True, "data": None})
        job = self._get_git_smart_commit_job_or_raise(alias, job_id)
        return _json({"ok": True, "data": self._git_smart_commit_snapshot(job)})

    async def get_git_smart_commit_job(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        _ = auth
        job = self._get_git_smart_commit_job_or_raise(alias, request.match_info["job_id"])
        return _json({"ok": True, "data": self._git_smart_commit_snapshot(job)})

    async def put_git_identity_view(self, request: web.Request) -> web.Response:
        base_auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        scope = str(body.get("scope") or "").strip().lower()
        auth = base_auth if scope == "global" else self._bot_auth(base_auth, alias)
        if scope != "global" and self._allows_readonly_bot_capability(request, CAP_GIT_OPS, auth):
            auth = auth.with_capabilities({*auth.capabilities, CAP_GIT_OPS})
        _require_capability(auth, CAP_ADMIN_OPS if scope == "global" else CAP_GIT_OPS)
        data = await asyncio.to_thread(
            update_git_identity_config,
            self.manager,
            alias,
            auth.user_id,
            scope=scope,
            name=body.get("name", ""),
            email=body.get("email", ""),
        )
        return _json({"ok": True, "data": data})

    async def post_git_init(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        data = await asyncio.to_thread(init_git_repository, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": data})

    async def get_git_diff_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        path = request.query.get("path", "")
        staged = request.query.get("staged", "").strip().lower() in {"1", "true", "yes"}
        data = await asyncio.to_thread(get_git_diff, self.manager, alias, auth.user_id, path, staged=staged)
        return _json({"ok": True, "data": data})

    async def post_git_stage(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(stage_git_paths, self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已暂存所选文件", "overview": overview}})

    async def post_git_unstage(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(unstage_git_paths, self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已取消暂存所选文件", "overview": overview}})

    async def post_git_discard(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(discard_git_paths, self.manager, alias, auth.user_id, body.get("paths", []))
        return _json({"ok": True, "data": {"message": "已丢弃所选文件改动", "overview": overview}})

    async def post_git_discard_all(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(discard_all_git_changes, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已丢弃全部改动", "overview": overview}})

    async def post_git_commit(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        overview = await asyncio.to_thread(commit_git_changes, self.manager, alias, auth.user_id, body.get("message", ""))
        return _json({"ok": True, "data": {"message": "已创建提交", "overview": overview}})

    async def post_git_fetch(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(fetch_git_remote, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已抓取远端更新", "overview": overview}})

    async def post_git_pull(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(pull_git_remote, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已拉取远端更新", "overview": overview}})

    async def post_git_push(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(push_git_remote, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已推送本地提交", "overview": overview}})

    async def post_git_stash(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(stash_git_changes, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已暂存当前工作区", "overview": overview}})

    async def post_git_stash_pop(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_GIT_OPS)
        alias = self._manager_alias(request)
        overview = await asyncio.to_thread(pop_git_stash, self.manager, alias, auth.user_id)
        return _json({"ok": True, "data": {"message": "已恢复最近一次暂存", "overview": overview}})

    async def upload_file(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
        filename = field.filename or ""
        result = await save_uploaded_file_from_chunks(self.manager, alias, self._chat_user_id(auth), filename, _iter_field_chunks(field))
        return _json({"ok": True, "data": result})

    async def upload_chat_attachment(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise WebApiError(400, "missing_file", "请使用 multipart/form-data 并提供 file 字段")
        filename = field.filename or ""
        result = await save_chat_attachment_from_chunks(self.manager, alias, self._chat_user_id(auth), filename, _iter_field_chunks(field))
        return _json({"ok": True, "data": result})

    async def delete_chat_attachment_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_CHAT_SEND)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        result = delete_chat_attachment(self.manager, alias, self._chat_user_id(auth), body.get("saved_path", ""))
        return _json({"ok": True, "data": result})

    async def create_directory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = create_directory(
            self.manager,
            alias,
            self._chat_user_id(auth),
            body.get("name", ""),
            parent_path=body.get("parent_path"),
        )
        return _json({"ok": True, "data": data})

    async def create_workdir_directory_view(self, request: web.Request) -> web.Response:
        auth = await self._with_auth(request)
        alias = self._manager_alias(request)
        auth = self._bot_auth(auth, alias)
        request["auth"] = auth
        if CAP_CREATE_WORKDIR_DIRECTORY not in auth.capabilities and CAP_MANAGE_BOTS not in auth.capabilities:
            _require_capability(auth, CAP_CREATE_WORKDIR_DIRECTORY)
        body = await self._parse_json(request)
        data = create_workdir_directory(
            self.manager,
            alias,
            self._chat_user_id(auth),
            body.get("parent_path", ""),
            body.get("name", ""),
        )
        return _json({"ok": True, "data": data})

    async def open_workdir_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        if not self._is_local_admin(auth):
            raise WebApiError(403, "local_admin_required", "仅本地管理员可打开系统文件夹")
        if not _is_loopback_request(request):
            raise WebApiError(403, "loopback_required", "仅本机访问可打开系统文件夹")
        alias = self._manager_alias(request)
        working_dir = get_working_directory(self.manager, alias, self._chat_user_id(auth))["working_dir"]
        try:
            data = open_directory_in_desktop(working_dir)
        except DesktopOpenError as exc:
            raise WebApiError(exc.status, exc.code, exc.message) from exc
        return _json({"ok": True, "data": data})

    async def post_files_reveal(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_VIEW_FILE_TREE)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": reveal_directory_tree(self.manager, alias, self._chat_user_id(auth), str(body.get("path", "")))})

    async def write_file_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = write_file_content(
            self.manager,
            alias,
            self._chat_user_id(auth),
            body.get("path", ""),
            body.get("content", ""),
            expected_mtime_ns=body.get("expected_mtime_ns"),
            encoding=body.get("encoding"),
        )
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def create_text_file_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = create_text_file(
            self.manager,
            alias,
            self._chat_user_id(auth),
            body.get("filename", ""),
            body.get("content", ""),
            parent_path=body.get("parent_path"),
        )
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def rename_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = rename_path(self.manager, alias, self._chat_user_id(auth), body.get("path", ""), body.get("new_name", ""))
        return _json({"ok": True, "data": data})

    async def copy_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = copy_path(self.manager, alias, self._chat_user_id(auth), body.get("path", ""))
        return _json({"ok": True, "data": _serialize_file_version_fields(data)})

    async def move_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = move_path(self.manager, alias, self._chat_user_id(auth), body.get("path", ""), body.get("target_parent_path", ""))
        return _json({"ok": True, "data": data})

    async def delete_path_view(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_WRITE_FILES)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = delete_path(self.manager, alias, self._chat_user_id(auth), body.get("path", ""))
        return _json({"ok": True, "data": data})

    async def download_file(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_READ_FILE_CONTENT)
        alias = self._manager_alias(request)
        filename = request.query.get("filename", "")
        metadata = get_file_metadata(self.manager, alias, self._chat_user_id(auth), filename)
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
        data = await asyncio.to_thread(read_file_content, self.manager, alias, self._chat_user_id(auth), filename, mode=mode, lines=lines)
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

    async def post_invoke_plugin_action(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        plugin_id = request.match_info.get("plugin_id", "").strip()
        body = await self._parse_json(request)
        data = await invoke_plugin_action(self.manager, alias, auth, plugin_id, dict(body or {}))
        return _json({"ok": True, "data": data})

    async def download_plugin_artifact(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_RUN_PLUGINS)
        alias = self._manager_alias(request)
        artifact_id = request.match_info.get("artifact_id", "").strip()
        record = get_plugin_artifact(self.manager, alias, auth, artifact_id)
        return web.FileResponse(
            path=record.path,
            headers={
                "Content-Disposition": f'attachment; filename="{record.filename}"',
                "Content-Type": record.content_type,
            },
        )

    async def admin_bots(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        items = self._filter_bots_for_auth(auth, list_bots(self.manager, auth.user_id))
        return _json({"ok": True, "data": self._decorate_bots_for_auth(auth, items)})

    async def admin_cli_error_stats(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        try:
            hours = int(str(request.query.get("hours", "24") or "24"))
            limit = int(str(request.query.get("limit", "200") or "200"))
        except ValueError as exc:
            raise WebApiError(400, "invalid_request", "hours 和 limit 必须是整数") from exc
        data = await asyncio.to_thread(
            collect_cli_error_stats,
            self.manager,
            hours=max(1, min(hours, 24 * 30)),
            alias=str(request.query.get("alias", "") or "").strip(),
            cli_type=str(request.query.get("cli_type", "") or "").strip(),
            category=str(request.query.get("category", "") or "").strip(),
            limit=max(1, min(limit, 1000)),
        )
        return _json({"ok": True, "data": data})
    
    async def admin_processing(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": get_processing_sessions(alias)})

    async def admin_add_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        body = await self._parse_json(request)
        raw_bypass = body.get("bypass_approval_and_sandbox")
        if raw_bypass is None and "bypassApprovalAndSandbox" in body:
            raw_bypass = body.get("bypassApprovalAndSandbox")
        bypass_approval_and_sandbox = _parse_optional_bool(
            raw_bypass,
            field_name="bypass_approval_and_sandbox",
            default=False,
        )
        if bypass_approval_and_sandbox and not ({CAP_RUN_UNSAFE_CLI, CAP_ADMIN_OPS} & auth.capabilities):
            raise WebApiError(403, "forbidden", "当前账号无权限默认绕过审批和沙箱")
        try:
            _BOT_PERMISSION_STORE.assert_can_create_bot(auth.account_id, is_local_admin=self._is_local_admin(auth))
        except ValueError as exc:
            raise WebApiError(403, "bot_quota_exceeded", str(exc)) from exc
        data = await add_managed_bot(
            self.manager,
            alias=body.get("alias", ""),
            cli_type=body.get("cli_type"),
            cli_path=body.get("cli_path"),
            working_dir=body.get("working_dir"),
            supported_execution_modes=body.get("supported_execution_modes", body.get("supportedExecutionModes")),
            default_execution_mode=body.get("default_execution_mode", body.get("defaultExecutionMode")),
            native_agent=body.get("native_agent", body.get("nativeAgent")),
            bypass_approval_and_sandbox=bypass_approval_and_sandbox,
        )
        alias = data["bot"]["alias"]
        if not self._is_local_admin(auth):
            _BOT_PERMISSION_STORE.set_bot_owner(alias, auth.account_id, grant_owner=True)
        data = {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}
        return _json({"ok": True, "data": data})

    async def admin_remove_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        delete_history = str(request.query.get("delete_history", "")).strip().lower() in {"1", "true", "yes", "on"}
        delete_workspace = str(request.query.get("delete_workspace", "")).strip().lower() in {"1", "true", "yes", "on"}
        if delete_workspace:
            _require_capability(auth, CAP_WRITE_FILES)
        data = await remove_managed_bot_with_history(
            self.manager,
            alias,
            delete_history=delete_history,
            delete_workspace=delete_workspace,
        )
        _BOT_PERMISSION_STORE.remove_bot_owner(alias)
        return _json({"ok": True, "data": data})

    async def admin_start_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        data = await start_managed_bot(self.manager, alias)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_stop_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        data = await stop_managed_bot(self.manager, alias)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_update_cli(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_cli(
            self.manager,
            alias=alias,
            cli_type=body.get("cli_type", ""),
            cli_path=body.get("cli_path", ""),
        )
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_update_execution(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_execution_config(self.manager, alias, body)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_rename_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await rename_managed_bot(self.manager, alias, str(body.get("new_alias", "")))
        renamed_alias = str(data.get("bot", {}).get("alias") or "").strip().lower()
        if renamed_alias:
            _BOT_PERMISSION_STORE.rename_bot(alias, renamed_alias)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_update_workdir(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        data = await update_bot_workdir(
            self.manager,
            alias,
            body.get("working_dir", ""),
            self._chat_user_id(auth),
            force_reset=bool(body.get("force_reset")),
        )
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_update_prompt_presets(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_MANAGE_BOTS)
        alias = self._manager_alias(request)
        body = await self._parse_json(request)
        if "prompt_presets" in body:
            presets = body["prompt_presets"]
        elif "promptPresets" in body:
            presets = body["promptPresets"]
        else:
            raise WebApiError(400, "invalid_prompt_presets", "缺少 prompt_presets")
        data = await update_bot_prompt_presets(self.manager, alias, presets, auth.user_id)
        return _json({"ok": True, "data": {**data, "bot": self._decorate_bot_for_auth(auth, data["bot"])}})

    async def admin_update_global_prompt_presets(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        if "prompt_presets" in body:
            presets = body["prompt_presets"]
        elif "promptPresets" in body:
            presets = body["promptPresets"]
        else:
            raise WebApiError(400, "invalid_prompt_presets", "缺少 prompt_presets")
        data = await update_global_prompt_presets(self.manager, presets)
        return _json({"ok": True, "data": data})

    async def admin_get_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": get_git_proxy_settings()})

    async def admin_patch_git_proxy(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        try:
            data = update_git_proxy_address(body["address"] if "address" in body else body.get("port", ""))
        except ValueError as exc:
            raise WebApiError(400, "invalid_git_proxy_port", str(exc)) from exc
        return _json({"ok": True, "data": data})

    async def admin_get_update(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": get_update_status(_REPO_ROOT)})

    async def admin_runtime_diagnostics(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json(
            {
                "ok": True,
                "data": {
                    **migration_diagnostics(_REPO_ROOT),
                    "runtime": self._runtime_diagnostics.snapshot(),
                },
            }
        )

    async def admin_patch_update(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        data = set_update_enabled(bool(body.get("update_enabled", True)), _REPO_ROOT)
        return _json({"ok": True, "data": data})

    async def admin_update_check(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        data = await asyncio.to_thread(check_for_updates, _REPO_ROOT)
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
        async for event in stream_update_download(_REPO_ROOT):
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

    async def admin_update_offline_packages(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        data = await asyncio.to_thread(list_offline_update_packages, _REPO_ROOT)
        return _json({"ok": True, "data": data})

    async def admin_update_offline_prepare(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        package_path = str(body.get("path") or body.get("package_path") or "").strip()
        version = str(body.get("version") or "").strip()
        if not package_path:
            raise WebApiError(400, "missing_package_path", "离线包路径不能为空")
        data = await asyncio.to_thread(prepare_offline_update, _REPO_ROOT, package_path, version=version)
        return _json({"ok": True, "data": data})

    async def admin_update_offline_prepare_stream(self, request: web.Request) -> web.StreamResponse:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        package_path = str(body.get("path") or body.get("package_path") or "").strip()
        version = str(body.get("version") or "").strip()
        if not package_path:
            raise WebApiError(400, "missing_package_path", "离线包路径不能为空")

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def progress(line: str) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "phase": "log", "downloaded_bytes": 0, "message": line},
            )

        task = asyncio.create_task(
            asyncio.to_thread(prepare_offline_update, _REPO_ROOT, package_path, version=version, log_callback=progress)
        )
        client_disconnected = False
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if client_disconnected:
                    continue
                try:
                    await response.write(_format_sse("progress", event))
                except _CLIENT_DISCONNECT_ERRORS:
                    client_disconnected = True
            data = await task
            done = {"type": "done", "phase": "log", "downloaded_bytes": 0, "percent": 100, "status": data}
            if not client_disconnected:
                await response.write(_format_sse("done", done))
                await response.write_eof()
        except Exception as exc:
            error = {"type": "error", "phase": "error", "downloaded_bytes": 0, "message": str(exc)}
            if not client_disconnected:
                await response.write(_format_sse("error", error))
                await response.write_eof()
        return response

    async def admin_env_get(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": self.env_config_service.snapshot()})

    async def admin_inline_completion_config_get(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": self.inline_completion_config_store.get_public_config()})

    async def admin_inline_completion_config_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        try:
            data = self.inline_completion_config_store.update(await self._parse_json(request))
        except InlineCompletionConfigError as exc:
            raise WebApiError(exc.status, exc.code, exc.message) from exc
        return _json({"ok": True, "data": data})

    async def admin_native_agent_config_get(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": get_native_agent_config_payload()})

    async def admin_native_agent_preflight_get(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        data = get_native_agent_preflight_payload(
            cwd=str(request.query.get("cwd", "")).strip(),
            pi_command=str(request.query.get("pi_command", request.query.get("piCommand", ""))).strip(),
        )
        return _json({"ok": True, "data": data})

    async def admin_native_agent_config_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        return _json({"ok": True, "data": update_native_agent_config_payload(body)})

    async def admin_env_patch(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        try:
            data = self.env_config_service.patch(body)
        except EnvValidationError as exc:
            raise WebApiError(400, exc.code, exc.message, exc.data) from exc
        return _json({"ok": True, "data": data})

    async def admin_env_reload_preview(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        body = await self._parse_json(request)
        try:
            data = self.env_config_service.reload_preview(body)
        except EnvValidationError as exc:
            raise WebApiError(400, exc.code, exc.message, exc.data) from exc
        return _json({"ok": True, "data": data})

    async def admin_restart(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        self._schedule_restart_request()
        return _json({"ok": True, "data": {"restart_requested": True}})

    async def admin_tunnel(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        return _json({"ok": True, "data": await self._fresh_tunnel_snapshot()})

    async def admin_tunnel_start(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        if self._exposure_service.is_fixed_public_forward():
            return _json({"ok": True, "data": await self._fixed_forward_service.start()})
        started_at = time.perf_counter()
        diag_log_event(logger, "tunnel_start_stage", stage="request")
        snapshot = await self._tunnel_service.start()
        diag_log_slow(
            logger,
            "tunnel_start",
            int(round((time.perf_counter() - started_at) * 1000)),
            stage=str(snapshot.get("status") or ""),
            public_url=str(snapshot.get("public_url") or ""),
        )
        await self._notify_or_schedule_tunnel_public_url(snapshot, reason="manual_tunnel_start")
        return _json({"ok": True, "data": snapshot})

    async def admin_tunnel_stop(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        if self._exposure_service.is_fixed_public_forward():
            return _json({"ok": True, "data": await self._fixed_forward_service.stop()})
        return _json({"ok": True, "data": await self._tunnel_service.stop()})

    async def admin_tunnel_restart(self, request: web.Request) -> web.Response:
        await self._with_capability(request, CAP_ADMIN_OPS)
        if self._exposure_service.is_fixed_public_forward():
            return _json({"ok": True, "data": await self._fixed_forward_service.restart()})
        started_at = time.perf_counter()
        diag_log_event(logger, "tunnel_restart_stage", stage="request")
        snapshot = await self._tunnel_service.restart()
        diag_log_slow(
            logger,
            "tunnel_restart",
            int(round((time.perf_counter() - started_at) * 1000)),
            stage=str(snapshot.get("status") or ""),
            public_url=str(snapshot.get("public_url") or ""),
        )
        await self._notify_or_schedule_tunnel_public_url(snapshot, reason="manual_tunnel_restart")
        return _json({"ok": True, "data": snapshot})

    async def admin_single_bot(self, request: web.Request) -> web.Response:
        auth = await self._with_capability(request, CAP_ADMIN_OPS)
        alias = self._manager_alias(request)
        return _json({"ok": True, "data": {"bot": self._decorate_bot_for_auth(auth, build_bot_summary(self.manager, alias))}})

    async def _auto_refresh_update_status(self) -> None:
        status = get_update_status(_REPO_ROOT)
        if not status.get("update_enabled"):
            return
        try:
            checked_status = await asyncio.to_thread(check_for_updates, _REPO_ROOT)
            latest_version = str(checked_status.get("last_available_version") or "").strip()
            current_version = str(checked_status.get("current_version") or "").strip()
            pending_version = str(
                checked_status.get("pending_update_version")
                or status.get("pending_update_version")
                or ""
            ).strip()
            if latest_version and latest_version != current_version and latest_version != pending_version:
                logger.info("检测到新版本 %s，开始后台下载更新包", latest_version)
                await asyncio.to_thread(download_latest_update, _REPO_ROOT)
        except Exception as exc:
            logger.warning("自动后台下载更新失败: %s", exc)

    def _build_app(self) -> web.Application:
        app = web.Application(
            middlewares=[cors_middleware, diag_slow_request_middleware, error_middleware],
            client_max_size=25 * 1024 * 1024,
        )
        self._register_app_routes(app)
        base_path = self._web_base_path()
        if base_path:
            subapp = web.Application(
                client_max_size=25 * 1024 * 1024,
            )
            self._register_app_routes(subapp)
            self._register_static_routes(subapp)
            self._register_spa_fallback(subapp)
            app.add_subapp(base_path, subapp)
        self._register_static_routes(app)
        self._register_spa_fallback(app)
        return app

    def _register_app_routes(self, app: web.Application) -> None:
        for module in (
            auth_routes,
            announcement_routes,
            cluster_routes,
            chat_routes,
            terminal_routes,
            debug_routes,
            files_routes,
            plugin_routes,
            git_routes,
            admin_routes,
            bot_settings_routes,
            lan_chat_routes,
            transfer_routes,
        ):
            module.register(app, self)
        app.router.add_get("/api/notifications/settings", self.get_notification_settings)
        app.router.add_post("/api/notifications/pushplus/test", self.post_pushplus_test)
        app.router.add_get("/api/notifications/ws", self.notifications_ws)

    def _register_static_routes(self, app: web.Application) -> None:
        assets_dir = Path(self._get_static_dir("assets"))
        if assets_dir.exists():
            app.router.add_static("/assets", path=str(assets_dir), name="assets")

    def _register_spa_fallback(self, app: web.Application) -> None:
        app.router.add_get("/{tail:.*}", self.serve_index, name="index")

    @staticmethod
    def _web_base_path() -> str:
        value = str(WEB_BASE_PATH or "").strip()
        if not value or value == "/":
            return ""
        return value.rstrip("/")
    
    def _get_static_dir(self, subdir=None):
        """Get static directory path."""
        script_dir = Path(__file__).resolve().parent.parent.parent
        static_dir = script_dir / "front" / "dist"
        if subdir:
            static_dir = static_dir / subdir
        return str(static_dir)

    def _public_runtime_env_script(self) -> str:
        base_path = self._web_base_path()
        payload = {
            "WEB_BASE_PATH": base_path,
            "VITE_BASE_PATH": base_path,
            "VITE_API_BASE_URL": base_path,
        }
        return f"<script>window.__TCB_PUBLIC_ENV__={json.dumps(payload, ensure_ascii=False)};</script>"

    def _inject_public_runtime_env(self, html: str) -> str:
        script = self._public_runtime_env_script()
        html_without_stale_env = _PUBLIC_RUNTIME_ENV_SCRIPT_RE.sub("", html)
        head_match = _HEAD_TAG_RE.search(html_without_stale_env)
        if head_match:
            return (
                f"{html_without_stale_env[:head_match.end()]}\n"
                f"    {script}{html_without_stale_env[head_match.end():]}"
            )
        return f"{script}\n{html_without_stale_env}"

    def _is_unmatched_terminal_ws_path(self, request: web.Request) -> bool:
        path = request.path.rstrip("/")
        terminal_paths = ("/terminal/ws", "/terminal/ws-probe")
        if not path.startswith("/node/") or not any(path.endswith(suffix) for suffix in terminal_paths):
            return False
        configured_path = self._web_base_path()
        return not configured_path or not any(path == f"{configured_path}{suffix}" for suffix in terminal_paths)
    
    async def serve_index(self, request):
        """Serve index.html for SPA routes."""
        if self._is_unmatched_terminal_ws_path(request):
            logger.warning(
                "终端 WebSocket 路径未匹配当前 WEB_BASE_PATH: path=%s configured_base=%s",
                request.path,
                self._web_base_path() or "/",
            )
            return web.Response(
                text=(
                    "Terminal WebSocket route not found for this WEB_BASE_PATH. "
                    f"path={request.path} configured_base={self._web_base_path() or '/'}"
                ),
                status=404,
                content_type="text/plain",
            )
        index_path = Path(self._get_static_dir()) / "index.html"
        if index_path.exists():
            html = index_path.read_text(encoding="utf-8")
            response = web.Response(text=self._inject_public_runtime_env(html), content_type="text/html")
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        return web.Response(text="Not found", status=404)

    async def start(self):
        if self._runner is not None:
            return
        app = self._build_app()
        await self.transfer_service.start()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        self._loop_lag_task = asyncio.create_task(self._watch_loop_lag(), name="web-loop-lag-watch")
        if get_update_status().get("update_enabled"):
            self._update_task = asyncio.create_task(self._auto_refresh_update_status())
        if self._fixed_forward_service.should_autostart():
            fixed_snapshot = await self._fixed_forward_service.start()
            logger.info("固定公网转发状态: %s %s", fixed_snapshot.get("status"), fixed_snapshot.get("public_url") or "")
        if self._tunnel_service.should_autostart():
            tunnel_snapshot = await self._tunnel_service.start()
            await self._notify_or_schedule_tunnel_public_url(tunnel_snapshot, reason="web_server_start")
            logger.info("Web tunnel 状态: %s %s", tunnel_snapshot.get("status"), tunnel_snapshot.get("public_url") or "")
        local_url = TunnelService._build_local_url(self._host, self._port)
        logger.info(
            "Web API 已启动: %s (token=%s, allowed_origins=%s, node_id=%s, base_path=%s, public_url=%s, fixed_public_url=%s)",
            local_url,
            "已配置" if WEB_API_TOKEN else "未配置",
            ",".join(WEB_ALLOWED_ORIGINS),
            TCB_NODE_ID or "",
            self._web_base_path() or "/",
            WEB_PUBLIC_URL or "",
            WEB_FIXED_PUBLIC_FORWARD_URL or "",
        )

    async def _watch_loop_lag(self) -> None:
        loop = asyncio.get_running_loop()
        interval_seconds = 1.0
        expected_at = loop.time() + interval_seconds
        while True:
            await asyncio.sleep(interval_seconds)
            now = loop.time()
            lag_ms = max(0, int(round((now - expected_at) * 1000)))
            expected_at = now + interval_seconds
            self._loop_lag_tracker.observe(lag_ms)
            threshold_ms = diag_loop_lag_ms()
            if lag_ms < threshold_ms or not diag_enabled():
                continue
            pending = [
                task
                for task in asyncio.all_tasks(loop)
                if task is not asyncio.current_task(loop) and not task.done()
            ]
            names: list[str] = []
            stacks: list[str] = []
            for task in pending[:8]:
                name = task.get_name()
                coro = task.get_coro()
                task_name = name or getattr(coro, "__qualname__", "") or type(coro).__name__
                names.append(task_name)
                stack = task.get_stack(limit=2)
                if stack:
                    frame = stack[-1]
                    stacks.append(f"{task_name}:{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}")
            diag_log_slow(
                logger,
                "event_loop_lag",
                lag_ms,
                threshold_ms=threshold_ms,
                lag_ms=lag_ms,
                pending_count=len(pending),
                pending=",".join(names),
                stacks="|".join(stacks),
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
        if self._loop_lag_task is not None:
            self._loop_lag_task.cancel()
            await asyncio.gather(self._loop_lag_task, return_exceptions=True)
            self._loop_lag_task = None
        if self._tunnel_ready_task is not None:
            self._tunnel_ready_task.cancel()
            await asyncio.gather(self._tunnel_ready_task, return_exceptions=True)
            self._tunnel_ready_task = None
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
        await self._terminal_manager.shutdown()
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
        notification_tasks = list(self._notification_tasks)
        self._notification_tasks.clear()
        for task in notification_tasks:
            task.cancel()
        if notification_tasks:
            await asyncio.gather(*notification_tasks, return_exceptions=True)
        await self._notification_service.close()
        plugin_service = getattr(self.manager, "plugin_service", None)
        if plugin_service is not None:
            await plugin_service.shutdown()
        await self.lan_chat_service.close()
        await self.inline_completion_service.close()
        if preserve_tunnel:
            self._tunnel_service.preserve_for_restart()
        else:
            await self._tunnel_service.stop()
        await self._fixed_forward_service.stop()
        await self.transfer_service.close()
        await self._runner.cleanup()
        await asyncio.to_thread(close_session_store)
        self._runner = None
        self._site = None
        logger.info("Web API 已停止")
