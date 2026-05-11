"""Web 模式共享服务层。"""

from __future__ import annotations

import asyncio
import copy
import hmac
import json
import logging
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from xml.etree import ElementTree

from bot.assistant.cron.store import (
    delete_job_run_audit,
    delete_job_runtime_state,
    read_job_definition,
    read_job_run_audit,
)
from bot.assistant.dream.service import AssistantDreamConfig, apply_dream_result, prepare_dream_prompt
from bot.assistant.dream.managed_context import collect_managed_bot_dream_context
from bot.assistant.cron.types import AssistantCronJob
from bot.assistant.diagnostics import get_perf_diagnostics
from bot.assistant.compaction import (
    finalize_compaction,
    is_compaction_prompt_active,
    list_pending_capture_ids,
    refresh_compaction_state,
    snapshot_managed_surface,
)
from bot.assistant.context import compile_assistant_prompt
from bot.assistant.memory.knowledge_indexer import index_knowledge_memories
from bot.assistant.memory.eval import MemoryEvalCase, run_memory_eval
from bot.assistant.memory.store import AssistantMemoryStore, MemorySearchRow
from bot.assistant.memory.recall import recall_assistant_memories
from bot.assistant.perf import activate_perf_capture, list_perf_records, new_stage_durations, write_perf_record
from bot.assistant.memory.working_indexer import index_working_memories
from bot.assistant.memory.writer import write_hot_path_memories
from bot.claude_done import ClaudeDoneCollector, build_claude_done_session
from bot.assistant.docs import sync_managed_prompt_files
from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.upgrade.patch_generation import generate_pending_patch
from bot.assistant.upgrade.diff import parse_patch_files, run_upgrade_dry_run
from bot.assistant.proposals import get_proposal, list_proposals, set_proposal_status
from bot.assistant.runtime import AssistantRunRequest
from bot.assistant.upgrade.service import (
    approve_pending_upgrade_patch,
    apply_approved_upgrade,
    read_upgrade_apply_failure,
    read_upgrade_apply_result,
    read_upgrade_metadata,
    resolve_approved_upgrade_patch_path,
    resolve_approved_upgrade_repo_root,
    write_upgrade_apply_failure,
    write_upgrade_dry_run_result,
    write_upgrade_metadata,
)
from bot.assistant.upgrade.targets import list_upgrade_targets, resolve_upgrade_target
from bot.assistant.state import (
    attach_assistant_persist_hook,
    clear_assistant_runtime_state,
    record_assistant_capture,
    restore_assistant_runtime_state,
)
from bot.agents import build_agent_prompt_input
from bot.cli_params import CliParamsConfig, get_default_params, get_params_schema, normalize_cli_model_options
from bot.cluster.config import normalize_bot_cluster_config
from bot.cluster.bundles import (
    ClusterBundleError,
    build_cluster_bundle_diff,
    build_cluster_bundle_schema,
    get_cluster_template,
    list_cluster_templates,
    normalize_cluster_bundle,
)
from bot.cluster.runtime import ClusterRuntime, ClusterRunRequest, ClusterToolError
from bot.cluster.setup import (
    CLUSTER_MCP_SERVER_NAME,
    build_cli_install_command,
    build_cli_remove_command,
    build_cli_verify_command,
    prepare_cluster_mcp_launcher,
)
from bot.config import CLI_MODEL_OPTIONS, WEB_PORT
from bot.cli import (
    build_cli_command,
    extract_codex_error_output,
    normalize_cli_type,
    parse_claude_stream_json_line,
    parse_claude_stream_json_output,
    parse_codex_json_line,
    parse_codex_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    should_suggest_reset_codex_session,
)
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import AgentProfile, BotProfile, UserSession
from bot.platform.output import strip_ansi_escape
from bot.platform.processes import build_hidden_process_kwargs, terminate_process_tree_sync
from bot.session_store import rename_bot_sessions as rename_stored_bot_sessions
from bot.sessions import (
    align_session_paths,
    clear_bot_sessions,
    get_or_create_session,
    rekey_bot_sessions,
    reset_session,
    sessions,
    sessions_lock,
    update_bot_working_dir,
)
from bot.updater import download_latest_update
from bot.utils import is_dangerous_command
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer
from bot.web.chat_store import ChatStore
from bot.web.native_history_adapter import create_stream_trace_state, consume_stream_trace_chunk
from bot.web.api_common import (
    AuthContext,
    WebApiError,
    _raise,
    _require_capability,
    get_chat_session_for_alias,
    get_profile_or_raise,
    get_session_for_alias,
    resolve_session_bot_id,
)
from bot.web.auth_store import CAP_RUN_PLUGINS, CAP_TERMINAL_EXEC, CAP_VIEW_PLUGINS, CAP_WRITE_FILES
from bot.web.files_service import (
    change_working_directory,
    copy_path,
    create_directory,
    create_text_file,
    delete_chat_attachment,
    delete_path,
    display_browser_directory as _display_browser_directory,
    ensure_path_within_base_dir as _ensure_path_within_base_dir,
    get_browser_directory as _get_browser_directory,
    get_directory_listing,
    get_file_metadata,
    get_working_directory,
    invalidate_workspace_indexes as _invalidate_workspace_indexes,
    is_windows_drive_root as _is_windows_drive_root,
    is_windows_drives_virtual_root as _is_windows_drives_virtual_root,
    list_directory_entries as _list_directory_entries,
    list_directory_entry_items as _list_directory_entry_items,
    looks_like_windows_path as _looks_like_windows_path,
    move_path,
    normalize_windows_drive_root as _normalize_windows_drive_root,
    read_file_content,
    require_real_browser_directory as _require_real_browser_directory,
    resolve_browser_target_path as _resolve_browser_target_path,
    reveal_directory_tree,
    rename_path,
    save_chat_attachment,
    save_uploaded_file,
    write_file_content,
)
from bot.web.plugin_api_service import (
    dispose_plugin_view,
    get_plugin_artifact,
    get_plugin_view_window,
    install_plugin,
    invoke_plugin_action,
    list_installable_plugins,
    list_plugins,
    open_plugin_view,
    render_plugin_view,
    resolve_plugin_file_target,
    update_plugin,
)
from bot.web.terminal_actions import (
    TerminalActionConfigConflict,
    TerminalActionValidationError,
    load_terminal_actions_config,
    resolve_terminal_action,
    save_terminal_actions_config,
    serialize_terminal_actions_config,
)

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLUSTER_RUNTIME = ClusterRuntime()


@dataclass
class _ClusterRunControl:
    semaphore: asyncio.Semaphore
    agent_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)


_CLUSTER_RUN_CONTROLS: dict[str, _ClusterRunControl] = {}
_ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_AVATAR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_DRIVES_VIRTUAL_ROOT = "::windows-drives::"
_WINDOWS_DRIVES_DISPLAY_ROOT = "盘符列表"
_WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
_WINDOWS_STYLE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
WORKDIR_CHANGE_REQUIRES_RESET = "workdir_change_requires_reset"
WORKDIR_CHANGE_BLOCKED_PROCESSING = "workdir_change_blocked_processing"
CODEX_DONE_QUIET_SECONDS = 0.5
@dataclass
class CliAttemptState:
    """单次 CLI 尝试的会话状态。"""

    cli_session_id: Optional[str]
    resume_session: bool
    codex_session_id: Optional[str] = None


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


def _split_csv_query(value: str | None) -> list[str] | None:
    items = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return items or None


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


def _build_assistant_runtime_item(manager: MultiBotManager, profile: BotProfile) -> dict[str, Any] | None:
    if profile.bot_mode != "assistant":
        return None
    runtime = manager.assistant_runtime
    if runtime is None:
        return None
    snapshot_for_bot = getattr(runtime, "snapshot_for_bot", None)
    if not callable(snapshot_for_bot):
        return None
    snapshot = snapshot_for_bot(profile.alias)
    return snapshot if isinstance(snapshot, dict) else None


def get_chat_session_for_alias(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    agent_id: str = "main",
) -> tuple[BotProfile, AgentProfile, UserSession]:
    profile = get_profile_or_raise(manager, alias)
    normalized_agent_id = str(agent_id or "main").strip().lower() or "main"
    try:
        agent = profile.get_agent(normalized_agent_id)
    except KeyError:
        _raise(404, "agent_not_found", "未找到 agent")
    if normalized_agent_id == "main":
        return profile, agent, get_session_for_alias(manager, alias, user_id)
    if normalized_agent_id != "main" and profile.bot_mode != "cli":
        _raise(400, "agent_not_supported", "仅 CLI Bot 支持子 agent")
    session = get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=user_id,
        default_working_dir=profile.working_dir,
        load_persisted_state=profile.bot_mode != "assistant",
        agent_id=agent.id,
    )
    return profile, agent, align_session_paths(session, profile.working_dir, profile.bot_mode)


def _supports_cli_runtime(profile: BotProfile) -> bool:
    return profile.bot_mode in ("cli", "assistant")


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


def _build_agent_runtime_map(bot_id: int, user_id: int | None) -> dict[str, dict[str, Any]]:
    if user_id is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    with sessions_lock:
        for (session_bot_id, session_user_id, session_agent_id), session in sessions.items():
            if session_bot_id != bot_id or session_user_id != user_id:
                continue
            with session._lock:
                result[session_agent_id] = {
                    "is_processing": bool(session.is_processing),
                    "message_count": max(0, int(session.message_count or 0)),
                    "active_conversation_id": session.active_conversation_id or "",
                }
    return result


