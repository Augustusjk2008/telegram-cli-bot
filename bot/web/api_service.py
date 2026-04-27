"""Web 模式共享服务层。"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import ntpath
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from xml.etree import ElementTree

from bot.assistant_cron_store import (
    delete_job_run_audit,
    delete_job_runtime_state,
    read_job_definition,
    read_job_run_audit,
)
from bot.assistant_dream import AssistantDreamConfig, apply_dream_result, prepare_dream_prompt
from bot.assistant_cron_types import AssistantCronJob
from bot.assistant_compaction import (
    finalize_compaction,
    is_compaction_prompt_active,
    list_pending_capture_ids,
    refresh_compaction_state,
    snapshot_managed_surface,
)
from bot.assistant_context import compile_assistant_prompt
from bot.assistant_memory_recall import recall_assistant_memories
from bot.assistant_working_memory_indexer import index_working_memories
from bot.assistant_memory_writer import write_hot_path_memories
from bot.claude_done import ClaudeDoneCollector, build_claude_done_session
from bot.assistant_docs import sync_managed_prompt_files
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_proposals import list_proposals, set_proposal_status
from bot.assistant_runtime import AssistantRunRequest
from bot.assistant_upgrade import apply_approved_upgrade
from bot.assistant_state import (
    attach_assistant_persist_hook,
    clear_assistant_runtime_state,
    record_assistant_capture,
    restore_assistant_runtime_state,
)
from bot.cli_params import get_default_params, get_params_schema, normalize_cli_model_options
from bot.config import CLI_MODEL_OPTIONS
from bot.cli import (
    build_cli_command,
    normalize_cli_type,
    parse_claude_stream_json_line,
    parse_claude_stream_json_output,
    parse_codex_json_line,
    parse_codex_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
)
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import BotProfile, UserSession
from bot.platform.output import strip_ansi_escape
from bot.platform.processes import build_hidden_process_kwargs, terminate_process_tree_sync
from bot.platform.scripts import execute_script, get_scripts_dir, list_available_scripts, stream_execute_script
from bot.runtime_paths import get_chat_attachments_dir
from bot.session_store import rename_bot_sessions as rename_stored_bot_sessions
from bot.sessions import (
    align_session_paths,
    get_or_create_session,
    rekey_bot_sessions,
    reset_session,
    sessions,
    sessions_lock,
    update_bot_working_dir,
)
from bot.updater import download_latest_update
from bot.utils import is_dangerous_command
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.native_history_adapter import create_stream_trace_state, consume_stream_trace_chunk
from bot.web.auth_store import CAP_RUN_PLUGINS, CAP_VIEW_PLUGINS, MEMBER_CAPABILITIES
from bot.web import workspace_index_service

logger = logging.getLogger(__name__)
UPLOAD_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
_ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_AVATAR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_DRIVES_VIRTUAL_ROOT = "::windows-drives::"
_WINDOWS_DRIVES_DISPLAY_ROOT = "盘符列表"
_WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
_WINDOWS_STYLE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
WORKDIR_CHANGE_REQUIRES_RESET = "workdir_change_requires_reset"
WORKDIR_CHANGE_BLOCKED_PROCESSING = "workdir_change_blocked_processing"
CODEX_DONE_QUIET_SECONDS = 0.5
_RASTER_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class WebApiError(Exception):
    """Web API 业务异常。"""

    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass
class AuthContext:
    """Web 请求的认证上下文。"""

    user_id: int
    token_used: bool
    account_id: str = "legacy-default"
    username: str = "legacy"
    role: str = "member"
    capabilities: set[str] = field(default_factory=lambda: set(MEMBER_CAPABILITIES))


@dataclass
class CliAttemptState:
    """单次 CLI 尝试的会话状态。"""

    cli_session_id: Optional[str]
    resume_session: bool
    codex_session_id: Optional[str] = None


def _raise(status: int, code: str, message: str, data: dict[str, Any] | None = None):
    raise WebApiError(status=status, code=code, message=message, data=data)


def _require_capability(auth: AuthContext, capability: str) -> None:
    if capability in auth.capabilities:
        return
    _raise(403, "forbidden", "当前账号无权限执行此操作")


def _avatar_asset_dirs() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "front" / "public" / "assets" / "avatars",
        repo_root / "front" / "dist" / "assets" / "avatars",
    ]


def _is_safe_avatar_name(name: str) -> bool:
    candidate = str(name or "").strip()
    if not candidate:
        return False
    if Path(candidate).name != candidate:
        return False
    if not _AVATAR_NAME_RE.fullmatch(candidate):
        return False
    return Path(candidate).suffix.lower() in _ALLOWED_AVATAR_EXTENSIONS


def _read_png_dimensions(path: Path) -> Optional[tuple[int, int]]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _read_gif_dimensions(path: Path) -> Optional[tuple[int, int]]:
    header = path.read_bytes()[:10]
    if len(header) < 10 or header[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", header[6:10])
    return width, height


def _read_jpeg_dimensions(path: Path) -> Optional[tuple[int, int]]:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return None
        while True:
            marker_prefix = handle.read(1)
            while marker_prefix and marker_prefix != b"\xff":
                marker_prefix = handle.read(1)
            if not marker_prefix:
                return None
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker:
                return None
            marker_value = marker[0]
            if marker_value in {0xD8, 0xD9}:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) < 2:
                return None
            segment_length = struct.unpack(">H", length_bytes)[0]
            if segment_length < 2:
                return None
            if marker_value in {
                0xC0, 0xC1, 0xC2, 0xC3,
                0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB,
                0xCD, 0xCE, 0xCF,
            }:
                payload = handle.read(segment_length - 2)
                if len(payload) < 5:
                    return None
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            handle.seek(segment_length - 2, os.SEEK_CUR)


def _read_webp_dimensions(path: Path) -> Optional[tuple[int, int]]:
    header = path.read_bytes()[:30]
    if len(header) < 16 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
        return None
    chunk = header[12:16]
    if chunk == b"VP8X" and len(header) >= 30:
        width = 1 + int.from_bytes(header[24:27], "little")
        height = 1 + int.from_bytes(header[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(header) >= 30:
        width, height = struct.unpack("<HH", header[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(header) >= 25:
        b0, b1, b2, b3 = header[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return width, height
    return None


def _parse_svg_dimension(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    matched = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(px)?\s*", value)
    if not matched:
        return None
    return int(round(float(matched.group(1))))


def _read_svg_dimensions(path: Path) -> Optional[tuple[int, int]]:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    width = _parse_svg_dimension(root.attrib.get("width"))
    height = _parse_svg_dimension(root.attrib.get("height"))
    if width and height:
        return width, height
    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if not view_box:
        return None
    parts = re.split(r"[\s,]+", view_box.strip())
    if len(parts) != 4:
        return None
    try:
        return int(round(float(parts[2]))), int(round(float(parts[3])))
    except ValueError:
        return None


def _read_avatar_dimensions(path: Path) -> Optional[tuple[int, int]]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".png":
            return _read_png_dimensions(path)
        if suffix == ".gif":
            return _read_gif_dimensions(path)
        if suffix in {".jpg", ".jpeg"}:
            return _read_jpeg_dimensions(path)
        if suffix == ".webp":
            return _read_webp_dimensions(path)
        if suffix == ".svg":
            return _read_svg_dimensions(path)
    except (ElementTree.ParseError, OSError, UnicodeDecodeError, ValueError, struct.error):
        return None
    return None


def _is_supported_avatar_asset(path: Path) -> bool:
    dimensions = _read_avatar_dimensions(path)
    return dimensions == (64, 64)


def list_avatar_assets() -> dict[str, Any]:
    items_by_name: dict[str, dict[str, str]] = {}
    for directory in _avatar_asset_dirs():
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file():
                continue
            if not _is_safe_avatar_name(path.name):
                continue
            if not _is_supported_avatar_asset(path):
                continue
            items_by_name.setdefault(
                path.name,
                {
                    "name": path.name,
                    "url": f"/assets/avatars/{path.name}",
                },
            )

    return {"items": [items_by_name[name] for name in sorted(items_by_name.keys())]}


def _normalize_avatar_name(value: Any, *, require_existing: bool) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if not _is_safe_avatar_name(candidate):
        _raise(400, "invalid_avatar_name", "头像文件名不合法")
    if require_existing:
        available_names = {item["name"] for item in list_avatar_assets()["items"]}
        if available_names and candidate not in available_names:
            _raise(400, "invalid_avatar_name", "头像文件不存在")
    return candidate


def _assistant_home_or_raise(manager: MultiBotManager, alias: str):
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "assistant":
        _raise(409, "unsupported_bot_mode", "仅 assistant Bot 支持 proposal 审批")
    return bootstrap_assistant_home(profile.working_dir)


def _assistant_cron_service_or_raise(manager: MultiBotManager, alias: str):
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "assistant":
        _raise(409, "unsupported_bot_mode", "仅 assistant Bot 支持定时任务")
    service = manager.assistant_cron_service
    if service is None or service.bot_alias != profile.alias:
        _raise(503, "assistant_cron_unavailable", "assistant cron 服务尚未启动")
    return service


def _deep_merge_dict(base: dict[str, Any], patch_payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch_payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _build_assistant_cron_job_item(job: AssistantCronJob, *, state: Any) -> dict[str, Any]:
    return {
        **job.to_dict(),
        "next_run_at": state.next_run_at,
        "last_status": state.last_status,
        "last_error": state.last_error,
        "last_success_at": state.last_success_at,
        "pending": bool(state.pending_run_id or state.current_run_id),
        "pending_run_id": state.pending_run_id or state.current_run_id,
        "coalesced_count": state.coalesced_count,
    }


def get_profile_or_raise(manager: MultiBotManager, alias: str) -> BotProfile:
    alias = (alias or "").strip().lower()
    if alias == manager.main_profile.alias:
        return manager.main_profile
    profile = manager.managed_profiles.get(alias)
    if profile is None:
        _raise(404, "bot_not_found", f"未找到别名为 `{alias}` 的 Bot")
    return profile


def resolve_session_bot_id(manager: MultiBotManager, alias: str) -> int:
    app = manager.applications.get(alias)
    if app:
        bot_id = app.bot_data.get("bot_id")
        if isinstance(bot_id, int):
            return bot_id
    return -int(zlib.adler32(f"web:{alias}".encode("utf-8")))


def get_session_for_alias(manager: MultiBotManager, alias: str, user_id: int) -> UserSession:
    profile = get_profile_or_raise(manager, alias)
    session = get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=user_id,
        default_working_dir=profile.working_dir,
        load_persisted_state=profile.bot_mode != "assistant",
    )

    if profile.bot_mode == "assistant" and session.persist_hook is None:
        home = bootstrap_assistant_home(profile.working_dir)
        attach_assistant_persist_hook(session, home, user_id)
        restore_assistant_runtime_state(session, home, user_id)

    return align_session_paths(session, profile.working_dir, profile.bot_mode)


def _supports_cli_runtime(profile: BotProfile) -> bool:
    return profile.bot_mode in ("cli", "assistant")


def _get_browser_directory(session: UserSession) -> str:
    if isinstance(session.browse_dir, str) and session.browse_dir.strip():
        return session.browse_dir
    return session.working_dir


def _is_windows_drives_virtual_root(path: str) -> bool:
    return str(path or "").strip() == _WINDOWS_DRIVES_VIRTUAL_ROOT


def _is_windows_drive_root(path: str) -> bool:
    return bool(_WINDOWS_DRIVE_ROOT_RE.fullmatch(str(path or "").strip()))


def _looks_like_windows_path(path: str) -> bool:
    value = str(path or "").strip()
    return bool(_WINDOWS_STYLE_PATH_RE.match(value) or _is_windows_drive_root(value))


def _normalize_windows_drive_root(path: str) -> str:
    value = str(path or "").strip().replace("/", "\\")
    if not _is_windows_drive_root(value):
        _raise(400, "invalid_drive_root", f"无效盘符路径: {path}")
    return f"{value[0].upper()}:\\"


def _display_browser_directory(path: str) -> str:
    if _is_windows_drives_virtual_root(path):
        return _WINDOWS_DRIVES_DISPLAY_ROOT
    return path


def _build_directory_listing_response(
    working_dir: str,
    entries: list[dict[str, Any]],
    *,
    is_virtual_root: bool = False,
) -> dict[str, Any]:
    return {
        "working_dir": _display_browser_directory(working_dir),
        "entries": entries,
        "is_virtual_root": is_virtual_root,
    }


def _list_windows_drive_entries() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for drive_code in range(ord("A"), ord("Z") + 1):
        drive_root = f"{chr(drive_code)}:\\"
        if os.path.isdir(drive_root):
            entries.append({"name": drive_root, "is_dir": True})
    return _build_directory_listing_response(
        _WINDOWS_DRIVES_VIRTUAL_ROOT,
        entries,
        is_virtual_root=True,
    )


def _require_real_browser_directory(browser_dir: str) -> str:
    if _is_windows_drives_virtual_root(browser_dir):
        _raise(409, "virtual_directory_unsupported", "当前视图仅用于切换盘符，不能直接执行文件操作")
    return browser_dir


def _resolve_browser_target_path(current_dir: str, new_path: str) -> str:
    path = str(new_path or "").strip()
    if not path:
        _raise(400, "missing_path", "路径不能为空")

    if _is_windows_drives_virtual_root(current_dir):
        if path in {"..", "."}:
            return _WINDOWS_DRIVES_VIRTUAL_ROOT
        return _normalize_windows_drive_root(path)

    if _is_windows_drive_root(current_dir) and path == "..":
        return _WINDOWS_DRIVES_VIRTUAL_ROOT

    if _looks_like_windows_path(current_dir) or _looks_like_windows_path(path):
        candidate = path
        if not ntpath.isabs(candidate):
            candidate = ntpath.join(current_dir, candidate)
        return ntpath.abspath(ntpath.expanduser(candidate))

    candidate = path
    if not os.path.isabs(candidate):
        candidate = os.path.join(current_dir, candidate)
    return os.path.abspath(os.path.expanduser(candidate))


def _build_session_ids(session: UserSession) -> dict[str, Any]:
    return {
        "codex_session_id": session.codex_session_id,
        "claude_session_id": session.claude_session_id,
        "claude_session_initialized": session.claude_session_initialized,
    }


def _build_running_reply_snapshot(session: UserSession) -> Optional[dict[str, Any]]:
    if not session.running_started_at:
        return None
    return {
        "user_text": session.running_user_text or "",
        "preview_text": session.running_preview_text or "",
        "started_at": session.running_started_at,
        "updated_at": session.running_updated_at or session.running_started_at,
    }


def _get_chat_history_service(session: UserSession) -> ChatHistoryService:
    return ChatHistoryService(ChatStore(Path(session.working_dir)))


def build_session_snapshot(profile: BotProfile, session: UserSession) -> dict[str, Any]:
    return _get_chat_history_service(session).build_session_snapshot(profile, session)


def _build_capabilities(profile: BotProfile, is_main: bool) -> list[str]:
    capabilities = ["session", "history"]
    if _supports_cli_runtime(profile):
        capabilities.extend(["chat", "exec", "files"])
    if is_main:
        capabilities.append("admin")
    return capabilities


def _build_run_status(manager: MultiBotManager, alias: str, profile: BotProfile) -> str:
    app = manager.applications.get(alias)
    if app:
        return "running"
    if alias == manager.main_profile.alias:
        return "configured"
    return "configured" if profile.enabled else "stopped"


def build_bot_summary(
    manager: MultiBotManager,
    alias: str,
    user_id: Optional[int] = None,
    *,
    profile: Optional[BotProfile] = None,
    session: Optional[UserSession] = None,
) -> dict[str, Any]:
    profile = profile or get_profile_or_raise(manager, alias)
    app = manager.applications.get(alias)

    # 优先使用当前用户 session 的工作目录（如果用户已登录）
    working_dir = profile.working_dir
    is_processing = False
    if user_id is not None:
        try:
            current_session = session or get_session_for_alias(manager, alias, user_id)
            if current_session and current_session.working_dir:
                working_dir = current_session.working_dir
            if current_session:
                with current_session._lock:
                    is_processing = current_session.is_processing
        except Exception:
            # 如果获取 session 失败，使用 profile 的工作目录
            pass

    return {
        "alias": profile.alias,
        "enabled": profile.enabled,
        "bot_mode": profile.bot_mode,
        "cli_type": profile.cli_type,
        "cli_path": profile.cli_path,
        "working_dir": working_dir,
        "avatar_name": profile.avatar_name or "",
        "is_main": alias == manager.main_profile.alias,
        "status": _build_run_status(manager, alias, profile),
        "is_processing": is_processing,
        "bot_username": (app.bot_data.get("bot_username") if app else "") or "",
        "capabilities": _build_capabilities(profile, alias == manager.main_profile.alias),
    }


def list_bots(manager: MultiBotManager, user_id: Optional[int] = None) -> list[dict[str, Any]]:
    aliases = [manager.main_profile.alias, *sorted(manager.managed_profiles.keys())]
    return [build_bot_summary(manager, alias, user_id) for alias in aliases]


def get_overview(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    return {
        "bot": build_bot_summary(manager, alias, user_id, profile=profile, session=session),
        "session": build_session_snapshot(profile, session),
    }


async def list_plugins(manager: MultiBotManager, auth: AuthContext, refresh: bool = False) -> list[dict[str, Any]]:
    _require_capability(auth, CAP_VIEW_PLUGINS)
    if refresh:
        return await manager.plugin_service.reload_plugins()
    return manager.plugin_service.list_plugins()


async def list_installable_plugins(manager: MultiBotManager, auth: AuthContext) -> list[dict[str, Any]]:
    _require_capability(auth, CAP_VIEW_PLUGINS)
    return manager.plugin_service.list_installable_plugins()


async def install_plugin(
    manager: MultiBotManager,
    auth: AuthContext,
    body: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    plugin_id = str(body.get("pluginId") or body.get("plugin_id") or body.get("id") or "").strip()
    source_path = str(body.get("sourcePath") or body.get("source_path") or "").strip()
    if not plugin_id and not source_path:
        _raise(400, "missing_plugin_id", "插件 ID 或目录不能为空")
    install_args = {}
    if source_path:
        install_args["source_path"] = source_path
    if not plugin_id:
        plugin_id = None
    try:
        return await manager.plugin_service.install_plugin(plugin_id, **install_args)
    except KeyError as exc:
        _raise(404, "plugin_not_found", str(exc))
    except FileNotFoundError as exc:
        _raise(400, "invalid_plugin_source", str(exc))
    except FileExistsError as exc:
        _raise(409, "plugin_already_installed", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))


async def update_plugin(
    manager: MultiBotManager,
    auth: AuthContext,
    plugin_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    try:
        return await manager.plugin_service.update_plugin(
            plugin_id,
            enabled=body.get("enabled") if "enabled" in body else None,
            config=dict(body.get("config") or {}) if "config" in body else None,
        )
    except KeyError as exc:
        _raise(404, "plugin_not_found", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))


def resolve_plugin_file_target(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    path: str,
) -> dict[str, Any]:
    _require_capability(auth, CAP_VIEW_PLUGINS)
    get_profile_or_raise(manager, alias)
    return manager.plugin_service.resolve_file_target(path)


def _resolve_plugin_render_input(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(input_payload or {})
    path_value = resolved.get("path")
    if path_value is None:
        return resolved
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    resolved["path"] = _resolve_safe_path(browser_dir, str(path_value))
    return resolved


async def render_plugin_view(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    plugin_id: str,
    view_id: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    resolved_input = _resolve_plugin_render_input(manager, alias, auth.user_id, input_payload)
    try:
        return await manager.plugin_service.render_view(
            bot_alias=alias,
            plugin_id=plugin_id,
            view_id=view_id,
            input_payload=resolved_input,
            audit_context={"account_id": auth.account_id, "bot_alias": alias},
        )
    except KeyError as exc:
        _raise(404, "plugin_not_found", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))
    except RuntimeError as exc:
        _raise(500, "plugin_render_failed", str(exc))


async def open_plugin_view(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    plugin_id: str,
    view_id: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    resolved_input = _resolve_plugin_render_input(manager, alias, auth.user_id, input_payload)
    try:
        return await manager.plugin_service.open_view(
            bot_alias=alias,
            plugin_id=plugin_id,
            view_id=view_id,
            input_payload=resolved_input,
            audit_context={"account_id": auth.account_id, "bot_alias": alias},
        )
    except KeyError as exc:
        _raise(404, "plugin_not_found", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))
    except RuntimeError as exc:
        _raise(500, "plugin_open_failed", str(exc))


async def get_plugin_view_window(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    plugin_id: str,
    session_id: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    try:
        return await manager.plugin_service.get_view_window(
            bot_alias=alias,
            plugin_id=plugin_id,
            session_id=session_id,
            request_payload=request_payload,
            audit_context={"account_id": auth.account_id, "bot_alias": alias},
        )
    except KeyError as exc:
        _raise(404, "plugin_session_not_found", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))
    except RuntimeError as exc:
        _raise(500, "plugin_window_failed", str(exc))


async def dispose_plugin_view(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    plugin_id: str,
    session_id: str,
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    try:
        return await manager.plugin_service.dispose_view(
            bot_alias=alias,
            plugin_id=plugin_id,
            session_id=session_id,
            audit_context={"account_id": auth.account_id, "bot_alias": alias},
        )
    except KeyError as exc:
        _raise(404, "plugin_session_not_found", str(exc))
    except RuntimeError as exc:
        _raise(500, "plugin_dispose_failed", str(exc))


async def invoke_plugin_action(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    plugin_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    try:
        return await manager.plugin_service.invoke_action(
            bot_alias=alias,
            plugin_id=plugin_id,
            view_id=str(body.get("viewId") or "").strip(),
            session_id=str(body.get("sessionId") or "").strip() or None,
            action_id=str(body.get("actionId") or "").strip(),
            payload=dict(body.get("payload") or {}),
            audit_context={"account_id": auth.account_id, "bot_alias": alias},
        )
    except KeyError as exc:
        _raise(404, "plugin_session_not_found", str(exc))
    except ValueError as exc:
        _raise(400, "invalid_plugin_request", str(exc))
    except RuntimeError as exc:
        _raise(500, "plugin_action_failed", str(exc))


def get_plugin_artifact(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    artifact_id: str,
):
    _require_capability(auth, CAP_RUN_PLUGINS)
    get_profile_or_raise(manager, alias)
    try:
        return manager.plugin_service.get_artifact(bot_alias=alias, artifact_id=artifact_id)
    except KeyError as exc:
        _raise(404, "plugin_artifact_not_found", str(exc))


def list_assistant_proposals(
    manager: MultiBotManager,
    alias: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    return {"items": list_proposals(home, status=status)}


async def approve_assistant_proposal(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
    *,
    reviewer: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        return set_proposal_status(home, proposal_id, "approved", reviewer=reviewer)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))


async def reject_assistant_proposal(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
    *,
    reviewer: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        return set_proposal_status(home, proposal_id, "rejected", reviewer=reviewer)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))


async def apply_assistant_upgrade(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return apply_approved_upgrade(home, proposal_id, repo_root=repo_root)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        _raise(500, "assistant_upgrade_failed", detail or "应用 upgrade 失败")


def list_assistant_cron_jobs(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    items = []
    for job in service.list_jobs():
        state = service.get_job_state(job.id)
        items.append(_build_assistant_cron_job_item(job, state=state))
    return {"items": items}


async def create_assistant_cron_job(manager: MultiBotManager, alias: str, payload: dict[str, Any]) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    try:
        job = AssistantCronJob.from_dict(payload)
        try:
            read_job_definition(service.assistant_home, job.id)
        except FileNotFoundError:
            pass
        else:
            _raise(409, "cron_job_exists", f"job `{job.id}` 已存在")
        saved = await service.save_job(job)
    except ValueError as exc:
        _raise(400, "invalid_cron_job", str(exc))
    state = service.get_job_state(saved.id)
    return {"job": _build_assistant_cron_job_item(saved, state=state)}


async def update_assistant_cron_job(
    manager: MultiBotManager,
    alias: str,
    job_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    try:
        current = read_job_definition(service.assistant_home, job_id)
    except FileNotFoundError:
        _raise(404, "cron_job_not_found", f"job `{job_id}` 不存在")

    merged = _deep_merge_dict(current.to_dict(), payload)
    merged["id"] = job_id
    try:
        saved = await service.save_job(AssistantCronJob.from_dict(merged))
    except ValueError as exc:
        _raise(400, "invalid_cron_job", str(exc))
    state = service.get_job_state(saved.id)
    return {"job": _build_assistant_cron_job_item(saved, state=state)}


async def delete_assistant_cron_job(manager: MultiBotManager, alias: str, job_id: str) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    if not await service.delete_job(job_id):
        _raise(404, "cron_job_not_found", f"job `{job_id}` 不存在")
    delete_job_runtime_state(service.assistant_home, job_id)
    delete_job_run_audit(service.assistant_home, job_id)
    return {"removed": True, "job_id": job_id}


async def run_assistant_cron_job_now(manager: MultiBotManager, alias: str, job_id: str) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    try:
        return await service.run_job_now(job_id)
    except FileNotFoundError:
        _raise(404, "cron_job_not_found", f"job `{job_id}` 不存在")


def list_assistant_cron_runs(
    manager: MultiBotManager,
    alias: str,
    job_id: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    service = _assistant_cron_service_or_raise(manager, alias)
    try:
        read_job_definition(service.assistant_home, job_id)
    except FileNotFoundError:
        _raise(404, "cron_job_not_found", f"job `{job_id}` 不存在")
    items = read_job_run_audit(service.assistant_home, job_id, limit=max(1, limit))
    items.reverse()
    return {"items": items}


def _apply_cli_model_options(schema: dict[str, Any]) -> dict[str, Any]:
    next_schema = copy.deepcopy(schema)
    model_field = next_schema.get("model")
    model_options = normalize_cli_model_options(CLI_MODEL_OPTIONS)
    if isinstance(model_field, dict) and model_options:
        model_field["enum"] = model_options
    return next_schema


def get_cli_params_payload(manager: MultiBotManager, alias: str, cli_type: Optional[str] = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    if not resolved_cli_type:
        _raise(400, "missing_cli_type", "缺少 CLI 类型")

    try:
        params = profile.cli_params.get_params(resolved_cli_type)
        schema = _apply_cli_model_options(get_params_schema(resolved_cli_type))
        defaults = get_default_params(resolved_cli_type)
    except ValueError as exc:
        _raise(400, "invalid_cli_type", str(exc))

    return {
        "cli_type": resolved_cli_type,
        "params": copy.deepcopy(params),
        "schema": schema,
        "defaults": defaults,
    }


async def update_cli_params(
    manager: MultiBotManager,
    alias: str,
    cli_type: Optional[str],
    key: str,
    value: Any,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    if not key or not key.strip():
        _raise(400, "missing_param_key", "缺少参数名")

    try:
        await manager.set_bot_cli_param(alias, resolved_cli_type, key.strip(), value)
    except ValueError as exc:
        _raise(400, "invalid_param_value", str(exc))

    return get_cli_params_payload(manager, alias, resolved_cli_type)


async def reset_cli_params(manager: MultiBotManager, alias: str, cli_type: Optional[str] = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    try:
        await manager.reset_bot_cli_params(alias, resolved_cli_type)
    except ValueError as exc:
        _raise(400, "invalid_cli_type", str(exc))
    return get_cli_params_payload(manager, alias, resolved_cli_type)


def _resolve_safe_path(base_dir: str, filename: str) -> str:
    candidate = str(filename or "").strip()
    if not candidate or candidate == "." or "\x00" in candidate:
        _raise(400, "unsafe_path", "文件路径不安全")
    if os.path.isabs(candidate):
        return os.path.abspath(os.path.expanduser(candidate))
    return os.path.abspath(os.path.join(base_dir, os.path.expanduser(candidate)))


def _resolve_safe_write_path(base_dir: str, path: str) -> str:
    candidate = str(path or "").strip()
    if not candidate or candidate == "." or "\x00" in candidate:
        _raise(400, "unsafe_write_path", "文件路径不安全")
    if os.path.isabs(candidate):
        _raise(400, "unsafe_write_path", "不允许写入绝对路径")

    resolved_base = os.path.abspath(base_dir)
    resolved_path = os.path.abspath(os.path.join(resolved_base, os.path.expanduser(candidate)))

    try:
        if os.path.commonpath([resolved_base, resolved_path]) != resolved_base:
            _raise(400, "unsafe_write_path", "文件路径不安全")
    except ValueError:
        _raise(400, "unsafe_write_path", "文件路径不安全")

    return resolved_path


def _ensure_editable_text_file(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            while handle.read(1024 * 1024):
                pass
    except UnicodeDecodeError:
        _raise(400, "not_text_file", "文件不是可编辑的文本文件")


def _write_text_file_atomically(path: str, content: str) -> None:
    directory = os.path.dirname(path)
    temporary_path = os.path.join(directory, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def _stat_file_version(path: str) -> int:
    return os.stat(path).st_mtime_ns


def _ensure_file_version_advanced(path: str, previous_mtime_ns: int) -> int:
    current_mtime_ns = _stat_file_version(path)
    if current_mtime_ns > previous_mtime_ns:
        return current_mtime_ns

    for step_ns in (
        100,
        1_000,
        10_000,
        100_000,
        1_000_000,
        10_000_000,
        100_000_000,
        1_000_000_000,
        2_000_000_000,
    ):
        adjusted_mtime_ns = previous_mtime_ns + step_ns
        os.utime(path, ns=(adjusted_mtime_ns, adjusted_mtime_ns))
        current_mtime_ns = _stat_file_version(path)
        if current_mtime_ns > previous_mtime_ns:
            return current_mtime_ns

    _raise(500, "write_file_failed", "文件版本更新失败")


def _resolve_new_directory_path(base_dir: str, name: str) -> tuple[str, str]:
    candidate = str(name or "").strip()
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "invalid_directory_name", "文件夹名称不合法")

    path_separators = {os.path.sep}
    if os.path.altsep:
        path_separators.add(os.path.altsep)
    if any(separator and separator in candidate for separator in path_separators):
        _raise(400, "invalid_directory_name", "文件夹名称不能包含路径分隔符")

    return candidate, os.path.abspath(os.path.join(base_dir, candidate))


def _validate_text_filename(name: str) -> str:
    candidate = str(name or "").strip()
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "invalid_filename", "文件名不合法")

    path_separators = {os.path.sep}
    if os.path.altsep:
        path_separators.add(os.path.altsep)
    if any(separator and separator in candidate for separator in path_separators):
        _raise(400, "invalid_filename", "文件名不能包含路径分隔符")

    return candidate


def _resolve_action_parent_dir(session: UserSession, parent_path: str | None = None) -> str:
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    candidate = str(parent_path or "").strip()
    if not candidate:
        return browser_dir

    resolved_base = os.path.abspath(browser_dir)
    if os.path.isabs(candidate):
        resolved_path = os.path.abspath(os.path.expanduser(candidate))
    else:
        resolved_path = os.path.abspath(os.path.join(resolved_base, os.path.expanduser(candidate)))

    try:
        if os.path.commonpath([resolved_base, resolved_path]) != resolved_base:
            _raise(400, "unsafe_write_path", "文件路径不安全")
    except ValueError:
        _raise(400, "unsafe_write_path", "文件路径不安全")

    if not os.path.isdir(resolved_path):
        _raise(404, "dir_not_found", f"目录不存在: {resolved_path}")
    return resolved_path


def _ensure_file_browser_supported(manager: MultiBotManager, alias: str) -> BotProfile:
    profile = get_profile_or_raise(manager, alias)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持文件操作")
    return profile


def _sanitize_uploaded_filename(filename: str) -> str:
    candidate = os.path.basename(ntpath.basename(str(filename or "").strip()))
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "unsafe_filename", "文件名不合法")
    return candidate


def _build_chat_attachment_dir(alias: str, user_id: int) -> str:
    return str(get_chat_attachments_dir(alias, user_id))


def _resolve_unique_upload_path(base_dir: str, filename: str) -> tuple[str, str]:
    safe_name = _sanitize_uploaded_filename(filename)
    stem, suffix = os.path.splitext(safe_name)
    resolved_name = safe_name
    resolved_path = os.path.join(base_dir, resolved_name)
    counter = 1
    while os.path.exists(resolved_path):
        resolved_name = f"{stem}-{counter}{suffix}"
        resolved_path = os.path.join(base_dir, resolved_name)
        counter += 1
    return resolved_path, resolved_name


def _resolve_chat_attachment_path(alias: str, user_id: int, saved_path: str) -> Path:
    candidate = Path(str(saved_path or "").strip())
    if not str(candidate):
        _raise(400, "missing_saved_path", "附件路径不能为空")
    if not candidate.is_absolute():
        _raise(400, "invalid_saved_path", "附件路径必须是绝对路径")

    attachment_dir = get_chat_attachments_dir(alias, user_id).resolve()
    resolved_candidate = candidate.expanduser().resolve(strict=False)
    try:
        resolved_candidate.relative_to(attachment_dir)
    except ValueError:
        _raise(403, "attachment_delete_forbidden", "只能删除当前 Bot 当前用户上传的附件")
    return resolved_candidate


def _list_directory_entries(working_dir: str) -> dict[str, Any]:
    entries = []
    for entry in sorted(os.scandir(working_dir), key=lambda item: (not item.is_dir(), item.name.lower())):
        item = {
            "name": entry.name,
            "is_dir": entry.is_dir(),
        }
        if entry.is_file():
            item["size"] = entry.stat().st_size
        entries.append(item)
    return _build_directory_listing_response(working_dir, entries)


def _list_directory_entry_items(working_dir: str) -> list[dict[str, Any]]:
    return _list_directory_entries(working_dir)["entries"]


def _ensure_path_within_base_dir(base_dir: str, target_dir: str) -> None:
    try:
        base_path = Path(base_dir).resolve()
        target_path = Path(target_dir).resolve()
        target_path.relative_to(base_path)
    except ValueError:
        _raise(403, "forbidden_path", "当前账号无权访问该目录")


def _invalidate_workspace_indexes(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *paths: str | os.PathLike[str] | None,
) -> None:
    session = get_session_for_alias(manager, alias, user_id)
    candidates = [session.working_dir, _get_browser_directory(session), *paths]
    for candidate in candidates:
        if candidate:
            workspace_index_service.invalidate_workspace_index(candidate)


def get_directory_listing(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str | None = None,
    *,
    base_dir: str | None = None,
    restrict_to_base_dir: bool = False,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = str(base_dir or _get_browser_directory(session))
    target_dir = browser_dir
    if path is not None and str(path).strip():
        target_dir = _resolve_browser_target_path(browser_dir, str(path))
    if restrict_to_base_dir and base_dir:
        _ensure_path_within_base_dir(base_dir, target_dir)
    if _is_windows_drives_virtual_root(target_dir):
        return _list_windows_drive_entries()
    try:
        return _list_directory_entries(target_dir)
    except FileNotFoundError:
        _raise(404, "working_dir_not_found", f"目录不存在: {target_dir}")
    except Exception as exc:
        _raise(500, "list_dir_failed", str(exc))


def reveal_directory_tree(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    root = Path(_require_real_browser_directory(_get_browser_directory(session))).expanduser().resolve()
    raw_path = Path(str(path or "").strip())
    if not str(raw_path):
        _raise(400, "missing_path", "路径不能为空")
    target = (raw_path if raw_path.is_absolute() else root / raw_path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise(403, "forbidden_path", "当前账号无权访问该目录")
    if not target.exists():
        _raise(404, "path_not_found", "文件或文件夹不存在")

    highlight_path = target.relative_to(root).as_posix()
    branch_target = target if target.is_dir() else target.parent
    branch_paths = [""]
    if branch_target != root:
        relative_parts = branch_target.relative_to(root).parts
        branch_paths.extend(
            "/".join(relative_parts[:index])
            for index in range(1, len(relative_parts) + 1)
        )

    branches: dict[str, list[dict[str, Any]]] = {}
    for branch_path in branch_paths:
        branch_dir = root / Path(*branch_path.split("/")) if branch_path else root
        branches[branch_path] = _list_directory_entry_items(str(branch_dir))

    return {
        "root_path": str(root),
        "highlight_path": highlight_path,
        "expanded_paths": [item for item in branch_paths if item],
        "branches": branches,
    }


def create_directory(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    name: str,
    parent_path: str | None = None,
) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    parent_dir = _resolve_action_parent_dir(session, parent_path)
    directory_name, target_path = _resolve_new_directory_path(parent_dir, name)

    if os.path.exists(target_path):
        _raise(409, "path_exists", "目标已存在")

    try:
        os.mkdir(target_path)
    except FileExistsError:
        _raise(409, "path_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "create_directory_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "name": directory_name,
        "created_path": target_path,
        "working_dir": browser_dir,
    }


def create_text_file(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    content: str = "",
    parent_path: str | None = None,
) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    parent_dir = _resolve_action_parent_dir(session, parent_path)
    file_name = _validate_text_filename(filename)
    target_path = os.path.abspath(os.path.join(parent_dir, file_name))

    if os.path.exists(target_path):
        _raise(409, "file_already_exists", "文件已存在")

    try:
        with open(target_path, "x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        _raise(409, "file_already_exists", "文件已存在")
    except Exception as exc:
        _raise(500, "create_file_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": os.path.relpath(target_path, browser_dir).replace("\\", "/"),
        "file_size_bytes": os.path.getsize(target_path),
        "last_modified_ns": _stat_file_version(target_path),
    }


def rename_path(manager: MultiBotManager, alias: str, user_id: int, path: str, new_name: str) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_rename_path", "缺少待重命名路径")

    source_path = _resolve_safe_write_path(browser_dir, source_rel)
    target_name = _validate_text_filename(new_name)

    if not os.path.isfile(source_path):
        _raise(404, "file_not_found", "文件不存在")

    target_path = os.path.abspath(os.path.join(os.path.dirname(source_path), target_name))
    if os.path.exists(target_path):
        _raise(409, "rename_target_exists", "目标已存在")

    try:
        os.rename(source_path, target_path)
    except FileExistsError:
        _raise(409, "rename_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "rename_path_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "old_path": source_rel,
        "path": target_relative_path,
    }


def _build_copy_filename(source_name: str, directory: str) -> str:
    stem, suffix = os.path.splitext(source_name)
    candidate = f"{stem} 副本{suffix}"
    counter = 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem} 副本 {counter}{suffix}"
        counter += 1
    return candidate


def copy_path(manager: MultiBotManager, alias: str, user_id: int, path: str) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_copy_path", "缺少待复制路径")

    source_path = _resolve_safe_write_path(browser_dir, source_rel)
    if not os.path.isfile(source_path):
        _raise(404, "file_not_found", "文件不存在")

    target_name = _build_copy_filename(os.path.basename(source_path), os.path.dirname(source_path))
    target_path = os.path.abspath(os.path.join(os.path.dirname(source_path), target_name))

    try:
        shutil.copy2(source_path, target_path)
    except FileExistsError:
        _raise(409, "copy_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "copy_path_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "source_path": source_rel,
        "path": target_relative_path,
        "file_size_bytes": os.path.getsize(target_path),
        "last_modified_ns": _stat_file_version(target_path),
    }


def move_path(manager: MultiBotManager, alias: str, user_id: int, path: str, target_parent_path: str) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_move_path", "缺少待移动路径")

    source_path = _resolve_safe_write_path(browser_dir, source_rel)
    if not os.path.exists(source_path):
        _raise(404, "path_not_found", "路径不存在")

    target_dir = _resolve_action_parent_dir(session, target_parent_path)
    target_path = os.path.abspath(os.path.join(target_dir, os.path.basename(source_path)))
    source_abs = os.path.abspath(source_path)

    if os.path.isdir(source_abs):
        try:
            if os.path.commonpath([source_abs, os.path.abspath(target_dir)]) == source_abs:
                _raise(400, "invalid_move_target", "不能将文件夹移动到自身或其子文件夹中")
        except ValueError:
            _raise(400, "invalid_move_target", "不能将文件夹移动到自身或其子文件夹中")

    if os.path.normcase(source_abs) == os.path.normcase(target_path):
        _raise(400, "same_move_target", "路径已在目标文件夹中")
    if os.path.exists(target_path):
        _raise(409, "move_target_exists", "目标已存在")

    try:
        shutil.move(source_path, target_path)
    except FileExistsError:
        _raise(409, "move_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "move_path_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "old_path": source_rel,
        "path": target_relative_path,
    }


def delete_path(manager: MultiBotManager, alias: str, user_id: int, path: str) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    target_path = _resolve_safe_path(browser_dir, path)

    if os.path.normcase(os.path.abspath(target_path)) == os.path.normcase(os.path.abspath(browser_dir)):
        _raise(400, "cannot_delete_current_dir", "不能删除当前目录")
    if not os.path.exists(target_path):
        _raise(404, "path_not_found", "文件或文件夹不存在")

    try:
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
            deleted_type = "directory"
        else:
            os.remove(target_path)
            deleted_type = "file"
    except Exception as exc:
        _raise(500, "delete_path_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": path,
        "deleted_type": deleted_type,
        "working_dir": browser_dir,
    }


def get_working_directory(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    return {"working_dir": session.working_dir}


def change_working_directory(manager: MultiBotManager, alias: str, user_id: int, new_path: str) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    current_dir = _get_browser_directory(session)
    path = _resolve_browser_target_path(current_dir, new_path)
    if not _is_windows_drives_virtual_root(path) and not os.path.isdir(path):
        _raise(404, "dir_not_found", f"目录不存在: {path}")

    session.browse_dir = path
    session.persist()
    return {
        "working_dir": _display_browser_directory(session.browse_dir),
        "is_virtual_root": _is_windows_drives_virtual_root(session.browse_dir),
    }


def get_history(manager: MultiBotManager, alias: str, user_id: int, limit: int = 50) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    service = _get_chat_history_service(session)
    return {"items": service.list_history(profile, session, limit=max(1, limit))}


def get_history_delta(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    after_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    items = _get_chat_history_service(session).list_history(profile, session, limit=max(1, limit))
    marker = str(after_id or "")
    if not marker:
        return {"items": items, "reset": False}

    ids = [str(item.get("id") or "") for item in items]
    if marker not in ids:
        return {"items": items, "reset": True}
    return {"items": items[ids.index(marker) + 1:], "reset": False}


def get_history_trace(manager: MultiBotManager, alias: str, user_id: int, message_id: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    service = _get_chat_history_service(session)
    data = service.get_message_trace(profile, session, message_id)
    if data is None:
        _raise(404, "trace_not_found", "未找到对应消息的过程详情")
    return data


def reset_user_session(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    bot_id = resolve_session_bot_id(manager, alias)
    state_path = None
    if profile.bot_mode == "assistant":
        state_path = Path(profile.working_dir) / ".assistant" / "state" / "users" / f"{user_id}.json"

    with sessions_lock:
        session = sessions.get((bot_id, user_id))

    if session is None:
        if profile.bot_mode == "assistant" and (state_path is None or not state_path.exists()):
            return {"reset": reset_session(bot_id, user_id)}
        session = get_session_for_alias(manager, alias, user_id)
    else:
        session = align_session_paths(session, profile.working_dir, profile.bot_mode)

    _get_chat_history_service(session).reset_active_conversation(profile, session)
    removed = reset_session(bot_id, user_id)
    if profile.bot_mode == "assistant" and state_path is not None and state_path.exists():
        home = bootstrap_assistant_home(profile.working_dir)
        removed = clear_assistant_runtime_state(home, user_id) or removed
    return {"reset": removed}


def kill_user_process(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    with session._lock:
        if not session.is_processing or session.process is None:
            return {"killed": False, "message": msg("kill", "no_task")}
        process = session.process
        session.stop_requested = True

    try:
        if process.poll() is None:
            process.terminate()
            return {"killed": True, "message": msg("kill", "killed"), "stop_requested": True}
        return {"killed": False, "message": msg("kill", "already_done")}
    except Exception as exc:
        _raise(500, "kill_failed", msg("kill", "error", error=str(exc)))


def _build_cli_env(cli_type: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    if cli_type == "codex":
        env["CI"] = "true"
    return env


def _prepare_assistant_prompt(
    profile: BotProfile,
    session: UserSession,
    *,
    user_id: int,
    user_text: str,
    cli_type: str,
) -> tuple[Any, dict[str, str], str, bool]:
    assistant_home = bootstrap_assistant_home(profile.working_dir)
    assistant_pre_surface = snapshot_managed_surface(assistant_home)
    compaction_prompt_active = is_compaction_prompt_active(assistant_home)
    sync_result = sync_managed_prompt_files(assistant_home)
    prompt_source_text = user_text
    try:
        index_working_memories(assistant_home)
    except Exception as exc:
        logger.warning("assistant working memory index failed user=%s error=%s", user_id, exc)
    try:
        recall = recall_assistant_memories(assistant_home, user_id=user_id, user_text=user_text)
        if recall.prompt_block:
            prompt_source_text = f"{recall.prompt_block}\n\n{user_text}"
    except Exception as exc:
        logger.warning("assistant memory recall failed user=%s error=%s", user_id, exc)
    compiled_prompt = compile_assistant_prompt(
        prompt_source_text,
        managed_prompt_hash=sync_result.managed_prompt_hash,
        seen_managed_prompt_hash=session.managed_prompt_hash_seen,
    )
    if compiled_prompt.managed_prompt_hash_seen != session.managed_prompt_hash_seen:
        session.managed_prompt_hash_seen = compiled_prompt.managed_prompt_hash_seen
        session.persist()
    return assistant_home, assistant_pre_surface, compiled_prompt.prompt_text, compaction_prompt_active


def _is_dream_request(request: AssistantRunRequest | None) -> bool:
    return bool(request is not None and request.task_mode == "dream")


def _prepare_dream_assistant_prompt(
    manager: MultiBotManager,
    profile: BotProfile,
    session: UserSession,
    request: AssistantRunRequest,
    *,
    user_text: str,
) -> tuple[Any, str, dict[str, Any]]:
    assistant_home = bootstrap_assistant_home(profile.working_dir)
    sync_result = sync_managed_prompt_files(assistant_home)
    context_user_id = request.context_user_id if request.context_user_id is not None else request.user_id
    context_session = get_session_for_alias(manager, profile.alias, context_user_id)
    config = AssistantDreamConfig.from_task_payload(request.task_payload)
    prepared_prompt = prepare_dream_prompt(
        assistant_home,
        profile=profile,
        session=context_session,
        history_service=_get_chat_history_service(context_session),
        config=config,
        visible_text=user_text,
    )
    compiled_prompt = compile_assistant_prompt(
        prepared_prompt.prompt_text,
        managed_prompt_hash=sync_result.managed_prompt_hash,
        seen_managed_prompt_hash=session.managed_prompt_hash_seen,
    )
    if compiled_prompt.managed_prompt_hash_seen != session.managed_prompt_hash_seen:
        session.managed_prompt_hash_seen = compiled_prompt.managed_prompt_hash_seen
        session.persist()
    return assistant_home, compiled_prompt.prompt_text, prepared_prompt.context_stats


def _finalize_dream_execution(
    manager: MultiBotManager,
    request: AssistantRunRequest,
    result: dict[str, Any],
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, request.bot_alias)
    assistant_home = bootstrap_assistant_home(profile.working_dir)
    raw_output = str(result.get("output") or "")
    applied = apply_dream_result(
        assistant_home,
        raw_output=raw_output,
        visible_text=str(request.visible_text or request.text or "").strip(),
        prompt_excerpt=str(result.get("dream_prompt_text") or "").strip()[:400],
        context_stats=dict(result.get("dream_context_stats") or {}),
        run_id=request.run_id,
        job_id=request.job_id,
        scheduled_at=request.scheduled_at,
        context_user_id=request.context_user_id,
        synthetic_user_id=request.user_id,
    )
    finalized = dict(result)
    finalized["output"] = applied.summary
    finalized["summary"] = applied.summary
    finalized["applied_paths"] = list(applied.applied_paths)
    finalized["audit_path"] = applied.audit_path
    if applied.proposal_id:
        finalized["proposal_id"] = applied.proposal_id
    return finalized


def _finalize_assistant_chat_turn(
    assistant_home,
    *,
    user_id: int,
    user_text: str,
    response: str,
    assistant_pre_surface: dict[str, str],
    compaction_prompt_active: bool,
) -> None:
    capture = record_assistant_capture(assistant_home, user_id, user_text, response)
    try:
        write_hot_path_memories(
            assistant_home,
            user_id=user_id,
            user_text=user_text,
            assistant_text=response,
            source_ref=str(capture.get("id") or "chat"),
        )
    except Exception as exc:
        logger.warning("assistant memory hot-path write failed user=%s error=%s", user_id, exc)
    refresh_compaction_state(assistant_home, latest_capture=capture)
    consumed_capture_ids = list_pending_capture_ids(assistant_home) or [capture["id"]]
    sync_managed_prompt_files(assistant_home)
    assistant_post_surface = snapshot_managed_surface(assistant_home)
    compaction_result = finalize_compaction(
        assistant_home,
        before=assistant_pre_surface,
        after=assistant_post_surface,
        consumed_capture_ids=consumed_capture_ids,
        review_prompt_active=compaction_prompt_active,
    )
    if compaction_result in {"changed", "noop"}:
        sync_managed_prompt_files(assistant_home)


def _log_assistant_chat_finalize_failure(task: asyncio.Task[Any], *, user_id: int) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("处理 assistant chat 收尾失败 user=%s error=%s", user_id, exc)


def _schedule_assistant_chat_turn_finalization(
    assistant_home,
    *,
    user_id: int,
    user_text: str,
    response: str,
    assistant_pre_surface: dict[str, str],
    compaction_prompt_active: bool,
) -> None:
    task = asyncio.create_task(
        asyncio.to_thread(
            _finalize_assistant_chat_turn,
            assistant_home,
            user_id=user_id,
            user_text=user_text,
            response=response,
            assistant_pre_surface=assistant_pre_surface,
            compaction_prompt_active=compaction_prompt_active,
        )
    )
    task.add_done_callback(lambda done_task: _log_assistant_chat_finalize_failure(done_task, user_id=user_id))


def _chunk_text(text: str, size: int = 160) -> list[str]:
    cleaned = text or ""
    if not cleaned:
        return []
    return [cleaned[index:index + size] for index in range(0, len(cleaned), size)]


def _prepare_cli_attempt_state(session: UserSession, cli_type: str) -> CliAttemptState:
    with session._lock:
        if cli_type == "codex":
            return CliAttemptState(
                cli_session_id=session.codex_session_id,
                resume_session=bool(session.codex_session_id),
                codex_session_id=session.codex_session_id,
            )
        if cli_type == "claude":
            if not session.claude_session_id:
                session.claude_session_id = str(uuid.uuid4())
                session.claude_session_initialized = False
            return CliAttemptState(
                cli_session_id=session.claude_session_id,
                resume_session=session.claude_session_initialized,
            )
    return CliAttemptState(cli_session_id=None, resume_session=False)


def _clear_invalid_cli_session(session: UserSession, cli_type: str) -> bool:
    with session._lock:
        if cli_type == "codex":
            if session.codex_session_id is None:
                return False
            session.codex_session_id = None
            return True
        if cli_type == "claude":
            changed = session.claude_session_id is not None or session.claude_session_initialized
            session.claude_session_id = None
            session.claude_session_initialized = False
            return changed
    return False


def _extract_codex_stream_preview(raw_output: str) -> Optional[str]:
    preview_text = ""
    current_delta = ""
    fallback_parts: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_codex_json_line(stripped)
        if parsed["error_text"]:
            fallback_parts.append(parsed["error_text"])
            continue

        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            if not stripped.startswith("{"):
                fallback_parts.append(stripped)
            continue

        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type") or "").strip()
        item = event.get("item")
        if not isinstance(item, dict):
            if parsed["delta_text"]:
                preview_text = parsed["delta_text"]
            continue

        item_type = str(item.get("type") or "").strip()
        if item_type not in {"assistant_message", "agent_message"}:
            continue

        if event_type == "item.delta":
            delta_value = item.get("delta")
            text_value = item.get("text")
            chunk = ""
            if isinstance(delta_value, str) and delta_value:
                chunk = delta_value
            elif isinstance(text_value, str) and text_value:
                chunk = text_value
            if chunk:
                current_delta += chunk
                preview_text = current_delta
            continue

        if event_type == "item.completed":
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                current_delta = ""
                preview_text = text_value.strip()
            continue

        if parsed["delta_text"]:
            preview_text = parsed["delta_text"]

    if preview_text.strip():
        return preview_text.strip()

    fallback_text = "\n".join(part for part in fallback_parts if part).strip()
    return fallback_text or None


def _extract_claude_stream_preview(raw_output: str) -> Optional[str]:
    preview_parts: list[str] = []
    fallback_parts: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_claude_stream_json_line(stripped)
        if parsed["delta_text"]:
            preview_parts.append(parsed["delta_text"])
            continue
        if parsed["completed_text"]:
            fallback_parts.append(parsed["completed_text"])
            continue
        if parsed["error_text"]:
            fallback_parts.append(parsed["error_text"])
            continue
        if not stripped.startswith("{"):
            fallback_parts.append(stripped)

    preview_text = "".join(preview_parts).strip()
    if preview_text:
        return preview_text

    fallback_text = "\n".join(part for part in fallback_parts if part).strip()
    return fallback_text or None


def _build_stream_status_event(cli_type: str, elapsed_seconds: int, raw_output: str) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "status",
        "elapsed_seconds": elapsed_seconds,
    }
    if cli_type == "codex":
        preview_text = _extract_codex_stream_preview(raw_output)
        if preview_text:
            event["preview_text"] = preview_text[-800:]
    elif cli_type == "claude":
        preview_text = _extract_claude_stream_preview(raw_output)
        if preview_text:
            event["preview_text"] = preview_text[-800:]
    return event


class _StreamPreviewState:
    def __init__(self, cli_type: str, *, max_raw_chars: int = 256_000):
        self.cli_type = cli_type
        self.max_raw_chars = max(1, int(max_raw_chars))
        self._raw_parts: list[str] = []
        self._raw_size = 0
        self._preview_text = ""
        self._codex_delta = ""

    def consume(self, chunk: str) -> None:
        text = str(chunk or "")
        if not text:
            return
        self._append_raw(text)
        if self.cli_type == "codex":
            self._consume_codex(text)
        elif self.cli_type == "claude":
            self._consume_claude(text)

    def _append_raw(self, text: str) -> None:
        self._raw_parts.append(text)
        self._raw_size += len(text)
        while self._raw_size > self.max_raw_chars and self._raw_parts:
            extra = self._raw_size - self.max_raw_chars
            first = self._raw_parts[0]
            if len(first) <= extra:
                self._raw_size -= len(first)
                self._raw_parts.pop(0)
                continue
            self._raw_parts[0] = first[extra:]
            self._raw_size -= extra
            break

    def _consume_codex(self, text: str) -> None:
        fallback_parts: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parsed = parse_codex_json_line(stripped)
            if parsed["error_text"]:
                fallback_parts.append(parsed["error_text"])
                continue

            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                if not stripped.startswith("{"):
                    fallback_parts.append(stripped)
                continue

            if not isinstance(event, dict):
                continue

            event_type = str(event.get("type") or "").strip()
            item = event.get("item")
            if isinstance(item, dict) and str(item.get("type") or "").strip() in {"assistant_message", "agent_message"}:
                delta_value = item.get("delta")
                text_value = item.get("text")
                if event_type == "item.delta":
                    chunk = delta_value if isinstance(delta_value, str) and delta_value else text_value
                    if isinstance(chunk, str) and chunk:
                        self._codex_delta += chunk
                        self._preview_text = self._codex_delta
                    continue
                if event_type == "item.completed" and isinstance(text_value, str) and text_value.strip():
                    self._codex_delta = ""
                    self._preview_text = text_value.strip()
                    continue

            if parsed["delta_text"]:
                self._preview_text = parsed["delta_text"]

        if not self._preview_text and fallback_parts:
            self._preview_text = "\n".join(part for part in fallback_parts if part).strip()

    def _consume_claude(self, text: str) -> None:
        preview_parts: list[str] = []
        fallback_parts: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parsed = parse_claude_stream_json_line(stripped)
            if parsed["delta_text"]:
                preview_parts.append(parsed["delta_text"])
                continue
            if parsed["completed_text"]:
                fallback_parts.append(parsed["completed_text"])
                continue
            if parsed["error_text"]:
                fallback_parts.append(parsed["error_text"])
                continue
            if not stripped.startswith("{"):
                fallback_parts.append(stripped)
        if preview_parts:
            self._preview_text += "".join(preview_parts)
        elif not self._preview_text and fallback_parts:
            self._preview_text = "\n".join(part for part in fallback_parts if part).strip()

    def status_event(self, *, elapsed_seconds: int) -> dict[str, Any]:
        event: dict[str, Any] = {"type": "status", "elapsed_seconds": elapsed_seconds}
        if self._preview_text.strip():
            event["preview_text"] = self._preview_text.strip()[-800:]
        return event

    def raw_output_for_parse(self) -> str:
        return "".join(self._raw_parts)


def _extract_final_codex_completed_message(raw_output: str) -> Optional[str]:
    last_completed: Optional[str] = None
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_codex_json_line(stripped)
        completed_text = str(parsed.get("completed_text") or "").strip()
        if completed_text:
            last_completed = completed_text
    return last_completed


def _load_codex_json_event(line: str) -> dict[str, Any]:
    try:
        event: Any = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return event if isinstance(event, dict) else {}


def _codex_line_allows_quiet_finish(line: str, completed_text: str) -> bool:
    event = _load_codex_json_event(line)
    event_type = str(event.get("type") or "").strip()
    if event_type == "turn.completed":
        return True

    payload: Any = None
    if event_type == "event_msg":
        payload = event.get("payload")
    elif event_type == "response_item":
        payload = event.get("item")

    if not isinstance(payload, dict):
        return False

    payload_type = str(payload.get("type") or "").strip()
    if event_type == "event_msg" and payload_type == "agent_message" and completed_text:
        phase = str(payload.get("phase") or "").strip().lower()
        return phase not in {"commentary", "progress", "partial"}
    if event_type == "response_item" and payload_type == "message":
        phase = str(payload.get("phase") or "").strip().lower()
        return bool(completed_text and phase in {"final", "final_answer"})
    return False


def _advance_codex_done_candidate(
    line: str,
    *,
    thread_id: Optional[str],
    candidate_text: Optional[str],
    candidate_seen_at: Optional[float],
    now: float,
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    stripped = line.strip()
    if not stripped:
        return thread_id, candidate_text, candidate_seen_at

    parsed = parse_codex_json_line(stripped)
    next_thread_id = thread_id
    if parsed["thread_id"]:
        next_thread_id = parsed["thread_id"]

    completed_text = str(parsed.get("completed_text") or "").strip()
    if completed_text:
        candidate_text = completed_text

    if _codex_line_allows_quiet_finish(stripped, completed_text):
        return next_thread_id, candidate_text, now

    return next_thread_id, candidate_text, candidate_seen_at


def _trace_event_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(event.get("kind") or ""),
        str(event.get("raw_type") or ""),
        str(event.get("call_id") or ""),
        str(event.get("summary") or ""),
    )


def _merge_trace_events(*sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in sources:
        for item in source or []:
            if not isinstance(item, dict):
                continue
            key = _trace_event_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))
    return merged


def _build_terminal_trace(
    *,
    live_trace: list[dict[str, Any]],
    stop_requested: bool,
    returncode: int,
) -> list[dict[str, Any]]:
    trace = _merge_trace_events(live_trace)
    if stop_requested:
        return _merge_trace_events(
            trace,
            [{"kind": "cancelled", "source": "runtime", "summary": "用户终止输出"}],
        )
    if isinstance(returncode, int) and returncode not in (0,):
        return _merge_trace_events(
            trace,
            [{"kind": "error", "source": "runtime", "summary": f"命令退出码 {returncode}"}],
        )
    return trace


async def _reconcile_native_trace_before_completion(
    service: ChatHistoryService,
    turn_handle,
    *,
    profile: BotProfile,
    session: UserSession,
    user_text: str,
    assistant_text: str,
    completion_state: str,
    native_session_id: str | None,
    poll_attempts: int = 4,
    poll_interval_seconds: float = 0.1,
) -> None:
    if completion_state != "completed":
        return
    normalized_session_id = str(native_session_id or "").strip()
    if not normalized_session_id:
        return

    attempts = max(1, int(poll_attempts))
    for attempt_index in range(attempts):
        if service.reconcile_turn_trace(
            turn_handle,
            profile=profile,
            session=session,
            user_text=user_text,
            assistant_text=assistant_text,
            native_session_id=normalized_session_id,
        ):
            return
        if attempt_index + 1 >= attempts:
            return
        await asyncio.sleep(poll_interval_seconds)


def _resolve_completion_state(
    session: UserSession,
    *,
    returncode: int,
    response_text: str,
) -> str:
    with session._lock:
        stop_requested = bool(session.stop_requested)
    has_response = bool(str(response_text or "").strip())
    if stop_requested and (not isinstance(returncode, int) or returncode != 0):
        return "cancelled"
    if stop_requested and returncode == 0 and has_response:
        return "completed"
    if stop_requested:
        return "cancelled"
    if isinstance(returncode, int) and returncode not in (0,):
        return "error"
    return "completed"


def _calculate_elapsed_seconds(loop: asyncio.AbstractEventLoop, started_at: float) -> int:
    return max(0, int(loop.time() - started_at))


def _wait_for_process_exit_sync(process: subprocess.Popen, timeout: float) -> Optional[int]:
    try:
        return process.wait(timeout=timeout)
    except Exception:
        return None


def _resolve_process_returncode(process: subprocess.Popen | None, waited_returncode: Any = None) -> int:
    if isinstance(waited_returncode, int):
        return waited_returncode
    candidate = getattr(process, "returncode", None) if process is not None else None
    if isinstance(candidate, int):
        return candidate
    if process is None:
        return -1
    try:
        polled = process.poll()
    except Exception:
        return -1
    return polled if isinstance(polled, int) else -1


def _terminate_process_sync(process: subprocess.Popen, kill_timeout: float = 2.0) -> None:
    try:
        if process.poll() is not None:
            pass
        else:
            terminate_process_tree_sync(process)
    except Exception:
        pass


async def _communicate_process(process: subprocess.Popen) -> tuple[str, int]:
    stdout = getattr(process, "stdout", None)
    if stdout is None or not hasattr(stdout, "readline"):
        output, _ = process.communicate()
        return str(output or ""), getattr(process, "returncode", None) or process.wait() or 0

    output_queue: queue.Queue[Any] = queue.Queue()
    reader_done = threading.Event()
    chunks: list[str] = []

    def read_stdout() -> None:
        try:
            stdout = process.stdout
            if stdout is None:
                return
            while True:
                line = stdout.readline()
                if line:
                    output_queue.put(line)
                    continue
                if process.poll() is not None:
                    remaining = stdout.read()
                    if remaining:
                        output_queue.put(remaining)
                    break
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - defensive
            output_queue.put(exc)
        finally:
            reader_done.set()

    threading.Thread(target=read_stdout, daemon=True).start()

    try:
        while not reader_done.is_set() or not output_queue.empty():
            drained = False
            while True:
                try:
                    item = output_queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                if isinstance(item, Exception):
                    raise item
                chunks.append(str(item))

            if not drained:
                await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        _terminate_process_sync(process)
        raise

    return "".join(chunks), process.poll() or 0


async def _communicate_codex_process(process: subprocess.Popen) -> tuple[str, Optional[str], int]:
    stdout = getattr(process, "stdout", None)
    if stdout is None or not hasattr(stdout, "readline"):
        raw_output, returncode = await _communicate_process(process)
        final_text, thread_id = parse_codex_json_output(raw_output)
        if not final_text:
            final_text = msg("chat", "no_output")
        return final_text, thread_id, returncode

    loop = asyncio.get_running_loop()
    output_queue: queue.Queue[Any] = queue.Queue()
    reader_done = threading.Event()
    chunks: list[str] = []
    thread_id: Optional[str] = None
    candidate_text: Optional[str] = None
    candidate_seen_at: Optional[float] = None
    done_terminate_started_at: Optional[float] = None
    done_force_killed = False

    def read_stdout() -> None:
        try:
            if process.stdout is None:
                return
            stdout = process.stdout
            while True:
                line = stdout.readline()
                if line:
                    output_queue.put(line)
                    continue
                if process.poll() is not None:
                    remaining = stdout.read()
                    if remaining:
                        output_queue.put(remaining)
                    break
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - defensive
            output_queue.put(exc)
        finally:
            reader_done.set()

    threading.Thread(target=read_stdout, daemon=True).start()

    try:
        while not reader_done.is_set() or not output_queue.empty():
            drained = False
            while True:
                try:
                    item = output_queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                if isinstance(item, Exception):
                    raise item
                chunk = str(item)
                chunks.append(chunk)
                now = loop.time()
                for line in chunk.splitlines():
                    thread_id, candidate_text, candidate_seen_at = _advance_codex_done_candidate(
                        line,
                        thread_id=thread_id,
                        candidate_text=candidate_text,
                        candidate_seen_at=candidate_seen_at,
                        now=now,
                    )

            now = loop.time()
            if (
                candidate_seen_at is not None
                and done_terminate_started_at is None
                and process.poll() is None
                and (now - candidate_seen_at) >= CODEX_DONE_QUIET_SECONDS
            ):
                done_terminate_started_at = now
                process.terminate()
            elif (
                done_terminate_started_at is not None
                and not done_force_killed
                and process.poll() is None
                and (now - done_terminate_started_at) >= 1.0
            ):
                done_force_killed = True
                await loop.run_in_executor(None, _terminate_process_sync, process)

            if not drained:
                await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        _terminate_process_sync(process)
        raise

    waited_returncode = await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
    returncode = _resolve_process_returncode(process, waited_returncode)
    if done_terminate_started_at is not None:
        returncode = 0

    raw_output = "".join(chunks)
    final_text, parsed_thread_id = parse_codex_json_output(raw_output)
    final_text = candidate_text or _extract_final_codex_completed_message(raw_output) or final_text
    if not final_text:
        final_text = msg("chat", "no_output")
    return final_text, thread_id or parsed_thread_id, returncode


async def _communicate_claude_process(
    process: subprocess.Popen,
    *,
    done_session=None,
) -> tuple[str, Optional[str], int]:
    if done_session is None or not getattr(done_session, "enabled", False):
        raw_output, returncode = await _communicate_process(process)
        final_text, session_id = parse_claude_stream_json_output(raw_output)
        if not final_text:
            final_text = msg("chat", "no_output")
        return final_text, session_id, returncode

    loop = asyncio.get_running_loop()
    output_queue: queue.Queue[Any] = queue.Queue()
    reader_done = threading.Event()
    collector = ClaudeDoneCollector(done_session)
    done_terminate_started_at: Optional[float] = None
    done_force_killed = False

    def read_stdout() -> None:
        try:
            if process.stdout is None:
                return
            stdout = process.stdout
            while True:
                line = stdout.readline()
                if line:
                    output_queue.put(line)
                    continue
                if process.poll() is not None:
                    remaining = stdout.read()
                    if remaining:
                        output_queue.put(remaining)
                    break
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - defensive
            output_queue.put(exc)
        finally:
            reader_done.set()

    reader_thread = threading.Thread(target=read_stdout, daemon=True)
    reader_thread.start()

    while not reader_done.is_set() or not output_queue.empty():
        now = loop.time()
        drained = False
        while True:
            try:
                item = output_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            if isinstance(item, Exception):
                raise item
            collector.consume_chunk(str(item), now=now)

        if (
            collector.detector is not None
            and done_terminate_started_at is None
            and collector.detector.poll(now=now)
            and process.poll() is None
        ):
            done_terminate_started_at = now
            process.terminate()
        elif (
            done_terminate_started_at is not None
            and not done_force_killed
            and process.poll() is None
            and (now - done_terminate_started_at) >= 1.0
        ):
            done_force_killed = True
            await loop.run_in_executor(None, _terminate_process_sync, process)

        if not drained:
            await asyncio.sleep(0.1)

    waited_returncode = await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
    returncode = _resolve_process_returncode(process, waited_returncode)
    if done_terminate_started_at is not None:
        returncode = 0

    final_text = collector.final_text
    if not final_text:
        final_text = msg("chat", "no_output")
    return final_text, collector.session_id, returncode


async def _stream_cli_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> AsyncIterator[dict[str, Any]]:
    profile = get_profile_or_raise(manager, alias)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    session = get_session_for_alias(manager, alias, user_id)
    text = (user_text or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    prompt_text = text
    assistant_home = None
    assistant_pre_surface: dict[str, str] = {}
    compaction_prompt_active = False

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    if profile.bot_mode == "assistant":
        assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active = _prepare_assistant_prompt(
            profile,
            session,
            user_id=user_id,
            user_text=text,
            cli_type=cli_type,
        )

    done_session = None
    if cli_type == "claude":
        done_session = build_claude_done_session(prompt_text, cli_type=cli_type)
        prompt_text = done_session.prompt_text

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.is_processing = True

    loop: asyncio.AbstractEventLoop | None = None
    try:
        session.touch()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        session_id_changed = False
        meta_sent = False
        max_attempts = 2 if cli_type == "claude" else 1
        service = _get_chat_history_service(session)
        turn_handle = service.start_turn(
            profile=profile,
            session=session,
            user_text=text,
            native_provider=cli_type,
            assistant_home=str(assistant_home.root) if assistant_home is not None else None,
            managed_prompt_hash=session.managed_prompt_hash_seen,
            prompt_surface_version="v1" if assistant_home is not None else None,
        )

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude")),
                    params_config=profile.cli_params,
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=session.working_dir,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                    **build_hidden_process_kwargs(),
                )
            except FileNotFoundError:
                _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(prompt_text + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    process.wait()
                    _raise(500, "cli_write_failed", msg("chat", "cli_failed") + f": {exc}")

            with session._lock:
                session.process = process

            if not meta_sent:
                yield {
                    "type": "meta",
                    "alias": alias,
                    "cli_type": cli_type,
                    "working_dir": session.working_dir,
                    "resume_session": attempt.resume_session,
                }
                meta_sent = True

            output_queue: queue.Queue[Any] = queue.Queue()
            reader_done = threading.Event()
            preview_state = _StreamPreviewState(cli_type)
            thread_id: Optional[str] = None
            last_status_signature: tuple[int, Optional[str]] | None = None
            claude_collector = ClaudeDoneCollector(done_session) if done_session and done_session.enabled else None
            done_terminate_started_at: Optional[float] = None
            done_force_killed = False
            codex_done_candidate: Optional[str] = None
            codex_done_seen_at: Optional[float] = None
            trace_state = create_stream_trace_state(cli_type)
            live_trace_events: list[dict[str, Any]] = []
            latest_preview_text = ""

            def read_stdout() -> None:
                try:
                    if process.stdout is None:
                        return
                    stdout = process.stdout
                    while True:
                        line = stdout.readline()
                        if line:
                            output_queue.put(line)
                            continue
                        if process.poll() is not None:
                            remaining = stdout.read()
                            if remaining:
                                output_queue.put(remaining)
                            break
                        time.sleep(0.05)
                except Exception as exc:  # pragma: no cover - defensive
                    output_queue.put(exc)
                finally:
                    reader_done.set()

            threading.Thread(target=read_stdout, daemon=True).start()

            try:
                while not reader_done.is_set() or not output_queue.empty():
                    drained = False
                    while True:
                        try:
                            item = output_queue.get_nowait()
                        except queue.Empty:
                            break
                        drained = True
                        if isinstance(item, Exception):
                            raise item

                        text_chunk = str(item)
                        preview_state.consume(text_chunk)
                        for trace_event in consume_stream_trace_chunk(cli_type, text_chunk, trace_state):
                            live_trace_events.append(trace_event)
                            service.append_trace_event(turn_handle, trace_event)
                            yield {"type": "trace", "event": trace_event}

                        if cli_type == "codex":
                            now = loop.time()
                            for line in text_chunk.splitlines():
                                thread_id, codex_done_candidate, codex_done_seen_at = _advance_codex_done_candidate(
                                    line,
                                    thread_id=thread_id,
                                    candidate_text=codex_done_candidate,
                                    candidate_seen_at=codex_done_seen_at,
                                    now=now,
                                )
                        elif claude_collector is not None:
                            claude_collector.consume_chunk(text_chunk, now=loop.time())

                    with session._lock:
                        stop_requested = bool(session.stop_requested)

                    if (
                        stop_requested
                        and done_terminate_started_at is None
                        and process.poll() is None
                    ):
                        done_terminate_started_at = loop.time()
                        process.terminate()
                    elif (
                        claude_collector is not None
                        and claude_collector.detector is not None
                        and done_terminate_started_at is None
                        and claude_collector.detector.poll(now=loop.time())
                        and process.poll() is None
                    ):
                        done_terminate_started_at = loop.time()
                        process.terminate()
                    elif (
                        cli_type == "codex"
                        and codex_done_seen_at is not None
                        and done_terminate_started_at is None
                        and process.poll() is None
                        and (loop.time() - codex_done_seen_at) >= CODEX_DONE_QUIET_SECONDS
                    ):
                        done_terminate_started_at = loop.time()
                        process.terminate()
                    elif (
                        done_terminate_started_at is not None
                        and not done_force_killed
                        and process.poll() is None
                        and (loop.time() - done_terminate_started_at) >= 1.0
                    ):
                        done_force_killed = True
                        await loop.run_in_executor(None, _terminate_process_sync, process)

                    if claude_collector is not None:
                        status_event = {
                            "type": "status",
                            "elapsed_seconds": int(loop.time() - started_at),
                        }
                        preview_text = claude_collector.preview_text
                        if preview_text:
                            status_event["preview_text"] = preview_text[-800:]
                    else:
                        status_event = preview_state.status_event(elapsed_seconds=int(loop.time() - started_at))
                    status_signature = (
                        int(status_event.get("elapsed_seconds", 0)),
                        status_event.get("preview_text"),
                    )
                    if status_signature != last_status_signature and (
                        status_signature[0] > 0 or status_signature[1]
                    ):
                        preview_text = str(status_event.get("preview_text") or "")
                        if preview_text:
                            latest_preview_text = preview_text
                            service.replace_assistant_preview(turn_handle, preview_text)
                        yield status_event
                        last_status_signature = status_signature

                    if not drained:
                        await asyncio.sleep(0.1)

                waited_returncode = await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
                returncode = _resolve_process_returncode(process, waited_returncode)
                if done_terminate_started_at is not None:
                    returncode = 0
            except asyncio.CancelledError:
                if process.poll() is None:
                    await loop.run_in_executor(None, _terminate_process_sync, process)
                raise
            finally:
                with session._lock:
                    session.process = None

            raw_output = preview_state.raw_output_for_parse()
            if cli_type == "codex":
                response, parsed_thread_id = parse_codex_json_output(raw_output)
                thread_id = thread_id or parsed_thread_id
                response = codex_done_candidate or _extract_final_codex_completed_message(raw_output) or response
            elif cli_type == "claude":
                if claude_collector is not None:
                    response = claude_collector.final_text or ""
                else:
                    response, _ = parse_claude_stream_json_output(raw_output)
            else:
                response = raw_output.strip()

            response = response or msg("chat", "no_output")

            if (
                cli_type == "claude"
                and attempt.resume_session
                and should_reset_claude_session(response, returncode)
                and attempt_index + 1 < max_attempts
            ):
                if _clear_invalid_cli_session(session, cli_type):
                    session_id_changed = True
                continue

            if cli_type == "codex":
                with session._lock:
                    if thread_id:
                        if session.codex_session_id != thread_id:
                            session.codex_session_id = thread_id
                            session_id_changed = True
                    elif should_reset_codex_session(attempt.codex_session_id, response, returncode):
                        if session.codex_session_id is not None:
                            session.codex_session_id = None
                            session_id_changed = True
            elif cli_type == "claude":
                with session._lock:
                    if should_mark_claude_session_initialized(response, returncode):
                        if not session.claude_session_initialized:
                            session.claude_session_initialized = True
                            session_id_changed = True
                    elif should_reset_claude_session(response, returncode):
                        if session.claude_session_id is not None or session.claude_session_initialized:
                            session.claude_session_id = None
                            session.claude_session_initialized = False
                            session_id_changed = True

            if session_id_changed:
                session.persist()
                session_id_changed = False

            elapsed_seconds = _calculate_elapsed_seconds(loop, started_at)
            completion_state = _resolve_completion_state(
                session,
                returncode=returncode,
                response_text=response,
            )
            with session._lock:
                stop_requested = bool(session.stop_requested)
            final_trace = _build_terminal_trace(
                live_trace=live_trace_events,
                stop_requested=stop_requested,
                returncode=returncode,
            )
            for trace_event in final_trace[len(live_trace_events):]:
                service.append_trace_event(turn_handle, trace_event)
            native_session_id = session.codex_session_id if cli_type == "codex" else session.claude_session_id
            await _reconcile_native_trace_before_completion(
                service,
                turn_handle,
                profile=profile,
                session=session,
                user_text=text,
                assistant_text=response,
                completion_state=completion_state,
                native_session_id=native_session_id,
            )
            fallback_output = response if completion_state == "completed" else (latest_preview_text or response)
            done_message = service.complete_turn(
                turn_handle,
                completion_state=completion_state,
                content=fallback_output,
                native_session_id=native_session_id,
                error_code=None if completion_state == "completed" else completion_state,
                error_message=None if completion_state == "completed" else response,
            )
            if assistant_home is not None:
                _schedule_assistant_chat_turn_finalization(
                    assistant_home,
                    user_id=user_id,
                    user_text=text,
                    response=str(done_message.get("content") or response),
                    assistant_pre_surface=assistant_pre_surface,
                    compaction_prompt_active=compaction_prompt_active,
                )
            with session._lock:
                session.is_processing = False
            done_event = {
                "type": "done",
                "output": str(done_message.get("content") or response),
                "message": done_message,
                "elapsed_seconds": elapsed_seconds,
                "returncode": returncode,
                "session": build_session_snapshot(profile, session),
            }
            yield done_event
            return
    finally:
        lingering_process: subprocess.Popen | None = None
        with session._lock:
            lingering_process = session.process
            session.process = None
            session.is_processing = False
        if lingering_process is not None and lingering_process.poll() is None:
            if loop is not None:
                await loop.run_in_executor(None, _terminate_process_sync, lingering_process)
            else:
                _terminate_process_sync(lingering_process)


async def run_cli_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    session = get_session_for_alias(manager, alias, user_id)
    visible_input = request.visible_text if request is not None and request.visible_text is not None else user_text
    text = (visible_input or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    prompt_text = text
    assistant_home = None
    assistant_pre_surface: dict[str, str] = {}
    compaction_prompt_active = False
    finalize_assistant_turn = True
    dream_context_stats: dict[str, Any] | None = None
    dream_prompt_text = ""

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    if profile.bot_mode == "assistant":
        if _is_dream_request(request):
            assert request is not None
            assistant_home, prompt_text, dream_context_stats = _prepare_dream_assistant_prompt(
                manager,
                profile,
                session,
                request,
                user_text=text,
            )
            dream_prompt_text = prompt_text
            finalize_assistant_turn = False
        else:
            assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active = _prepare_assistant_prompt(
                profile,
                session,
                user_id=user_id,
                user_text=text,
                cli_type=cli_type,
            )

    done_session = None
    if cli_type == "claude":
        done_session = build_claude_done_session(prompt_text, cli_type=cli_type)
        prompt_text = done_session.prompt_text

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.is_processing = True

    try:
        session.touch()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        session_id_changed = False
        max_attempts = 2 if cli_type == "claude" else 1
        service = _get_chat_history_service(session)
        turn_handle = service.start_turn(
            profile=profile,
            session=session,
            user_text=text,
            native_provider=cli_type,
            assistant_home=str(assistant_home.root) if assistant_home is not None else None,
            managed_prompt_hash=session.managed_prompt_hash_seen,
            prompt_surface_version="v1" if assistant_home is not None else None,
        )

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude")),
                    params_config=profile.cli_params,
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=session.working_dir,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                    **build_hidden_process_kwargs(),
                )
            except FileNotFoundError:
                _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(prompt_text + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    process.wait()
                    _raise(500, "cli_write_failed", msg("chat", "cli_failed") + f": {exc}")

            with session._lock:
                session.process = process

            try:
                if cli_type == "codex":
                    response, thread_id, returncode = await _communicate_codex_process(process)
                elif cli_type == "claude":
                    response, _, returncode = await _communicate_claude_process(
                        process,
                        done_session=done_session,
                    )
                else:
                    response, returncode = await _communicate_process(process)
                    response = response.strip() or msg("chat", "no_output")
            finally:
                with session._lock:
                    session.process = None

            if (
                cli_type == "claude"
                and attempt.resume_session
                and should_reset_claude_session(response, returncode)
                and attempt_index + 1 < max_attempts
            ):
                if _clear_invalid_cli_session(session, cli_type):
                    session_id_changed = True
                continue

            if cli_type == "codex":
                with session._lock:
                    if thread_id:
                        if session.codex_session_id != thread_id:
                            session.codex_session_id = thread_id
                            session_id_changed = True
                    elif should_reset_codex_session(attempt.codex_session_id, response, returncode):
                        if session.codex_session_id is not None:
                            session.codex_session_id = None
                            session_id_changed = True
            elif cli_type == "claude":
                with session._lock:
                    if should_mark_claude_session_initialized(response, returncode):
                        if not session.claude_session_initialized:
                            session.claude_session_initialized = True
                            session_id_changed = True
                    elif should_reset_claude_session(response, returncode):
                        if session.claude_session_id is not None or session.claude_session_initialized:
                            session.claude_session_id = None
                            session.claude_session_initialized = False
                            session_id_changed = True

            if session_id_changed:
                session.persist()

            elapsed_seconds = _calculate_elapsed_seconds(loop, started_at)
            completion_state = _resolve_completion_state(
                session,
                returncode=returncode,
                response_text=response,
            )
            with session._lock:
                stop_requested = bool(session.stop_requested)
            terminal_trace = _build_terminal_trace(
                live_trace=[],
                stop_requested=stop_requested,
                returncode=returncode,
            )
            for trace_event in terminal_trace:
                service.append_trace_event(turn_handle, trace_event)
            native_session_id = session.codex_session_id if cli_type == "codex" else session.claude_session_id
            await _reconcile_native_trace_before_completion(
                service,
                turn_handle,
                profile=profile,
                session=session,
                user_text=text,
                assistant_text=response,
                completion_state=completion_state,
                native_session_id=native_session_id,
            )
            done_message = service.complete_turn(
                turn_handle,
                content=response if completion_state == "completed" else (response or msg("chat", "no_output")),
                completion_state=completion_state,
                native_session_id=native_session_id,
                error_code=None if completion_state == "completed" else completion_state,
                error_message=None if completion_state == "completed" else response,
            )
            if assistant_home is not None and finalize_assistant_turn:
                try:
                    _finalize_assistant_chat_turn(
                        assistant_home,
                        user_id=user_id,
                        user_text=text,
                        response=str(done_message.get("content") or response),
                        assistant_pre_surface=assistant_pre_surface,
                        compaction_prompt_active=compaction_prompt_active,
                    )
                except Exception as exc:
                    logger.warning("处理 assistant chat 收尾失败 user=%s error=%s", user_id, exc)
            with session._lock:
                session.is_processing = False
            response_payload = {
                "output": str(done_message.get("content") or response),
                "message": done_message,
                "elapsed_seconds": elapsed_seconds,
                "returncode": returncode,
                "session": build_session_snapshot(profile, session),
            }
            if dream_context_stats is not None:
                response_payload["dream_context_stats"] = dream_context_stats
                response_payload["dream_prompt_text"] = dream_prompt_text
            return response_payload
    finally:
        with session._lock:
            session.process = None
            session.is_processing = False


async def run_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode == "assistant":
        if manager.assistant_runtime is None:
            _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
        request = build_assistant_run_request(alias, user_id, user_text)
        return await manager.assistant_runtime.submit_interactive(request)
    if _supports_cli_runtime(profile):
        return await run_cli_chat(manager, alias, user_id, user_text)
    _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")


async def stream_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> AsyncIterator[dict[str, Any]]:
    try:
        profile = get_profile_or_raise(manager, alias)
        if profile.bot_mode == "assistant":
            if manager.assistant_runtime is None:
                _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
            request = build_assistant_run_request(alias, user_id, user_text)
            async for event in manager.assistant_runtime.stream_interactive(request):
                yield event
            return
        if _supports_cli_runtime(profile):
            async for event in _stream_cli_chat(manager, alias, user_id, user_text):
                yield event
            return
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")
    except WebApiError as exc:
        yield {"type": "error", "code": exc.code, "message": exc.message}
    except Exception as exc:  # pragma: no cover - defensive
        yield {"type": "error", "code": "internal_error", "message": str(exc)}


async def execute_shell_command(manager: MultiBotManager, alias: str, user_id: int, command: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持执行 Shell 命令")

    cmd = (command or "").strip()
    if not cmd:
        _raise(400, "empty_command", msg("shell", "usage"))
    if is_dangerous_command(cmd):
        _raise(400, "dangerous_command", msg("shell", "dangerous"))

    session = get_session_for_alias(manager, alias, user_id)

    def run_sync() -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=session.working_dir,
            timeout=60,
        )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, run_sync)
    except subprocess.TimeoutExpired:
        _raise(408, "shell_timeout", "命令执行超时 (60秒)")
    except Exception as exc:
        _raise(500, "shell_failed", str(exc))

    output = strip_ansi_escape(result.stdout or "")
    stderr = strip_ansi_escape(result.stderr or "")
    if stderr:
        output += f"\n\n[stderr]\n{stderr}"
    output = output or msg("shell", "no_output")
    return {
        "command": cmd,
        "output": output,
        "returncode": result.returncode,
        "working_dir": session.working_dir,
    }


def build_assistant_run_request(alias: str, user_id: int, user_text: str) -> AssistantRunRequest:
    return AssistantRunRequest(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        source="web",
        bot_alias=alias,
        user_id=user_id,
        text=user_text,
        interactive=True,
        visible_text=user_text,
    )


async def execute_assistant_run_request(manager: MultiBotManager, request: AssistantRunRequest) -> dict[str, Any]:
    result = await run_cli_chat(
        manager,
        request.bot_alias,
        request.user_id,
        request.text,
        request=request,
    )
    if _is_dream_request(request):
        return _finalize_dream_execution(manager, request, result)
    return result


async def stream_assistant_run_request(
    manager: MultiBotManager,
    request: AssistantRunRequest,
) -> AsyncIterator[dict[str, Any]]:
    async for event in _stream_cli_chat(manager, request.bot_alias, request.user_id, request.text):
        yield event


def save_chat_attachment(manager: MultiBotManager, alias: str, user_id: int, filename: str, data: bytes) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    if not data:
        _raise(400, "empty_file", "文件内容不能为空")
    if len(data) > UPLOAD_MAX_FILE_SIZE_BYTES:
        _raise(400, "file_too_large", msg("upload", "file_too_large"))

    attachment_dir = _build_chat_attachment_dir(alias, user_id)
    os.makedirs(attachment_dir, exist_ok=True)
    file_path, stored_filename = _resolve_unique_upload_path(attachment_dir, filename)
    with open(file_path, "wb") as handle:
        handle.write(data)
    return {
        "filename": stored_filename,
        "saved_path": file_path,
        "size": len(data),
    }


def delete_chat_attachment(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    saved_path: str,
) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    target_path = _resolve_chat_attachment_path(alias, user_id, saved_path)

    if target_path.exists() and not target_path.is_file():
        _raise(400, "invalid_saved_path", "附件路径必须指向文件")

    existed = target_path.exists()
    if existed:
        try:
            target_path.unlink()
        except FileNotFoundError:
            existed = False
        except Exception as exc:
            _raise(500, "delete_attachment_failed", str(exc))

    return {
        "filename": target_path.name,
        "saved_path": str(target_path),
        "existed": existed,
        "deleted": existed,
    }


def save_uploaded_file(manager: MultiBotManager, alias: str, user_id: int, filename: str, data: bytes) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    if not data:
        _raise(400, "empty_file", "文件内容不能为空")
    if len(data) > UPLOAD_MAX_FILE_SIZE_BYTES:
        _raise(400, "file_too_large", msg("upload", "file_too_large"))

    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    file_path = _resolve_safe_path(browser_dir, filename)
    with open(file_path, "wb") as handle:
        handle.write(data)
    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "filename": filename,
        "saved_path": file_path,
        "size": len(data),
    }


def write_file_content(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str,
    content: str,
    *,
    expected_mtime_ns: int | None = None,
) -> dict[str, Any]:
    _ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    file_path = _resolve_safe_write_path(browser_dir, path)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")

    current_mtime_ns = _stat_file_version(file_path)
    if expected_mtime_ns is not None and int(expected_mtime_ns) != current_mtime_ns:
        _raise(409, "file_version_conflict", "文件已被修改，请重新打开后再试")

    _ensure_editable_text_file(file_path)

    try:
        _write_text_file_atomically(file_path, content)
        next_mtime_ns = _ensure_file_version_advanced(file_path, current_mtime_ns)
    except Exception as exc:
        _raise(500, "write_file_failed", str(exc))

    _invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": path,
        "file_size_bytes": os.path.getsize(file_path),
        "last_modified_ns": next_mtime_ns,
    }


def get_file_metadata(manager: MultiBotManager, alias: str, user_id: int, filename: str) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    file_path = _resolve_safe_path(browser_dir, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")
    return {
        "filename": filename,
        "path": file_path,
        "size": os.path.getsize(file_path),
        "content_type": "application/octet-stream",
    }


def read_file_content(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    mode: str = "cat",
    lines: int = 20,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    file_path = _resolve_safe_path(browser_dir, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")

    file_size = os.path.getsize(file_path)
    raster_preview = _build_raster_image_preview(
        filename=filename,
        file_path=file_path,
        working_dir=browser_dir,
        mode=mode,
        file_size=file_size,
    )
    if raster_preview is not None:
        return raster_preview

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            if mode == "head":
                content_lines = []
                truncated = False
                for index, line in enumerate(handle):
                    if index >= lines:
                        truncated = True
                        break
                    content_lines.append(line.rstrip("\n"))
                content = "\n".join(content_lines)
                is_full_content = not truncated
            else:
                content = handle.read()
                is_full_content = True
    except UnicodeDecodeError:
        _raise(400, "unsupported_encoding", "文件不是文本文件或编码不支持")
    except Exception as exc:
        _raise(500, "read_file_failed", str(exc))

    return {
        "filename": filename,
        "mode": mode,
        "content": content,
        "working_dir": browser_dir,
        "file_size_bytes": file_size,
        "is_full_content": is_full_content,
        "last_modified_ns": _stat_file_version(file_path),
    }


def _build_raster_image_preview(
    *,
    filename: str,
    file_path: str,
    working_dir: str,
    mode: str,
    file_size: int,
) -> dict[str, Any] | None:
    content_type = _RASTER_IMAGE_CONTENT_TYPES.get(Path(filename).suffix.lower())
    if not content_type:
        return None

    return {
        "filename": filename,
        "mode": mode,
        "content": "",
        "preview_kind": "image",
        "content_type": content_type,
        "content_base64": base64.b64encode(Path(file_path).read_bytes()).decode("ascii"),
        "working_dir": working_dir,
        "file_size_bytes": file_size,
        "is_full_content": True,
        "last_modified_ns": _stat_file_version(file_path),
    }


def _get_system_scripts_dir(manager: MultiBotManager, alias: str) -> Path:
    profile = get_profile_or_raise(manager, alias)
    return get_scripts_dir(profile.working_dir)


def list_system_scripts(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    del user_id
    items = []
    for script_name, display_name, description, path in list_available_scripts(_get_system_scripts_dir(manager, alias)):
        items.append(
            {
                "script_name": script_name,
                "display_name": display_name,
                "description": description,
                "path": str(path),
            }
        )
    return {"items": items}


def _resolve_system_script_path(manager: MultiBotManager, alias: str, script_name: str) -> Path:
    if not script_name or not script_name.strip():
        _raise(400, "empty_script_name", "脚本名不能为空")

    requested_name = Path(script_name.strip()).name
    scripts_dir = _get_system_scripts_dir(manager, alias).resolve()

    for name, _, _, path in list_available_scripts(scripts_dir):
        if name.lower() == requested_name.lower():
            resolved = path.resolve()
            if scripts_dir not in resolved.parents:
                _raise(400, "invalid_script_path", "脚本路径无效")
            return resolved

    _raise(404, "script_not_found", f"未找到脚本: {script_name}")


async def run_system_script(manager: MultiBotManager, alias: str, user_id: int, script_name: str) -> dict[str, Any]:
    del user_id
    target_path = _resolve_system_script_path(manager, alias, script_name)
    loop = asyncio.get_running_loop()
    success, output = await loop.run_in_executor(None, execute_script, target_path)
    return {
        "script_name": target_path.name,
        "success": success,
        "output": output,
    }


async def _stream_system_script(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    script_name: str,
) -> AsyncIterator[dict[str, Any]]:
    del user_id
    target_path = _resolve_system_script_path(manager, alias, script_name)
    event_queue: queue.Queue[Any] = queue.Queue()
    worker_done = threading.Event()

    def run_stream() -> None:
        try:
            for event in stream_execute_script(target_path):
                event_queue.put(event)
        except Exception as exc:  # pragma: no cover - defensive
            event_queue.put(exc)
        finally:
            worker_done.set()

    threading.Thread(target=run_stream, daemon=True).start()

    while not worker_done.is_set() or not event_queue.empty():
        try:
            item = event_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue

        if isinstance(item, Exception):
            raise item
        if item.get("type") == "done":
            item = {
                **item,
                "script_name": target_path.name,
            }
        yield item


async def stream_system_script(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    script_name: str,
) -> AsyncIterator[dict[str, Any]]:
    try:
        async for event in _stream_system_script(manager, alias, user_id, script_name):
            yield event
    except WebApiError as exc:
        yield {"type": "error", "code": exc.code, "message": exc.message}
    except Exception as exc:  # pragma: no cover - defensive
        yield {"type": "error", "code": "script_stream_failed", "message": str(exc)}


async def _stream_update_download(repo_root: Path | None = None) -> AsyncIterator[dict[str, Any]]:
    target_repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    event_queue: queue.Queue[Any] = queue.Queue()
    worker_done = threading.Event()

    def on_progress(progress: dict[str, Any]) -> None:
        event_queue.put(
            {
                "type": "progress",
                **progress,
            }
        )

    def run_download() -> None:
        try:
            status = download_latest_update(
                repo_root=target_repo_root,
                progress_callback=on_progress,
            )
            event_queue.put(
                {
                    "type": "done",
                    "status": status,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            event_queue.put(exc)
        finally:
            worker_done.set()

    threading.Thread(target=run_download, daemon=True).start()

    while not worker_done.is_set() or not event_queue.empty():
        try:
            item = event_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue

        if isinstance(item, Exception):
            raise item
        yield item


async def stream_update_download(repo_root: Path | None = None) -> AsyncIterator[dict[str, Any]]:
    try:
        async for event in _stream_update_download(repo_root):
            yield event
    except Exception as exc:  # pragma: no cover - defensive
        yield {"type": "error", "code": "update_download_failed", "message": str(exc)}


async def add_managed_bot(
    manager: MultiBotManager,
    alias: str,
    bot_mode: str,
    cli_type: Optional[str],
    cli_path: Optional[str],
    working_dir: Optional[str],
    avatar_name: Optional[str] = None,
    token: str = "",
) -> dict[str, Any]:
    resolved_avatar_name = _normalize_avatar_name(avatar_name, require_existing=bool(str(avatar_name or "").strip()))
    try:
        profile = await manager.add_bot(
            alias=alias,
            token=token,
            cli_type=cli_type,
            cli_path=cli_path,
            working_dir=working_dir,
            bot_mode=bot_mode,
            avatar_name=resolved_avatar_name,
        )
    except ValueError as exc:
        _raise(400, "invalid_bot_config", str(exc))
    return {"bot": build_bot_summary(manager, profile.alias)}


async def remove_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.remove_bot(alias)
    return {"removed": True, "alias": alias}


async def start_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.start_bot(alias)
    return {"bot": build_bot_summary(manager, alias)}


async def stop_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.stop_bot(alias)
    return {"bot": build_bot_summary(manager, alias)}


async def update_bot_cli(manager: MultiBotManager, alias: str, cli_type: str, cli_path: str) -> dict[str, Any]:
    await manager.set_bot_cli(alias, cli_type, cli_path)
    return {"bot": build_bot_summary(manager, alias)}


async def rename_managed_bot(manager: MultiBotManager, alias: str, new_alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    old_alias = profile.alias
    old_bot_id = resolve_session_bot_id(manager, old_alias)
    workdir = profile.working_dir
    profile = await manager.rename_bot(alias, new_alias)
    new_bot_id = resolve_session_bot_id(manager, profile.alias)
    rekey_bot_sessions(old_bot_id, new_bot_id, old_alias=old_alias, new_alias=profile.alias)
    rename_stored_bot_sessions(old_bot_id, new_bot_id)
    ChatStore(Path(workdir)).rename_bot_identity(
        old_bot_id=old_bot_id,
        new_bot_id=new_bot_id,
        old_alias=old_alias,
        new_alias=profile.alias,
    )
    return {"bot": build_bot_summary(manager, profile.alias)}


def _reset_session_for_workdir_change(session: UserSession, working_dir: str) -> None:
    next_epoch = max(0, int(getattr(session, "session_epoch", 0) or 0)) + 1
    with session._lock:
        session.codex_session_id = None
        session.claude_session_id = None
        session.claude_session_initialized = False
        session.history = []
        session.web_turn_overlays = []
        session.running_user_text = None
        session.running_preview_text = ""
        session.running_started_at = None
        session.running_updated_at = None
        session.stop_requested = False
        session.message_count = 0
        session.session_epoch = next_epoch
        session.working_dir = working_dir
        session.browse_dir = working_dir
    session.persist()


async def update_bot_workdir(
    manager: MultiBotManager,
    alias: str,
    working_dir: str,
    user_id: Optional[int] = None,
    force_reset: bool = False,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_working_dir = os.path.abspath(os.path.expanduser(str(working_dir or "").strip()))
    if not os.path.isdir(resolved_working_dir):
        _raise(400, "invalid_working_dir", f"工作目录不存在: {resolved_working_dir}")
    if profile.bot_mode == "assistant":
        _raise(409, "unsupported_bot_mode", "assistant 型 Bot 不允许修改默认工作目录")
    session = get_session_for_alias(manager, alias, user_id) if user_id is not None else None

    if session is not None:
        service = _get_chat_history_service(session)
        current_working_dir = session.working_dir
        target_changed = resolved_working_dir != current_working_dir
        if target_changed:
            with session._lock:
                is_processing = session.is_processing
            if is_processing:
                _raise(
                    409,
                    WORKDIR_CHANGE_BLOCKED_PROCESSING,
                    "当前仍有任务运行，请先停止任务再切换工作目录",
                    data=service.summarize_active_conversation(profile, session),
                )

            if service.has_active_conversation(profile, session) and not force_reset:
                summary = service.summarize_active_conversation(profile, session)
                summary["requested_working_dir"] = resolved_working_dir
                _raise(
                    409,
                    WORKDIR_CHANGE_REQUIRES_RESET,
                    "切换工作目录会丢失当前会话，确认后重试",
                    data=summary,
                )

        if force_reset and service.has_active_conversation(profile, session):
            service.reset_active_conversation(profile, session)

        if target_changed or force_reset:
            _reset_session_for_workdir_change(session, resolved_working_dir)

    await manager.set_bot_workdir(alias, resolved_working_dir, update_sessions=False)
    return {"bot": build_bot_summary(manager, alias, user_id, profile=profile, session=session)}


async def update_bot_avatar(
    manager: MultiBotManager,
    alias: str,
    avatar_name: Any,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    resolved_avatar_name = _normalize_avatar_name(avatar_name, require_existing=True)
    await manager.set_bot_avatar(alias, resolved_avatar_name)
    return {"bot": build_bot_summary(manager, alias, user_id)}


def get_processing_sessions(alias: str) -> list[dict[str, Any]]:
    items = []
    with sessions_lock:
        for (bot_id, user_id), session in sessions.items():
            if session.bot_alias != alias:
                continue
            if not session.is_processing:
                continue
            items.append(
                {
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "working_dir": session.working_dir,
                    "message_count": session.message_count,
                }
            )
    return items
