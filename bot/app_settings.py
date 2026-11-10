"""Web 管理页的持久化应用设置。"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from bot.cluster.config import (
    AgentClusterConfig,
    BotClusterConfig,
    normalize_agent_cluster_config,
    normalize_bot_cluster_config,
)
from bot.models import (
    normalize_execution_mode_config,
    normalize_native_agent_config,
    normalize_prompt_presets,
)
from bot.runtime_paths import get_app_settings_path

APP_SETTINGS_FILE = get_app_settings_path()
_SETTINGS_LOCK = threading.Lock()
_DEFAULT_SETTINGS = {
    "main_bot_profile": {},
    "global_prompt_presets": [],
    "update_enabled": True,
    "update_channel": "release",
    "last_checked_at": "",
    "last_available_version": "",
    "last_available_release_url": "",
    "last_available_notes": "",
    "pending_update_version": "",
    "pending_update_path": "",
    "pending_update_notes": "",
    "pending_update_platform": "",
    "pending_update_package_kind": "",
    "pending_update_sha256": "",
    "update_last_error": "",
}

_UPDATE_TEXT_FIELDS = (
    "update_channel",
    "last_checked_at",
    "last_available_version",
    "last_available_release_url",
    "last_available_notes",
    "pending_update_version",
    "pending_update_path",
    "pending_update_notes",
    "pending_update_platform",
    "pending_update_package_kind",
    "pending_update_sha256",
    "update_last_error",
)


def _resolve_settings_file(settings_file: str | Path | None = None) -> Path:
    return Path(settings_file).expanduser().resolve() if settings_file is not None else APP_SETTINGS_FILE


def _normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_optional_text(value: Any, *, strip: bool = True) -> str:
    text = str(value or "")
    return text.strip() if strip else text


def _normalize_main_bot_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, Any] = {}
    if isinstance(value.get("chat_translation_enabled"), bool):
        normalized["chat_translation_enabled"] = value["chat_translation_enabled"]
    cli_type = str(value.get("cli_type") or "").strip().lower()
    if cli_type in {"claude", "codex", "codex_server", "antigravity", "deepseek"}:
        normalized["cli_type"] = cli_type

    for key in ("cli_path", "working_dir"):
        text = str(value.get(key) or "").strip()
        if text:
            normalized[key] = text

    cli_params = value.get("cli_params")
    if isinstance(cli_params, dict):
        normalized["cli_params"] = copy.deepcopy(cli_params)

    agents = value.get("agents")
    if isinstance(agents, list):
        normalized_agents: list[dict[str, Any]] = []
        for item in agents:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("id") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            if not agent_id or not name:
                continue
            normalized_agent = {
                "id": agent_id,
                "name": name,
                "system_prompt": str(item.get("system_prompt") or ""),
                "enabled": bool(item.get("enabled", True)),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
            if isinstance(item.get("cluster"), dict):
                agent_cluster = normalize_agent_cluster_config(item.get("cluster"))
                if agent_cluster != AgentClusterConfig():
                    normalized_agent["cluster"] = agent_cluster.to_dict()
            normalized_agents.append(normalized_agent)
        if normalized_agents:
            normalized["agents"] = normalized_agents

    if isinstance(value.get("cluster"), dict):
        cluster = normalize_bot_cluster_config(value.get("cluster"))
        if cluster != BotClusterConfig():
            normalized["cluster"] = cluster.to_dict()

    prompt_presets = normalize_prompt_presets(value.get("prompt_presets", value.get("promptPresets")))
    if prompt_presets:
        normalized["prompt_presets"] = prompt_presets

    if any(key in value for key in ("supported_execution_modes", "supportedExecutionModes", "default_execution_mode", "defaultExecutionMode")):
        supported_execution_modes, default_execution_mode = normalize_execution_mode_config(
            value.get("supported_execution_modes", value.get("supportedExecutionModes")),
            value.get("default_execution_mode", value.get("defaultExecutionMode")),
        )
        normalized["supported_execution_modes"] = supported_execution_modes
        normalized["default_execution_mode"] = default_execution_mode

    if any(key in value for key in ("native_agent", "nativeAgent")):
        normalized["native_agent"] = normalize_native_agent_config(
            value.get("native_agent", value.get("nativeAgent"))
        )

    if value.get("remote_workspace"):
        from bot.remote_workspace.transport import normalize_remote_workspace
        normalized["remote_workspace"] = normalize_remote_workspace(value["remote_workspace"])

    return normalized


def _sanitize_settings(raw: Any) -> dict[str, Any]:
    settings = dict(_DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    settings["main_bot_profile"] = _normalize_main_bot_profile(raw.get("main_bot_profile", {}))
    settings["global_prompt_presets"] = normalize_prompt_presets(
        raw.get("global_prompt_presets", raw.get("globalPromptPresets"))
    )
    settings["update_enabled"] = _normalize_bool(raw.get("update_enabled"), True)
    settings["update_channel"] = _normalize_optional_text(raw.get("update_channel", "release")) or "release"
    for key in _UPDATE_TEXT_FIELDS:
        if key == "update_channel":
            continue
        settings[key] = _normalize_optional_text(raw.get(key, settings[key]), strip=False)
    return settings


def _load_settings(settings_file: str | Path | None = None) -> dict[str, Any]:
    settings_path = _resolve_settings_file(settings_file)
    with _SETTINGS_LOCK:
        try:
            if not settings_path.exists():
                return _sanitize_settings(_DEFAULT_SETTINGS)
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _sanitize_settings(_DEFAULT_SETTINGS)
        return _sanitize_settings(raw)


def _serialize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    main_bot_profile = _normalize_main_bot_profile(settings.get("main_bot_profile", {}))
    if main_bot_profile:
        payload["main_bot_profile"] = main_bot_profile

    global_prompt_presets = normalize_prompt_presets(settings.get("global_prompt_presets"))
    if global_prompt_presets:
        payload["global_prompt_presets"] = global_prompt_presets

    update_enabled = _normalize_bool(settings.get("update_enabled"), True)
    if not update_enabled:
        payload["update_enabled"] = False

    update_channel = _normalize_optional_text(settings.get("update_channel", "release")) or "release"
    if update_channel != "release":
        payload["update_channel"] = update_channel

    for key in _UPDATE_TEXT_FIELDS:
        if key == "update_channel":
            continue
        value = _normalize_optional_text(settings.get(key, ""), strip=False)
        if value:
            payload[key] = value
    return payload


def _save_settings(settings: dict[str, Any], settings_file: str | Path | None = None) -> None:
    settings_path = _resolve_settings_file(settings_file)
    with _SETTINGS_LOCK:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(_serialize_settings(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_main_bot_profile(settings_file: str | Path | None = None) -> dict[str, Any]:
    settings = _load_settings(settings_file)
    return copy.deepcopy(settings["main_bot_profile"])


def get_global_prompt_presets(settings_file: str | Path | None = None) -> list[dict[str, str]]:
    settings = _load_settings(settings_file)
    return [dict(item) for item in settings["global_prompt_presets"]]


def update_main_bot_profile(profile: dict[str, Any], settings_file: str | Path | None = None) -> dict[str, Any]:
    normalized_profile = _normalize_main_bot_profile(profile)
    settings = _load_settings(settings_file)
    settings["main_bot_profile"] = normalized_profile
    _save_settings(settings, settings_file)
    return copy.deepcopy(normalized_profile)


def update_global_prompt_presets(
    presets: Any,
    settings_file: str | Path | None = None,
) -> list[dict[str, str]]:
    normalized = normalize_prompt_presets(presets, strict=True)
    settings = _load_settings(settings_file)
    settings["global_prompt_presets"] = normalized
    _save_settings(settings, settings_file)
    return [dict(item) for item in normalized]
