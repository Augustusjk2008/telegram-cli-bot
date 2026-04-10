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
}
_PORT_ERROR_MESSAGE = "代理端口必须是 1 到 65535 之间的整数"


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


def _sanitize_settings(raw: Any) -> dict[str, str]:
    settings = dict(_DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    try:
        settings["git_proxy_port"] = _normalize_git_proxy_port(raw.get("git_proxy_port", ""))
    except ValueError:
        settings["git_proxy_port"] = ""
    return settings


def _load_settings() -> dict[str, str]:
    with _SETTINGS_LOCK:
        try:
            if not APP_SETTINGS_FILE.exists():
                return dict(_DEFAULT_SETTINGS)
            raw = json.loads(APP_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(_DEFAULT_SETTINGS)
        return _sanitize_settings(raw)


def _save_settings(settings: dict[str, str]) -> None:
    with _SETTINGS_LOCK:
        APP_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        APP_SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
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
