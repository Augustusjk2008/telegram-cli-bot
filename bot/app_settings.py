"""Web 管理页的持久化应用设置。"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from bot.cluster.config import (
    AgentClusterConfig,
    BotClusterConfig,
    normalize_agent_cluster_config,
    normalize_bot_cluster_config,
)
from bot.config import MANAGED_BOTS_FILE

APP_SETTINGS_FILE = Path(MANAGED_BOTS_FILE).resolve().parent / ".web_admin_settings.json"
_SETTINGS_LOCK = threading.Lock()
_DEFAULT_SETTINGS = {
    "git_proxy_address": "",
    "git_proxy_port": "",
    "bot_avatar_names": {},
    "main_bot_profile": {},
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
    "update_last_error": "",
}
_PORT_ERROR_MESSAGE = "代理端口必须是 1 到 65535 之间的整数"
_PROXY_ADDRESS_ERROR_MESSAGE = "代理地址必须是 host:port，或 1 到 65535 之间的端口"
_PROXY_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")

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
    "update_last_error",
)


def _resolve_settings_file(settings_file: str | Path | None = None) -> Path:
    return Path(settings_file).expanduser().resolve() if settings_file is not None else APP_SETTINGS_FILE


def _normalize_git_proxy_port(value: Any) -> str:
    port = str(value or "").strip()
    if not port:
        return ""
    if not port.isdigit():
        raise ValueError(_PORT_ERROR_MESSAGE)

    port_number = int(port)
    if not 1 <= port_number <= 65535:
        raise ValueError(_PORT_ERROR_MESSAGE)
    return str(port_number)


def _normalize_git_proxy_host(host: Any) -> str:
    normalized = str(host or "").strip()
    if not normalized:
        raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
    if any(char.isspace() for char in normalized):
        raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
    if not _PROXY_HOST_RE.fullmatch(normalized):
        raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
    return normalized


def _normalize_git_proxy_address(value: Any) -> str:
    address = str(value or "").strip()
    if not address:
        return ""
    if address.isdigit():
        return f"127.0.0.1:{_normalize_git_proxy_port(address)}"
    if address.startswith("["):
        bracket_end = address.find("]")
        if bracket_end <= 1 or address[bracket_end + 1: bracket_end + 2] != ":":
            raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
        host = address[1:bracket_end].strip()
        port = _normalize_git_proxy_port(address[bracket_end + 2:])
        if not host or any(char.isspace() for char in host):
            raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
        return f"[{host}]:{port}"
    if address.count(":") != 1:
        raise ValueError(_PROXY_ADDRESS_ERROR_MESSAGE)
    host, port = address.rsplit(":", 1)
    return f"{_normalize_git_proxy_host(host)}:{_normalize_git_proxy_port(port)}"


def _git_proxy_port_from_address(address: str) -> str:
    normalized = str(address or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("["):
        bracket_end = normalized.find("]")
        if bracket_end > 0 and normalized[bracket_end + 1: bracket_end + 2] == ":":
            return normalized[bracket_end + 2:]
        return ""
    if ":" not in normalized:
        return ""
    return normalized.rsplit(":", 1)[1]


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
    cli_type = str(value.get("cli_type") or "").strip().lower()
    if cli_type in {"claude", "codex"}:
        normalized["cli_type"] = cli_type

    for key in ("cli_path", "working_dir"):
        text = str(value.get(key) or "").strip()
        if text:
            normalized[key] = text

    bot_mode = str(value.get("bot_mode") or "").strip().lower()
    if bot_mode in {"cli", "assistant"}:
        normalized["bot_mode"] = bot_mode

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

    return normalized


def _sanitize_settings(raw: Any) -> dict[str, Any]:
    settings = dict(_DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    try:
        if "git_proxy_address" in raw:
            settings["git_proxy_address"] = _normalize_git_proxy_address(raw.get("git_proxy_address", ""))
        else:
            settings["git_proxy_address"] = _normalize_git_proxy_address(raw.get("git_proxy_port", ""))
        settings["git_proxy_port"] = _git_proxy_port_from_address(settings["git_proxy_address"])
    except ValueError:
        settings["git_proxy_address"] = ""
        settings["git_proxy_port"] = ""
    settings["bot_avatar_names"] = _normalize_bot_avatar_names(raw.get("bot_avatar_names", {}))
    settings["main_bot_profile"] = _normalize_main_bot_profile(raw.get("main_bot_profile", {}))
    settings["update_enabled"] = _normalize_bool(raw.get("update_enabled"), True)
    settings["update_channel"] = _normalize_optional_text(raw.get("update_channel", "release")) or "release"
    for key in _UPDATE_TEXT_FIELDS:
        if key == "update_channel":
            continue
        settings[key] = _normalize_optional_text(raw.get(key, settings[key]), strip=False)
    return settings


def _normalize_bot_avatar_names(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_alias, raw_avatar_name in value.items():
        alias = str(raw_alias or "").strip().lower()
        if not alias:
            continue
        avatar_name = str(raw_avatar_name or "").strip()
        if avatar_name:
            normalized[alias] = avatar_name
    return normalized


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
    git_proxy_address = _normalize_git_proxy_address(
        settings.get("git_proxy_address", "") or settings.get("git_proxy_port", "")
    )
    if git_proxy_address:
        payload["git_proxy_address"] = git_proxy_address

    bot_avatar_names = _normalize_bot_avatar_names(settings.get("bot_avatar_names", {}))
    if bot_avatar_names:
        payload["bot_avatar_names"] = bot_avatar_names

    main_bot_profile = _normalize_main_bot_profile(settings.get("main_bot_profile", {}))
    if main_bot_profile:
        payload["main_bot_profile"] = main_bot_profile

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


def get_git_proxy_settings() -> dict[str, str]:
    settings = _load_settings()
    address = settings["git_proxy_address"]
    return {"address": address, "port": _git_proxy_port_from_address(address)}


def update_git_proxy_address(address: Any) -> dict[str, str]:
    normalized = _normalize_git_proxy_address(address)
    settings = _load_settings()
    settings["git_proxy_address"] = normalized
    settings["git_proxy_port"] = _git_proxy_port_from_address(normalized)
    _save_settings(settings)
    return {"address": normalized, "port": settings["git_proxy_port"]}


def update_git_proxy_port(port: Any) -> dict[str, str]:
    return update_git_proxy_address(port)


def get_bot_avatar_name(alias: str, settings_file: str | Path | None = None) -> str | None:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return None
    settings = _load_settings(settings_file)
    avatar_name = settings["bot_avatar_names"].get(normalized_alias)
    if not avatar_name:
        return None
    return str(avatar_name)


def list_bot_avatar_names(settings_file: str | Path | None = None) -> dict[str, str]:
    settings = _load_settings(settings_file)
    return dict(settings["bot_avatar_names"])


def get_main_bot_profile(settings_file: str | Path | None = None) -> dict[str, Any]:
    settings = _load_settings(settings_file)
    return copy.deepcopy(settings["main_bot_profile"])


def update_main_bot_profile(profile: dict[str, Any], settings_file: str | Path | None = None) -> dict[str, Any]:
    normalized_profile = _normalize_main_bot_profile(profile)
    settings = _load_settings(settings_file)
    settings["main_bot_profile"] = normalized_profile
    _save_settings(settings, settings_file)
    return copy.deepcopy(normalized_profile)


def update_bot_avatar_name(alias: str, avatar_name: Any, settings_file: str | Path | None = None) -> str:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        raise ValueError("bot alias 不能为空")

    normalized_avatar_name = str(avatar_name or "").strip()
    settings = _load_settings(settings_file)
    avatar_names = dict(settings["bot_avatar_names"])
    if not normalized_avatar_name:
        avatar_names.pop(normalized_alias, None)
    else:
        avatar_names[normalized_alias] = normalized_avatar_name
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings, settings_file)
    return normalized_avatar_name


def remove_bot_avatar_name(alias: str, settings_file: str | Path | None = None) -> None:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return
    settings = _load_settings(settings_file)
    avatar_names = dict(settings["bot_avatar_names"])
    if normalized_alias not in avatar_names:
        return
    avatar_names.pop(normalized_alias, None)
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings, settings_file)


def rename_bot_avatar_name(
    old_alias: str,
    new_alias: str,
    settings_file: str | Path | None = None,
) -> None:
    normalized_old_alias = str(old_alias or "").strip().lower()
    normalized_new_alias = str(new_alias or "").strip().lower()
    if not normalized_old_alias or not normalized_new_alias or normalized_old_alias == normalized_new_alias:
        return

    settings = _load_settings(settings_file)
    avatar_names = dict(settings["bot_avatar_names"])
    avatar_name = avatar_names.pop(normalized_old_alias, None)
    if avatar_name is None:
        settings["bot_avatar_names"] = avatar_names
        _save_settings(settings, settings_file)
        return

    avatar_names[normalized_new_alias] = avatar_name
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings, settings_file)


def get_git_proxy_url() -> str:
    address = get_git_proxy_settings()["address"]
    if not address:
        return ""
    return f"http://{address}"


def get_git_proxy_config_args() -> list[str]:
    proxy_url = get_git_proxy_url()
    return [
        "-c",
        f"http.proxy={proxy_url}",
        "-c",
        f"https.proxy={proxy_url}",
    ]


def build_git_proxy_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ.copy())
    proxy_url = get_git_proxy_url()
    env.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "http.proxy",
            "GIT_CONFIG_VALUE_0": proxy_url,
            "GIT_CONFIG_KEY_1": "https.proxy",
            "GIT_CONFIG_VALUE_1": proxy_url,
        }
    )
    return env
