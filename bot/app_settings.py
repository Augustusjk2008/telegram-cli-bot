"""Web 管理页的持久化应用设置。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from bot.config import MANAGED_BOTS_FILE

APP_SETTINGS_FILE = Path(MANAGED_BOTS_FILE).resolve().parent / ".web_admin_settings.json"
_SETTINGS_LOCK = threading.Lock()
_DEFAULT_SETTINGS = {
    "git_proxy_port": "",
    "bot_avatar_names": {},
}
_PORT_ERROR_MESSAGE = "代理端口必须是 1 到 65535 之间的整数"
_DEFAULT_BOT_AVATAR_NAME = "bot-default.png"


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


def _sanitize_settings(raw: Any) -> dict[str, Any]:
    settings = {
        "git_proxy_port": "",
        "bot_avatar_names": {},
    }
    if not isinstance(raw, dict):
        return settings

    try:
        settings["git_proxy_port"] = _normalize_git_proxy_port(raw.get("git_proxy_port", ""))
    except ValueError:
        settings["git_proxy_port"] = ""
    settings["bot_avatar_names"] = _normalize_bot_avatar_names(raw.get("bot_avatar_names", {}))
    return settings


def _normalize_bot_avatar_names(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_alias, raw_avatar_name in value.items():
        alias = str(raw_alias or "").strip().lower()
        if not alias:
            continue
        avatar_name = str(raw_avatar_name or "").strip() or _DEFAULT_BOT_AVATAR_NAME
        normalized[alias] = avatar_name
    return normalized


def _load_settings() -> dict[str, Any]:
    with _SETTINGS_LOCK:
        try:
            if not APP_SETTINGS_FILE.exists():
                return _sanitize_settings(_DEFAULT_SETTINGS)
            raw = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _sanitize_settings(_DEFAULT_SETTINGS)
        return _sanitize_settings(raw)


def _serialize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    git_proxy_port = _normalize_git_proxy_port(settings.get("git_proxy_port", ""))
    if git_proxy_port:
        payload["git_proxy_port"] = git_proxy_port

    bot_avatar_names = _normalize_bot_avatar_names(settings.get("bot_avatar_names", {}))
    if bot_avatar_names:
        payload["bot_avatar_names"] = bot_avatar_names
    return payload


def _save_settings(settings: dict[str, Any]) -> None:
    with _SETTINGS_LOCK:
        APP_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        APP_SETTINGS_FILE.write_text(
            json.dumps(_serialize_settings(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_git_proxy_settings() -> dict[str, str]:
    settings = _load_settings()
    return {"port": settings["git_proxy_port"]}


def update_git_proxy_port(port: Any) -> dict[str, str]:
    normalized = _normalize_git_proxy_port(port)
    settings = _load_settings()
    settings["git_proxy_port"] = normalized
    _save_settings(settings)
    return {"port": normalized}


def get_bot_avatar_name(alias: str) -> str | None:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return None
    settings = _load_settings()
    avatar_name = settings["bot_avatar_names"].get(normalized_alias)
    if not avatar_name:
        return None
    return str(avatar_name)


def list_bot_avatar_names() -> dict[str, str]:
    settings = _load_settings()
    return dict(settings["bot_avatar_names"])


def update_bot_avatar_name(alias: str, avatar_name: Any) -> str:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        raise ValueError("bot alias 不能为空")

    normalized_avatar_name = str(avatar_name or "").strip() or _DEFAULT_BOT_AVATAR_NAME
    settings = _load_settings()
    avatar_names = dict(settings["bot_avatar_names"])
    if normalized_avatar_name == _DEFAULT_BOT_AVATAR_NAME:
        avatar_names.pop(normalized_alias, None)
    else:
        avatar_names[normalized_alias] = normalized_avatar_name
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings)
    return normalized_avatar_name


def remove_bot_avatar_name(alias: str) -> None:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return
    settings = _load_settings()
    avatar_names = dict(settings["bot_avatar_names"])
    if normalized_alias not in avatar_names:
        return
    avatar_names.pop(normalized_alias, None)
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings)


def rename_bot_avatar_name(old_alias: str, new_alias: str) -> None:
    normalized_old_alias = str(old_alias or "").strip().lower()
    normalized_new_alias = str(new_alias or "").strip().lower()
    if not normalized_old_alias or not normalized_new_alias or normalized_old_alias == normalized_new_alias:
        return

    settings = _load_settings()
    avatar_names = dict(settings["bot_avatar_names"])
    avatar_name = avatar_names.pop(normalized_old_alias, None)
    if avatar_name is None:
        settings["bot_avatar_names"] = avatar_names
        _save_settings(settings)
        return

    avatar_names[normalized_new_alias] = avatar_name
    settings["bot_avatar_names"] = avatar_names
    _save_settings(settings)


def get_git_proxy_url() -> str:
    port = get_git_proxy_settings()["port"]
    if not port:
        return ""
    return f"http://127.0.0.1:{port}"


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