def _agent_summary_with_runtime(
    profile: BotProfile,
    agent: AgentProfile,
    runtime_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    runtime = runtime_map.get(agent.id, {})
    return {
        **agent.to_dict(),
        "is_main": agent.id == "main",
        "is_processing": bool(runtime.get("is_processing", False)),
        "message_count": max(0, int(runtime.get("message_count", 0) or 0)),
        "active_conversation_id": str(runtime.get("active_conversation_id") or ""),
    }


def _build_agent_status_items(
    profile: BotProfile,
    runtime_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _agent_summary_with_runtime(profile, agent, runtime_map)
        for agent in profile.normalized_agents()
    ]


def _build_activity_summary(agent_items: list[dict[str, Any]]) -> dict[str, Any]:
    busy_agents = [item for item in agent_items if item.get("is_processing")]
    busy_agent_ids = [str(item.get("id") or "main") for item in busy_agents]
    busy_agent_names = [str(item.get("name") or item.get("id") or "agent") for item in busy_agents]
    return {
        "activity_status": "busy" if busy_agents else "idle",
        "busy_agent_ids": busy_agent_ids,
        "busy_agent_names": busy_agent_names,
        "busy_agent_count": len(busy_agents),
        "is_processing": bool(busy_agents),
    }


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
    run_status = _build_run_status(manager, alias, profile)
    service_status = "offline" if run_status in {"stopped", "offline"} else "online"
    bot_id = resolve_session_bot_id(manager, alias)

    # 优先使用当前用户 session 的工作目录（如果用户已登录）
    working_dir = profile.working_dir
    if user_id is not None:
        try:
            current_session = session or get_session_for_alias(manager, alias, user_id)
            if current_session and current_session.working_dir:
                working_dir = current_session.working_dir
        except Exception:
            # 如果获取 session 失败，使用 profile 的工作目录
            pass
    agent_items = _build_agent_status_items(profile, _build_agent_runtime_map(bot_id, user_id))
    activity = _build_activity_summary(agent_items)

    return {
        "alias": profile.alias,
        "enabled": profile.enabled,
        "bot_mode": profile.bot_mode,
        "cli_type": profile.cli_type,
        "cli_path": profile.cli_path,
        "working_dir": working_dir,
        "avatar_name": profile.avatar_name or "",
        "is_main": alias == manager.main_profile.alias,
        "status": run_status,
        "service_status": service_status,
        "cluster": profile.cluster.to_dict(),
        **activity,
        "bot_username": (app.bot_data.get("bot_username") if app else "") or "",
        "capabilities": _build_capabilities(profile, alias == manager.main_profile.alias),
        "assistant_runtime": _build_assistant_runtime_item(manager, profile),
    }


def list_bots(manager: MultiBotManager, user_id: Optional[int] = None) -> list[dict[str, Any]]:
    aliases = [manager.main_profile.alias, *sorted(manager.managed_profiles.keys())]
    return [build_bot_summary(manager, alias, user_id) for alias in aliases]


def get_overview(manager: MultiBotManager, alias: str, user_id: int, agent_id: str = "main") -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    bot_id = resolve_session_bot_id(manager, alias)
    active_cluster_run = _CLUSTER_RUNTIME.find_active_run(alias, user_id)
    return {
        "bot": build_bot_summary(manager, alias, user_id, profile=profile, session=session),
        "session": build_session_snapshot(profile, session),
        "agents": _build_agent_status_items(profile, _build_agent_runtime_map(bot_id, user_id)),
        "active_agent_id": session.agent_id,
        "active_cluster_run": (
            {
                "run_id": active_cluster_run.run_id,
                "status": active_cluster_run.status,
                "tasks": _CLUSTER_RUNTIME.build_task_status(active_cluster_run.run_id, include_output=True),
            }
            if active_cluster_run is not None
            else None
        ),
    }


def list_agents(manager: MultiBotManager, alias: str, user_id: int | None = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    bot_id = resolve_session_bot_id(manager, alias)
    return {"items": _build_agent_status_items(profile, _build_agent_runtime_map(bot_id, user_id))}


def _cluster_token_path() -> Path:
    return Path.home() / ".tcb" / "cluster-mcp" / "token"


def _cluster_bridge_url() -> str:
    return f"http://127.0.0.1:{WEB_PORT}"


def verify_cluster_mcp_request(request_headers: dict[str, str]) -> None:
    auth = str(request_headers.get("Authorization") or "")
    if not auth.startswith("Bearer "):
        _raise(401, "cluster_mcp_unauthorized", "cluster MCP 未授权")
    token = auth.removeprefix("Bearer ").strip()
    token_path = _cluster_token_path()
    try:
        expected = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        _raise(401, "cluster_mcp_unauthorized", "cluster MCP token 不存在")
    if not token or not expected or not hmac.compare_digest(token, expected):
        _raise(401, "cluster_mcp_unauthorized", "cluster MCP 未授权")


def _cluster_cli_path(profile: BotProfile, cli_type: str) -> str:
    try:
        active_cli_type = normalize_cli_type(profile.cli_type)
    except ValueError:
        active_cli_type = ""
    return profile.cli_path if active_cli_type == cli_type and profile.cli_path else cli_type


def _cluster_runtime_mcp_status() -> dict[str, str]:
    launcher_name = "tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh"
    launcher_path = Path.home() / ".tcb" / "bin" / launcher_name
    config_path = Path.home() / ".tcb" / "cluster-mcp" / "config.json"
    token_path = _cluster_token_path()
    if not launcher_path.exists() or not config_path.exists():
        return {"state": "launcher_missing", "message": "未生成运行配置"}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"state": "broken", "message": f"运行配置无效: {exc}"}
    if str(config.get("server_name") or "") != CLUSTER_MCP_SERVER_NAME:
        return {"state": "stale", "message": "运行配置需更新"}
    configured_token_path = Path(str(config.get("token_file") or token_path))
    if not configured_token_path.exists():
        return {"state": "broken", "message": "运行 token 不存在"}
    return {"state": "runtime_ready", "message": "运行态可用"}


def _cluster_inactive_target_status() -> dict[str, str]:
    return {"state": "not_checked", "message": "未使用"}


def _cluster_mcp_target_status(profile: BotProfile, cli_type: str, *, active_cli_type: str) -> dict[str, str]:
    if cli_type != active_cli_type:
        return _cluster_inactive_target_status()
    cli_path = _cluster_cli_path(profile, cli_type)
    command = build_cli_verify_command(cli_type, cli_path)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **build_hidden_process_kwargs(),
        )
    except FileNotFoundError:
        return {"state": "cli_missing", "message": f"未找到 {cli_type}"}
    except subprocess.TimeoutExpired:
        return {"state": "broken", "message": "检测超时"}
    except OSError as exc:
        return {"state": "broken", "message": str(exc)}

    output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
    if completed.returncode == 0 and CLUSTER_MCP_SERVER_NAME in output:
        if "enabled: false" in output.lower():
            return {"state": "broken", "message": "已安装但未启用"}
        return {"state": "installed", "message": "已安装"}
    runtime_status = _cluster_runtime_mcp_status()
    if runtime_status["state"] == "runtime_ready":
        return runtime_status
    if "not found" in output.lower() or "no mcp" in output.lower() or completed.returncode != 0:
        return {"state": "mcp_missing", "message": "未安装"}
    return {"state": "mcp_missing", "message": "未安装"}


def get_cluster_status(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    try:
        active_cli_type = normalize_cli_type(profile.cli_type)
    except ValueError:
        active_cli_type = ""
    return {
        "enabled": bool(profile.cluster.enabled),
        "model_tiers": dict(profile.cluster.model_tiers),
        "mcp": {
            "server_name": CLUSTER_MCP_SERVER_NAME,
            "active_cli_type": active_cli_type,
            "runtime": _cluster_runtime_mcp_status(),
            "codex": _cluster_mcp_target_status(profile, "codex", active_cli_type=active_cli_type),
            "claude": _cluster_mcp_target_status(profile, "claude", active_cli_type=active_cli_type),
        },
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "enabled": agent.enabled,
                "allow_cluster": agent.cluster.allow_cluster,
                "allow_write": agent.cluster.allow_write,
            }
            for agent in profile.normalized_agents()
            if agent.id != "main"
        ],
    }


