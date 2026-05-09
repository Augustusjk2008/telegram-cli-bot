from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bot.manager import MultiBotManager
from bot.web.api_common import AuthContext, _raise, _require_capability, get_profile_or_raise, get_session_for_alias
from bot.web.auth_store import CAP_RUN_PLUGINS, CAP_VIEW_PLUGINS


def _require_real_browser_directory(browser_dir: str) -> str:
    if browser_dir == "::windows-drives::":
        _raise(409, "virtual_directory_unsupported", "当前视图仅用于切换盘符，不能直接执行文件操作")
    return browser_dir


def _get_browser_directory(session) -> str:
    if isinstance(session.browse_dir, str) and session.browse_dir.strip():
        return session.browse_dir
    return session.working_dir


def _resolve_safe_path(base_dir: str, filename: str) -> str:
    candidate = str(filename or "").strip()
    if not candidate or candidate == "." or "\x00" in candidate:
        _raise(400, "unsafe_path", "文件路径不安全")
    if os.path.isabs(candidate):
        return os.path.abspath(os.path.expanduser(candidate))
    return os.path.abspath(os.path.join(base_dir, os.path.expanduser(candidate)))


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

