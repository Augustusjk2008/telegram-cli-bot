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
from concurrent.futures import ThreadPoolExecutor
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
from bot import app_settings
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
    migrate_assistant_runtime_state_to_shared,
    record_assistant_capture,
    restore_assistant_runtime_state,
)
from bot.agents import build_agent_prompt_input
from bot.chat_identity import chat_session_user_id
from bot.cli_params import (
    CliParamsConfig,
    clamp_unsafe_cli_params,
    get_default_params,
    get_params_schema,
    normalize_cli_model_options,
    with_global_extra_args,
)
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
    build_pi_mcp_self_test_command,
    get_pi_cluster_extension_path,
    prepare_cluster_mcp_launcher,
    write_pi_cluster_extension,
)
from bot.prompts import render_prompt
from bot import config
from bot.config import CLI_MODEL_OPTIONS, WEB_PORT
from bot.cli import (
    build_cli_command,
    extract_codex_error_output,
    extract_kimi_error_output,
    normalize_cli_type,
    parse_claude_stream_json_line,
    parse_claude_stream_json_output,
    parse_codex_json_output,
    parse_kimi_stream_json_line,
    parse_kimi_stream_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    should_suggest_reset_codex_session,
)
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import AgentProfile, BotProfile, EXECUTION_MODE_CLI, UserSession, public_native_agent_config
from bot.native_agent import (
    NATIVE_AGENT_PROVIDER,
    get_native_agent_service,
    normalize_execution_mode,
)
from bot.native_agent.configuration import effective_native_agent_config
from bot.native_agent.config_store import (
    find_configured_model,
    get_pi_models_path,
    get_pi_settings_path,
    list_configured_models,
    load_native_agent_config,
    save_native_agent_config,
)
from bot.native_agent.legacy_migration import (
    LEGACY_EXECUTION_MODE_REMOVED_MESSAGE,
    is_legacy_execution_mode,
)
from bot.native_agent.pi_rpc_preflight import PiWindowsPreflightRequest, run_pi_windows_preflight
from bot.native_agent.pi_session_store import PiSessionStore, pi_session_key
from bot.native_agent.shadow_git_history import ShadowGitHistory
from bot.platform.output import strip_ansi_escape
from bot.platform.processes import build_chat_cli_process_kwargs, build_hidden_process_kwargs, terminate_process_tree_sync
from bot.platform.subprocess_streams import close_process_streams
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
from bot.utils import is_dangerous_command, split_command_argv
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer
from bot.web.chat_store import ChatStore
from bot.web.cli_context_usage import resolve_cli_context_usage
from bot.web.diagnostics import diag_log_event, diag_log_slow
from bot.web.git_commit_message import truncate_diff_text
from bot.web.native_history_adapter import create_stream_trace_state, consume_stream_trace_chunk
from bot.web.native_history_locator import locate_kimi_transcript
from bot.web.plan_mode import (
    PLAN_MODE_TASK_MODE,
    build_plan_execution_prompt,
    build_plan_mode_prompt,
    is_plan_execution_prompt,
    save_execution_plan,
)
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

_CODEX_EMPTY_PARSED: dict[str, Optional[str]] = {
    "thread_id": None,
    "completed_text": None,
    "delta_text": None,
    "error_text": None,
}

from bot.web.auth_store import CAP_RUN_PLUGINS, CAP_TERMINAL_EXEC, CAP_VIEW_PLUGINS, CAP_WRITE_FILES
from bot.web.files_service import (
    change_working_directory,
    copy_path,
    create_directory,
    create_workdir_directory,
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
    save_chat_attachment_from_chunks,
    save_uploaded_file,
    save_uploaded_file_from_chunks,
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
    uninstall_plugin,
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
CODEX_TERMINATE_GRACE_SECONDS = 1.0
CLI_CONTEXT_USAGE_RESOLVE_TIMEOUT_SECONDS = 0.25
_CLI_CONTEXT_USAGE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cli-context-usage")
@dataclass
class CliAttemptState:
    """单次 CLI 尝试的会话状态。"""

    cli_session_id: Optional[str]
    resume_session: bool
    codex_session_id: Optional[str] = None
    kimi_session_id: Optional[str] = None


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


def _normalize_public_base_path(base_path: str | None) -> str:
    value = str(base_path if base_path is not None else config.WEB_BASE_PATH or "").strip()
    if not value or value == "/":
        return ""
    return f"/{value.strip('/')}"


def _public_asset_url(path: str, *, base_path: str | None = None) -> str:
    normalized_path = f"/{str(path or '').lstrip('/')}"
    base = _normalize_public_base_path(base_path)
    if base and normalized_path != base and not normalized_path.startswith(f"{base}/"):
        return f"{base}{normalized_path}"
    return normalized_path


def list_avatar_assets(*, base_path: str | None = None) -> dict[str, Any]:
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
                    "url": _public_asset_url(f"/assets/avatars/{path.name}", base_path=base_path),
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
    home = bootstrap_assistant_home(profile.working_dir)
    _migrate_assistant_home_to_shared(home)
    return home


def _migrate_assistant_home_to_shared(home: Any) -> None:
    shared_user_id = chat_session_user_id(None)
    migrate_assistant_runtime_state_to_shared(home, shared_user_id)
    AssistantMemoryStore(home).migrate_chat_memories_to_shared(shared_user_id)


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
    shared_user_id = chat_session_user_id(user_id)
    normalized_agent_id = str(agent_id or "main").strip().lower() or "main"
    try:
        agent = profile.get_agent(normalized_agent_id)
    except KeyError:
        _raise(404, "agent_not_found", "未找到 agent")
    if normalized_agent_id == "main":
        return profile, agent, get_session_for_alias(manager, alias, shared_user_id)
    if normalized_agent_id != "main" and profile.bot_mode != "cli":
        _raise(400, "agent_not_supported", "仅 CLI Bot 支持子 agent")
    session = get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=shared_user_id,
        default_working_dir=profile.working_dir,
        load_persisted_state=profile.bot_mode != "assistant",
        agent_id=agent.id,
    )
    return profile, agent, align_session_paths(session, profile.working_dir, profile.bot_mode)


def _supports_cli_runtime(profile: BotProfile) -> bool:
    return profile.bot_mode in ("cli", "assistant")


def _supports_native_agent_runtime(profile: BotProfile) -> bool:
    modes = {
        str(mode or "").strip().lower()
        for mode in list(getattr(profile, "supported_execution_modes", []) or [])
        if str(mode or "").strip()
    }
    default_mode = str(getattr(profile, "default_execution_mode", "") or "").strip().lower()
    return NATIVE_AGENT_PROVIDER in modes or default_mode == NATIVE_AGENT_PROVIDER


def _build_session_ids(session: UserSession) -> dict[str, Any]:
    return {
        "codex_session_id": session.codex_session_id,
        "claude_session_id": session.claude_session_id,
        "kimi_session_id": session.kimi_session_id,
        "native_agent_session_id": session.native_agent_session_id,
        "claude_session_initialized": session.claude_session_initialized,
    }


def _clear_native_agent_session_locked(session: UserSession) -> bool:
    changed = bool(
        session.native_agent_session_id
        or session.native_agent_run_id
        or session.native_agent_server_key
    )
    session.native_agent_session_id = None
    session.native_agent_run_id = None
    session.native_agent_server_key = None
    return changed


def _clear_all_native_sessions_locked(session: UserSession) -> bool:
    changed = bool(
        session.codex_session_id
        or session.claude_session_id
        or session.kimi_session_id
        or session.claude_session_initialized
    )
    session.codex_session_id = None
    session.claude_session_id = None
    session.kimi_session_id = None
    session.claude_session_initialized = False
    return _clear_native_agent_session_locked(session) or changed


def _build_running_reply_snapshot(session: UserSession) -> Optional[dict[str, Any]]:
    if not session.running_started_at:
        return None
    return {
        "user_text": session.running_user_text or "",
        "preview_text": session.running_preview_text or "",
        "started_at": session.running_started_at,
        "updated_at": session.running_updated_at or session.running_started_at,
    }


def _get_chat_store(session: UserSession) -> ChatStore:
    store = ChatStore(Path(session.working_dir))
    store.migrate_conversations_to_shared(session.bot_id, chat_session_user_id(session.user_id))
    return store


def _get_chat_history_service(session: UserSession) -> ChatHistoryService:
    store = _get_chat_store(session)
    return ChatHistoryService(store)


def _history_service_for_execution_mode(session: UserSession, execution_mode: str) -> ChatHistoryService:
    if execution_mode == NATIVE_AGENT_PROVIDER:
        return ChatHistoryService(_get_chat_store(session), native_provider_filter=NATIVE_AGENT_PROVIDER)
    return ChatHistoryService(_get_chat_store(session), native_provider_exclude=NATIVE_AGENT_PROVIDER)


def _resolve_requested_execution_mode(execution_mode: str, profile: BotProfile) -> str:
    if is_legacy_execution_mode(execution_mode):
        _raise(400, "invalid_execution_mode", LEGACY_EXECUTION_MODE_REMOVED_MESSAGE)
    return normalize_execution_mode(execution_mode, profile)


def _resolve_chat_execution_mode(profile: BotProfile, execution_mode: str) -> str:
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    if resolved_execution_mode == NATIVE_AGENT_PROVIDER and not _supports_native_agent_runtime(profile):
        _raise(409, "native_agent_unavailable", "当前 Bot 未启用原生 agent")
    return resolved_execution_mode


def _should_route_assistant_runtime(task_mode: str, resolved_execution_mode: str) -> bool:
    return task_mode == "proposal_patch" or resolved_execution_mode != NATIVE_AGENT_PROVIDER


def _pi_store() -> PiSessionStore:
    return PiSessionStore()


def _pi_key_for_session(session: UserSession, conversation_id: str) -> str:
    return pi_session_key(
        cwd=session.working_dir,
        bot_id=int(session.bot_id or 0),
        user_id=int(session.user_id or 0),
        conversation_id=conversation_id,
    )