def prepare_cluster_setup(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    launcher = prepare_cluster_mcp_launcher(
        home_dir=Path.home(),
        repo_root=_REPO_ROOT,
        bridge_url=_cluster_bridge_url(),
    )
    return {
        **launcher.to_dict(),
        "install_command": build_cli_install_command(
            cli_type=profile.cli_type,
            cli_path=profile.cli_path,
            launcher_path=launcher.launcher_path,
        ),
        "verify_command": build_cli_verify_command(profile.cli_type, profile.cli_path),
        "remove_command": build_cli_remove_command(profile.cli_type, profile.cli_path),
    }


async def update_cluster_config(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        source = data.get("cluster") if isinstance(data.get("cluster"), dict) else data
        cluster = await manager.update_bot_cluster(alias, normalize_bot_cluster_config(source).to_dict())
    except ValueError as exc:
        _raise(400, "invalid_cluster_config", str(exc))
    return {"cluster": cluster, "status": get_cluster_status(manager, alias)}


def _raise_cluster_bundle_error(exc: ClusterBundleError) -> None:
    _raise(400, exc.code, exc.message)


def get_cluster_bundle_schema() -> dict[str, Any]:
    return build_cluster_bundle_schema()


def get_cluster_templates(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    _ = get_profile_or_raise(manager, alias)
    try:
        return {"templates": list_cluster_templates()}
    except ClusterBundleError as exc:
        _raise_cluster_bundle_error(exc)
    return {"templates": []}


def preview_cluster_template(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    try:
        bundle = get_cluster_template(str(data.get("template_id", data.get("templateId", "")) or ""))
        return {"bundle": bundle, "diff": build_cluster_bundle_diff(profile, bundle)}
    except ClusterBundleError as exc:
        _raise_cluster_bundle_error(exc)
    return {}


async def apply_cluster_template(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("confirm_overwrite_agents", data.get("confirmOverwriteAgents")) is not True:
        _raise(409, "cluster_bundle_overwrite_not_confirmed", "应用模板会覆盖当前子 agent 配置，请确认后重试")
    profile = get_profile_or_raise(manager, alias)
    try:
        bundle = get_cluster_template(str(data.get("template_id", data.get("templateId", "")) or ""))
        diff = build_cluster_bundle_diff(profile, bundle)
    except ClusterBundleError as exc:
        _raise_cluster_bundle_error(exc)
    result = await manager.replace_bot_cluster_bundle(alias, bundle["cluster"], bundle["agents"])
    return {**result, "bundle": bundle, "diff": diff, "status": get_cluster_status(manager, alias)}


def preview_cluster_config_bundle(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    try:
        bundle = normalize_cluster_bundle(data.get("bundle", data))
        return {"bundle": bundle, "diff": build_cluster_bundle_diff(profile, bundle)}
    except ClusterBundleError as exc:
        _raise_cluster_bundle_error(exc)
    return {}


async def apply_cluster_config_bundle(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("confirm_overwrite_agents", data.get("confirmOverwriteAgents")) is not True:
        _raise(409, "cluster_bundle_overwrite_not_confirmed", "应用配置会覆盖当前子 agent 配置，请确认后重试")
    profile = get_profile_or_raise(manager, alias)
    try:
        bundle = normalize_cluster_bundle(data.get("bundle", data))
        diff = build_cluster_bundle_diff(profile, bundle)
    except ClusterBundleError as exc:
        _raise_cluster_bundle_error(exc)
    result = await manager.replace_bot_cluster_bundle(alias, bundle["cluster"], bundle["agents"])
    return {**result, "bundle": bundle, "diff": diff, "status": get_cluster_status(manager, alias)}


def get_cluster_task_status(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    run_id: str,
    *,
    task_ids: list[str] | None = None,
    include_output: bool = True,
) -> dict[str, Any]:
    run = _CLUSTER_RUNTIME.get_run(run_id)
    if run is None or run.bot_alias != alias or run.user_id != user_id:
        _raise(404, "cluster_run_not_found", "未找到集群任务")
    _ = get_profile_or_raise(manager, alias)
    return _CLUSTER_RUNTIME.build_task_status(run_id, task_ids, include_output=include_output)


def _cluster_task_wait_seconds(payload: dict[str, Any]) -> float:
    raw = payload.get("wait_seconds", payload.get("waitSeconds", 0))
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 0.0
    return max(0.0, min(60.0, seconds))


async def _wait_for_cluster_tasks_if_requested(
    run_id: str,
    task_ids: list[str] | None,
    wait_seconds: float,
) -> None:
    if wait_seconds <= 0:
        return
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        status = _CLUSTER_RUNTIME.build_task_status(run_id, task_ids, include_output=False)
        if status["pending_count"] <= 0:
            return
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.2, remaining))


async def handle_cluster_mcp_tool(
    manager: MultiBotManager,
    run_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        if tool_name == "cluster_status":
            return {"ok": True, "data": _CLUSTER_RUNTIME.build_status(run_id)}
        if tool_name == "list_agents":
            return {"ok": True, "data": _CLUSTER_RUNTIME.build_status(run_id)["agents"]}
        if tool_name == "poll_agent_tasks":
            raw_task_ids = payload.get("task_ids", payload.get("taskIds"))
            task_ids = [str(item) for item in raw_task_ids] if isinstance(raw_task_ids, list) else None
            include_output = payload.get("include_output", payload.get("includeOutput", True)) is not False
            await _wait_for_cluster_tasks_if_requested(run_id, task_ids, _cluster_task_wait_seconds(payload))
            return {"ok": True, "data": _CLUSTER_RUNTIME.build_task_status(run_id, task_ids, include_output=include_output)}
        if tool_name != "ask_agent":
            _raise(404, "cluster_tool_not_found", "未知集群工具")

        request = _CLUSTER_RUNTIME.validate_ask_agent(run_id, payload)
        run = _CLUSTER_RUNTIME.get_run(run_id)
        if run is None:
            _raise(404, "cluster_run_not_found", "未找到集群任务")
        task = _CLUSTER_RUNTIME.create_agent_task(run_id, request)
        control = _cluster_run_control(run_id, run.profile.cluster.max_parallel_agents)
        background_task = asyncio.create_task(_run_cluster_agent_task(manager, run_id, task.task_id))
        control.tasks.add(background_task)
        background_task.add_done_callback(control.tasks.discard)
        background_task.add_done_callback(lambda _task, current_run_id=run_id: _cleanup_cluster_run_control_if_idle(current_run_id))
        return {
            "ok": True,
            "data": {
                "task_id": task.task_id,
                "agent_id": task.agent_id,
                "status": task.status,
                "model_tier": task.model_tier,
                "created_at": task.created_at,
            },
        }
    except KeyError:
        _raise(404, "cluster_run_not_found", "未找到集群任务")
    except ClusterToolError as exc:
        _raise(400, exc.code, exc.message)


async def create_agent(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        agent = await manager.create_bot_agent(alias, data)
    except ValueError as exc:
        _raise(400, "invalid_agent", str(exc))
    return {"agent": agent}


async def update_agent(manager: MultiBotManager, alias: str, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        agent = await manager.update_bot_agent(alias, agent_id, data)
    except KeyError:
        _raise(404, "agent_not_found", "未找到 agent")
    except ValueError as exc:
        _raise(400, "invalid_agent", str(exc))
    return {"agent": agent}


async def delete_agent(manager: MultiBotManager, alias: str, agent_id: str) -> dict[str, Any]:
    try:
        await manager.delete_bot_agent(alias, agent_id)
    except KeyError:
        _raise(404, "agent_not_found", "未找到 agent")
    except ValueError as exc:
        _raise(400, "invalid_agent", str(exc))
    return {"deleted": True}


def list_assistant_proposals(
    manager: MultiBotManager,
    alias: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    return {"items": list_proposals(home, status=status)}


def list_assistant_upgrade_targets(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    _assistant_home_or_raise(manager, alias)
    return {"items": list_upgrade_targets(manager)}


def _assistant_upgrade_patch_candidates(home, proposal_id: str) -> list[tuple[str, Path]]:
    return [
        ("approved", home.root / "upgrades" / "approved" / f"{proposal_id}.patch"),
        ("pending", home.root / "upgrades" / "pending" / f"{proposal_id}.patch"),
    ]


def _read_assistant_upgrade_diff(home, proposal_id: str) -> dict[str, Any]:
    for state, path in _assistant_upgrade_patch_candidates(home, proposal_id):
        if path.exists():
            text = path.read_text(encoding="utf-8")
            return {
                "available": True,
                "state": state,
                "source": path.relative_to(home.root).as_posix(),
                "text": text,
                "files": parse_patch_files(text),
            }
    return {"available": False, "state": "", "source": "", "text": "", "files": []}


def _read_assistant_generation_log(home, proposal_id: str, *, limit: int = 100) -> dict[str, Any]:
    path = home.root / "upgrades" / "logs" / f"{proposal_id}.generate.jsonl"
    if not path.exists():
        return {"available": False, "source": "", "items": []}
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"event": "unparsed", "message": line}
        if isinstance(payload, dict):
            items.append(payload)
    return {"available": True, "source": path.relative_to(home.root).as_posix(), "items": items}


def _read_assistant_apply_state(home, proposal_id: str, *, proposal: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    applied = read_upgrade_apply_result(home, proposal_id)
    failed = read_upgrade_apply_failure(home, proposal_id)
    diff_state = str(diff.get("state") or "")
    return {
        "available": bool(diff.get("available")) and diff_state == "approved",
        "applied": proposal.get("status") == "applied" or bool(applied),
        "last_error": str((failed or {}).get("error") or ""),
        "last_error_at": str((failed or {}).get("failed_at") or ""),
        "last_error_log_path": (
            f"upgrades/applied/{proposal_id}.last-error.json" if failed else ""
        ),
    }


def _read_assistant_upgrade_state(home, proposal_id: str, *, proposal: dict[str, Any]) -> dict[str, Any]:
    approved = read_upgrade_metadata(home, proposal_id, "approved")
    pending = read_upgrade_metadata(home, proposal_id, "pending")
    applied = read_upgrade_apply_result(home, proposal_id)
    approved_patch = home.root / "upgrades" / "approved" / f"{proposal_id}.patch"
    pending_patch = home.root / "upgrades" / "pending" / f"{proposal_id}.patch"
    metadata = approved or pending or {}
    pending_lifecycle = str((pending or {}).get("lifecycle") or "").strip()
    if applied:
        state = "applied"
    elif approved is not None or approved_patch.exists():
        state = "approved"
    elif pending is not None or pending_patch.exists():
        state = pending_lifecycle if pending_lifecycle in {"running", "failed"} else "pending"
    else:
        state = "none"
    sensitive_hits = [str(item) for item in metadata.get("sensitive_hits") or [] if str(item)]
    can_generate = proposal.get("status") == "approved"
    can_approve_patch = state == "pending" and pending is not None and not sensitive_hits
    can_dry_run = approved is not None or approved_patch.exists()
    return {
        "state": state,
        "target_alias": str(metadata.get("target_alias") or ""),
        "target_repo_root": str(metadata.get("target_repo_root") or ""),
        "base_commit": str(metadata.get("base_commit") or ""),
        "patch_source": str(metadata.get("patch_path") or ""),
        "generation_status": str((metadata.get("generator") or {}).get("status") or pending_lifecycle or ""),
        "chat_conclusion": str(metadata.get("chat_conclusion") or ""),
        "sensitive_hits": sensitive_hits,
        "dry_run": dict(metadata.get("dry_run") or {}),
        "can_generate": can_generate,
        "can_approve_patch": can_approve_patch,
        "can_dry_run": can_dry_run,
        "can_apply": can_dry_run and proposal.get("status") != "applied",
    }


def get_assistant_proposal_detail(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        proposal = get_proposal(home, proposal_id)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))
    diff = _read_assistant_upgrade_diff(home, proposal_id)
    return {
        "proposal": proposal,
        "diff": diff,
        "apply": _read_assistant_apply_state(home, proposal_id, proposal=proposal, diff=diff),
        "upgrade": _read_assistant_upgrade_state(home, proposal_id, proposal=proposal),
        "generation_log": _read_assistant_generation_log(home, proposal_id),
    }


def get_assistant_upgrade_apply_log(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    failed = read_upgrade_apply_failure(home, proposal_id)
    if failed is not None:
        return failed
    applied = read_upgrade_apply_result(home, proposal_id)
    if applied is not None:
        return applied
    _raise(404, "assistant_upgrade_log_not_found", f"未找到 `{proposal_id}` 的 apply 日志")


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


def _raise_patch_generation_error(exc: Exception) -> None:
    if isinstance(exc, RuntimeError) and str(exc).startswith("upgrade_target_dirty"):
        _raise(
            409,
            "upgrade_target_dirty",
            "目标工程有未提交改动，请清理后再生成 patch",
            data={"dirty_status": str(exc)},
        )
    if isinstance(exc, PermissionError):
        if str(exc) == "proposal_not_approved":
            _raise(409, "proposal_not_approved", "proposal 尚未批准，不能生成 patch")
        raise exc
    if isinstance(exc, FileExistsError):
        _raise(409, "patch_generation_already_running", str(exc))
    if isinstance(exc, ValueError):
        _raise(409, str(exc), str(exc))
    if isinstance(exc, (FileNotFoundError, subprocess.CalledProcessError)):
        detail = (
            exc.stderr if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        ) or (
            exc.stdout if isinstance(exc, subprocess.CalledProcessError)
            else ""
        ) or str(exc)
        _raise(500, "patch_generation_failed", str(detail).strip() or "生成 patch 失败")
    raise exc


def _raise_unavailable_upgrade_target(target: dict[str, Any]) -> None:
    reason = str(target.get("reason") or "upgrade_target_unavailable")
    dirty_paths = [str(item) for item in target.get("dirty_paths") or [] if str(item)]
    if reason == "upgrade_target_dirty":
        _raise(
            409,
            reason,
            "目标工程有未提交改动，请清理后再生成 patch",
            data={"dirty_paths": dirty_paths},
        )
    _raise(409, reason, "目标工程不可用", data={"dirty_paths": dirty_paths})


async def generate_assistant_proposal_patch(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
    *,
    target_alias: str,
    regenerate: bool,
    generated_by: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        proposal = get_proposal(home, proposal_id)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))
    if proposal.get("status") != "approved":
        _raise(409, "proposal_not_approved", "proposal 尚未批准，不能生成 patch")
    try:
        target = resolve_upgrade_target(manager, target_alias)
    except KeyError:
        _raise(404, "upgrade_target_not_found", target_alias)
    if not target.get("available"):
        _raise_unavailable_upgrade_target(target)
    try:
        return generate_pending_patch(
            home,
            proposal,
            target=target,
            generated_by=generated_by,
            regenerate=regenerate,
        )
    except Exception as exc:
        _raise_patch_generation_error(exc)


async def stream_generate_assistant_proposal_patch(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
    *,
    target_alias: str,
    regenerate: bool,
    generated_by: str,
) -> AsyncIterator[dict[str, Any]]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        proposal = get_proposal(home, proposal_id)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))
    if proposal.get("status") != "approved":
        _raise(409, "proposal_not_approved", "proposal 尚未批准，不能生成 patch")
    try:
        target = resolve_upgrade_target(manager, target_alias)
    except KeyError:
        _raise(404, "upgrade_target_not_found", target_alias)
    if not target.get("available"):
        _raise_unavailable_upgrade_target(target)

    event_queue: queue.Queue[Any] = queue.Queue()
    worker_done = threading.Event()

    def on_event(event: dict[str, Any]) -> None:
        event_queue.put(event)

    def run_generation() -> None:
        try:
            metadata = generate_pending_patch(
                home,
                proposal,
                target=target,
                generated_by=generated_by,
                regenerate=regenerate,
                event_callback=on_event,
            )
            event_queue.put({"type": "done", "metadata": metadata})
        except Exception as exc:  # pragma: no cover - event body is asserted at stream boundary
            logger.warning("assistant patch stream failed: alias=%s proposal=%s err=%s", alias, proposal_id, exc)
            event_queue.put({
                "type": "error",
                "code": "patch_generation_failed",
                "message": _normalize_error_message(exc).strip() or "patch_generation_failed",
                "metadata": read_upgrade_metadata(home, proposal_id, "pending"),
            })
        finally:
            worker_done.set()

    threading.Thread(target=run_generation, daemon=True).start()

    while not worker_done.is_set() or not event_queue.empty():
        try:
            item = event_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue
        yield item


async def approve_assistant_proposal_patch(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
    *,
    reviewer: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        return approve_pending_upgrade_patch(home, proposal_id, reviewer=reviewer)
    except PermissionError as exc:
        if str(exc) == "proposal_not_approved":
            _raise(409, "proposal_not_approved", "proposal 尚未批准，不能批准 patch")
        if str(exc) == "sensitive_patch_path":
            _raise(409, "sensitive_patch_path", "patch 命中敏感路径，不能批准")
        raise
    except FileNotFoundError as exc:
        _raise(404, "pending_patch_not_found", str(exc))


async def apply_assistant_upgrade(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    repo_root = resolve_approved_upgrade_repo_root(
        home,
        proposal_id,
        fallback_repo_root=Path(__file__).resolve().parents[2],
    )
    try:
        return apply_approved_upgrade(home, proposal_id, repo_root=repo_root)
    except PermissionError as exc:
        if str(exc) == "proposal_not_approved":
            _raise(409, "proposal_not_approved", "proposal 尚未批准，不能 apply")
        raise
    except FileNotFoundError as exc:
        _raise(404, "upgrade_patch_not_found", str(exc))
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("upgrade_target_dirty"):
            try:
                patch_path = resolve_approved_upgrade_patch_path(home, proposal_id)
            except FileNotFoundError:
                patch_path = home.root / "upgrades" / "approved" / f"{proposal_id}.patch"
            write_upgrade_apply_failure(
                home,
                proposal_id,
                repo_root=repo_root,
                patch_path=patch_path,
                error=detail,
            )
            _raise(
                409,
                "upgrade_target_dirty",
                "目标工程有未提交改动，请清理后再 apply",
                data={"dirty_status": detail},
            )
        raise
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        try:
            patch_path = resolve_approved_upgrade_patch_path(home, proposal_id)
        except FileNotFoundError:
            patch_path = home.root / "upgrades" / "approved" / f"{proposal_id}.patch"
        write_upgrade_apply_failure(
            home,
            proposal_id,
            repo_root=repo_root,
            patch_path=patch_path,
            error=detail or "应用 upgrade 失败",
        )
        _raise(500, "assistant_upgrade_failed", detail or "应用 upgrade 失败")


async def dry_run_assistant_upgrade(
    manager: MultiBotManager,
    alias: str,
    proposal_id: str,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    try:
        patch_path = resolve_approved_upgrade_patch_path(home, proposal_id)
    except FileNotFoundError as exc:
        _raise(404, "upgrade_patch_not_found", str(exc))
    repo_root = resolve_approved_upgrade_repo_root(
        home,
        proposal_id,
        fallback_repo_root=Path(__file__).resolve().parents[2],
    )
    result = run_upgrade_dry_run(repo_root=repo_root, patch_path=patch_path)
    write_upgrade_dry_run_result(home, proposal_id, result)
    return result


def _assistant_memory_score(row: MemorySearchRow) -> float:
    lexical_component = 1.0 / (1.0 + max(0.0, abs(float(row.lexical_score))))
    score = (lexical_component * 0.35) + (row.importance * 0.25) + (row.confidence * 0.25) + (row.freshness * 0.15)
    if row.scope == "user":
        score += 0.04
    if row.kind == "semantic":
        score += 0.02
    return round(min(score, 1.0), 4)


def search_assistant_memories(
    manager: MultiBotManager,
    alias: str,
    *,
    user_id: int,
    query_text: str,
    limit: int = 10,
    kinds: list[str] | None = None,
    scopes: list[str] | None = None,
    include_invalidated: bool = False,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    store = AssistantMemoryStore(home)
    stage_durations = new_stage_durations()
    started_at = time.perf_counter()
    with activate_perf_capture(stage_durations):
        recall_started_at = time.perf_counter()
        rows = store.search_lexical(
            user_id=user_id,
            query_text=query_text,
            kinds=kinds,
            scopes=scopes,
            include_invalidated=include_invalidated,
            limit=limit,
        )
        stage_durations["recall_ms"] += max(0, int(round((time.perf_counter() - recall_started_at) * 1000)))
    items = [
        {
            "id": row.id,
            "kind": row.kind,
            "scope": row.scope,
            "source_type": row.source_type,
            "source_ref": row.source_ref,
            "title": row.title,
            "summary": row.summary,
            "body": row.body,
            "updated_at": row.updated_at,
            "invalidated_at": row.invalidated_at,
            "score": _assistant_memory_score(row),
        }
        for row in rows
    ]
    elapsed_ms = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    write_perf_record(
        home,
        run_id=f"memory-search-{uuid.uuid4().hex[:8]}",
        bot_alias=alias,
        source="memory_search",
        task_mode="admin",
        interactive=False,
        user_id=user_id,
        status="completed",
        stage_durations=stage_durations,
        elapsed_ms=elapsed_ms,
        prompt_chars=len(query_text),
        output_chars=len(json.dumps(items, ensure_ascii=False)),
    )
    return {"items": items}


def invalidate_assistant_memory(
    manager: MultiBotManager,
    alias: str,
    memory_id: str,
    *,
    reason: str,
    user_id: int,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    store = AssistantMemoryStore(home)
    stage_durations = new_stage_durations()
    started_at = time.perf_counter()
    with activate_perf_capture(stage_durations):
        invalidated = store.invalidate(memory_id, reason=reason)
    if not invalidated:
        _raise(404, "assistant_memory_not_found", f"memory `{memory_id}` 不存在")
    elapsed_ms = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    write_perf_record(
        home,
        run_id=f"memory-invalidate-{uuid.uuid4().hex[:8]}",
        bot_alias=alias,
        source="memory_invalidate",
        task_mode="admin",
        interactive=False,
        user_id=user_id,
        status="completed",
        stage_durations=stage_durations,
        elapsed_ms=elapsed_ms,
        prompt_chars=len(memory_id),
    )
    return {"memory_id": memory_id, "invalidated": True, "reason": reason}


def bulk_invalidate_assistant_memories(
    manager: MultiBotManager,
    alias: str,
    *,
    memory_ids: list[str],
    reason: str,
    user_id: int,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    store = AssistantMemoryStore(home)
    stage_durations = new_stage_durations()
    started_at = time.perf_counter()
    invalidated = 0
    missing: list[str] = []
    with activate_perf_capture(stage_durations):
        for memory_id in memory_ids:
            clean_id = str(memory_id or "").strip()
            if not clean_id:
                continue
            if store.invalidate(clean_id, reason=reason):
                invalidated += 1
            else:
                missing.append(clean_id)
    elapsed_ms = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    write_perf_record(
        home,
        run_id=f"memory-bulk-invalidate-{uuid.uuid4().hex[:8]}",
        bot_alias=alias,
        source="memory_bulk_invalidate",
        task_mode="admin",
        interactive=False,
        user_id=user_id,
        status="completed",
        stage_durations=stage_durations,
        elapsed_ms=elapsed_ms,
        prompt_chars=sum(len(str(item)) for item in memory_ids),
    )
    return {"invalidated": invalidated, "missing": missing, "reason": reason}


def reindex_assistant_memory(
    manager: MultiBotManager,
    alias: str,
    *,
    user_id: int,
    force: bool = False,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    stage_durations = new_stage_durations()
    started_at = time.perf_counter()
    with activate_perf_capture(stage_durations):
        index_started_at = time.perf_counter()
        working = index_working_memories(home, user_id=user_id, force=force)
        knowledge = index_knowledge_memories(home, user_id=0)
        stage_durations["index_ms"] += max(0, int(round((time.perf_counter() - index_started_at) * 1000)))
    payload = {
        "working": {
            "indexed_count": working.indexed_count,
            "memory_ids": working.memory_ids,
        },
        "knowledge": {
            "indexed_count": knowledge.indexed_count,
            "memory_ids": knowledge.memory_ids,
        },
    }
    elapsed_ms = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    write_perf_record(
        home,
        run_id=f"memory-reindex-{uuid.uuid4().hex[:8]}",
        bot_alias=alias,
        source="memory_reindex",
        task_mode="admin",
        interactive=False,
        user_id=user_id,
        status="completed",
        stage_durations=stage_durations,
        elapsed_ms=elapsed_ms,
        output_chars=len(json.dumps(payload, ensure_ascii=False)),
    )
    return payload


def _parse_memory_eval_cases(payload: dict[str, Any]) -> list[MemoryEvalCase]:
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows:
        _raise(400, "invalid_eval_cases", "cases 不能为空")
    items: list[MemoryEvalCase] = []
    for row in rows:
        if not isinstance(row, dict):
            _raise(400, "invalid_eval_cases", "cases 必须为对象数组")
        query = str(row.get("query") or "").strip()
        expected_memory_kind = str(row.get("expected_memory_kind") or "").strip()
        if not query or not expected_memory_kind:
            _raise(400, "invalid_eval_cases", "case 缺少 query 或 expected_memory_kind")
        items.append(
            MemoryEvalCase(
                query=query,
                expected_memory_kind=expected_memory_kind,
                expected_hit_terms=[str(item) for item in row.get("expected_hit_terms", [])],
                must_not_hit_terms=[str(item) for item in row.get("must_not_hit_terms", [])],
            )
        )
    return items


def run_assistant_memory_eval_task(
    manager: MultiBotManager,
    alias: str,
    *,
    user_id: int,
    cases: list[MemoryEvalCase],
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    stage_durations = new_stage_durations()
    started_at = time.perf_counter()
    with activate_perf_capture(stage_durations):
        recall_started_at = time.perf_counter()
        run = run_memory_eval(home, user_id=user_id, cases=cases)
        stage_durations["recall_ms"] += max(0, int(round((time.perf_counter() - recall_started_at) * 1000)))
    payload = {
        "metrics": {
            "hit_at_5": run.metrics["hit_at_5"],
            "stale_recall_rate": run.metrics["stale_recall_rate"],
        },
        "report_path": run.report_path,
    }
    elapsed_ms = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    write_perf_record(
        home,
        run_id=f"memory-eval-{uuid.uuid4().hex[:8]}",
        bot_alias=alias,
        source="memory_eval",
        task_mode="admin",
        interactive=False,
        user_id=user_id,
        status="completed",
        stage_durations=stage_durations,
        elapsed_ms=elapsed_ms,
        output_chars=len(json.dumps(payload, ensure_ascii=False)),
    )
    return payload


def list_assistant_memory_eval_reports(
    manager: MultiBotManager,
    alias: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    items: list[dict[str, Any]] = []
    for path in sorted((home.root / "evals" / "memory").glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
        except OSError:
            created_at = ""
        items.append(
            {
                "report_path": str(path),
                "created_at": created_at,
                "metrics": {
                    "hit_at_5": float((payload.get("metrics") or {}).get("hit_at_5") or 0.0),
                    "stale_recall_rate": float((payload.get("metrics") or {}).get("stale_recall_rate") or 0.0),
                },
                "rows": [
                    {
                        "query": str(row.get("query") or ""),
                        "prompt_block": str(row.get("prompt_block") or ""),
                        "hit": bool(row.get("hit")),
                        "stale": bool(row.get("stale")),
                        "audit_path": row.get("audit_path"),
                    }
                    for row in payload.get("rows", [])
                    if isinstance(row, dict)
                ],
            }
        )
        if len(items) >= max(1, int(limit)):
            break
    return {"items": items}


def get_assistant_diagnostics(
    manager: MultiBotManager,
    alias: str,
    *,
    limit: int = 20,
    source: str = "",
    status: str = "",
    user_id: int | None = None,
    from_value: str = "",
    to_value: str = "",
) -> dict[str, Any]:
    home = _assistant_home_or_raise(manager, alias)
    return get_perf_diagnostics(
        home,
        limit=limit,
        source=source,
        status=status,
        user_id=user_id,
        from_value=from_value,
        to_value=to_value,
    )


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


def get_history(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    limit: int = 50,
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    service = _get_chat_history_service(session)
    return {"items": service.list_history(profile, session, limit=max(1, limit))}


def list_conversations(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    limit: int = 50,
    query: str = "",
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    store = ChatStore(Path(session.working_dir))
    active_id = str(getattr(session, "active_conversation_id", "") or "")
    items = store.list_conversations(
        bot_id=session.bot_id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        working_dir=session.working_dir,
        limit=max(1, limit),
        query=query,
    )
    return {
        "items": [
            {
                **item,
                "active": str(item.get("id") or "") == active_id,
                "bot_mode": str(item.get("bot_mode") or profile.bot_mode),
            }
            for item in items
        ],
        "active_conversation_id": active_id,
    }


def _create_agent_conversation(
    profile: BotProfile,
    session: UserSession,
    *,
    title: str = "",
) -> tuple[ChatStore, str]:
    store = ChatStore(Path(session.working_dir))
    conversation_id = store.create_conversation(
        bot_id=session.bot_id,
        bot_alias=session.bot_alias,
        user_id=session.user_id,
        agent_id=session.agent_id,
        bot_mode=profile.bot_mode,
        cli_type=profile.cli_type,
        working_dir=session.working_dir,
        session_epoch=max(0, int(getattr(session, "session_epoch", 0) or 0)),
        native_provider=normalize_cli_type(profile.cli_type),
        title=title,
    )
    with session._lock:
        session.active_conversation_id = conversation_id
        session.codex_session_id = None
        session.claude_session_id = None
        session.claude_session_initialized = False
    session.persist()
    return store, conversation_id


def _create_cluster_child_conversations(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    profile: BotProfile,
) -> None:
    if not profile.cluster.enabled:
        return
    for agent in profile.normalized_agents():
        if agent.id == "main" or not agent.enabled:
            continue
        _profile, _agent, child_session = get_chat_session_for_alias(manager, alias, user_id, agent.id)
        with child_session._lock:
            is_processing = bool(child_session.is_processing)
        if is_processing:
            _raise(409, "conversation_switch_blocked", "子 agent 正在运行，先终止或等待完成")
    for agent in profile.normalized_agents():
        if agent.id == "main" or not agent.enabled:
            continue
        _profile, _agent, child_session = get_chat_session_for_alias(manager, alias, user_id, agent.id)
        _create_agent_conversation(profile, child_session)


def create_conversation(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    title: str = "",
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    with session._lock:
        is_processing = bool(session.is_processing)
    if is_processing:
        _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    if session.agent_id == "main":
        _create_cluster_child_conversations(manager, alias, user_id, profile)
    store, conversation_id = _create_agent_conversation(profile, session, title=title)
    return {
        "conversation": {
            **store.get_conversation(conversation_id),
            "active": True,
            "bot_mode": profile.bot_mode,
            "agent_id": session.agent_id,
        },
        "messages": [],
    }


def select_conversation(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    conversation_id: str,
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    with session._lock:
        is_processing = bool(session.is_processing)
    if is_processing:
        _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    store = ChatStore(Path(session.working_dir))
    try:
        conversation = store.get_conversation(conversation_id)
    except KeyError:
        _raise(404, "conversation_not_found", "未找到会话")

    if int(conversation.get("bot_id") or 0) != session.bot_id or int(conversation.get("user_id") or 0) != session.user_id:
        _raise(404, "conversation_not_found", "未找到会话")
    if str(conversation.get("agent_id") or "main") != session.agent_id:
        _raise(404, "conversation_not_found", "未找到会话")
    if str(conversation.get("working_dir") or "") != session.working_dir:
        _raise(409, "conversation_workdir_mismatch", "会话工作目录和当前 Bot 不一致")
    if str(conversation.get("archived_at") or "").strip():
        _raise(404, "conversation_not_found", "未找到会话")

    native_provider = normalize_cli_type(str(conversation.get("native_provider") or profile.cli_type))
    native_session_id = str(conversation.get("native_session_id") or "").strip()
    with session._lock:
        session.active_conversation_id = str(conversation["id"])
        if native_provider == "codex":
            session.codex_session_id = native_session_id or None
        if native_provider == "claude":
            session.claude_session_id = native_session_id or None
            session.claude_session_initialized = bool(native_session_id)
    session.persist()

    messages = ChatHistoryService(store).list_history(profile, session, limit=50)
    return {
        "conversation": {
            **conversation,
            "active": True,
            "bot_mode": str(conversation.get("bot_mode") or profile.bot_mode),
            "agent_id": session.agent_id,
        },
        "messages": messages,
    }


def get_history_delta(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    after_id: str,
    limit: int = 50,
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    items = _get_chat_history_service(session).list_history(profile, session, limit=max(1, limit))
    marker = str(after_id or "")
    if not marker:
        return {"items": items, "reset": False}

    ids = [str(item.get("id") or "") for item in items]
    if marker not in ids:
        return {"items": items, "reset": True}
    return {"items": items[ids.index(marker) + 1:], "reset": False}


def get_history_trace(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    message_id: str,
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
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
            _terminate_process_sync(process)
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


def build_cluster_cli_params_override(profile: BotProfile, model_tier: str) -> CliParamsConfig:
    params = profile.cli_params.to_dict()
    cli_type = normalize_cli_type(profile.cli_type)
    tier = model_tier if model_tier in {"low", "medium", "high"} else "medium"
    model = str(profile.cluster.model_tiers.get(tier) or "").strip()
    if model:
        params.setdefault(cli_type, {})
        params[cli_type]["model"] = model
    return CliParamsConfig.from_dict(params)


def _quote_toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _cluster_mcp_injected_params(profile: BotProfile, params_config: CliParamsConfig) -> CliParamsConfig:
    cli_type = normalize_cli_type(profile.cli_type)
    launcher_name = "tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh"
    launcher_path = Path.home() / ".tcb" / "bin" / launcher_name
    params = params_config.to_dict()
    cli_params = params.setdefault(cli_type, {})
    extra_args = [str(item) for item in cli_params.get("extra_args", []) if str(item).strip()]
    if cli_type == "codex":
        injection = ["-c", f"mcp_servers.{CLUSTER_MCP_SERVER_NAME}.command={_quote_toml_string(str(launcher_path))}"]
    elif cli_type == "claude":
        config = {"mcpServers": {CLUSTER_MCP_SERVER_NAME: {"command": str(launcher_path)}}}
        injection = ["--mcp-config", json.dumps(config, ensure_ascii=False)]
    else:
        injection = []
    if injection and not all(arg in extra_args for arg in injection):
        cli_params["extra_args"] = [*extra_args, *injection]
    return CliParamsConfig.from_dict(params)


def _effective_cli_params(profile: BotProfile, params_config: CliParamsConfig, cluster_run_id: str) -> CliParamsConfig:
    if not cluster_run_id:
        return params_config
    return _cluster_mcp_injected_params(profile, params_config)


def _cluster_run_control(run_id: str, max_parallel_agents: int) -> _ClusterRunControl:
    control = _CLUSTER_RUN_CONTROLS.get(run_id)
    if control is None:
        control = _ClusterRunControl(asyncio.Semaphore(max(1, int(max_parallel_agents or 1))))
        _CLUSTER_RUN_CONTROLS[run_id] = control
    return control


def _cleanup_cluster_run_control_if_idle(run_id: str) -> None:
    control = _CLUSTER_RUN_CONTROLS.get(run_id)
    run = _CLUSTER_RUNTIME.get_run(run_id)
    if control is None or run is None:
        return
    if control.tasks:
        return
    if run.status not in {"completed", "failed", "error", "cancelled"}:
        return
    if any(task.status in {"queued", "running"} for task in run.tasks.values()):
        return
    _CLUSTER_RUN_CONTROLS.pop(run_id, None)


def _cluster_agent_result_error(result: dict[str, Any]) -> str:
    output = str(result.get("output") or "").strip()
    returncode = result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return output or f"子 agent 命令退出码 {returncode}"

    message = result.get("message") if isinstance(result.get("message"), dict) else {}
    state = str(message.get("state") or "").strip()
    meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
    completion_state = str(meta.get("completion_state") or "").strip()
    if state == "error" or (completion_state and completion_state != "completed"):
        reason = completion_state or state or "error"
        return output or str(message.get("content") or "").strip() or f"子 agent 执行失败: {reason}"
    return ""


async def _run_cluster_agent_task(
    manager: MultiBotManager,
    run_id: str,
    task_id: str,
) -> None:
    run = _CLUSTER_RUNTIME.get_run(run_id)
    if run is None:
        return
    task = run.tasks.get(task_id)
    if task is None:
        return
    control = _cluster_run_control(run_id, run.profile.cluster.max_parallel_agents)
    agent_lock = control.agent_locks.setdefault(task.agent_id, asyncio.Lock())
    try:
        async with control.semaphore:
            async with agent_lock:
                live_run = _CLUSTER_RUNTIME.get_run(run_id)
                if live_run is None:
                    return
                live_task = live_run.tasks.get(task_id)
                if live_task is None or live_task.status != "queued":
                    return
                live_task = _CLUSTER_RUNTIME.mark_agent_task_running(run_id, task_id)
                cli_params_override = build_cluster_cli_params_override(live_run.profile, live_task.model_tier)
                result = await run_cli_chat(
                    manager,
                    live_run.bot_alias,
                    live_run.user_id,
                    live_task.message,
                    agent_id=live_task.agent_id,
                    cli_params_override=cli_params_override,
                )
                error = _cluster_agent_result_error(result)
                if error:
                    _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, error)
                else:
                    _CLUSTER_RUNTIME.complete_agent_task(run_id, task_id, str(result.get("output") or ""))
    except asyncio.TimeoutError:
        _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, "子 agent 执行超时")
    except Exception as exc:
        _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, str(exc))


def _build_cluster_prompt(mentions: list[dict[str, Any]] | None, run_id: str = "") -> str:
    mentioned = ", ".join(
        str(item.get("agent_id") or item.get("agentId") or "").strip()
        for item in (mentions or [])
        if str(item.get("agent_id") or item.get("agentId") or "").strip()
    )
    return (
        "<tcb_cluster_mode>\n"
        "你处于 TCB 集群模式。可用 MCP server: tcb-cluster。\n"
        "需要委派时，调用 MCP 工具 ask_agent。\n"
        f"当前集群 run_id: {run_id or '无'}。调用 ask_agent 时带 run_id。\n"
        "ask_agent 会异步启动任务并返回 task_id，不会自动等子 agent 完成。\n"
        "ask_agent 的 timeout_seconds 是软期限；超时不强行中断子 agent，poll_agent_tasks 会通过 deadline_exceeded 告知主 agent。\n"
        "你可在同一轮对话内多轮指挥集群：连续 ask_agent 并发启动多个任务，调用 poll_agent_tasks 查看结果，再按结果追加新任务或汇总。\n"
        "如果需要等待结果，调用 poll_agent_tasks 时传 wait_seconds；如果用户只要求启动或你判断可后台运行，可先结束并说明任务仍在运行。\n"
        "最终回答前自行选择：等待并汇总已完成任务，或明确说明哪些任务仍在后台运行。\n"
        "如用户未显式提及子 agent，则你应自主决定是否和如何使用集群，使用前查询集群配置，使用时遵循安全和效率原则，即：多 agents 不要写相同文件，不要做重复的事情（尤其包括你自己，不要尝试代劳委派的子 agent 的工作，尽量等待其完成并采纳其结果）。\n"
        f"用户显式提及的子 agent: {mentioned or '无'}\n"
        "</tcb_cluster_mode>\n\n"
    )


def _current_native_session_id(session: UserSession, cli_type: str) -> str:
    normalized = normalize_cli_type(cli_type)
    if normalized == "codex":
        return str(session.codex_session_id or "").strip()
    if normalized == "claude":
        return str(session.claude_session_id or "").strip()
    return ""


def _apply_agent_prompt_if_needed(prompt_text: str, agent: AgentProfile, session: UserSession, cli_type: str) -> str:
    if agent.id == "main" or _current_native_session_id(session, cli_type):
        return prompt_text
    wrapped, prompt_hash = build_agent_prompt_input(prompt_text, agent.system_prompt)
    with session._lock:
        session.agent_prompt_hash_seen = prompt_hash or None
    return wrapped


def _prepare_assistant_prompt(
    profile: BotProfile,
    session: UserSession,
    *,
    user_id: int,
    user_text: str,
    cli_type: str,
) -> tuple[Any, dict[str, str], str, bool, dict[str, int]]:
    assistant_home = bootstrap_assistant_home(profile.working_dir)
    assistant_pre_surface = snapshot_managed_surface(assistant_home)
    compaction_prompt_active = is_compaction_prompt_active(assistant_home)
    stage_durations = new_stage_durations()
    with activate_perf_capture(stage_durations):
        sync_started_at = time.perf_counter()
        sync_result = sync_managed_prompt_files(assistant_home)
        stage_durations["sync_ms"] += max(0, int(round((time.perf_counter() - sync_started_at) * 1000)))
    prompt_source_text = user_text
    try:
        with activate_perf_capture(stage_durations):
            index_started_at = time.perf_counter()
            index_working_memories(assistant_home)
            stage_durations["index_ms"] += max(0, int(round((time.perf_counter() - index_started_at) * 1000)))
    except Exception as exc:
        logger.warning("assistant working memory index failed user=%s error=%s", user_id, exc)
    try:
        with activate_perf_capture(stage_durations):
            recall_started_at = time.perf_counter()
            recall = recall_assistant_memories(assistant_home, user_id=user_id, user_text=user_text)
            stage_durations["recall_ms"] += max(0, int(round((time.perf_counter() - recall_started_at) * 1000)))
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
    return assistant_home, assistant_pre_surface, compiled_prompt.prompt_text, compaction_prompt_active, stage_durations


def _normalize_assistant_prompt_preparation(
    value: tuple[Any, dict[str, str], str, bool] | tuple[Any, dict[str, str], str, bool, dict[str, int]],
) -> tuple[Any, dict[str, str], str, bool, dict[str, int]]:
    if len(value) == 5:
        return value
    assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active = value
    return assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active, new_stage_durations()


def _is_dream_request(request: AssistantRunRequest | None) -> bool:
    return bool(request is not None and request.task_mode == "dream")


def _is_proposal_patch_request(request: AssistantRunRequest | None) -> bool:
    return bool(request is not None and request.task_mode == "proposal_patch")


def _proposal_patch_request_payload(request: AssistantRunRequest) -> tuple[str, str, bool]:
    payload = dict(request.task_payload or {})
    proposal_id = str(payload.get("proposal_id") or payload.get("proposalId") or "").strip()
    target_alias = str(payload.get("target_alias") or payload.get("targetAlias") or "").strip()
    regenerate = bool(payload.get("regenerate"))
    return proposal_id, target_alias, regenerate


def _build_patch_generation_summary(metadata: dict[str, Any] | None, *, error_message: str = "") -> str:
    if error_message:
        return "\n".join([
            "patch 生成失败",
            f"原因: {error_message}",
        ])
    data = dict(metadata or {})
    files = [str(item) for item in data.get("changed_files") or [] if str(item)]
    summary = [
        "patch 已生成",
        f"目标工程: {str(data.get('target_alias') or '-')}",
        f"变更: {len(files)} 文件 · +{int(data.get('additions') or 0)} / -{int(data.get('deletions') or 0)}",
    ]
    if files:
        preview = ", ".join(files[:3])
        if len(files) > 3:
            preview += " ..."
        summary.append(f"文件: {preview}")
    sensitive_hits = [str(item) for item in data.get("sensitive_hits") or [] if str(item)]
    if sensitive_hits:
        summary.append(f"敏感路径: {', '.join(sensitive_hits)}")
    return "\n".join(summary)


def _persist_patch_chat_conclusion(
    home,
    proposal_id: str,
    metadata: dict[str, Any] | None,
    *,
    summary: str,
    message_id: str = "",
) -> dict[str, Any] | None:
    if metadata is None:
        return None
    next_metadata = dict(metadata)
    next_metadata["chat_conclusion"] = summary
    if message_id:
        next_metadata["chat_message_id"] = message_id
    write_upgrade_metadata(home, proposal_id, str(next_metadata.get("state") or "pending"), next_metadata)
    return next_metadata


def _append_patch_preview_text(current: str, message: str) -> str:
    parts = [part for part in (current.strip(), str(message or "").strip()) if part]
    if not parts:
        return ""
    merged = "\n".join(parts[-8:])
    return merged[-800:]


def _prepare_dream_assistant_prompt(
    manager: MultiBotManager,
    profile: BotProfile,
    session: UserSession,
    request: AssistantRunRequest,
    *,
    user_text: str,
) -> tuple[Any, str, dict[str, Any], dict[str, int]]:
    assistant_home = bootstrap_assistant_home(profile.working_dir)
    stage_durations = new_stage_durations()
    with activate_perf_capture(stage_durations):
        sync_started_at = time.perf_counter()
        sync_result = sync_managed_prompt_files(assistant_home)
        stage_durations["sync_ms"] += max(0, int(round((time.perf_counter() - sync_started_at) * 1000)))
    context_user_id = request.context_user_id if request.context_user_id is not None else request.user_id
    context_session = get_session_for_alias(manager, profile.alias, context_user_id)
    config = AssistantDreamConfig.from_task_payload(request.task_payload)
    managed_context = collect_managed_bot_dream_context(
        manager,
        current_alias=profile.alias,
        context_user_id=context_user_id,
        lookback_hours=config.lookback_hours,
        history_limit=config.history_limit,
        capture_limit=config.capture_limit,
        session_resolver=lambda alias, user_id: get_session_for_alias(manager, alias, user_id),
        history_service_factory=_get_chat_history_service,
    )
    prepared_prompt = prepare_dream_prompt(
        assistant_home,
        profile=profile,
        session=context_session,
        history_service=_get_chat_history_service(context_session),
        config=config,
        visible_text=user_text,
        managed_context_text=managed_context.text,
        managed_context_stats=managed_context.stats,
    )
    compiled_prompt = compile_assistant_prompt(
        prepared_prompt.prompt_text,
        managed_prompt_hash=sync_result.managed_prompt_hash,
        seen_managed_prompt_hash=session.managed_prompt_hash_seen,
    )
    if compiled_prompt.managed_prompt_hash_seen != session.managed_prompt_hash_seen:
        session.managed_prompt_hash_seen = compiled_prompt.managed_prompt_hash_seen
        session.persist()
    return assistant_home, compiled_prompt.prompt_text, prepared_prompt.context_stats, stage_durations


def _normalize_dream_prompt_preparation(
    value: tuple[Any, str, dict[str, Any]] | tuple[Any, str, dict[str, Any], dict[str, int]],
) -> tuple[Any, str, dict[str, Any], dict[str, int]]:
    if len(value) == 4:
        return value
    assistant_home, prompt_text, context_stats = value
    return assistant_home, prompt_text, context_stats, new_stage_durations()


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


def _decorate_codex_resume_error(
    response: str,
    *,
    session_id: Optional[str],
    returncode: int,
) -> tuple[str, bool]:
    normalized = str(response or "").strip()
    if not should_suggest_reset_codex_session(session_id, normalized, returncode):
        return normalized, False

    hint = str(msg("chat", "codex_resume_reset_hint") or "").strip()
    if not hint:
        return normalized, True
    if "新会话" in normalized or "重置会话" in normalized:
        return normalized, True
    if not normalized:
        return hint, True
    return f"{normalized}\n\n{hint}", True


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
    error_text = extract_codex_error_output(raw_output) if returncode != 0 else None
    final_text = error_text or candidate_text or _extract_final_codex_completed_message(raw_output) or final_text
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


async def _stream_cli_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    agent_id: str = "main",
    cli_params_override: CliParamsConfig | None = None,
    cluster_run_id: str = "",
    cluster_mentions: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    profile, agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    visible_input = request.visible_text if request is not None and request.visible_text is not None else user_text
    text = (visible_input or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    prompt_text = text
    if cluster_run_id:
        prompt_text = _build_cluster_prompt(cluster_mentions, cluster_run_id) + prompt_text
    assistant_home = None
    assistant_pre_surface: dict[str, str] = {}
    compaction_prompt_active = False
    assistant_stage_durations = new_stage_durations()

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    if cluster_run_id:
        env["TCB_CLUSTER_ACTIVE"] = "1"
        env["TCB_CLUSTER_RUN_ID"] = cluster_run_id
        env["TCB_CLUSTER_BOT_ALIAS"] = alias
        env["TCB_CLUSTER_USER_ID"] = str(user_id)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    if profile.bot_mode == "assistant":
        assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active, assistant_stage_durations = (
            _normalize_assistant_prompt_preparation(
                _prepare_assistant_prompt(
                    profile,
                    session,
                    user_id=user_id,
                    user_text=text,
                    cli_type=cli_type,
                )
            )
        )
    elif agent.id != "main":
        prompt_text = _apply_agent_prompt_if_needed(prompt_text, agent, session, cli_type)

    done_session = None
    if cli_type == "claude":
        done_session = build_claude_done_session(prompt_text, cli_type=cli_type)
        prompt_text = done_session.prompt_text

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.stop_requested = False
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
            params_for_attempt = _effective_cli_params(profile, cli_params_override or profile.cli_params, cluster_run_id)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude")),
                    params_config=params_for_attempt,
                    working_dir=session.working_dir,
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
                    "cluster_run_id": cluster_run_id,
                }
                meta_sent = True

            output_queue: queue.Queue[Any] = queue.Queue()
            reader_done = threading.Event()
            preview_state = _StreamPreviewState(cli_type)
            persistence_buffer = StreamingPersistenceBuffer(
                service,
                turn_handle,
                loop_time=loop.time,
            )
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
            cli_started_at = time.perf_counter()

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
                            persistence_buffer.queue_trace(trace_event)
                            persistence_buffer.maybe_flush()
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
                            persistence_buffer.queue_preview(preview_text)
                            persistence_buffer.maybe_flush()
                        yield status_event
                        last_status_signature = status_signature

                    if not drained:
                        await asyncio.sleep(0.1)

                waited_returncode = await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
                returncode = _resolve_process_returncode(process, waited_returncode)
                if done_terminate_started_at is not None:
                    returncode = 0
            except asyncio.CancelledError:
                persistence_buffer.flush()
                if process.poll() is None:
                    await loop.run_in_executor(None, _terminate_process_sync, process)
                raise
            finally:
                with session._lock:
                    session.process = None
            assistant_stage_durations["cli_ms"] += max(0, int(round((time.perf_counter() - cli_started_at) * 1000)))

            raw_output = preview_state.raw_output_for_parse()
            if cli_type == "codex":
                response, parsed_thread_id = parse_codex_json_output(raw_output)
                thread_id = thread_id or parsed_thread_id
                response = codex_done_candidate or _extract_final_codex_completed_message(raw_output) or response
                if returncode != 0:
                    response = extract_codex_error_output(raw_output) or response
            elif cli_type == "claude":
                if claude_collector is not None:
                    response = claude_collector.final_text or ""
                else:
                    response, _ = parse_claude_stream_json_output(raw_output)
            else:
                response = raw_output.strip()

            response = response or msg("chat", "no_output")
            should_force_error_output = False

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

            if cli_type == "codex":
                response, should_force_error_output = _decorate_codex_resume_error(
                    response,
                    session_id=attempt.codex_session_id,
                    returncode=returncode,
                )

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
            persistence_buffer.flush()
            for trace_event in final_trace[len(live_trace_events):]:
                persistence_buffer.queue_trace(trace_event)
            persistence_buffer.flush()
            native_session_id = session.codex_session_id if cli_type == "codex" else session.claude_session_id
            trace_started_at = time.perf_counter()
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
            assistant_stage_durations["trace_ms"] += max(0, int(round((time.perf_counter() - trace_started_at) * 1000)))
            fallback_output = (
                response
                if completion_state == "completed" or should_force_error_output
                else (latest_preview_text or response)
            )
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
            if assistant_home is not None:
                meta = done_message.get("meta") if isinstance(done_message.get("meta"), dict) else {}
                perf_request = request or AssistantRunRequest(
                    run_id=f"run_{uuid.uuid4().hex[:12]}",
                    source="web",
                    bot_alias=alias,
                    user_id=user_id,
                    text=user_text,
                    interactive=True,
                    visible_text=text,
                )
                write_perf_record(
                    assistant_home,
                    run_id=perf_request.run_id,
                    bot_alias=alias,
                    source=perf_request.source,
                    task_mode=perf_request.task_mode,
                    interactive=perf_request.interactive,
                    user_id=perf_request.user_id,
                    status=completion_state,
                    stage_durations=assistant_stage_durations,
                    elapsed_ms=max(0, int(elapsed_seconds * 1000)),
                    prompt_chars=len(prompt_text),
                    output_chars=len(str(done_message.get("content") or response)),
                    trace_count=int(meta.get("traceCount") or len(final_trace)),
                    tool_call_count=int(meta.get("toolCallCount") or 0),
                    process_count=int(meta.get("processCount") or len(final_trace)),
                    error="" if completion_state == "completed" else str(response or ""),
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
    agent_id: str = "main",
    cli_params_override: CliParamsConfig | None = None,
    cluster_run_id: str = "",
    cluster_mentions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile, agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    visible_input = request.visible_text if request is not None and request.visible_text is not None else user_text
    text = (visible_input or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    prompt_text = text
    if cluster_run_id:
        prompt_text = _build_cluster_prompt(cluster_mentions, cluster_run_id) + prompt_text
    assistant_home = None
    assistant_pre_surface: dict[str, str] = {}
    compaction_prompt_active = False
    finalize_assistant_turn = True
    dream_context_stats: dict[str, Any] | None = None
    dream_prompt_text = ""
    assistant_stage_durations = new_stage_durations()

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    if cluster_run_id:
        env["TCB_CLUSTER_ACTIVE"] = "1"
        env["TCB_CLUSTER_RUN_ID"] = cluster_run_id
        env["TCB_CLUSTER_BOT_ALIAS"] = alias
        env["TCB_CLUSTER_USER_ID"] = str(user_id)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    if profile.bot_mode == "assistant":
        if _is_dream_request(request):
            assert request is not None
            assistant_home, prompt_text, dream_context_stats, assistant_stage_durations = _normalize_dream_prompt_preparation(
                _prepare_dream_assistant_prompt(
                    manager,
                    profile,
                    session,
                    request,
                    user_text=text,
                )
            )
            dream_prompt_text = prompt_text
            finalize_assistant_turn = False
        else:
            assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active, assistant_stage_durations = (
                _normalize_assistant_prompt_preparation(
                    _prepare_assistant_prompt(
                        profile,
                        session,
                        user_id=user_id,
                        user_text=text,
                        cli_type=cli_type,
                    )
                )
            )
    elif agent.id != "main":
        prompt_text = _apply_agent_prompt_if_needed(prompt_text, agent, session, cli_type)

    done_session = None
    if cli_type == "claude":
        done_session = build_claude_done_session(prompt_text, cli_type=cli_type)
        prompt_text = done_session.prompt_text

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.stop_requested = False
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
            params_for_attempt = _effective_cli_params(profile, cli_params_override or profile.cli_params, cluster_run_id)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude")),
                    params_config=params_for_attempt,
                    working_dir=session.working_dir,
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

            cli_started_at = time.perf_counter()
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
            assistant_stage_durations["cli_ms"] += max(0, int(round((time.perf_counter() - cli_started_at) * 1000)))
            should_force_error_output = False

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

            if cli_type == "codex":
                response, should_force_error_output = _decorate_codex_resume_error(
                    response,
                    session_id=attempt.codex_session_id,
                    returncode=returncode,
                )

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
            trace_started_at = time.perf_counter()
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
            assistant_stage_durations["trace_ms"] += max(0, int(round((time.perf_counter() - trace_started_at) * 1000)))
            done_message = service.complete_turn(
                turn_handle,
                content=(
                    response
                    if completion_state == "completed" or should_force_error_output
                    else (response or msg("chat", "no_output"))
                ),
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
            if assistant_home is not None:
                meta = done_message.get("meta") if isinstance(done_message.get("meta"), dict) else {}
                perf_request = request or AssistantRunRequest(
                    run_id=f"run_{uuid.uuid4().hex[:12]}",
                    source="web",
                    bot_alias=alias,
                    user_id=user_id,
                    text=user_text,
                    interactive=True,
                    visible_text=text,
                )
                write_perf_record(
                    assistant_home,
                    run_id=perf_request.run_id,
                    bot_alias=alias,
                    source=perf_request.source,
                    task_mode=perf_request.task_mode,
                    interactive=perf_request.interactive,
                    user_id=perf_request.user_id,
                    status=completion_state,
                    stage_durations=assistant_stage_durations,
                    elapsed_ms=max(0, int(elapsed_seconds * 1000)),
                    prompt_chars=len(prompt_text),
                    output_chars=len(str(done_message.get("content") or response)),
                    trace_count=int(meta.get("traceCount") or len(terminal_trace)),
                    tool_call_count=int(meta.get("toolCallCount") or 0),
                    process_count=int(meta.get("processCount") or len(terminal_trace)),
                    error="" if completion_state == "completed" else str(response or ""),
                )
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


async def run_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    task_mode: str = "standard",
    task_payload: dict[str, Any] | None = None,
    visible_text: str | None = None,
    agent_id: str = "main",
    cluster: bool = False,
    mentions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode == "assistant":
        if manager.assistant_runtime is None:
            _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
        if task_mode == "proposal_patch":
            _ensure_proposal_patch_chat_available(manager, alias, user_id)
        request = build_assistant_run_request(
            alias,
            user_id,
            user_text,
            task_mode=task_mode,
            task_payload=task_payload,
            visible_text=visible_text,
        )
        return await manager.assistant_runtime.submit_interactive(request)
    if _supports_cli_runtime(profile):
        if cluster and not profile.cluster.enabled:
            _raise(409, "cluster_not_enabled", "该 Bot 未启用集群模式")
        cluster_run = None
        if cluster:
            cluster_run = _CLUSTER_RUNTIME.start_run(
                ClusterRunRequest(
                    bot_alias=alias,
                    user_id=user_id,
                    profile=profile,
                    mentions=list(mentions or []),
                )
            )
        run_status = "completed"
        try:
            return await run_cli_chat(
                manager,
                alias,
                user_id,
                user_text,
                agent_id=agent_id,
                cluster_run_id=cluster_run.run_id if cluster_run else "",
                cluster_mentions=list(mentions or []),
            )
        except Exception:
            run_status = "error"
            raise
        finally:
            if cluster_run:
                _CLUSTER_RUNTIME.finish_run(cluster_run.run_id, run_status)
                _cleanup_cluster_run_control_if_idle(cluster_run.run_id)
    _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")


async def stream_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    task_mode: str = "standard",
    task_payload: dict[str, Any] | None = None,
    visible_text: str | None = None,
    agent_id: str = "main",
    cluster: bool = False,
    mentions: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        profile = get_profile_or_raise(manager, alias)
        if profile.bot_mode == "assistant":
            if manager.assistant_runtime is None:
                _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
            if task_mode == "proposal_patch":
                _ensure_proposal_patch_chat_available(manager, alias, user_id)
            request = build_assistant_run_request(
                alias,
                user_id,
                user_text,
                task_mode=task_mode,
                task_payload=task_payload,
                visible_text=visible_text,
            )
            async for event in manager.assistant_runtime.stream_interactive(request):
                yield event
            return
        if _supports_cli_runtime(profile):
            if cluster and not profile.cluster.enabled:
                _raise(409, "cluster_not_enabled", "该 Bot 未启用集群模式")
            cluster_run = None
            if cluster:
                cluster_run = _CLUSTER_RUNTIME.start_run(
                    ClusterRunRequest(
                        bot_alias=alias,
                        user_id=user_id,
                        profile=profile,
                        mentions=list(mentions or []),
                    )
                )
            run_status = "completed"
            try:
                async for event in _stream_cli_chat(
                    manager,
                    alias,
                    user_id,
                    user_text,
                    agent_id=agent_id,
                    cluster_run_id=cluster_run.run_id if cluster_run else "",
                    cluster_mentions=list(mentions or []),
                ):
                    if event.get("type") == "error":
                        run_status = "error"
                    yield event
            except Exception:
                run_status = "error"
                raise
            finally:
                if cluster_run:
                    _CLUSTER_RUNTIME.finish_run(cluster_run.run_id, run_status)
                    _cleanup_cluster_run_control_if_idle(cluster_run.run_id)
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


def build_assistant_run_request(
    alias: str,
    user_id: int,
    user_text: str,
    *,
    task_mode: str = "standard",
    task_payload: dict[str, Any] | None = None,
    visible_text: str | None = None,
) -> AssistantRunRequest:
    return AssistantRunRequest(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        source="web",
        bot_alias=alias,
        user_id=user_id,
        text=user_text,
        interactive=True,
        visible_text=visible_text if visible_text is not None else user_text,
        task_mode=task_mode if task_mode in {"standard", "dream", "proposal_patch"} else "standard",
        task_payload=task_payload,
    )


def _ensure_proposal_patch_chat_available(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
) -> None:
    session = get_session_for_alias(manager, alias, user_id)
    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", "聊天正忙，等会再试")
    runtime = manager.assistant_runtime
    if runtime is None:
        return
    snapshot = runtime.snapshot_for_bot(alias)
    if int(snapshot.get("pending_count") or 0) > 0:
        _raise(409, "session_busy", "聊天正忙，等会再试")


async def _stream_assistant_proposal_patch_request(
    manager: MultiBotManager,
    request: AssistantRunRequest,
) -> AsyncIterator[dict[str, Any]]:
    profile = get_profile_or_raise(manager, request.bot_alias)
    session = get_session_for_alias(manager, request.bot_alias, request.user_id)
    home = _assistant_home_or_raise(manager, request.bot_alias)
    proposal_id, target_alias, regenerate = _proposal_patch_request_payload(request)
    if not proposal_id:
        _raise(400, "missing_proposal_id", "缺少 proposal_id")
    if not target_alias:
        _raise(400, "missing_target_alias", "缺少 target_alias")
    try:
        proposal = get_proposal(home, proposal_id)
    except FileNotFoundError as exc:
        _raise(404, "proposal_not_found", str(exc))
    if proposal.get("status") != "approved":
        _raise(409, "proposal_not_approved", "proposal 尚未批准，不能生成 patch")
    try:
        target = resolve_upgrade_target(manager, target_alias)
    except KeyError:
        _raise(404, "upgrade_target_not_found", target_alias)
    if not target.get("available"):
        _raise_unavailable_upgrade_target(target)

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.stop_requested = False
        session.is_processing = True

    try:
        service = _get_chat_history_service(session)
        turn_handle = service.start_turn(
            profile=profile,
            session=session,
            user_text=str(request.visible_text or request.text or "").strip(),
            native_provider=profile.cli_type,
            assistant_home=str(home.root),
            managed_prompt_hash=session.managed_prompt_hash_seen,
            prompt_surface_version="v1",
        )
        started_at = time.perf_counter()
        event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        worker_done = threading.Event()
        preview_text = ""
    except Exception:
        with session._lock:
            session.is_processing = False
        raise

    def on_event(event: dict[str, Any]) -> None:
        event_queue.put(dict(event))

    def run_generation() -> None:
        try:
            metadata = generate_pending_patch(
                home,
                proposal,
                target=target,
                generated_by=str(request.user_id),
                regenerate=regenerate,
                event_callback=on_event,
            )
            summary = _build_patch_generation_summary(metadata)
            done_message = service.complete_turn(
                turn_handle,
                content=summary,
                completion_state="completed",
            )
            persisted = _persist_patch_chat_conclusion(
                home,
                proposal_id,
                metadata,
                summary=summary,
                message_id=str(done_message.get("id") or ""),
            )
            event_queue.put({
                "type": "done",
                "metadata": persisted or metadata,
                "output": summary,
                "message": done_message,
                "elapsed_seconds": int(round(max(time.perf_counter() - started_at, 0))),
            })
        except Exception as exc:
            error_message = _normalize_error_message(exc).strip() or "patch_generation_failed"
            metadata_dict = read_upgrade_metadata(home, proposal_id, "pending")
            summary = _build_patch_generation_summary(metadata_dict, error_message=error_message)
            done_message = service.complete_turn(
                turn_handle,
                content=summary,
                completion_state="failed",
                error_code="patch_generation_failed",
                error_message=error_message,
            )
            persisted = _persist_patch_chat_conclusion(
                home,
                proposal_id,
                metadata_dict,
                summary=summary,
                message_id=str(done_message.get("id") or ""),
            )
            event_queue.put({
                "type": "done",
                "metadata": persisted or metadata_dict or {},
                "output": summary,
                "message": done_message,
                "elapsed_seconds": int(round(max(time.perf_counter() - started_at, 0))),
            })
        finally:
            with session._lock:
                session.is_processing = False
            worker_done.set()

    try:
        threading.Thread(target=run_generation, daemon=True).start()
    except Exception:
        with session._lock:
            session.is_processing = False
        raise

    while not worker_done.is_set() or not event_queue.empty():
        try:
            item = event_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue

        item_type = str(item.get("type") or "")
        if item_type == "trace":
            event = dict(item.get("event") or {})
            if event:
                service.append_trace_event(turn_handle, event)
            yield item
            continue
        if item_type == "log":
            preview_text = _append_patch_preview_text(preview_text, str(item.get("text") or ""))
            if preview_text:
                service.replace_assistant_preview(turn_handle, preview_text)
            yield item
            continue
        if item_type == "status":
            preview_text = _append_patch_preview_text(preview_text, str(item.get("message") or ""))
            if preview_text:
                service.replace_assistant_preview(turn_handle, preview_text)
            yield item
            continue
        if item_type == "done":
            yield {
                "type": "done",
                "metadata": dict(item.get("metadata") or {}),
                "output": str(item.get("output") or ""),
                "message": item.get("message"),
                "elapsed_seconds": int(item.get("elapsed_seconds") or round(max(time.perf_counter() - started_at, 0))),
            }
            return
        if item_type == "error":
            error_message = str(item.get("message") or "patch_generation_failed").strip() or "patch_generation_failed"
            metadata = item.get("metadata")
            metadata_dict = dict(metadata) if isinstance(metadata, dict) else read_upgrade_metadata(home, proposal_id, "pending")
            summary = _build_patch_generation_summary(metadata_dict, error_message=error_message)
            done_message = service.complete_turn(
                turn_handle,
                content=summary,
                completion_state="failed",
                error_code=str(item.get("code") or "patch_generation_failed"),
                error_message=error_message,
            )
            persisted = _persist_patch_chat_conclusion(
                home,
                proposal_id,
                metadata_dict,
                summary=summary,
                message_id=str(done_message.get("id") or ""),
            )
            yield {
                "type": "done",
                "metadata": persisted or metadata_dict or {},
                "output": summary,
                "message": done_message,
                "elapsed_seconds": int(round(max(time.perf_counter() - started_at, 0))),
            }
            return
    return


async def execute_assistant_run_request(manager: MultiBotManager, request: AssistantRunRequest) -> dict[str, Any]:
    if _is_proposal_patch_request(request):
        async for event in _stream_assistant_proposal_patch_request(manager, request):
            if str(event.get("type") or "") == "done":
                return {key: value for key, value in event.items() if key != "type"}
        return {"output": "", "message": None, "metadata": None}
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
    if _is_proposal_patch_request(request):
        async for event in _stream_assistant_proposal_patch_request(manager, request):
            yield event
        return
    async for event in _stream_cli_chat(
        manager,
        request.bot_alias,
        request.user_id,
        request.text,
        request=request,
    ):
        yield event


def get_terminal_actions_config(manager: MultiBotManager, alias: str, auth: AuthContext) -> dict[str, Any]:
    _require_capability(auth, CAP_TERMINAL_EXEC)
    profile = get_profile_or_raise(manager, alias)
    result = load_terminal_actions_config(profile.working_dir)
    return serialize_terminal_actions_config(result, editable=CAP_WRITE_FILES in auth.capabilities)


def save_terminal_actions_config_for_bot(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _require_capability(auth, CAP_WRITE_FILES)
    profile = get_profile_or_raise(manager, alias)
    try:
        result = save_terminal_actions_config(
            profile.working_dir,
            dict(payload.get("config") or {}),
            expected_mtime_ns=str(payload.get("expectedMtimeNs") or ""),
        )
    except TerminalActionConfigConflict as exc:
        _raise(409, "terminal_actions_conflict", str(exc))
    except TerminalActionValidationError as exc:
        _raise(400, "invalid_terminal_actions_config", str(exc))
    return serialize_terminal_actions_config(result, editable=True)


def resolve_terminal_action_for_bot(
    manager: MultiBotManager,
    alias: str,
    auth: AuthContext,
    action_id: str,
    *,
    confirmed: bool,
):
    _require_capability(auth, CAP_TERMINAL_EXEC)
    profile = get_profile_or_raise(manager, alias)
    try:
        return resolve_terminal_action(profile.working_dir, action_id, confirmed=confirmed)
    except KeyError as exc:
        _raise(404, "terminal_action_not_found", str(exc))
    except TerminalActionValidationError as exc:
        if "需要确认" in str(exc):
            _raise(409, "terminal_action_confirmation_required", str(exc))
        _raise(400, "invalid_terminal_action", str(exc))


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


async def remove_managed_bot_with_history(
    manager: MultiBotManager,
    alias: str,
    *,
    delete_history: bool = False,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    bot_id = resolve_session_bot_id(manager, alias)
    history_deleted = 0
    if delete_history:
        history_deleted = ChatStore(Path(profile.working_dir)).delete_bot_history(bot_id=bot_id)
        clear_bot_sessions(bot_id)
    await manager.remove_bot(alias)
    return {
        "removed": True,
        "alias": alias,
        "history_deleted": bool(delete_history),
        "history_deleted_count": history_deleted,
    }


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
        session.active_conversation_id = None
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