def _safe_pi_workspace_meta(record: Any | None, latest: dict[str, Any] | None = None) -> dict[str, Any]:
    latest = latest if isinstance(latest, dict) else {}
    head = str(getattr(record, "workspace_history_head", "") or latest.get("workspace_history_head") or "").strip()
    linear_index = int(getattr(record, "linear_index", 0) or latest.get("linear_index") or 0)
    degraded = bool(getattr(record, "degraded", False)) if record is not None else False
    degraded_reason = str(getattr(record, "degraded_reason", "") or "")
    return {
        "workspace_history_head": head,
        "linear_index": linear_index,
        "rollback_supported": bool(head and not degraded),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


def get_file_browser_directory(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = _require_real_browser_directory(_get_browser_directory(session))
    return {"working_dir": browser_dir}


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
    _ = user_id
    result: dict[str, dict[str, Any]] = {}
    with sessions_lock:
        for (session_bot_id, session_user_id, session_agent_id), session in sessions.items():
            if session_bot_id != bot_id or session_user_id != chat_session_user_id(session_user_id):
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

    # 优先使用共享聊天 session 的工作目录（如果已建立）
    working_dir = profile.working_dir
    if user_id is not None:
        try:
            current_session = session or get_session_for_alias(manager, alias, chat_session_user_id(user_id))
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
        "supported_execution_modes": list(profile.supported_execution_modes),
        "default_execution_mode": profile.default_execution_mode,
        "native_agent": public_native_agent_config(effective_native_agent_config(profile.native_agent)),
        "working_dir": working_dir,
        "avatar_name": profile.avatar_name or "",
        "prompt_presets": [dict(item) for item in profile.prompt_presets],
        "global_prompt_presets": app_settings.get_global_prompt_presets(manager.app_settings_file),
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


def get_overview(manager: MultiBotManager, alias: str, user_id: int, agent_id: str = "main", execution_mode: str = "") -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    bot_id = resolve_session_bot_id(manager, alias)
    active_cluster_run = _find_active_cluster_run_for_session(alias, user_id, session)
    history_service = _history_service_for_execution_mode(session, resolved_execution_mode)
    return {
        "bot": {
            **build_bot_summary(manager, alias, user_id, profile=profile, session=session),
            "execution_mode": resolved_execution_mode,
        },
        "session": history_service.build_session_snapshot(profile, session),
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


def _cluster_launcher_path() -> Path:
    launcher_name = "tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh"
    return Path.home() / ".tcb" / "bin" / launcher_name


def _cluster_mcp_config_path() -> Path:
    return Path.home() / ".tcb" / "cluster-mcp" / "config.json"


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
    launcher_path = _cluster_launcher_path()
    config_path = _cluster_mcp_config_path()
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


def _profile_cluster_active_cli_type(profile: BotProfile) -> str:
    supported_modes = {
        str(mode or "").strip().lower()
        for mode in list(getattr(profile, "supported_execution_modes", []) or [])
        if str(mode or "").strip()
    }
    default_mode = str(getattr(profile, "default_execution_mode", "") or "").strip().lower()
    if default_mode == NATIVE_AGENT_PROVIDER or supported_modes == {NATIVE_AGENT_PROVIDER}:
        return "pi"
    try:
        return normalize_cli_type(profile.cli_type)
    except ValueError:
        return ""


def _same_path(left: Path, right: Path) -> bool:
    try:
        return str(left.expanduser().resolve()).lower() == str(right.expanduser().resolve()).lower()
    except OSError:
        return str(left.expanduser()).lower() == str(right.expanduser()).lower()


def _pi_mcp_command_points_to_launcher(command: Any, launcher_path: Path) -> bool:
    if isinstance(command, str):
        candidate = command
    elif isinstance(command, list) and command:
        candidate = command[0]
    else:
        return False
    return _same_path(Path(str(candidate or "")), launcher_path)


def _cluster_pi_mcp_target_status(*, active_cli_type: str) -> dict[str, str]:
    if active_cli_type != "pi":
        return _cluster_inactive_target_status()
    config_path = _cluster_mcp_config_path()
    runtime_status = _cluster_runtime_mcp_status()
    if runtime_status["state"] != "runtime_ready":
        return runtime_status
    extension_path = get_pi_cluster_extension_path()
    if not extension_path.exists():
        return {"state": "mcp_missing", "message": f"未安装 Pi 集群扩展: {extension_path}"}
    command = build_pi_mcp_self_test_command(config_path)
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
        return {"state": "broken", "message": "未找到 Python，无法自检"}
    except subprocess.TimeoutExpired:
        return {"state": "broken", "message": "Pi 集群扩展自检超时"}
    except OSError as exc:
        return {"state": "broken", "message": str(exc)}
    if completed.returncode != 0:
        output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
        return {"state": "broken", "message": output or "Pi 集群扩展自检失败"}
    return {"state": "installed", "message": "Pi 集群扩展已配置"}


def get_cluster_status(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    active_cli_type = _profile_cluster_active_cli_type(profile)
    return {
        "enabled": bool(profile.cluster.enabled),
        "model_tiers": dict(profile.cluster.model_tiers),
        "mcp": {
            "server_name": CLUSTER_MCP_SERVER_NAME,
            "active_cli_type": active_cli_type,
            "runtime": _cluster_runtime_mcp_status(),
            "codex": _cluster_mcp_target_status(profile, "codex", active_cli_type=active_cli_type),
            "claude": _cluster_mcp_target_status(profile, "claude", active_cli_type=active_cli_type),
            "kimi": _cluster_mcp_target_status(profile, "kimi", active_cli_type=active_cli_type),
            "pi": _cluster_pi_mcp_target_status(active_cli_type=active_cli_type),
        },
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "enabled": agent.enabled,
                "allow_cluster": agent.cluster.allow_cluster,
                "allow_write": agent.cluster.allow_write,
                "session_policy": agent.cluster.session_policy,
                "timeout_seconds": agent.cluster.timeout_seconds,
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
    active_cli_type = _profile_cluster_active_cli_type(profile)
    if active_cli_type == "pi":
        extension_path = write_pi_cluster_extension(repo_root=_REPO_ROOT)
        return {
            **launcher.to_dict(),
            "install_command": [],
            "verify_command": [],
            "remove_command": [],
            "pi_extension_path": str(extension_path),
            "pi_extension_name": "tcb-cluster.ts",
            "self_test_command": build_pi_mcp_self_test_command(launcher.config_path),
        }
    cli_type = active_cli_type if active_cli_type in {"codex", "claude", "kimi"} else profile.cli_type
    return {
        **launcher.to_dict(),
        "install_command": build_cli_install_command(
            cli_type=cli_type,
            cli_path=profile.cli_path,
            launcher_path=launcher.launcher_path,
        ),
        "verify_command": build_cli_verify_command(cli_type, profile.cli_path),
        "remove_command": build_cli_remove_command(cli_type, profile.cli_path),
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
    include_messages: bool = False,
    message_limit: int = 20,
) -> dict[str, Any]:
    user_id = chat_session_user_id(user_id)
    run = _CLUSTER_RUNTIME.get_run(run_id)
    if run is None or run.bot_alias != alias or run.user_id != user_id:
        _raise(404, "cluster_run_not_found", "未找到集群任务")
    _ = get_profile_or_raise(manager, alias)
    return _CLUSTER_RUNTIME.build_task_status(
        run_id,
        task_ids,
        include_output=include_output,
        include_messages=include_messages,
        message_limit=message_limit,
    )


def _cluster_task_wait_seconds(payload: dict[str, Any]) -> float:
    raw = payload.get("wait_seconds", payload.get("waitSeconds", 0))
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 0.0
    return max(0.0, min(60.0, seconds))


def _cluster_wait_seconds(payload: dict[str, Any]) -> float:
    raw = payload.get("wait_seconds", payload.get("waitSeconds", 60))
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = 60.0
    return max(1.0, min(300.0, seconds))


def _cluster_task_message_limit(payload: dict[str, Any]) -> int:
    raw = payload.get("message_limit", payload.get("messageLimit", 20))
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 20
    return max(1, min(100, limit))


def _cluster_after_sequence(payload: dict[str, Any], run_id: str) -> int:
    if "after_sequence" in payload or "afterSequence" in payload:
        raw = payload.get("after_sequence", payload.get("afterSequence", 0))
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0
    return _CLUSTER_RUNTIME.agent_message_read_sequence(run_id)


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
        run = _CLUSTER_RUNTIME.get_run(run_id)
        if run is None:
            _raise(404, "cluster_run_not_found", "未找到集群任务")
        current_profile = get_profile_or_raise(manager, run.bot_alias)
        if not current_profile.cluster.enabled:
            _raise(409, "cluster_not_enabled", "该 Bot 未启用集群模式")

        if tool_name == "cluster_status":
            return {"ok": True, "data": _CLUSTER_RUNTIME.build_status(run_id)}
        if tool_name == "list_agents":
            return {"ok": True, "data": _CLUSTER_RUNTIME.build_status(run_id)["agents"]}
        if tool_name == "poll_agent_tasks":
            raw_task_ids = payload.get("task_ids", payload.get("taskIds"))
            task_ids = [str(item) for item in raw_task_ids] if isinstance(raw_task_ids, list) else None
            include_output = payload.get("include_output", payload.get("includeOutput", True)) is not False
            include_messages = payload.get("include_messages", payload.get("includeMessages", True)) is not False
            await _wait_for_cluster_tasks_if_requested(run_id, task_ids, _cluster_task_wait_seconds(payload))
            return {
                "ok": True,
                "data": _CLUSTER_RUNTIME.build_task_status(
                    run_id,
                    task_ids,
                    include_output=include_output,
                    include_messages=include_messages,
                    message_limit=_cluster_task_message_limit(payload),
                ),
            }
        if tool_name == "wait_agent_messages":
            uses_managed_cursor = "after_sequence" not in payload and "afterSequence" not in payload
            result = await _CLUSTER_RUNTIME.wait_agent_messages(
                run_id,
                after_sequence=_cluster_after_sequence(payload, run_id),
                wait_seconds=_cluster_wait_seconds(payload),
                include_progress=payload.get("include_progress", payload.get("includeProgress", True)) is not False,
                include_final=payload.get("include_final", payload.get("includeFinal", True)) is not False,
                message_limit=_cluster_task_message_limit(payload),
            )
            if uses_managed_cursor and result.get("messages"):
                _CLUSTER_RUNTIME.mark_agent_messages_read(run_id, result.get("cursor", 0))
            return {"ok": True, "data": result}
        if tool_name != "ask_agent":
            _raise(404, "cluster_tool_not_found", "未知集群工具")

        request = _CLUSTER_RUNTIME.validate_ask_agent(run_id, payload)
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
                "timeout_seconds": task.timeout_seconds,
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


def get_native_agent_config_payload() -> dict[str, Any]:
    try:
        native_config = load_native_agent_config()
    except ValueError as exc:
        _raise(400, "invalid_native_agent_config", str(exc))
    return {
        "config": native_config,
        "backend": "pi",
        "config_path": str(get_pi_settings_path()),
        "models_path": str(get_pi_models_path()),
        "workspace_history_enabled": bool(native_config.get("workspace_history_enabled", True)),
        "models": list_configured_models(native_config),
        "selected_model": str(native_config.get("model") or native_config.get("selected_model") or "").strip(),
        "selected_reasoning_effort": str(native_config.get("reasoning_effort") or "").strip(),
        "needs_restart": False,
        "preflight": get_native_agent_preflight_payload(native_config=native_config),
    }


def get_native_agent_preflight_payload(
    *,
    cwd: str = "",
    pi_command: str = "",
    native_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        resolved_config = native_config if native_config is not None else load_native_agent_config()
    except ValueError as exc:
        _raise(400, "invalid_native_agent_config", str(exc))
    command = str(
        pi_command
        or resolved_config.get("pi_command")
        or config.NATIVE_AGENT_PI_COMMAND
        or config.NATIVE_AGENT_COMMAND
        or "pi"
    ).strip() or "pi"
    workspace_history_enabled = resolved_config.get("workspace_history_enabled", True)
    return run_pi_windows_preflight(
        PiWindowsPreflightRequest(
            cwd=Path(cwd or Path.cwd()),
            pi_command=command,
            workspace_history_enabled=bool(workspace_history_enabled) if workspace_history_enabled is not None else None,
        )
    )


def update_native_agent_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_config = payload.get("config", payload)
    if not isinstance(raw_config, dict):
        _raise(400, "invalid_native_agent_config", "原生 Agent 配置必须是 JSON 对象")
    try:
        return save_native_agent_config(raw_config)
    except ValueError as exc:
        _raise(400, "invalid_native_agent_config", str(exc))


def get_native_agent_models_payload(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    models = list_configured_models()
    selected_model = str(profile.native_agent.get("model") or profile.native_agent.get("native_agent_model") or "").strip()
    if not selected_model and models:
        selected_model = str(models[0].get("id") or "")
    selected_item = _find_native_agent_model_item(models, selected_model)
    effective_config = effective_native_agent_config(profile.native_agent)
    selected_reasoning_effort = str(
        profile.native_agent.get("reasoning_effort")
        or effective_config.get("reasoning_effort")
        or ""
    ).strip()
    selected_reasoning_effort = _normalize_selected_reasoning_effort(selected_item, selected_reasoning_effort)
    return {
        "items": models,
        "selected_model": selected_model,
        "selected_reasoning_effort": selected_reasoning_effort,
    }


async def update_bot_native_agent_model(
    manager: MultiBotManager,
    alias: str,
    model: Any,
    reasoning_effort: Any = None,
) -> dict[str, Any]:
    selected_model = str(model or "").strip()
    selected_reasoning_effort = str(reasoning_effort or "").strip()
    if not selected_model:
        _raise(400, "missing_native_agent_model", "模型不能为空")
    configured_model = find_configured_model(selected_model)
    if configured_model is None:
        _raise(400, "invalid_native_agent_model", f"模型未在原生 Agent 配置中找到: {selected_model}")
    reasoning_efforts = [
        str(item or "").strip()
        for item in configured_model.get("reasoning_efforts", [])
        if str(item or "").strip()
    ]
    if selected_reasoning_effort and selected_reasoning_effort not in reasoning_efforts:
        _raise(400, "invalid_native_agent_reasoning_effort", f"推理强度不可用于模型: {selected_reasoning_effort}")
    try:
        await manager.set_bot_native_agent_model(alias, selected_model, selected_reasoning_effort)
    except ValueError as exc:
        _raise(400, "invalid_native_agent_model", str(exc))
    return {
        **get_native_agent_models_payload(manager, alias),
        "bot": build_bot_summary(manager, alias),
    }


def _find_native_agent_model_item(models: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    for item in models:
        if str(item.get("id") or "") == model_id:
            return item
    return None


def _normalize_selected_reasoning_effort(model: dict[str, Any] | None, selected: str) -> str:
    if model is None:
        return ""
    efforts = [str(item or "").strip() for item in model.get("reasoning_efforts", []) if str(item or "").strip()]
    if not efforts:
        return ""
    if selected in efforts:
        return selected
    default_effort = str(model.get("default_reasoning_effort") or "").strip()
    if default_effort in efforts:
        return default_effort
    return efforts[0]


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
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    service = _history_service_for_execution_mode(session, resolved_execution_mode)
    return {"items": service.list_history(profile, session, limit=max(1, limit))}


def _conversation_execution_mode(conversation: dict[str, Any]) -> str:
    return NATIVE_AGENT_PROVIDER if str(conversation.get("native_provider") or "").strip().lower() == NATIVE_AGENT_PROVIDER else "cli"


def _ensure_conversation_execution_mode(conversation: dict[str, Any], requested_execution_mode: str) -> str:
    conversation_mode = _conversation_execution_mode(conversation)
    if requested_execution_mode == NATIVE_AGENT_PROVIDER and conversation_mode != NATIVE_AGENT_PROVIDER:
        _raise(409, "conversation_execution_mode_mismatch", "会话执行模式和当前选择不一致")
    if requested_execution_mode != NATIVE_AGENT_PROVIDER and conversation_mode == NATIVE_AGENT_PROVIDER:
        _raise(409, "conversation_execution_mode_mismatch", "会话执行模式和当前选择不一致")
    return conversation_mode


def _active_conversation_matches_execution_mode(
    store: ChatStore,
    conversation_id: str,
    execution_mode: str,
) -> bool:
    normalized_id = str(conversation_id or "").strip()
    if not normalized_id:
        return False
    try:
        provider = store.get_conversation_native_provider(normalized_id)
    except KeyError:
        return True
    conversation_mode = NATIVE_AGENT_PROVIDER if str(provider or "").strip().lower() == NATIVE_AGENT_PROVIDER else EXECUTION_MODE_CLI
    return conversation_mode == execution_mode


def list_conversations(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    limit: int = 50,
    query: str = "",
    agent_id: str = "main",
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    store = _get_chat_store(session)
    active_id = str(getattr(session, "active_conversation_id", "") or "")
    visible_active_id = active_id if _active_conversation_matches_execution_mode(store, active_id, resolved_execution_mode) else ""
    items = store.list_conversations(
        bot_id=session.bot_id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        working_dir=session.working_dir,
        limit=max(1, limit),
        query=query,
        native_provider=NATIVE_AGENT_PROVIDER if resolved_execution_mode == NATIVE_AGENT_PROVIDER else None,
        native_provider_exclude=NATIVE_AGENT_PROVIDER if resolved_execution_mode != NATIVE_AGENT_PROVIDER else None,
    )
    pi_store = _pi_store() if resolved_execution_mode == NATIVE_AGENT_PROVIDER else None

    def decorate(item: dict[str, Any]) -> dict[str, Any]:
        workspace_meta: dict[str, Any] = {}
        if pi_store is not None:
            conversation_id = str(item.get("id") or "")
            workspace_meta = _safe_pi_workspace_meta(
                pi_store.get(_pi_key_for_session(session, conversation_id)),
                store.latest_active_workspace_history(conversation_id),
            )
        return {
            **item,
            **workspace_meta,
            "active": str(item.get("id") or "") == visible_active_id,
            "bot_mode": str(item.get("bot_mode") or profile.bot_mode),
            "execution_mode": _conversation_execution_mode(item),
        }

    return {
        "items": [decorate(item) for item in items],
        "active_conversation_id": visible_active_id,
        "execution_mode": resolved_execution_mode,
    }


def _create_agent_conversation(
    profile: BotProfile,
    session: UserSession,
    *,
    title: str = "",
    execution_mode: str = "",
) -> tuple[ChatStore, str]:
    store = _get_chat_store(session)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    native_provider = NATIVE_AGENT_PROVIDER if resolved_execution_mode == NATIVE_AGENT_PROVIDER else normalize_cli_type(profile.cli_type)
    conversation_id = store.create_conversation(
        bot_id=session.bot_id,
        bot_alias=session.bot_alias,
        user_id=session.user_id,
        agent_id=session.agent_id,
        bot_mode=profile.bot_mode,
        cli_type=profile.cli_type,
        working_dir=session.working_dir,
        session_epoch=max(0, int(getattr(session, "session_epoch", 0) or 0)),
        native_provider=native_provider,
        title=title,
    )
    with session._lock:
        session.active_conversation_id = conversation_id
        _clear_all_native_sessions_locked(session)
        if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
            _clear_native_agent_session_locked(session)
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
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    with session._lock:
        is_processing = bool(session.is_processing)
    if is_processing:
        _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    if session.agent_id == "main" and resolved_execution_mode != NATIVE_AGENT_PROVIDER:
        _create_cluster_child_conversations(manager, alias, user_id, profile)
    store, conversation_id = _create_agent_conversation(profile, session, title=title, execution_mode=resolved_execution_mode)
    return {
        "conversation": {
            **store.get_conversation(conversation_id),
            "active": True,
            "bot_mode": profile.bot_mode,
            "agent_id": session.agent_id,
            "execution_mode": resolved_execution_mode,
        },
        "messages": [],
    }


def select_conversation(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    conversation_id: str,
    agent_id: str = "main",
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    requested_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    with session._lock:
        is_processing = bool(session.is_processing)
    if is_processing:
        _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    store = _get_chat_store(session)
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
    if str(conversation.get("native_provider") or "").strip().lower() == NATIVE_AGENT_PROVIDER:
        native_provider = NATIVE_AGENT_PROVIDER
    conversation_execution_mode = _ensure_conversation_execution_mode(conversation, requested_execution_mode)
    native_session_id = str(conversation.get("native_session_id") or "").strip()
    workspace_meta: dict[str, Any] = {}
    if native_provider == NATIVE_AGENT_PROVIDER:
        pi_store = _pi_store()
        record = pi_store.get(_pi_key_for_session(session, str(conversation["id"])))
        if record is not None and record.pi_session_id:
            native_session_id = record.pi_session_id
        workspace_meta = _safe_pi_workspace_meta(
            record,
            store.latest_active_workspace_history(str(conversation["id"])),
        )
    with session._lock:
        session.active_conversation_id = str(conversation["id"])
        _clear_all_native_sessions_locked(session)
        if native_provider == "codex":
            session.codex_session_id = native_session_id or None
        if native_provider == "claude":
            session.claude_session_id = native_session_id or None
            session.claude_session_initialized = bool(native_session_id)
        if native_provider == "kimi":
            session.kimi_session_id = native_session_id or None
        if native_provider == NATIVE_AGENT_PROVIDER:
            session.native_agent_session_id = native_session_id or None
            session.native_agent_server_key = None
    session.persist()

    messages = _history_service_for_execution_mode(session, conversation_execution_mode).list_history(profile, session, limit=50)
    return {
        "conversation": {
            **conversation,
            **workspace_meta,
            "active": True,
            "bot_mode": str(conversation.get("bot_mode") or profile.bot_mode),
            "agent_id": session.agent_id,
            "execution_mode": conversation_execution_mode,
        },
        "messages": messages,
    }


def delete_conversation(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    conversation_id: str,
    *,
    agent_id: str = "main",
    delete_native_session: bool = False,
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    requested_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    with session._lock:
        is_processing = bool(session.is_processing)
    if is_processing:
        _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    store = _get_chat_store(session)
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

    native_cleared = False
    is_active = str(session.active_conversation_id or "") == str(conversation_id or "")
    native_provider = normalize_cli_type(str(conversation.get("native_provider") or profile.cli_type))
    if str(conversation.get("native_provider") or "").strip().lower() == NATIVE_AGENT_PROVIDER:
        native_provider = NATIVE_AGENT_PROVIDER
    _ensure_conversation_execution_mode(conversation, requested_execution_mode)
    native_session_id = str(conversation.get("native_session_id") or "").strip()
    pi_record_deleted = False
    if delete_native_session and native_provider == NATIVE_AGENT_PROVIDER:
        pi_record_deleted = _pi_store().delete_conversation(
            cwd=session.working_dir,
            bot_id=session.bot_id,
            user_id=session.user_id,
            conversation_id=conversation_id,
        )
    with session._lock:
        if is_active:
            session.active_conversation_id = None
            if native_provider == NATIVE_AGENT_PROVIDER and session.native_agent_session_id:
                _clear_native_agent_session_locked(session)
                native_cleared = True
        if delete_native_session and native_session_id:
            if native_provider == "codex" and session.codex_session_id == native_session_id:
                session.codex_session_id = None
                native_cleared = True
            elif native_provider == "claude" and session.claude_session_id == native_session_id:
                session.claude_session_id = None
                session.claude_session_initialized = False
                native_cleared = True
            elif native_provider == "kimi" and session.kimi_session_id == native_session_id:
                session.kimi_session_id = None
                native_cleared = True
            elif native_provider == NATIVE_AGENT_PROVIDER and session.native_agent_session_id == native_session_id:
                _clear_native_agent_session_locked(session)
                native_cleared = True
        if pi_record_deleted:
            native_cleared = True
    session.persist()

    store.delete_conversation_by_id(conversation_id)
    listed = list_conversations(manager, alias, user_id, agent_id=agent_id, execution_mode=requested_execution_mode)
    return {
        "deleted_conversation_id": conversation_id,
        "active_conversation_id": str(session.active_conversation_id or ""),
        "native_session_cleared": native_cleared,
        "items": listed["items"],
        "messages": [] if is_active else None,
    }


def _agent_ids_for_profile(profile: BotProfile) -> list[str]:
    ids: list[str] = []
    for agent in profile.normalized_agents():
        agent_id = str(agent.id or "main").strip().lower() or "main"
        if agent_id not in ids:
            ids.append(agent_id)
    return ids or ["main"]


def delete_all_conversations(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    agent_id: str = "main",
    execution_mode: str = "",
    delete_native_session: bool = False,
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    with session._lock:
        if bool(session.is_processing):
            _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")
        active_conversation_id = str(session.active_conversation_id or "")

    store = _get_chat_store(session)
    native_conversations_to_delete: list[dict[str, Any]] = []
    if delete_native_session and resolved_execution_mode == NATIVE_AGENT_PROVIDER:
        native_conversations_to_delete = store.list_conversations(
            bot_id=session.bot_id,
            user_id=session.user_id,
            working_dir=session.working_dir,
            agent_id=session.agent_id,
            native_provider=NATIVE_AGENT_PROVIDER,
            limit=100,
        )
    deleted_count = store.archive_bot_conversations(
        bot_id=session.bot_id,
        user_id=session.user_id,
        working_dir=session.working_dir,
        agent_id=session.agent_id,
        native_provider=NATIVE_AGENT_PROVIDER if resolved_execution_mode == NATIVE_AGENT_PROVIDER else None,
        native_provider_exclude=NATIVE_AGENT_PROVIDER if resolved_execution_mode != NATIVE_AGENT_PROVIDER else None,
    )
    if native_conversations_to_delete:
        pi_store = _pi_store()
        for item in native_conversations_to_delete:
            pi_store.delete_conversation(
                cwd=session.working_dir,
                bot_id=session.bot_id,
                user_id=session.user_id,
                conversation_id=str(item.get("id") or ""),
            )

    native_cleared = False
    with session._lock:
        if _active_conversation_matches_execution_mode(store, active_conversation_id, resolved_execution_mode):
            session.active_conversation_id = None
            session.message_count = 0
        if delete_native_session:
            if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
                if session.native_agent_session_id:
                    _clear_native_agent_session_locked(session)
                    native_cleared = True
            else:
                if session.codex_session_id is not None:
                    session.codex_session_id = None
                    native_cleared = True
                if session.claude_session_id is not None:
                    session.claude_session_id = None
                    session.claude_session_initialized = False
                    native_cleared = True
                if session.kimi_session_id is not None:
                    session.kimi_session_id = None
                    native_cleared = True
    session.persist()

    return {
        "deleted_count": deleted_count,
        "active_conversation_id": str(session.active_conversation_id or ""),
        "native_session_cleared": native_cleared,
        "items": [],
        "messages": [],
    }


def get_history_delta(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    after_id: str,
    limit: int = 50,
    agent_id: str = "main",
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    items = _history_service_for_execution_mode(session, resolved_execution_mode).list_history(profile, session, limit=max(1, limit))
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
    execution_mode: str = "",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    service = _history_service_for_execution_mode(session, resolved_execution_mode)
    data = service.get_message_trace(profile, session, message_id)
    if data is None:
        _raise(404, "trace_not_found", "未找到对应消息的过程详情")
    return data


def _require_native_history_turn(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    conversation_id: str,
    turn_id: str,
    agent_id: str = "main",
) -> tuple[BotProfile, UserSession, ChatStore, dict[str, Any], dict[str, Any]]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = normalize_execution_mode(NATIVE_AGENT_PROVIDER, profile)
    if resolved_execution_mode != NATIVE_AGENT_PROVIDER:
        _raise(409, "native_agent_unavailable", "当前 Bot 未启用原生 agent")
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_conversation_id:
        _raise(400, "missing_conversation_id", "缺少 conversation_id")
    if not normalized_turn_id:
        _raise(400, "missing_turn_id", "缺少 turn_id")

    store = _get_chat_store(session)
    try:
        conversation = store.get_conversation(normalized_conversation_id)
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
    if str(conversation.get("native_provider") or "").strip().lower() != NATIVE_AGENT_PROVIDER:
        _raise(409, "conversation_execution_mode_mismatch", "会话执行模式和当前选择不一致")

    target = store.get_turn_workspace_history(normalized_turn_id)
    if target is None or str(target.get("conversation_id") or "") != normalized_conversation_id:
        _raise(404, "target_turn_not_found", "未找到目标会话点")
    if str(target.get("discarded_at") or "").strip():
        _raise(409, "target_turn_discarded", "目标会话点已被丢弃")
    if not str(target.get("workspace_history_head") or "").strip():
        _raise(409, "workspace_history_head_missing", "目标会话点没有工作区记录")
    return profile, session, store, conversation, target


def get_native_agent_history_changes(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    conversation_id: str,
    turn_id: str,
    agent_id: str = "main",
) -> dict[str, Any]:
    _profile, session, _store, _conversation, target = _require_native_history_turn(
        manager,
        alias,
        user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        agent_id=agent_id,
    )
    try:
        data = ShadowGitHistory().changes(
            cwd=session.working_dir,
            conversation_id=str(conversation_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
        )
    except KeyError:
        _raise(409, "workspace_history_record_missing", "本地工作区记录缺失，请重新开始会话")
    data["linear_index"] = int(data.get("linear_index") or target.get("linear_index") or 0)
    return data


def get_native_agent_history_diff(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    conversation_id: str,
    turn_id: str,
    path: str,
    agent_id: str = "main",
) -> dict[str, Any]:
    _profile, session, _store, _conversation, _target = _require_native_history_turn(
        manager,
        alias,
        user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        agent_id=agent_id,
    )
    try:
        data = ShadowGitHistory().diff(
            cwd=session.working_dir,
            conversation_id=str(conversation_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
            path=path,
        )
    except ValueError:
        _raise(400, "invalid_path", "文件路径无效")
    except KeyError:
        _raise(400, "history_diff_path_invalid", "只能查看该轮会话变更内的文件 diff")
    diff_text, truncated = truncate_diff_text(str(data.get("diff") or ""))
    data["diff"] = diff_text
    data["truncated"] = bool(truncated)
    return data


async def rollback_native_agent_history(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    conversation_id: str,
    target_turn_id: str,
    agent_id: str = "main",
) -> dict[str, Any]:
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    resolved_execution_mode = normalize_execution_mode(NATIVE_AGENT_PROVIDER, profile)
    if resolved_execution_mode != NATIVE_AGENT_PROVIDER:
        _raise(409, "native_agent_unavailable", "当前 Bot 未启用原生 agent")
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_turn_id = str(target_turn_id or "").strip()
    if not normalized_conversation_id:
        _raise(400, "missing_conversation_id", "缺少 conversation_id")
    if not normalized_turn_id:
        _raise(400, "missing_target_turn_id", "缺少 target_turn_id")
    with session._lock:
        if bool(session.is_processing):
            _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    store = _get_chat_store(session)
    try:
        conversation = store.get_conversation(normalized_conversation_id)
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
    if str(conversation.get("native_provider") or "").strip().lower() != NATIVE_AGENT_PROVIDER:
        _raise(409, "conversation_execution_mode_mismatch", "会话执行模式和当前选择不一致")

    target = store.get_turn_workspace_history(normalized_turn_id)
    if target is None or str(target.get("conversation_id") or "") != normalized_conversation_id:
        _raise(404, "target_turn_not_found", "未找到目标会话点")
    if str(target.get("discarded_at") or "").strip():
        _raise(409, "target_turn_discarded", "目标会话点已被丢弃")
    target_head = str(target.get("workspace_history_head") or "").strip()
    if not target_head:
        _raise(409, "workspace_history_head_missing", "目标会话点没有可撤回的工作区记录")

    pi_store = _pi_store()
    pi_key = _pi_key_for_session(session, normalized_conversation_id)
    record = pi_store.get(pi_key)
    if record is None:
        _raise(409, "workspace_history_record_missing", "本地工作区记录缺失，请重新开始会话")
    if record is not None and record.degraded:
        _raise(409, "workspace_history_degraded", record.degraded_reason or "workspace history 状态已降级")
    latest = store.latest_active_workspace_history(normalized_conversation_id)
    latest_head = str((latest or {}).get("workspace_history_head") or "").strip()
    if record is not None and record.workspace_history_head and latest_head and record.workspace_history_head != latest_head:
        _raise(409, "workspace_history_head_drift", "工作区记录和会话历史不一致，请刷新后重试")

    active_cluster_run = _find_active_cluster_run_for_session(alias, user_id, session)
    if active_cluster_run is not None:
        cluster_status = _CLUSTER_RUNTIME.build_task_status(active_cluster_run.run_id, include_output=False)
        pending_count = int(cluster_status.get("pending_count") or 0)
        if pending_count > 0:
            _raise(
                409,
                "cluster_child_task_running",
                "子 agent 正在运行，请等待完成或取消后再撤回",
                {"cluster_run_id": active_cluster_run.run_id, "pending_count": pending_count},
            )

    status = await get_native_agent_service().rollback_workspace_history(
        profile=profile,
        session=session,
        conversation_id=normalized_conversation_id,
        target_head=target_head,
        native_session_id=str(getattr(record, "pi_session_id", "") or conversation.get("native_session_id") or ""),
    )
    if status.degraded:
        pi_store.mark_degraded(pi_key, status.message)
        if int(status.locked_file_count or 0) > 0:
            _raise(
                409,
                "workspace_history_locked",
                "部分文件被占用，无法撤回；请关闭相关程序后重试",
                {"locked_file_count": int(status.locked_file_count or 0)},
            )
        _raise(409, "workspace_history_unavailable", status.message or "workspace history 不可用")
    if status.head and status.head != target_head:
        _raise(409, "workspace_history_head_drift", "工作区撤回结果和目标记录不一致")

    try:
        updated_record = pi_store.mark_discarded_after(pi_key, normalized_turn_id)
    except KeyError:
        _raise(409, "workspace_history_record_missing", "本地工作区记录缺失，请重新开始会话")
    store.mark_turns_after_discarded(normalized_conversation_id, normalized_turn_id)
    store.update_turn_workspace_history(
        normalized_turn_id,
        updated_record.workspace_history_head or target_head,
        updated_record.linear_index or int(target.get("linear_index") or 0),
    )
    with session._lock:
        session.active_conversation_id = normalized_conversation_id
        session.native_agent_session_id = updated_record.pi_session_id or session.native_agent_session_id
        session.native_agent_server_key = None
    session.persist()
    return {
        "conversation_id": normalized_conversation_id,
        "current_turn_id": normalized_turn_id,
        "rollback_supported": False,
        "message": "已撤回到所选会话点；该操作不可撤销",
    }


def reset_user_session(manager: MultiBotManager, alias: str, user_id: int, agent_id: str = "main") -> dict[str, Any]:
    user_id = chat_session_user_id(user_id)
    profile = get_profile_or_raise(manager, alias)
    bot_id = resolve_session_bot_id(manager, alias)
    normalized_agent_id = str(agent_id or "main").strip().lower() or "main"
    state_path = None
    if profile.bot_mode == "assistant" and normalized_agent_id == "main":
        state_path = Path(profile.working_dir) / ".assistant" / "state" / "users" / f"{user_id}.json"

    with sessions_lock:
        session = sessions.get((bot_id, user_id, normalized_agent_id))

    if session is None:
        if profile.bot_mode == "assistant" and (state_path is None or not state_path.exists()):
            return {"reset": reset_session(bot_id, user_id, agent_id=normalized_agent_id)}
        if normalized_agent_id == "main":
            session = get_session_for_alias(manager, alias, user_id)
        else:
            _profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, normalized_agent_id)
    else:
        session = align_session_paths(session, profile.working_dir, profile.bot_mode)

    with session._lock:
        if bool(session.is_processing):
            _raise(409, "conversation_switch_blocked", "当前任务运行中，先终止或等待完成")

    _get_chat_history_service(session).reset_active_conversation(profile, session)
    removed = reset_session(bot_id, user_id, agent_id=normalized_agent_id)
    if profile.bot_mode == "assistant" and normalized_agent_id == "main" and state_path is not None and state_path.exists():
        home = bootstrap_assistant_home(profile.working_dir)
        removed = clear_assistant_runtime_state(home, user_id) or removed
    return {"reset": removed}


def _is_session_processing(session: UserSession) -> bool:
    with session._lock:
        return bool(session.is_processing)


def _find_active_cluster_run_for_session(alias: str, user_id: int, session: UserSession) -> Any | None:
    user_id = chat_session_user_id(user_id)
    for _ in range(100):
        active_run = _CLUSTER_RUNTIME.find_active_run(alias, user_id)
        if active_run is None:
            return None
        status = _CLUSTER_RUNTIME.build_task_status(active_run.run_id, include_output=False)
        if int(status.get("pending_count") or 0) > 0 or _is_session_processing(session):
            return active_run
        _CLUSTER_RUNTIME.finish_run(active_run.run_id, "completed")
    return _CLUSTER_RUNTIME.find_active_run(alias, user_id)


def _finish_stale_cluster_run_if_idle(alias: str, user_id: int) -> str | None:
    user_id = chat_session_user_id(user_id)
    active_run = _CLUSTER_RUNTIME.find_active_run(alias, user_id)
    if active_run is None:
        return None
    status = _CLUSTER_RUNTIME.build_task_status(active_run.run_id, include_output=False)
    if int(status.get("pending_count") or 0) > 0:
        return None
    _CLUSTER_RUNTIME.finish_run(active_run.run_id, "completed")
    return active_run.run_id


async def kill_user_process(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    agent_id: str = "main",
    execution_mode: str = "",
) -> dict[str, Any]:
    user_id = chat_session_user_id(user_id)
    profile = get_profile_or_raise(manager, alias)
    resolved_execution_mode = _resolve_requested_execution_mode(execution_mode, profile)
    normalized_agent_id = str(agent_id or "main").strip().lower() or "main"
    if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
        normalized_agent_id = "main"
    if normalized_agent_id == "main":
        session = get_session_for_alias(manager, alias, user_id)
    else:
        _profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, normalized_agent_id)
    with session._lock:
        is_processing = bool(session.is_processing)
        process = session.process
        native_agent_session_id = str(session.native_agent_session_id or "").strip()
        native_agent_server_key = str(session.native_agent_server_key or "").strip()
        if not is_processing:
            return {"killed": False, "message": msg("kill", "no_task")}
        if process is None and (native_agent_session_id or native_agent_server_key):
            session.stop_requested = True
            stale_cleared = False
        elif process is None:
            session.stop_requested = False
            session.is_processing = False
            session.process = None
            session.running_user_text = None
            session.running_preview_text = ""
            session.running_started_at = None
            session.running_updated_at = None
            stale_cleared = True
        else:
            stale_cleared = False
            session.stop_requested = True

    if stale_cleared:
        _get_chat_history_service(session).reconcile_idle_streaming_turns(session)
        session.persist()
        result = {"killed": False, "message": msg("kill", "already_done"), "stale_cleared": True}
        if cluster_run_id := _finish_stale_cluster_run_if_idle(alias, user_id):
            result["cluster_run_finished"] = cluster_run_id
        return result

    try:
        if process is None and (native_agent_session_id or native_agent_server_key):
            aborted = await get_native_agent_service().abort(session)
            session.persist()
            result = {
                "killed": bool(aborted),
                "message": "已请求原生 agent 停止" if aborted else msg("kill", "already_done"),
                "stop_requested": True,
                "native_agent_aborted": bool(aborted),
            }
            if cluster_run := _find_active_cluster_run_for_session(alias, user_id, session):
                await _cancel_cluster_run(cluster_run.run_id, "主 agent 已停止")
                result["cluster_run_cancelled"] = cluster_run.run_id
            return result
        if process is not None and process.poll() is None:
            _terminate_process_sync(process)
            close_process_streams(process)
            session.persist()
            result = {"killed": True, "message": msg("kill", "killed"), "stop_requested": True}
            if cluster_run := _find_active_cluster_run_for_session(alias, user_id, session):
                await _cancel_cluster_run(cluster_run.run_id, "主 agent 已停止")
                result["cluster_run_cancelled"] = cluster_run.run_id
            return result
        close_process_streams(process)
        with session._lock:
            _reset_session_runtime_flags(session)
        _get_chat_history_service(session).reconcile_idle_streaming_turns(session)
        session.persist()
        result = {"killed": False, "message": msg("kill", "already_done"), "stale_cleared": True}
        if cluster_run_id := _finish_stale_cluster_run_if_idle(alias, user_id):
            result["cluster_run_finished"] = cluster_run_id
        return result
    except Exception as exc:
        _raise(500, "kill_failed", msg("kill", "error", error=str(exc)))


async def reply_native_agent_permission(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    permission_id: str,
    *,
    approved: bool,
    message: str = "",
    agent_id: str = "main",
) -> dict[str, Any]:
    _profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    normalized_permission_id = str(permission_id or "").strip()
    if not normalized_permission_id:
        _raise(400, "permission_required", "缺少权限请求 ID")
    try:
        result = await get_native_agent_service().reply_permission(
            session,
            normalized_permission_id,
            approved=bool(approved),
            message=str(message or ""),
        )
    except RuntimeError as exc:
        _raise(409, "native_agent_permission_unavailable", str(exc))
    except Exception as exc:
        _raise(500, "native_agent_permission_failed", f"原生 agent 权限处理失败: {exc}")
    return {"permission_id": normalized_permission_id, "approved": bool(approved), "result": result}


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


def _filter_claude_host_cluster_extra_args(extra_args: list[str]) -> list[str]:
    filtered: list[str] = []
    skip_next = False
    skip_mcp_values = False
    args_with_values = {"--mcp-config", "--agent", "--agents"}
    args_without_values = {"--strict-mcp-config"}
    for arg in extra_args:
        if skip_mcp_values:
            if not arg.startswith("-"):
                continue
            skip_mcp_values = False
        if skip_next:
            skip_next = False
            continue
        if arg == "--mcp-config":
            skip_mcp_values = True
            continue
        if arg in {"--agent", "--agents"}:
            skip_next = True
            continue
        if any(arg.startswith(f"{name}=") for name in args_with_values):
            continue
        if arg in args_without_values:
            continue
        filtered.append(arg)
    return filtered


def _cluster_mcp_injected_params(profile: BotProfile, params_config: CliParamsConfig) -> CliParamsConfig:
    cli_type = normalize_cli_type(profile.cli_type)
    launcher_name = "tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh"
    home_root = Path.home() / ".tcb"
    launcher_path = home_root / "bin" / launcher_name
    params = params_config.to_dict()
    cli_params = params.setdefault(cli_type, {})
    extra_args = [str(item) for item in cli_params.get("extra_args", []) if str(item).strip()]
    if cli_type == "codex":
        injection = ["-c", f"mcp_servers.{CLUSTER_MCP_SERVER_NAME}.command={_quote_toml_string(str(launcher_path))}"]
    elif cli_type == "claude":
        extra_args = _filter_claude_host_cluster_extra_args(extra_args)
        config = {"mcpServers": {CLUSTER_MCP_SERVER_NAME: {"command": str(launcher_path)}}}
        config_path = home_root / "cluster-mcp" / "mcp_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        injection = ["--mcp-config", str(config_path), "--strict-mcp-config"]
    elif cli_type == "kimi":
        config = {"mcpServers": {CLUSTER_MCP_SERVER_NAME: {"command": str(launcher_path)}}}
        injection = ["--mcp-config", json.dumps(config, ensure_ascii=False)]
    else:
        injection = []
    if injection and not all(arg in extra_args for arg in injection):
        cli_params["extra_args"] = [*extra_args, *injection]
    return CliParamsConfig.from_dict(params)


def _effective_cli_params(
    profile: BotProfile,
    params_config: CliParamsConfig,
    cluster_run_id: str,
    *,
    allow_unsafe_cli: bool = False,
) -> CliParamsConfig:
    params = with_global_extra_args(params_config, config.CLI_GLOBAL_EXTRA_ARGS)
    params = clamp_unsafe_cli_params(params, allow_unsafe_cli=allow_unsafe_cli)
    if cluster_run_id:
        params = _cluster_mcp_injected_params(profile, params)
    return params


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


async def _cancel_cluster_run(run_id: str, message: str = "已取消") -> None:
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return
    run = _CLUSTER_RUNTIME.get_run(normalized_run_id)
    if run is None:
        _CLUSTER_RUN_CONTROLS.pop(normalized_run_id, None)
        return
    _CLUSTER_RUNTIME.cancel_run_tasks(normalized_run_id, message)
    _CLUSTER_RUNTIME.finish_run(normalized_run_id, "cancelled")
    await _CLUSTER_RUNTIME.notify_agent_task_message(normalized_run_id)
    _CLUSTER_RUN_CONTROLS.pop(normalized_run_id, None)


def _start_cluster_run_if_requested(
    *,
    profile: BotProfile,
    alias: str,
    shared_user_id: int,
    cluster: bool,
    execution_mode: str,
    mentions: list[dict[str, Any]] | None,
    allow_unsafe_cli: bool,
):
    if not cluster:
        return None
    if not profile.cluster.enabled:
        _raise(409, "cluster_not_enabled", "该 Bot 未启用集群模式")
    return _CLUSTER_RUNTIME.start_run(
        ClusterRunRequest(
            bot_alias=alias,
            user_id=shared_user_id,
            profile=profile,
            execution_mode=execution_mode,
            mentions=list(mentions or []),
            allow_unsafe_cli=allow_unsafe_cli,
        )
    )


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
                final_output = ""
                returncode = 0
                event_stream = (
                    _stream_native_agent_chat(
                        manager,
                        live_run.bot_alias,
                        live_run.user_id,
                        live_task.message,
                        agent_id=live_task.agent_id,
                        solo_mode=True,
                        allow_unsafe_cli=live_run.allow_unsafe_cli,
                    )
                    if live_run.execution_mode == NATIVE_AGENT_PROVIDER
                    else _stream_cli_chat(
                        manager,
                        live_run.bot_alias,
                        live_run.user_id,
                        live_task.message,
                        agent_id=live_task.agent_id,
                        cli_params_override=build_cluster_cli_params_override(live_run.profile, live_task.model_tier),
                        allow_unsafe_cli=live_run.allow_unsafe_cli,
                    )
                )
                async for event in event_stream:
                    event_type = str(event.get("type") or "")
                    if event_type == "status":
                        progress_text = str(event.get("preview_text") or "").strip()
                        if progress_text:
                            _CLUSTER_RUNTIME.append_agent_task_message(
                                run_id,
                                task_id,
                                kind="progress",
                                content=progress_text,
                            )
                            await _CLUSTER_RUNTIME.notify_agent_task_message(run_id)
                        continue
                    if event_type in {"trace", "meta"}:
                        continue
                    if event_type == "done":
                        final_output = str(event.get("output") or "")
                        raw_returncode = event.get("returncode")
                        returncode = raw_returncode if isinstance(raw_returncode, int) else 0
                        break
                    if event_type == "error":
                        final_output = str(event.get("message") or "")
                        returncode = 1
                        break

                result = {"output": final_output, "returncode": returncode}
                error = _cluster_agent_result_error(result)
                if error:
                    _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, error)
                else:
                    _CLUSTER_RUNTIME.complete_agent_task(run_id, task_id, final_output)
                await _CLUSTER_RUNTIME.notify_agent_task_message(run_id)
    except asyncio.TimeoutError:
        _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, "子 agent 执行超时")
        await _CLUSTER_RUNTIME.notify_agent_task_message(run_id)
    except Exception as exc:
        _CLUSTER_RUNTIME.fail_agent_task(run_id, task_id, str(exc))
        await _CLUSTER_RUNTIME.notify_agent_task_message(run_id)


def _build_cluster_prompt(mentions: list[dict[str, Any]] | None, run_id: str = "") -> str:
    mentioned = ", ".join(
        str(item.get("agent_id") or item.get("agentId") or "").strip()
        for item in (mentions or [])
        if str(item.get("agent_id") or item.get("agentId") or "").strip()
    )
    return render_prompt(
        "cluster_mode",
        run_id=run_id or "无",
        mentioned_agents=mentioned or "无",
    )


def _has_cluster_child_agents(profile: BotProfile) -> bool:
    return any(agent.id != "main" for agent in profile.normalized_agents())


def _build_cluster_disabled_prompt() -> str:
    return render_prompt("cluster_disabled")


def _apply_cluster_prompt(
    profile: BotProfile,
    prompt_text: str,
    *,
    cluster_run_id: str = "",
    cluster_mentions: list[dict[str, Any]] | None = None,
) -> str:
    if cluster_run_id:
        return _build_cluster_prompt(cluster_mentions, cluster_run_id) + prompt_text
    if not profile.cluster.enabled and _has_cluster_child_agents(profile):
        return _build_cluster_disabled_prompt() + prompt_text
    return prompt_text


def _current_native_session_id(session: UserSession, cli_type: str) -> str:
    if str(cli_type or "").strip().lower() == NATIVE_AGENT_PROVIDER:
        return str(session.native_agent_session_id or "").strip()
    normalized = normalize_cli_type(cli_type)
    if normalized == "codex":
        return str(session.codex_session_id or "").strip()
    if normalized == "claude":
        return str(session.claude_session_id or "").strip()
    if normalized == "kimi":
        return str(session.kimi_session_id or "").strip()
    return ""


def _status_context_session_id(
    session: UserSession,
    cli_type: str,
    attempt: CliAttemptState,
    *,
    thread_id: Optional[str] = None,
) -> str:
    normalized = normalize_cli_type(cli_type)
    if normalized == "codex":
        candidate = str(thread_id or attempt.cli_session_id or "").strip()
        if candidate:
            return candidate
        with session._lock:
            return str(session.codex_session_id or "").strip()
    if normalized == "claude":
        candidate = str(attempt.cli_session_id or "").strip()
        if candidate:
            return candidate
        with session._lock:
            return str(session.claude_session_id or "").strip()
    if normalized == "kimi":
        candidate = str(attempt.kimi_session_id or attempt.cli_session_id or "").strip()
        if candidate:
            return candidate
        with session._lock:
            return str(session.kimi_session_id or "").strip()
    return ""


def _context_usage_signature(context_usage: dict[str, Any] | None) -> tuple[tuple[str, str], ...] | None:
    if not context_usage:
        return None
    items: list[tuple[str, str]] = []
    for key, value in sorted(context_usage.items()):
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            encoded = str(value)
        items.append((str(key), encoded))
    return tuple(items)


def _context_left_percent(context_usage: dict[str, Any] | None) -> int | None:
    if not isinstance(context_usage, dict):
        return None
    value = context_usage.get("context_left_percent")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _with_compaction_count(
    context_usage: dict[str, Any] | None,
    *,
    previous_left_percent: int | None,
    compaction_count: int,
) -> tuple[dict[str, Any] | None, int | None, int]:
    if not isinstance(context_usage, dict) or not context_usage:
        return context_usage, previous_left_percent, compaction_count

    current_left_percent = _context_left_percent(context_usage)
    if current_left_percent is None:
        return dict(context_usage), previous_left_percent, compaction_count

    next_count = compaction_count
    if previous_left_percent is not None and current_left_percent >= previous_left_percent + 20:
        next_count += 1

    next_usage = dict(context_usage)
    if next_count > 0:
        next_usage["compaction_count"] = next_count
    else:
        next_usage.pop("compaction_count", None)

    return next_usage, current_left_percent, next_count


async def _resolve_cli_context_usage_bounded(
    cli_type: str,
    session_id: str | None,
    *,
    cwd_hint: str | None,
    timeout_seconds: float = CLI_CONTEXT_USAGE_RESOLVE_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    normalized_cli_type = normalize_cli_type(cli_type)
    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(
        _CLI_CONTEXT_USAGE_EXECUTOR,
        resolve_cli_context_usage,
        normalized_cli_type,
        normalized_session_id,
        cwd_hint,
    )
    done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
    if not done:
        def _consume_late_result(late_task: asyncio.Future[dict[str, Any] | None]) -> None:
            try:
                late_task.result()
            except Exception:
                logger.debug(
                    "异步查询 CLI context_usage 失败 cli_type=%s session_id=%s",
                    normalized_cli_type,
                    normalized_session_id,
                    exc_info=True,
                )

        task.add_done_callback(_consume_late_result)
        logger.debug(
            "查询 CLI context_usage 超时 cli_type=%s session_id=%s timeout=%.2f",
            normalized_cli_type,
            normalized_session_id,
            timeout_seconds,
        )
        return None
    try:
        return task.result()
    except Exception:
        logger.debug(
            "查询 CLI context_usage 失败 cli_type=%s session_id=%s",
            normalized_cli_type,
            normalized_session_id,
            exc_info=True,
        )
        return None


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
    started_at = time.perf_counter()
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
    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
    diag_log_slow(
        logger,
        "assistant_prompt_prepare",
        elapsed_ms,
        alias=profile.alias,
        agent=session.agent_id,
        user_id=user_id,
        prompt_chars=len(compiled_prompt.prompt_text),
        sync_ms=stage_durations.get("sync_ms", 0),
        index_ms=stage_durations.get("index_ms", 0),
        recall_ms=stage_durations.get("recall_ms", 0),
    )
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


def _is_plan_request(request: AssistantRunRequest | None) -> bool:
    return bool(request is not None and request.task_mode == PLAN_MODE_TASK_MODE)


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
    started_at = time.perf_counter()
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
    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
    diag_log_slow(
        logger,
        "assistant_dream_prepare",
        elapsed_ms,
        alias=profile.alias,
        agent=session.agent_id,
        user_id=request.user_id,
        prompt_chars=len(compiled_prompt.prompt_text),
        sync_ms=stage_durations.get("sync_ms", 0),
    )
    return assistant_home, compiled_prompt.prompt_text, prepared_prompt.context_stats, stage_durations


def _normalize_dream_prompt_preparation(
    value: tuple[Any, str, dict[str, Any]] | tuple[Any, str, dict[str, Any], dict[str, int]],
) -> tuple[Any, str, dict[str, Any], dict[str, int]]:
    if len(value) == 4:
        return value
    assistant_home, prompt_text, context_stats = value
    return assistant_home, prompt_text, context_stats, new_stage_durations()


@dataclass
class _AssistantRequestPromptPreparation:
    assistant_home: Any | None
    assistant_pre_surface: dict[str, str]
    prompt_text: str
    compaction_prompt_active: bool
    finalize_assistant_turn: bool
    dream_context_stats: dict[str, Any] | None
    dream_prompt_text: str
    stage_durations: dict[str, int] = field(default_factory=new_stage_durations)


def _prepare_assistant_request_prompt(
    manager: MultiBotManager,
    profile: BotProfile,
    session: UserSession,
    request: AssistantRunRequest | None,
    *,
    user_id: int,
    user_text: str,
    cli_type: str,
) -> _AssistantRequestPromptPreparation:
    _migrate_assistant_home_to_shared(bootstrap_assistant_home(profile.working_dir))
    if _is_dream_request(request):
        assert request is not None
        assistant_home, prompt_text, dream_context_stats, stage_durations = _normalize_dream_prompt_preparation(
            _prepare_dream_assistant_prompt(
                manager,
                profile,
                session,
                request,
                user_text=user_text,
            )
        )
        return _AssistantRequestPromptPreparation(
            assistant_home=assistant_home,
            assistant_pre_surface={},
            prompt_text=prompt_text,
            compaction_prompt_active=False,
            finalize_assistant_turn=False,
            dream_context_stats=dream_context_stats,
            dream_prompt_text=prompt_text,
            stage_durations=stage_durations,
        )

    context_user_id = request.context_user_id if request is not None and request.context_user_id is not None else user_id
    assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active, stage_durations = (
        _normalize_assistant_prompt_preparation(
            _prepare_assistant_prompt(
                profile,
                session,
                user_id=context_user_id,
                user_text=user_text,
                cli_type=cli_type,
            )
        )
    )
    return _AssistantRequestPromptPreparation(
        assistant_home=assistant_home,
        assistant_pre_surface=assistant_pre_surface,
        prompt_text=prompt_text,
        compaction_prompt_active=compaction_prompt_active,
        finalize_assistant_turn=True,
        dream_context_stats=None,
        dream_prompt_text="",
        stage_durations=stage_durations,
    )


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
    message = finalized.get("message")
    if isinstance(message, dict):
        next_message = dict(message)
        next_message["content"] = applied.summary
        next_message["state"] = "done"
        finalized["message"] = next_message
        message_id = str(next_message.get("id") or "").strip()
        if message_id:
            session = get_session_for_alias(manager, request.bot_alias, request.user_id)
            service = _get_chat_history_service(session)
            try:
                finalized["message"] = service.replace_message_content(
                    message_id,
                    applied.summary,
                    state="done",
                )
            except KeyError:
                pass
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
    started_at = time.perf_counter()
    capture_ms = 0
    hot_path_ms = 0
    compaction_ms = 0
    capture = record_assistant_capture(assistant_home, user_id, user_text, response)
    capture_ms = int(round((time.perf_counter() - started_at) * 1000))
    try:
        hot_path_started_at = time.perf_counter()
        write_hot_path_memories(
            assistant_home,
            user_id=user_id,
            user_text=user_text,
            assistant_text=response,
            source_ref=str(capture.get("id") or "chat"),
        )
        hot_path_ms = int(round((time.perf_counter() - hot_path_started_at) * 1000))
    except Exception as exc:
        logger.warning("assistant memory hot-path write failed user=%s error=%s", user_id, exc)
        hot_path_ms = int(round((time.perf_counter() - hot_path_started_at) * 1000))
    compaction_started_at = time.perf_counter()
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
    compaction_ms = int(round((time.perf_counter() - compaction_started_at) * 1000))
    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
    diag_log_slow(
        logger,
        "assistant_chat_finalize",
        elapsed_ms,
        user_id=user_id,
        capture_id=str(capture.get("id") or ""),
        capture_ms=capture_ms,
        hot_path_ms=hot_path_ms,
        compaction_ms=compaction_ms,
        compaction_result=compaction_result,
    )


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
        if cli_type == "kimi":
            existing_session = bool(session.kimi_session_id)
            if not session.kimi_session_id:
                session.kimi_session_id = str(uuid.uuid4())
            return CliAttemptState(
                cli_session_id=session.kimi_session_id,
                resume_session=existing_session,
                kimi_session_id=session.kimi_session_id,
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
        if cli_type == "kimi":
            if session.kimi_session_id is None:
                return False
            session.kimi_session_id = None
            return True
    return False


def _extract_plain_error_output(raw_output: str) -> Optional[str]:
    parts: list[str] = []
    for line in str(raw_output or "").splitlines():
        stripped = strip_ansi_escape(line).strip()
        if not stripped:
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            parts.append(stripped)
    text = "\n".join(part for part in parts if part).strip()
    return text or None


def _extract_codex_error_detail(raw_output: str) -> Optional[str]:
    return extract_codex_error_output(raw_output) or _extract_plain_error_output(raw_output)


def _extract_claude_error_detail(raw_output: str) -> Optional[str]:
    error_parts: list[str] = []
    for line in str(raw_output or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_claude_stream_json_line(stripped)
        if parsed["error_text"]:
            error_parts.append(parsed["error_text"])
    text = "\n".join(part for part in error_parts if part).strip()
    return text or _extract_plain_error_output(raw_output)


def _extract_kimi_error_detail(raw_output: str) -> Optional[str]:
    return extract_kimi_error_output(raw_output) or _extract_plain_error_output(raw_output)


def _parse_codex_event(line: str) -> tuple[dict[str, Optional[str]], dict[str, Any]]:
    try:
        event: Any = json.loads(line)
    except json.JSONDecodeError:
        return dict(_CODEX_EMPTY_PARSED), {}
    if not isinstance(event, dict):
        return dict(_CODEX_EMPTY_PARSED), {}
    return _parse_codex_event_dict(event), event


def _extract_codex_content_text_from_event(content: Any) -> Optional[str]:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None

    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip()
        if block_type not in {"text", "output_text"}:
            continue
        text_value = block.get("text")
        if isinstance(text_value, str) and text_value.strip():
            text_parts.append(text_value.strip())
    return "\n".join(text_parts).strip() or None


def _extract_codex_thread_id_from_event(event: dict[str, Any]) -> Optional[str]:
    for key in ("thread_id", "threadId", "session_id", "sessionId", "conversation_id", "conversationId"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for nested_key in ("thread", "session", "conversation"):
        nested = event.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("id", "thread_id", "threadId", "session_id", "sessionId", "conversation_id", "conversationId"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_codex_error_text_from_event(event: dict[str, Any]) -> Optional[str]:
    values: list[str] = []

    def append(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    append(event.get("message"))
    append(event.get("error"))
    error = event.get("error")
    if isinstance(error, dict):
        append(error.get("message"))
        append(error.get("detail"))
        append(error.get("code"))
    for key in ("detail", "details", "reason"):
        append(event.get(key))
    return "\n".join(dict.fromkeys(values)).strip() or None


def _parse_codex_event_dict(event: dict[str, Any]) -> dict[str, Optional[str]]:
    result = dict(_CODEX_EMPTY_PARSED)
    result["thread_id"] = _extract_codex_thread_id_from_event(event)
    event_type = str(event.get("type") or "").strip()

    if event_type == "error":
        result["error_text"] = _extract_codex_error_text_from_event(event)
        return result

    if event_type in {"response_item", "event_msg"}:
        payload = event.get("item")
        if not isinstance(payload, dict):
            payload = event.get("payload")
        if not isinstance(payload, dict):
            return result
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "message":
            role = str(payload.get("role") or "").strip().lower()
            if role != "assistant":
                return result
            text_value = _extract_codex_content_text_from_event(payload.get("content"))
            if not text_value:
                return result
            phase = str(payload.get("phase") or "").strip().lower()
            if phase in {"final", "final_answer"}:
                result["completed_text"] = text_value
            result["delta_text"] = text_value
            return result
        if payload_type == "agent_message":
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                text_value = message.strip()
                result["completed_text"] = text_value
                result["delta_text"] = text_value
            return result
        return result

    if not event_type.startswith("item."):
        return result
    item = event.get("item")
    if not isinstance(item, dict):
        return result
    item_type = str(item.get("type") or "").strip()
    if item_type not in {"agent_message", "assistant_message"}:
        return result
    text_value = item.get("text")
    delta_value = item.get("delta")

    if event_type == "item.completed":
        if isinstance(text_value, str) and text_value:
            result["completed_text"] = text_value
            result["delta_text"] = text_value
        return result

    if event_type == "item.delta":
        if isinstance(delta_value, str) and delta_value:
            result["delta_text"] = delta_value
        elif isinstance(text_value, str) and text_value:
            result["delta_text"] = text_value
    return result


def _extract_codex_stream_preview(raw_output: str) -> Optional[str]:
    preview_text = ""
    current_delta = ""
    fallback_parts: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed, event = _parse_codex_event(stripped)
        if parsed["error_text"]:
            fallback_parts.append(parsed["error_text"])
            continue

        if not event:
            if not stripped.startswith("{"):
                fallback_parts.append(stripped)
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


def _extract_kimi_stream_preview(raw_output: str) -> Optional[str]:
    parts: list[str] = []
    fallback_parts: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_kimi_stream_json_line(stripped)
        if parsed["completed_text"] or parsed["delta_text"]:
            parts.append(str(parsed["completed_text"] or parsed["delta_text"]))
        elif parsed["error_text"]:
            fallback_parts.append(parsed["error_text"])
        elif not stripped.startswith("{"):
            fallback_parts.append(stripped)
    text = "\n".join(part for part in parts if part).strip()
    return text or "\n".join(part for part in fallback_parts if part).strip() or None


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
    elif cli_type == "kimi":
        preview_text = _extract_kimi_stream_preview(raw_output)
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
        elif self.cli_type == "kimi":
            self._consume_kimi(text)

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
            parsed, event = _parse_codex_event(stripped)
            if parsed["error_text"]:
                fallback_parts.append(parsed["error_text"])
                continue

            if not event:
                if not stripped.startswith("{"):
                    fallback_parts.append(stripped)
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

    def _consume_kimi(self, text: str) -> None:
        preview = _extract_kimi_stream_preview(text)
        if preview:
            self._preview_text = preview

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
        parsed, _event = _parse_codex_event(stripped)
        completed_text = str(parsed.get("completed_text") or "").strip()
        if completed_text:
            last_completed = completed_text
    return last_completed


def _load_codex_json_event(line: str) -> dict[str, Any]:
    _parsed, event = _parse_codex_event(line)
    return event


def _codex_line_allows_quiet_finish(
    line: str,
    completed_text: str,
    event: dict[str, Any] | None = None,
) -> bool:
    if event is None:
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

    parsed, event = _parse_codex_event(stripped)
    next_thread_id = thread_id
    if parsed["thread_id"]:
        next_thread_id = parsed["thread_id"]

    completed_text = str(parsed.get("completed_text") or "").strip()
    if completed_text:
        candidate_text = completed_text

    if _codex_line_allows_quiet_finish(stripped, completed_text, event):
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


class _KimiWireTail:
    def __init__(self, session_id: str, *, skip_existing: bool = False):
        self.session_id = str(session_id or "").strip()
        self.path: Path | None = None
        self.offset = 0
        self.state = create_stream_trace_state("kimi")
        if skip_existing:
            self._prime_existing_offset()

    def _prime_existing_offset(self) -> None:
        ref = locate_kimi_transcript(self.session_id)
        if ref is None:
            return
        try:
            self.path = ref.path
            self.offset = ref.path.stat().st_size
        except OSError:
            self.path = None
            self.offset = 0

    def poll(self) -> list[dict[str, Any]]:
        if not self.session_id:
            return []
        if self.path is None:
            ref = locate_kimi_transcript(self.session_id)
            if ref is None:
                return []
            self.path = ref.path
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []
        if not chunk:
            return []
        return consume_stream_trace_chunk("kimi", chunk, self.state)


def _build_terminal_trace(
    *,
    live_trace: list[dict[str, Any]],
    stop_requested: bool,
    returncode: int,
    error_detail: str = "",
) -> list[dict[str, Any]]:
    trace = _merge_trace_events(live_trace)
    if stop_requested:
        return _merge_trace_events(
            trace,
            [{"kind": "cancelled", "source": "runtime", "summary": "用户终止输出"}],
        )
    if isinstance(returncode, int) and returncode not in (0,):
        summary = f"命令退出码 {returncode}"
        detail = str(error_detail or "").strip()
        if detail:
            summary = f"{summary}\n{detail[-2000:]}"
        return _merge_trace_events(
            trace,
            [{"kind": "error", "source": "runtime", "summary": summary}],
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
    started_at = time.perf_counter()
    provider = normalize_cli_type(getattr(profile, "cli_type", ""))
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
            elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
            diag_log_slow(
                logger,
                "trace_reconcile_slow",
                elapsed_ms,
                alias=session.bot_alias,
                agent=session.agent_id,
                provider=provider,
                turn_id=getattr(turn_handle, "turn_id", ""),
                attempts=attempt_index + 1,
                recovered=True,
            )
            return
        if attempt_index + 1 >= attempts:
            elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
            diag_log_slow(
                logger,
                "trace_reconcile_slow",
                elapsed_ms,
                alias=session.bot_alias,
                agent=session.agent_id,
                provider=provider,
                turn_id=getattr(turn_handle, "turn_id", ""),
                attempts=attempt_index + 1,
                recovered=False,
            )
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


PROCESS_STDOUT_EXIT_DRAIN_SECONDS = 0.2


def _close_process_stdout(process: Any) -> None:
    stdout = getattr(process, "stdout", None)
    if stdout is None:
        return
    try:
        stdout.close()
    except Exception:
        pass


def _start_process_stdout_reader(
    process: subprocess.Popen,
    output_queue: queue.Queue[Any],
    *,
    drain_seconds: float = PROCESS_STDOUT_EXIT_DRAIN_SECONDS,
) -> threading.Event:
    reader_done = threading.Event()

    def read_stdout() -> None:
        try:
            stdout = process.stdout
            if stdout is None or not hasattr(stdout, "readline"):
                return
            while True:
                line = stdout.readline()
                if line:
                    output_queue.put(line)
                    continue
                if process.poll() is not None:
                    break
                time.sleep(0.01)
        except Exception as exc:  # pragma: no cover - defensive
            output_queue.put(exc)
        finally:
            reader_done.set()

    threading.Thread(target=read_stdout, daemon=True).start()
    return reader_done


def _maybe_stop_waiting_for_stdout_after_exit(
    process: subprocess.Popen,
    reader_done: threading.Event,
    output_queue: queue.Queue[Any],
    exit_seen_at: float | None,
    *,
    drain_seconds: float = PROCESS_STDOUT_EXIT_DRAIN_SECONDS,
) -> tuple[bool, float | None]:
    if reader_done.is_set():
        return False, None
    if process.poll() is None:
        return False, None
    now = time.monotonic()
    if exit_seen_at is None:
        return False, now
    if not output_queue.empty():
        return False, exit_seen_at
    if now - exit_seen_at < drain_seconds:
        return False, exit_seen_at
    _close_process_stdout(process)
    return True, exit_seen_at


def _reset_session_runtime_flags(session: UserSession) -> None:
    session.process = None
    session.native_agent_run_id = None
    session.is_processing = False
    session.stop_requested = False
    session.running_user_text = None
    session.running_preview_text = ""
    session.running_started_at = None
    session.running_updated_at = None


async def _communicate_process(process: subprocess.Popen) -> tuple[str, int]:
    try:
        stdout = getattr(process, "stdout", None)
        if stdout is None or not hasattr(stdout, "readline"):
            output, _ = process.communicate()
            return str(output or ""), getattr(process, "returncode", None) or process.wait() or 0

        output_queue: queue.Queue[Any] = queue.Queue()
        reader_done = _start_process_stdout_reader(process, output_queue)
        chunks: list[str] = []
        stdout_exit_seen_at: float | None = None

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

                should_stop, stdout_exit_seen_at = _maybe_stop_waiting_for_stdout_after_exit(
                    process,
                    reader_done,
                    output_queue,
                    stdout_exit_seen_at,
                )
                if should_stop:
                    break
                if not drained:
                    await asyncio.sleep(0.05)
        except Exception:
            _terminate_process_sync(process)
            raise
        except asyncio.CancelledError:
            _terminate_process_sync(process)
            raise

        return "".join(chunks), process.poll() or 0
    finally:
        close_process_streams(process)


async def _communicate_codex_process(process: subprocess.Popen) -> tuple[str, Optional[str], int]:
    try:
        stdout = getattr(process, "stdout", None)
        if stdout is None or not hasattr(stdout, "readline"):
            raw_output, returncode = await _communicate_process(process)
            final_text, thread_id = parse_codex_json_output(raw_output)
            if not final_text:
                final_text = msg("chat", "no_output")
            return final_text, thread_id, returncode

        loop = asyncio.get_running_loop()
        output_queue: queue.Queue[Any] = queue.Queue()
        reader_done = _start_process_stdout_reader(process, output_queue)
        chunks: list[str] = []
        thread_id: Optional[str] = None
        candidate_text: Optional[str] = None
        candidate_seen_at: Optional[float] = None
        done_terminate_started_at: Optional[float] = None
        done_force_killed = False
        done_stdout_closed = False
        stdout_exit_seen_at: float | None = None

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
                if candidate_seen_at is not None and (now - candidate_seen_at) >= CODEX_DONE_QUIET_SECONDS:
                    if process.poll() is not None and output_queue.empty():
                        if not done_stdout_closed:
                            _close_process_stdout(process)
                            done_stdout_closed = True
                        break
                    if done_terminate_started_at is None and process.poll() is None:
                        done_terminate_started_at = now
                        await loop.run_in_executor(None, _terminate_process_sync, process)
                    elif (
                        done_terminate_started_at is not None
                        and not done_force_killed
                        and process.poll() is None
                        and (now - done_terminate_started_at) >= CODEX_TERMINATE_GRACE_SECONDS
                    ):
                        done_force_killed = True
                        await loop.run_in_executor(None, _terminate_process_sync, process)

                should_stop, stdout_exit_seen_at = _maybe_stop_waiting_for_stdout_after_exit(
                    process,
                    reader_done,
                    output_queue,
                    stdout_exit_seen_at,
                )
                if should_stop:
                    break
                if not drained:
                    await asyncio.sleep(0.05)
            waited_returncode = await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
            returncode = _resolve_process_returncode(process, waited_returncode)
            if done_terminate_started_at is not None:
                returncode = 0

            raw_output = "".join(chunks)
            final_text, parsed_thread_id = parse_codex_json_output(raw_output)
            error_text = _extract_codex_error_detail(raw_output) if returncode != 0 else None
            final_text = error_text or candidate_text or _extract_final_codex_completed_message(raw_output) or final_text
            if not final_text:
                final_text = msg("chat", "no_output")
            return final_text, thread_id or parsed_thread_id, returncode
        except Exception:
            _terminate_process_sync(process)
            raise
        except asyncio.CancelledError:
            _terminate_process_sync(process)
            raise
    finally:
        close_process_streams(process)


async def _communicate_claude_process(
    process: subprocess.Popen,
    *,
    done_session=None,
) -> tuple[str, Optional[str], int]:
    try:
        if done_session is None or not getattr(done_session, "enabled", False):
            raw_output, returncode = await _communicate_process(process)
            final_text, session_id = parse_claude_stream_json_output(raw_output)
            if not final_text:
                final_text = msg("chat", "no_output")
            return final_text, session_id, returncode

        loop = asyncio.get_running_loop()
        output_queue: queue.Queue[Any] = queue.Queue()
        reader_done = _start_process_stdout_reader(process, output_queue)
        collector = ClaudeDoneCollector(done_session)
        done_terminate_started_at: Optional[float] = None
        done_force_killed = False
        stdout_exit_seen_at: float | None = None

        try:
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
                    await loop.run_in_executor(None, _terminate_process_sync, process)
                elif (
                    done_terminate_started_at is not None
                    and not done_force_killed
                    and process.poll() is None
                    and (now - done_terminate_started_at) >= 1.0
                ):
                    done_force_killed = True
                    await loop.run_in_executor(None, _terminate_process_sync, process)

                should_stop, stdout_exit_seen_at = _maybe_stop_waiting_for_stdout_after_exit(
                    process,
                    reader_done,
                    output_queue,
                    stdout_exit_seen_at,
                )
                if should_stop:
                    break
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
        except Exception:
            _terminate_process_sync(process)
            raise
        except asyncio.CancelledError:
            _terminate_process_sync(process)
            raise
    finally:
        close_process_streams(process)


async def _communicate_kimi_process(process: subprocess.Popen) -> tuple[str, int]:
    try:
        raw_output, returncode = await _communicate_process(process)
        response = parse_kimi_stream_json_output(raw_output)
        if returncode != 0:
            response = _extract_kimi_error_detail(raw_output) or response
        return response or msg("chat", "no_output"), returncode
    finally:
        close_process_streams(process)


async def _stream_cli_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    agent_id: str = "main",
    cli_params_override: CliParamsConfig | None = None,
    allow_unsafe_cli: bool = False,
    cluster_run_id: str = "",
    cluster_mentions: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    total_started_at = time.perf_counter()
    user_id = chat_session_user_id(user_id)
    profile, agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    visible_input = request.visible_text if request is not None and request.visible_text is not None else user_text
    text = (visible_input or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    is_plan_mode = _is_plan_request(request)
    base_prompt_text = build_plan_mode_prompt(text, cluster_active=bool(cluster_run_id)) if is_plan_mode else text
    prompt_text = _apply_cluster_prompt(
        profile,
        base_prompt_text,
        cluster_run_id=cluster_run_id,
        cluster_mentions=cluster_mentions,
    )
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
        context_user_id = request.context_user_id if request is not None and request.context_user_id is not None else user_id
        assistant_home, assistant_pre_surface, prompt_text, compaction_prompt_active, assistant_stage_durations = (
            _normalize_assistant_prompt_preparation(
                _prepare_assistant_prompt(
                    profile,
                    session,
                    user_id=context_user_id,
                    user_text=text,
                    cli_type=cli_type,
                )
            )
        )
        if is_plan_mode:
            prompt_text = build_plan_mode_prompt(prompt_text, cluster_active=bool(cluster_run_id))
        prompt_text = _apply_cluster_prompt(
            profile,
            prompt_text,
            cluster_run_id=cluster_run_id,
            cluster_mentions=cluster_mentions,
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
    process_pid = 0
    output_bytes = 0
    final_trace_count = 0
    sqlite_flush_count = 0
    completion_state_for_diag = ""
    normal_return_for_diag = False
    active_process: subprocess.Popen | None = None
    try:
        session.touch()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        session_id_changed = False
        meta_sent = False
        max_attempts = 2 if cli_type == "claude" else 1
        service = _get_chat_history_service(session)
        persist_started_at = time.perf_counter()
        turn_handle = service.start_turn(
            profile=profile,
            session=session,
            user_text=text,
            native_provider=cli_type,
            assistant_home=str(assistant_home.root) if assistant_home is not None else None,
            managed_prompt_hash=session.managed_prompt_hash_seen,
            prompt_surface_version="v1" if assistant_home is not None else None,
            actor=_actor_from_request(request),
        )
        assistant_stage_durations["db_ms"] += max(
            0,
            int(round((time.perf_counter() - persist_started_at) * 1000)),
        )
        turn_context_left_percent: int | None = None
        turn_compaction_count = 0

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            params_for_attempt = _effective_cli_params(
                profile,
                cli_params_override or profile.cli_params,
                cluster_run_id,
                allow_unsafe_cli=allow_unsafe_cli,
            )
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude", "kimi")),
                    params_config=params_for_attempt,
                    working_dir=session.working_dir,
                    task_mode=request.task_mode if request is not None else "standard",
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            try:
                spawn_started_at = time.perf_counter()
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
                    **build_chat_cli_process_kwargs(),
                )
                active_process = process
                process_pid = int(getattr(process, "pid", 0) or 0)
                diag_log_event(
                    logger,
                    "cli_stream_start",
                    alias=alias,
                    agent=session.agent_id,
                    cli_type=cli_type,
                    pid=process_pid,
                    cluster_run_id=cluster_run_id,
                    resume_session=attempt.resume_session,
                    attempt=attempt_index + 1,
                )
                diag_log_slow(
                    logger,
                    "cli_spawn",
                    int(round((time.perf_counter() - spawn_started_at) * 1000)),
                    alias=alias,
                    agent=session.agent_id,
                    cli_type=cli_type,
                    pid=process_pid,
                    cluster_run_id=cluster_run_id,
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
                    close_process_streams(process)
                    _terminate_process_sync(process)
                    _wait_for_process_exit_sync(process, 1.0)
                    _raise(500, "cli_write_failed", msg("chat", "cli_failed") + f": {exc}")

            with session._lock:
                session.process = process

            turn_event_ids = {
                "turn_id": turn_handle.turn_id,
                "assistant_message_id": turn_handle.assistant_message_id,
            }

            if not meta_sent:
                yield {
                    "type": "meta",
                    **turn_event_ids,
                    "alias": alias,
                    "cli_type": cli_type,
                    "working_dir": session.working_dir,
                    "resume_session": attempt.resume_session,
                    "cluster_run_id": cluster_run_id,
                }
                meta_sent = True

            output_queue: queue.Queue[Any] = queue.Queue()
            reader_done = _start_process_stdout_reader(process, output_queue)
            preview_state = _StreamPreviewState(cli_type)
            persistence_buffer = StreamingPersistenceBuffer(
                service,
                turn_handle,
                loop_time=loop.time,
            )
            thread_id: Optional[str] = None
            last_status_signature: tuple[int, Optional[str], tuple[tuple[str, str], ...] | None] | None = None
            last_context_usage: dict[str, Any] | None = None
            last_context_usage_signature: tuple[tuple[str, str], ...] | None = None
            last_context_usage_persisted_at = 0.0
            claude_collector = ClaudeDoneCollector(done_session) if done_session and done_session.enabled else None
            done_terminate_started_at: Optional[float] = None
            done_force_killed = False
            done_stdout_closed = False
            stdout_exit_seen_at: float | None = None
            codex_done_candidate: Optional[str] = None
            codex_done_seen_at: Optional[float] = None
            trace_state = create_stream_trace_state(cli_type)
            live_trace_events: list[dict[str, Any]] = []
            live_trace_event_keys: set[tuple[str, str, str, str]] = set()
            latest_preview_text = ""
            last_context_usage_resolved_at = 0.0
            kimi_wire_tail = (
                _KimiWireTail(attempt.cli_session_id or "", skip_existing=attempt.resume_session)
                if cli_type == "kimi"
                else None
            )

            def append_live_trace_event(trace_event: dict[str, Any]) -> dict[str, Any] | None:
                event_key = _trace_event_key(trace_event)
                if event_key in live_trace_event_keys:
                    return None
                live_trace_event_keys.add(event_key)
                live_trace_events.append(trace_event)
                persistence_buffer.queue_trace(trace_event)
                persistence_buffer.maybe_flush()
                return trace_event

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
                        output_bytes += len(text_chunk.encode("utf-8", errors="replace"))
                        preview_state.consume(text_chunk)
                        for trace_event in consume_stream_trace_chunk(cli_type, text_chunk, trace_state):
                            appended_trace = append_live_trace_event(trace_event)
                            if appended_trace is not None:
                                yield {"type": "trace", **turn_event_ids, "event": appended_trace}

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

                    if kimi_wire_tail is not None:
                        for trace_event in kimi_wire_tail.poll():
                            appended_trace = append_live_trace_event(trace_event)
                            if appended_trace is not None:
                                yield {"type": "trace", **turn_event_ids, "event": appended_trace}

                    with session._lock:
                        stop_requested = bool(session.stop_requested)

                    if (
                        stop_requested
                        and done_terminate_started_at is None
                        and process.poll() is None
                    ):
                        done_terminate_started_at = loop.time()
                        await loop.run_in_executor(None, _terminate_process_sync, process)
                    elif (
                        claude_collector is not None
                        and claude_collector.detector is not None
                        and done_terminate_started_at is None
                        and claude_collector.detector.poll(now=loop.time())
                        and process.poll() is None
                    ):
                        done_terminate_started_at = loop.time()
                        await loop.run_in_executor(None, _terminate_process_sync, process)
                    elif (
                        cli_type == "codex"
                        and codex_done_seen_at is not None
                        and done_terminate_started_at is None
                        and process.poll() is None
                        and (loop.time() - codex_done_seen_at) >= CODEX_DONE_QUIET_SECONDS
                    ):
                        done_terminate_started_at = loop.time()
                        await loop.run_in_executor(None, _terminate_process_sync, process)
                    elif (
                        done_terminate_started_at is not None
                        and not done_force_killed
                        and process.poll() is None
                        and (loop.time() - done_terminate_started_at) >= CODEX_TERMINATE_GRACE_SECONDS
                    ):
                        done_force_killed = True
                        await loop.run_in_executor(None, _terminate_process_sync, process)

                    if (
                        cli_type == "codex"
                        and codex_done_seen_at is not None
                        and (loop.time() - codex_done_seen_at) >= CODEX_DONE_QUIET_SECONDS
                        and process.poll() is not None
                        and output_queue.empty()
                    ):
                        if not done_stdout_closed:
                            _close_process_stdout(process)
                            done_stdout_closed = True
                        break

                    should_stop, stdout_exit_seen_at = _maybe_stop_waiting_for_stdout_after_exit(
                        process,
                        reader_done,
                        output_queue,
                        stdout_exit_seen_at,
                    )
                    if should_stop:
                        break

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
                    status_event.update(turn_event_ids)
                    status_context_usage = None
                    status_session_id = _status_context_session_id(
                        session,
                        cli_type,
                        attempt,
                        thread_id=thread_id,
                    )
                    now = loop.time()
                    should_refresh_context_usage = (
                        bool(status_session_id)
                        and (
                            last_context_usage is None
                            or (now - last_context_usage_resolved_at) >= 1.0
                        )
                    )
                    if should_refresh_context_usage and status_session_id:
                        status_context_usage = await _resolve_cli_context_usage_bounded(
                            cli_type,
                            status_session_id,
                            cwd_hint=session.working_dir,
                        )
                        last_context_usage_resolved_at = now
                    elif status_session_id:
                        status_context_usage = last_context_usage
                    if status_context_usage:
                        (
                            status_context_usage,
                            turn_context_left_percent,
                            turn_compaction_count,
                        ) = _with_compaction_count(
                            status_context_usage,
                            previous_left_percent=turn_context_left_percent,
                            compaction_count=turn_compaction_count,
                        )
                        status_event["context_usage"] = status_context_usage
                        context_usage_signature = _context_usage_signature(status_context_usage)
                        last_context_usage = status_context_usage
                        if (
                            context_usage_signature != last_context_usage_signature
                            or loop.time() - last_context_usage_persisted_at >= 1.0
                        ):
                            await service.update_context_usage_async(turn_handle, status_context_usage)
                            last_context_usage_signature = context_usage_signature
                            last_context_usage_persisted_at = loop.time()
                    status_signature = (
                        int(status_event.get("elapsed_seconds", 0)),
                        status_event.get("preview_text"),
                        _context_usage_signature(status_context_usage),
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
            except Exception:
                persistence_buffer.flush()
                if process.poll() is None:
                    await loop.run_in_executor(None, _terminate_process_sync, process)
                raise
            finally:
                with session._lock:
                    session.process = None
                close_process_streams(process)
            assistant_stage_durations["cli_ms"] += max(0, int(round((time.perf_counter() - cli_started_at) * 1000)))
            sqlite_flush_count = persistence_buffer.flush_count

            raw_output = preview_state.raw_output_for_parse()
            error_detail = ""
            if cli_type == "codex":
                response, parsed_thread_id = parse_codex_json_output(raw_output)
                thread_id = thread_id or parsed_thread_id
                response = codex_done_candidate or _extract_final_codex_completed_message(raw_output) or response
                if returncode != 0:
                    error_detail = _extract_codex_error_detail(raw_output) or ""
                    response = error_detail or response
            elif cli_type == "claude":
                if claude_collector is not None:
                    response = claude_collector.final_text or ""
                    raw_output = claude_collector.raw_output
                else:
                    response, _ = parse_claude_stream_json_output(raw_output)
                if returncode != 0:
                    error_detail = _extract_claude_error_detail(raw_output) or ""
                    response = error_detail or response
            elif cli_type == "kimi":
                response = parse_kimi_stream_json_output(raw_output)
                if returncode != 0:
                    error_detail = _extract_kimi_error_detail(raw_output) or ""
                    response = error_detail or response
            else:
                response = raw_output.strip()
                if returncode != 0:
                    error_detail = response

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
            elif cli_type == "kimi":
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
                error_detail=response if completion_state == "error" else error_detail,
            )
            final_trace_count = len(final_trace)
            persistence_buffer.flush()
            for trace_event in final_trace[len(live_trace_events):]:
                persistence_buffer.queue_trace(trace_event)
            persistence_buffer.flush()
            sqlite_flush_count = persistence_buffer.flush_count
            native_session_id = _current_native_session_id(session, cli_type)
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
                else (response or latest_preview_text)
            )
            context_usage = await _resolve_cli_context_usage_bounded(
                cli_type,
                native_session_id,
                cwd_hint=session.working_dir,
            )
            if context_usage is None:
                context_usage = last_context_usage
            (
                context_usage,
                turn_context_left_percent,
                turn_compaction_count,
            ) = _with_compaction_count(
                context_usage,
                previous_left_percent=turn_context_left_percent,
                compaction_count=turn_compaction_count,
            )
            complete_started_at = time.perf_counter()
            done_message = await asyncio.to_thread(
                service.complete_turn,
                turn_handle,
                completion_state=completion_state,
                content=fallback_output,
                native_session_id=native_session_id,
                error_code=None if completion_state == "completed" else completion_state,
                error_message=None if completion_state == "completed" else response,
                context_usage=context_usage,
            )
            assistant_stage_durations["db_ms"] += max(
                0,
                int(round((time.perf_counter() - complete_started_at) * 1000)),
            )
            completion_state_for_diag = completion_state
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
                **turn_event_ids,
                "output": str(done_message.get("content") or response),
                "message": done_message,
                "elapsed_seconds": elapsed_seconds,
                "returncode": returncode,
                "session": build_session_snapshot(profile, session),
            }
            elapsed_ms = int(round((time.perf_counter() - total_started_at) * 1000))
            diag_log_event(
                logger,
                "cli_stream_done",
                alias=alias,
                agent=session.agent_id,
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state,
                returncode=returncode,
                elapsed_ms=elapsed_ms,
                output_bytes=output_bytes,
                trace_count=final_trace_count,
                sqlite_flush_count=sqlite_flush_count,
                cli_ms=assistant_stage_durations.get("cli_ms", 0),
                trace_ms=assistant_stage_durations.get("trace_ms", 0),
                db_ms=assistant_stage_durations.get("db_ms", 0),
            )
            diag_log_slow(
                logger,
                "cli_stream_total",
                elapsed_ms,
                alias=alias,
                agent=session.agent_id,
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state,
                output_bytes=output_bytes,
                trace_count=final_trace_count,
                sqlite_flush_count=sqlite_flush_count,
            )
            normal_return_for_diag = True
            yield done_event
            return
    finally:
        elapsed_ms = int(round((time.perf_counter() - total_started_at) * 1000))
        if not normal_return_for_diag:
            diag_log_slow(
                logger,
                "cli_stream_total",
                elapsed_ms,
                alias=alias,
                agent=getattr(session, "agent_id", agent_id),
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state_for_diag or "incomplete",
                output_bytes=output_bytes,
                trace_count=final_trace_count,
                sqlite_flush_count=sqlite_flush_count,
            )
        lingering_process: subprocess.Popen | None = None
        with session._lock:
            lingering_process = session.process
            _reset_session_runtime_flags(session)
        lingering_process = lingering_process or active_process
        if lingering_process is not None and lingering_process.poll() is None:
            if loop is not None:
                await loop.run_in_executor(None, _terminate_process_sync, lingering_process)
            else:
                _terminate_process_sync(lingering_process)
        close_process_streams(lingering_process)


async def run_cli_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    agent_id: str = "main",
    cli_params_override: CliParamsConfig | None = None,
    allow_unsafe_cli: bool = False,
    cluster_run_id: str = "",
    cluster_mentions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total_started_at = time.perf_counter()
    user_id = chat_session_user_id(user_id)
    profile, agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    visible_input = request.visible_text if request is not None and request.visible_text is not None else user_text
    text = (visible_input or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    is_plan_mode = _is_plan_request(request)
    base_prompt_text = build_plan_mode_prompt(text, cluster_active=bool(cluster_run_id)) if is_plan_mode else text
    prompt_text = _apply_cluster_prompt(
        profile,
        base_prompt_text,
        cluster_run_id=cluster_run_id,
        cluster_mentions=cluster_mentions,
    )
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
        prepared_prompt = _prepare_assistant_request_prompt(
            manager,
            profile,
            session,
            request,
            user_id=user_id,
            user_text=text,
            cli_type=cli_type,
        )
        assistant_home = prepared_prompt.assistant_home
        assistant_pre_surface = prepared_prompt.assistant_pre_surface
        prompt_text = prepared_prompt.prompt_text
        compaction_prompt_active = prepared_prompt.compaction_prompt_active
        finalize_assistant_turn = prepared_prompt.finalize_assistant_turn
        dream_context_stats = prepared_prompt.dream_context_stats
        dream_prompt_text = prepared_prompt.dream_prompt_text
        assistant_stage_durations = prepared_prompt.stage_durations
        if not _is_dream_request(request):
            if is_plan_mode:
                prompt_text = build_plan_mode_prompt(prompt_text, cluster_active=bool(cluster_run_id))
        prompt_text = _apply_cluster_prompt(
            profile,
            prompt_text,
            cluster_run_id=cluster_run_id,
            cluster_mentions=cluster_mentions,
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

    process_pid = 0
    output_bytes = 0
    final_trace_count = 0
    completion_state_for_diag = ""
    normal_return_for_diag = False
    active_process: subprocess.Popen | None = None
    try:
        session.touch()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        session_id_changed = False
        max_attempts = 2 if cli_type == "claude" else 1
        service = _get_chat_history_service(session)
        persist_started_at = time.perf_counter()
        turn_handle = service.start_turn(
            profile=profile,
            session=session,
            user_text=text,
            native_provider=cli_type,
            assistant_home=str(assistant_home.root) if assistant_home is not None else None,
            managed_prompt_hash=session.managed_prompt_hash_seen,
            prompt_surface_version="v1" if assistant_home is not None else None,
            actor=_actor_from_request(request),
        )
        assistant_stage_durations["db_ms"] += max(
            0,
            int(round((time.perf_counter() - persist_started_at) * 1000)),
        )

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            params_for_attempt = _effective_cli_params(
                profile,
                cli_params_override or profile.cli_params,
                cluster_run_id,
                allow_unsafe_cli=allow_unsafe_cli,
            )
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=prompt_text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type in ("codex", "claude", "kimi")),
                    params_config=params_for_attempt,
                    working_dir=session.working_dir,
                    task_mode=request.task_mode if request is not None else "standard",
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            try:
                spawn_started_at = time.perf_counter()
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
                    **build_chat_cli_process_kwargs(),
                )
                active_process = process
                process_pid = int(getattr(process, "pid", 0) or 0)
                diag_log_event(
                    logger,
                    "cli_run_start",
                    alias=alias,
                    agent=session.agent_id,
                    cli_type=cli_type,
                    pid=process_pid,
                    cluster_run_id=cluster_run_id,
                    resume_session=attempt.resume_session,
                    attempt=attempt_index + 1,
                )
                diag_log_slow(
                    logger,
                    "cli_spawn",
                    int(round((time.perf_counter() - spawn_started_at) * 1000)),
                    alias=alias,
                    agent=session.agent_id,
                    cli_type=cli_type,
                    pid=process_pid,
                    cluster_run_id=cluster_run_id,
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
                    close_process_streams(process)
                    _terminate_process_sync(process)
                    _wait_for_process_exit_sync(process, 1.0)
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
                elif cli_type == "kimi":
                    response, returncode = await _communicate_kimi_process(process)
                else:
                    response, returncode = await _communicate_process(process)
                    response = response.strip() or msg("chat", "no_output")
                output_bytes = len(str(response or "").encode("utf-8", errors="replace"))
            except Exception:
                if process.poll() is None:
                    _terminate_process_sync(process)
                raise
            finally:
                with session._lock:
                    session.process = None
                close_process_streams(process)
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
            elif cli_type == "kimi":
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
            error_detail = response if completion_state == "error" else ""
            with session._lock:
                stop_requested = bool(session.stop_requested)
            terminal_trace = _build_terminal_trace(
                live_trace=[],
                stop_requested=stop_requested,
                returncode=returncode,
                error_detail=error_detail,
            )
            final_trace_count = len(terminal_trace)
            for trace_event in terminal_trace:
                service.append_trace_event(turn_handle, trace_event)
            native_session_id = _current_native_session_id(session, cli_type)
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
            context_usage = await _resolve_cli_context_usage_bounded(
                cli_type,
                native_session_id,
                cwd_hint=session.working_dir,
            )
            complete_started_at = time.perf_counter()
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
                context_usage=context_usage,
            )
            assistant_stage_durations["db_ms"] += max(
                0,
                int(round((time.perf_counter() - complete_started_at) * 1000)),
            )
            completion_state_for_diag = completion_state
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
            elapsed_ms = int(round((time.perf_counter() - total_started_at) * 1000))
            diag_log_event(
                logger,
                "cli_run_done",
                alias=alias,
                agent=session.agent_id,
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state,
                returncode=returncode,
                elapsed_ms=elapsed_ms,
                output_bytes=output_bytes,
                trace_count=final_trace_count,
                cli_ms=assistant_stage_durations.get("cli_ms", 0),
                trace_ms=assistant_stage_durations.get("trace_ms", 0),
                db_ms=assistant_stage_durations.get("db_ms", 0),
            )
            diag_log_slow(
                logger,
                "cli_run_total",
                elapsed_ms,
                alias=alias,
                agent=session.agent_id,
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state,
                output_bytes=output_bytes,
                trace_count=final_trace_count,
            )
            normal_return_for_diag = True
            return response_payload
    finally:
        if not normal_return_for_diag:
            elapsed_ms = int(round((time.perf_counter() - total_started_at) * 1000))
            diag_log_slow(
                logger,
                "cli_run_total",
                elapsed_ms,
                alias=alias,
                agent=getattr(session, "agent_id", agent_id),
                cli_type=cli_type,
                pid=process_pid,
                cluster_run_id=cluster_run_id,
                completion_state=completion_state_for_diag or "incomplete",
                output_bytes=output_bytes,
                trace_count=final_trace_count,
            )
        with session._lock:
            lingering_process = session.process
            _reset_session_runtime_flags(session)
        lingering_process = lingering_process or active_process
        if lingering_process is not None and lingering_process.poll() is None:
            _terminate_process_sync(lingering_process)
        close_process_streams(lingering_process)


def _normalized_chat_text(
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    visible_text: str | None = None,
) -> str:
    visible_input = request.visible_text if request is not None and request.visible_text is not None else visible_text
    text = (visible_input if visible_input is not None else user_text or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]
    return text


async def _run_native_agent_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    task_mode: str = "standard",
    task_payload: dict[str, Any] | None = None,
    visible_text: str | None = None,
    agent_id: str = "main",
    cluster: bool = False,
    mentions: list[dict[str, Any]] | None = None,
    solo_mode: bool = False,
    actor: dict[str, Any] | None = None,
    allow_unsafe_cli: bool = False,
    prepare_assistant_request: bool = False,
) -> dict[str, Any]:
    shared_user_id = chat_session_user_id(user_id)
    profile, _agent, session = get_chat_session_for_alias(manager, alias, shared_user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")

    effective_task_mode = request.task_mode if request is not None else task_mode
    effective_task_payload = request.task_payload if request is not None else task_payload
    text = _normalized_chat_text(user_text, request=request, visible_text=visible_text)
    request_obj = request or build_assistant_run_request(
        alias,
        shared_user_id,
        user_text,
        task_mode=effective_task_mode,
        task_payload=effective_task_payload,
        visible_text=visible_text,
        actor=actor,
    )
    is_plan_mode = effective_task_mode == PLAN_MODE_TASK_MODE
    cluster_run = _start_cluster_run_if_requested(
        profile=profile,
        alias=alias,
        shared_user_id=shared_user_id,
        cluster=cluster,
        execution_mode=NATIVE_AGENT_PROVIDER,
        mentions=mentions,
        allow_unsafe_cli=allow_unsafe_cli,
    )
    prepared_prompt: _AssistantRequestPromptPreparation | None = None
    run_status = "completed"
    try:
        if prepare_assistant_request and profile.bot_mode == "assistant":
            prepared_prompt = _prepare_assistant_request_prompt(
                manager,
                profile,
                session,
                request_obj,
                user_id=shared_user_id,
                user_text=text,
                cli_type=normalize_cli_type(profile.cli_type),
            )
            prompt_text = prepared_prompt.prompt_text
            if not _is_dream_request(request_obj) and is_plan_mode:
                prompt_text = build_plan_mode_prompt(prompt_text, cluster_active=bool(cluster_run))
        else:
            prompt_text = build_plan_mode_prompt(text, cluster_active=bool(cluster_run)) if is_plan_mode else text
        prompt_text = _apply_cluster_prompt(
            profile,
            prompt_text,
            cluster_run_id=cluster_run.run_id if cluster_run else "",
            cluster_mentions=list(mentions or []),
        )
        result = await get_native_agent_service().run_chat(
            profile=profile,
            session=session,
            user_text=text,
            prompt_text=prompt_text,
            history_service=_history_service_for_execution_mode(session, NATIVE_AGENT_PROVIDER),
            actor=_actor_from_request(request_obj),
            cluster_run_id=cluster_run.run_id if cluster_run else "",
            solo_mode=solo_mode,
        )
        if prepared_prompt is not None:
            result = dict(result)
            if prepared_prompt.assistant_home is not None and prepared_prompt.finalize_assistant_turn:
                try:
                    _finalize_assistant_chat_turn(
                        prepared_prompt.assistant_home,
                        user_id=shared_user_id,
                        user_text=text,
                        response=str(result.get("output") or ""),
                        assistant_pre_surface=prepared_prompt.assistant_pre_surface,
                        compaction_prompt_active=prepared_prompt.compaction_prompt_active,
                    )
                except Exception as exc:
                    logger.warning("处理 assistant native chat 收尾失败 user=%s error=%s", shared_user_id, exc)
            result["assistant_stage_durations"] = dict(prepared_prompt.stage_durations)
            if prepared_prompt.dream_context_stats is not None:
                result["dream_context_stats"] = prepared_prompt.dream_context_stats
                result["dream_prompt_text"] = prepared_prompt.dream_prompt_text
        return result
    except Exception:
        run_status = "error"
        raise
    finally:
        if cluster_run:
            _CLUSTER_RUNTIME.finish_run(cluster_run.run_id, run_status)
            _cleanup_cluster_run_control_if_idle(cluster_run.run_id)


async def _stream_native_agent_chat(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    user_text: str,
    *,
    request: AssistantRunRequest | None = None,
    task_mode: str = "standard",
    task_payload: dict[str, Any] | None = None,
    visible_text: str | None = None,
    agent_id: str = "main",
    cluster: bool = False,
    mentions: list[dict[str, Any]] | None = None,
    solo_mode: bool = False,
    actor: dict[str, Any] | None = None,
    protocol: str = "",
    allow_unsafe_cli: bool = False,
    prepare_assistant_request: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    shared_user_id = chat_session_user_id(user_id)
    profile, _agent, session = get_chat_session_for_alias(manager, alias, shared_user_id, agent_id)
    if not _supports_cli_runtime(profile):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")

    effective_task_mode = request.task_mode if request is not None else task_mode
    effective_task_payload = request.task_payload if request is not None else task_payload
    text = _normalized_chat_text(user_text, request=request, visible_text=visible_text)
    request_obj = request or build_assistant_run_request(
        alias,
        shared_user_id,
        user_text,
        task_mode=effective_task_mode,
        task_payload=effective_task_payload,
        visible_text=visible_text,
        actor=actor,
    )
    is_plan_mode = effective_task_mode == PLAN_MODE_TASK_MODE
    cluster_run = _start_cluster_run_if_requested(
        profile=profile,
        alias=alias,
        shared_user_id=shared_user_id,
        cluster=cluster,
        execution_mode=NATIVE_AGENT_PROVIDER,
        mentions=mentions,
        allow_unsafe_cli=allow_unsafe_cli,
    )
    prepared_prompt: _AssistantRequestPromptPreparation | None = None
    finalization_scheduled = False
    run_status = "completed"
    try:
        if prepare_assistant_request and profile.bot_mode == "assistant":
            prepared_prompt = _prepare_assistant_request_prompt(
                manager,
                profile,
                session,
                request_obj,
                user_id=shared_user_id,
                user_text=text,
                cli_type=normalize_cli_type(profile.cli_type),
            )
            prompt_text = prepared_prompt.prompt_text
            if not _is_dream_request(request_obj) and is_plan_mode:
                prompt_text = build_plan_mode_prompt(prompt_text, cluster_active=bool(cluster_run))
        else:
            prompt_text = build_plan_mode_prompt(text, cluster_active=bool(cluster_run)) if is_plan_mode else text
        prompt_text = _apply_cluster_prompt(
            profile,
            prompt_text,
            cluster_run_id=cluster_run.run_id if cluster_run else "",
            cluster_mentions=list(mentions or []),
        )
        async for event in get_native_agent_service().stream_chat(
            profile=profile,
            session=session,
            user_text=text,
            prompt_text=prompt_text,
            history_service=_history_service_for_execution_mode(session, NATIVE_AGENT_PROVIDER),
            actor=_actor_from_request(request_obj),
            protocol=protocol,
            cluster_run_id=cluster_run.run_id if cluster_run else "",
            solo_mode=solo_mode,
        ):
            if event.get("type") == "error":
                run_status = "error"
            if prepared_prompt is not None and event.get("type") == "done":
                event = dict(event)
                if (
                    not finalization_scheduled
                    and prepared_prompt.assistant_home is not None
                    and prepared_prompt.finalize_assistant_turn
                ):
                    finalization_scheduled = True
                    _schedule_assistant_chat_turn_finalization(
                        prepared_prompt.assistant_home,
                        user_id=shared_user_id,
                        user_text=text,
                        response=str(event.get("output") or ""),
                        assistant_pre_surface=prepared_prompt.assistant_pre_surface,
                        compaction_prompt_active=prepared_prompt.compaction_prompt_active,
                    )
                event["assistant_stage_durations"] = dict(prepared_prompt.stage_durations)
                if prepared_prompt.dream_context_stats is not None:
                    event["dream_context_stats"] = prepared_prompt.dream_context_stats
                    event["dream_prompt_text"] = prepared_prompt.dream_prompt_text
            yield event
    except Exception:
        run_status = "error"
        raise
    finally:
        if cluster_run:
            _CLUSTER_RUNTIME.finish_run(cluster_run.run_id, run_status)
            _cleanup_cluster_run_control_if_idle(cluster_run.run_id)


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
    execution_mode: str = "",
    solo_mode: bool = False,
    actor: dict[str, Any] | None = None,
    allow_unsafe_cli: bool = False,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    shared_user_id = chat_session_user_id(user_id)
    resolved_execution_mode = _resolve_chat_execution_mode(profile, execution_mode)
    if profile.bot_mode == "assistant" and _should_route_assistant_runtime(task_mode, resolved_execution_mode):
        if manager.assistant_runtime is None:
            _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
        if task_mode == "proposal_patch":
            _ensure_proposal_patch_chat_available(manager, alias, shared_user_id)
        request = build_assistant_run_request(
            alias,
            shared_user_id,
            user_text,
            task_mode=task_mode,
            task_payload=task_payload,
            visible_text=visible_text,
            actor=actor,
        )
        return await manager.assistant_runtime.submit_interactive(request)
    if _supports_cli_runtime(profile):
        if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
            return await _run_native_agent_chat(
                manager,
                alias,
                shared_user_id,
                user_text,
                task_mode=task_mode,
                task_payload=task_payload,
                visible_text=visible_text,
                agent_id=agent_id,
                cluster=cluster,
                mentions=mentions,
                solo_mode=solo_mode,
                actor=actor,
                allow_unsafe_cli=allow_unsafe_cli,
            )
        cluster_run = _start_cluster_run_if_requested(
            profile=profile,
            alias=alias,
            shared_user_id=shared_user_id,
            cluster=cluster,
            execution_mode=EXECUTION_MODE_CLI,
            mentions=mentions,
            allow_unsafe_cli=allow_unsafe_cli,
        )
        run_status = "completed"
        request = build_assistant_run_request(
            alias,
            shared_user_id,
            user_text,
            task_mode=task_mode,
            task_payload=task_payload,
            visible_text=visible_text,
            actor=actor,
        )
        try:
            return await run_cli_chat(
                manager,
                alias,
                shared_user_id,
                user_text,
                request=request,
                agent_id=agent_id,
                cluster_run_id=cluster_run.run_id if cluster_run else "",
                cluster_mentions=list(mentions or []),
                allow_unsafe_cli=allow_unsafe_cli,
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
    execution_mode: str = "",
    solo_mode: bool = False,
    actor: dict[str, Any] | None = None,
    protocol: str = "",
    allow_unsafe_cli: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    try:
        profile = get_profile_or_raise(manager, alias)
        shared_user_id = chat_session_user_id(user_id)
        resolved_execution_mode = _resolve_chat_execution_mode(profile, execution_mode)
        if profile.bot_mode == "assistant" and _should_route_assistant_runtime(task_mode, resolved_execution_mode):
            if manager.assistant_runtime is None:
                _raise(503, "assistant_runtime_unavailable", "assistant 运行时尚未启动")
            if task_mode == "proposal_patch":
                _ensure_proposal_patch_chat_available(manager, alias, shared_user_id)
            request = build_assistant_run_request(
                alias,
                shared_user_id,
                user_text,
                task_mode=task_mode,
                task_payload=task_payload,
                visible_text=visible_text,
                actor=actor,
            )
            async for event in manager.assistant_runtime.stream_interactive(request):
                yield event
            return
        if _supports_cli_runtime(profile):
            if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
                async for event in _stream_native_agent_chat(
                    manager,
                    alias,
                    shared_user_id,
                    user_text,
                    task_mode=task_mode,
                    task_payload=task_payload,
                    visible_text=visible_text,
                    agent_id=agent_id,
                    cluster=cluster,
                    mentions=mentions,
                    solo_mode=solo_mode,
                    actor=actor,
                    protocol=protocol,
                    allow_unsafe_cli=allow_unsafe_cli,
                ):
                    yield event
                return
            cluster_run = _start_cluster_run_if_requested(
                profile=profile,
                alias=alias,
                shared_user_id=shared_user_id,
                cluster=cluster,
                execution_mode=EXECUTION_MODE_CLI,
                mentions=mentions,
                allow_unsafe_cli=allow_unsafe_cli,
            )
            run_status = "completed"
            request = build_assistant_run_request(
                alias,
                shared_user_id,
                user_text,
                task_mode=task_mode,
                task_payload=task_payload,
                visible_text=visible_text,
                actor=actor,
            )
            try:
                async for event in _stream_cli_chat(
                    manager,
                    alias,
                    shared_user_id,
                    user_text,
                    request=request,
                    agent_id=agent_id,
                    cluster_run_id=cluster_run.run_id if cluster_run else "",
                    cluster_mentions=list(mentions or []),
                    allow_unsafe_cli=allow_unsafe_cli,
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
    try:
        argv = split_command_argv(cmd)
    except ValueError:
        _raise(400, "empty_command", msg("shell", "usage"))

    session = get_session_for_alias(manager, alias, user_id)
    try:
        process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=session.working_dir,
            ),
            timeout=60,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    except asyncio.TimeoutError:
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        _raise(408, "shell_timeout", "命令执行超时 (60秒)")
    except Exception as exc:
        _raise(500, "shell_failed", str(exc))

    output = strip_ansi_escape((stdout or b"").decode("utf-8", errors="replace") if isinstance(stdout, bytes) else (stdout or ""))
    stderr = strip_ansi_escape((stderr or b"").decode("utf-8", errors="replace") if isinstance(stderr, bytes) else (stderr or ""))
    if stderr:
        output += f"\n\n[stderr]\n{stderr}"
    output = output or msg("shell", "no_output")
    return {
        "command": cmd,
        "output": output,
        "returncode": process.returncode,
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
    actor: dict[str, Any] | None = None,
) -> AssistantRunRequest:
    normalized_task_mode = task_mode if task_mode in {"standard", "dream", "proposal_patch", PLAN_MODE_TASK_MODE} else "standard"
    if normalized_task_mode == PLAN_MODE_TASK_MODE and is_plan_execution_prompt(user_text):
        normalized_task_mode = "standard"
    shared_user_id = chat_session_user_id(user_id)
    actor_data = dict(actor or {})
    return AssistantRunRequest(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        source="web",
        bot_alias=alias,
        user_id=shared_user_id,
        text=user_text,
        interactive=True,
        visible_text=visible_text if visible_text is not None else user_text,
        context_user_id=shared_user_id,
        task_mode=normalized_task_mode,
        task_payload=task_payload,
        actor_user_id=_optional_int(actor_data.get("user_id")),
        actor_account_id=str(actor_data.get("account_id") or "").strip() or None,
        actor_username=str(actor_data.get("username") or "").strip() or None,
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _actor_from_request(request: AssistantRunRequest | None) -> dict[str, Any] | None:
    if request is None:
        return None
    actor: dict[str, Any] = {}
    if request.actor_user_id is not None:
        actor["user_id"] = request.actor_user_id
    if request.actor_account_id:
        actor["account_id"] = request.actor_account_id
    if request.actor_username:
        actor["username"] = request.actor_username
    return actor or None


def execute_plan(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    content: str,
    *,
    title: str = "",
    agent_id: str = "main",
    execution_mode: str = "",
) -> dict[str, Any]:
    user_id = chat_session_user_id(user_id)
    plan_text = str(content or "").strip()
    if not plan_text:
        _raise(400, "empty_plan", "方案不能为空")
    profile, _agent, session = get_chat_session_for_alias(manager, alias, user_id, agent_id)
    saved = save_execution_plan(session.working_dir, plan_text, title=title)
    conversation_data = create_conversation(
        manager,
        alias,
        user_id,
        title=title or "执行方案",
        agent_id=agent_id,
        execution_mode=execution_mode,
    )
    execution_message = build_plan_execution_prompt(saved.relative_path)
    return {
        "plan_path": saved.relative_path,
        "conversation": conversation_data["conversation"],
        "messages": conversation_data["messages"],
        "execution_message": execution_message,
        "bot_mode": profile.bot_mode,
    }


def _ensure_proposal_patch_chat_available(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
) -> None:
    user_id = chat_session_user_id(user_id)
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
            actor=_actor_from_request(request),
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
                generated_by=str(request.actor_user_id or request.user_id),
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
    profile = get_profile_or_raise(manager, request.bot_alias)
    resolved_execution_mode = _resolve_chat_execution_mode(profile, "")
    if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
        result = await _run_native_agent_chat(
            manager,
            request.bot_alias,
            request.user_id,
            request.text,
            request=request,
            prepare_assistant_request=True,
        )
    else:
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
    if _is_dream_request(request):
        result = await execute_assistant_run_request(manager, request)
        yield {"type": "done", **result}
        return
    profile = get_profile_or_raise(manager, request.bot_alias)
    resolved_execution_mode = _resolve_chat_execution_mode(profile, "")
    if resolved_execution_mode == NATIVE_AGENT_PROVIDER:
        async for event in _stream_native_agent_chat(
            manager,
            request.bot_alias,
            request.user_id,
            request.text,
            request=request,
            prepare_assistant_request=True,
        ):
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
    supported_execution_modes: Any = None,
    default_execution_mode: Any = None,
    native_agent: Any = None,
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
            supported_execution_modes=supported_execution_modes,
            default_execution_mode=default_execution_mode,
            native_agent=native_agent,
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


async def update_bot_execution_config(manager: MultiBotManager, alias: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        await manager.set_bot_execution_config(alias, data)
    except ValueError as exc:
        _raise(400, "invalid_bot_execution_config", str(exc))
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
        _clear_all_native_sessions_locked(session)
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


async def update_bot_prompt_presets(
    manager: MultiBotManager,
    alias: str,
    presets: Any,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    get_profile_or_raise(manager, alias)
    try:
        await manager.set_bot_prompt_presets(alias, presets)
    except ValueError as exc:
        _raise(400, "invalid_prompt_presets", str(exc))
    return {"bot": build_bot_summary(manager, alias, user_id)}


async def update_global_prompt_presets(
    manager: MultiBotManager,
    presets: Any,
) -> dict[str, Any]:
    try:
        normalized = app_settings.update_global_prompt_presets(presets, manager.app_settings_file)
    except ValueError as exc:
        _raise(400, "invalid_prompt_presets", str(exc))
    return {"global_prompt_presets": normalized}


def get_processing_sessions(alias: str) -> list[dict[str, Any]]:
    items = []
    with sessions_lock:
        for (bot_id, user_id, agent_id), session in sessions.items():
            if session.bot_alias != alias:
                continue
            if not session.is_processing:
                continue
            items.append(
                {
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "working_dir": session.working_dir,
                    "message_count": session.message_count,
                }
            )
    return items
