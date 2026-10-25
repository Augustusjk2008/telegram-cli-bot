"""全局配置、常量、日志初始化"""

import asyncio
import json
import logging
import math
import os
import re
import sys
from typing import Any, List, Optional, Set

from bot.cli_params import CLI_MODEL_OPTION_TYPES, normalize_cli_model_options
from bot.native_agent.legacy_migration import resolve_pi_agent_env

try:
    import winreg as _WINREG
except ImportError:
    _WINREG = None

_WINDOWS_SYSTEM_ENV_SUBKEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_WINDOWS_ENV_REF_RE = re.compile(r"%([^%]+)%")

# 加载 .env 文件中的环境变量
_INITIAL_PROCESS_ENV = dict(os.environ)
_INITIAL_PROCESS_ENV_KEYS = {key.casefold() for key in _INITIAL_PROCESS_ENV}
_INITIAL_PROCESS_ENV_NAMES = {key.casefold(): key for key in _INITIAL_PROCESS_ENV}
_RUNTIME_SYSTEM_ENV_NAMES: dict[str, str] = {}
try:
    from dotenv import dotenv_values, load_dotenv
    _DOTENV_VALUES = {
        key: value
        for key, value in dotenv_values().items()
        if value is not None
    }
    load_dotenv()
except ImportError:
    dotenv_values = None
    _DOTENV_VALUES = {}
    pass  # python-dotenv 未安装时跳过

# ============ 环境变量读取 ============
def _split_csv_env(raw_value: str) -> List[str]:
    return [item.strip() for item in (raw_value or "").split(",") if item.strip()]


def _parse_cli_model_options(raw_value: str) -> list[str] | dict[str, list[str]]:
    """Parse the legacy CSV or the per-CLI JSON model table."""
    value = str(raw_value or "").strip()
    if not value:
        return normalize_cli_model_options([])

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return normalize_cli_model_options(_split_csv_env(value))

    if isinstance(payload, list):
        return normalize_cli_model_options(payload)
    if not isinstance(payload, dict):
        logging.warning("忽略无效的 CLI_MODEL_OPTIONS：必须是 CSV 或 JSON object")
        return normalize_cli_model_options([])

    parsed: dict[str, list[str]] = {}
    for key, options in payload.items():
        cli_type = str(key or "").strip().lower()
        if cli_type not in CLI_MODEL_OPTION_TYPES:
            logging.warning("忽略无效的 CLI_MODEL_OPTIONS.%s：不支持的 CLI 类型", key)
            continue
        if not isinstance(options, list):
            logging.warning("忽略无效的 CLI_MODEL_OPTIONS.%s：必须是字符串数组", key)
            continue
        parsed[cli_type] = normalize_cli_model_options(options)
    return parsed


def _parse_cli_global_extra_args(raw_value: str) -> dict[str, list[str]]:
    value = (raw_value or "").strip()
    if not value:
        return {}
    try:
        payload: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        logging.warning("忽略无效的 CLI_GLOBAL_EXTRA_ARGS JSON: %s", exc)
        return {}
    if not isinstance(payload, dict):
        logging.warning("忽略无效的 CLI_GLOBAL_EXTRA_ARGS：必须是 JSON object")
        return {}

    parsed: dict[str, list[str]] = {}
    for key, args in payload.items():
        cli_type = str(key or "").strip().lower()
        if cli_type not in SUPPORTED_CLI_TYPES:
            logging.warning("忽略无效的 CLI_GLOBAL_EXTRA_ARGS.%s：不支持的 CLI 类型", key)
            continue
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            logging.warning("忽略无效的 CLI_GLOBAL_EXTRA_ARGS.%s：必须是字符串数组", key)
            return {}
        parsed[cli_type] = [item for item in args if item.strip()]
    return parsed


def _get_project_config(name: str, default: str = "") -> str:
    """读取项目配置，优先使用当前进程显式环境变量，其次回退到仓库 .env。"""
    env_value = os.environ.get(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value)
    dotenv_value = _DOTENV_VALUES.get(name)
    if dotenv_value is not None and str(dotenv_value).strip():
        return str(dotenv_value)
    return default


def _get_project_bool(name: str, default: bool = False) -> bool:
    value = _get_project_config(name, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_project_float(name: str, default: float) -> float:
    raw_value = _get_project_config(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError:
        logging.warning("忽略无效的浮点配置 %s=%s，使用默认值 %s", name, raw_value, default)
        return default
    if not math.isfinite(value):
        logging.warning("忽略非有限浮点配置 %s=%s，使用默认值 %s", name, raw_value, default)
        return default
    return value


def _get_project_int(name: str, default: int) -> int:
    raw_value = _get_project_config(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        logging.warning("忽略无效的整数配置 %s=%s，使用默认值 %s", name, raw_value, default)
        return default


def _get_project_optional_int(name: str, default: int = 0) -> int:
    raw_value = _get_project_config(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        logging.warning("忽略无效的整数配置 %s=%s，使用默认值 %s", name, raw_value, default)
        return default


_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _normalize_node_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not _NODE_ID_RE.fullmatch(normalized):
        logging.warning("忽略无效的 TCB_NODE_ID=%s", normalized)
        return ""
    return normalized


def _normalize_base_path(value: str, node_id: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized == "/":
        return ""
    normalized = normalized.rstrip("/")
    expected = f"/node/{node_id}" if node_id else ""
    if expected and normalized == expected:
        return normalized
    logging.warning("忽略无效的 WEB_BASE_PATH=%s，必须为空或等于 %s", normalized, expected or "/node/<TCB_NODE_ID>")
    return ""


def _effective_frontend_base_path(name: str, web_base_path: str) -> str:
    raw_value = _get_project_config(name, "").strip()
    if not raw_value:
        return web_base_path
    normalized = raw_value.rstrip("/") if raw_value != "/" else ""
    if normalized == web_base_path:
        return web_base_path
    logging.warning("忽略无效的 %s=%s，必须为空或等于 WEB_BASE_PATH=%s", name, raw_value, web_base_path)
    return web_base_path


DEFAULT_APP_UPDATE_REPOSITORY = "Augustusjk2008/telegram-cli-bot"

# ============ 常量定义 ============
SUPPORTED_CLI_TYPES = {"claude", "codex", "codex_server", "antigravity", "deepseek"}
# Display guidance only; the actual installation directory is resolved from
# the dsh.cmd wrapper so it can move with a user's Desktop installation.
DEEPSEEK_DESKTOP_CLI_PATH_HINT = r"桌面版安装目录\resources\runtime\cli\bin\dsh.cmd"


def _refresh_environment_config() -> None:
    """Refresh values derived from the current process environment."""
    global ALLOWED_USER_IDS, CLI_TYPE, CLI_PATH, TCB_CODEX_SERVER_VOICE_ENABLED
    global TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS, TELEGRAM_BROADCAST_COMPLETIONS
    global NATIVE_AGENT_BACKEND, NATIVE_AGENT_PATH, NATIVE_AGENT_ENABLED, NATIVE_AGENT_PI_HOME
    global NATIVE_AGENT_PI_COMMAND, NATIVE_AGENT_COMMAND, NATIVE_AGENT_PROVIDER, NATIVE_AGENT_MODEL
    global NATIVE_AGENT_BASE_URL, NATIVE_AGENT_API_KEY, NATIVE_AGENT_PI_AGENT
    global NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED, NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS
    global NATIVE_AGENT_REASONING_EFFORT, NATIVE_AGENT_THINKING_DEPTH, CLI_MODEL_OPTIONS
    global CLI_GLOBAL_EXTRA_ARGS, MODEL_PRICES_FILE, WORKING_DIR, CLAUDE_DONE_DETECTOR_ENABLED
    global CLAUDE_DONE_QUIET_SECONDS, CLAUDE_DONE_SENTINEL_MODE, MANAGED_BOTS_FILE, WEB_ENABLED
    global WEB_HOST, WEB_PORT, WEB_PUBLIC_URL, WEB_API_TOKEN, WEB_ALLOWED_ORIGINS, WEB_DEFAULT_USER_ID
    global WEB_TERMINAL_SHELL_PATH, TCB_NODE_ID, WEB_BASE_PATH, EFFECTIVE_VITE_BASE_PATH
    global EFFECTIVE_VITE_API_BASE_URL, WEB_FIXED_PUBLIC_FORWARD_ENABLED, WEB_FIXED_PUBLIC_FORWARD_URL
    global TCB_HUB_FRPS_PORT, TCB_HUB_NODE_TOKEN, TCB_HUB_FRPS_TOKEN, TCB_HUB_FRPC_PATH
    global TCB_HUB_FRPC_AUTOSTART, WEB_TUNNEL_MODE, WEB_TUNNEL_AUTOSTART
    global WEB_TUNNEL_CLOUDFLARED_PATH, WEB_TUNNEL_STATE_FILE, APP_UPDATE_REPOSITORY
    global TCB_STORAGE_MIGRATION_WORKERS
    global TCB_LSP_ENABLED, TCB_LSP_PYRIGHT_COMMAND, TCB_LSP_TYPESCRIPT_COMMAND
    global TCB_LSP_CLANGD_COMMAND, TCB_LSP_REQUEST_TIMEOUT_SECONDS, TCB_LSP_IDLE_TIMEOUT_SECONDS
    global TCB_LSP_MAX_RUNTIMES, TCB_LSP_EXTERNAL_SOURCES_ENABLED, CHAT_COMPLETION_NOTIFY_ENABLED
    global PUSHPLUS_ENABLED, PUSHPLUS_TOKEN, PUSHPLUS_TOPIC, PUSHPLUS_TEMPLATE, PUSHPLUS_CHANNEL
    global PUSHPLUS_API_URL, PUSHPLUS_TIMEOUT_SECONDS, PUSHPLUS_PREVIEW_CHARS

    allowed_user_ids: list[int] = []
    allowed_raw = os.environ.get("ALLOWED_USER_IDS", "")
    for uid in allowed_raw.split(","):
        uid = uid.strip()
        if uid:
            try:
                allowed_user_ids.append(int(uid))
            except ValueError:
                logging.warning("忽略无效的用户ID: %s", uid)
    ALLOWED_USER_IDS = allowed_user_ids

    TELEGRAM_ENABLED = _get_project_bool("TELEGRAM_ENABLED", False)
    TELEGRAM_BOT_TOKEN = _get_project_config("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_ALLOWED_USER_IDS = set()
    for uid in _split_csv_env(_get_project_config("TELEGRAM_ALLOWED_USER_IDS", "")):
        if uid.isascii() and uid.isdigit() and int(uid) > 0:
            TELEGRAM_ALLOWED_USER_IDS.add(int(uid))
        else:
            logging.warning("忽略无效的 TELEGRAM_ALLOWED_USER_IDS 项：需要正整数用户 ID")
    TELEGRAM_BROADCAST_COMPLETIONS = _get_project_bool("TELEGRAM_BROADCAST_COMPLETIONS", False)

    CLI_TYPE = _get_project_config("CLI_TYPE", "codex").strip().lower()
    configured_cli_path = _get_project_config("CLI_PATH", "").strip()
    CLI_PATH = configured_cli_path or {
        "claude": "claude",
        "antigravity": "agy",
        "deepseek": "dsh",
    }.get(CLI_TYPE, "codex")
    TCB_CODEX_SERVER_VOICE_ENABLED = _get_project_bool("TCB_CODEX_SERVER_VOICE_ENABLED", False)
    NATIVE_AGENT_BACKEND = "pi"
    NATIVE_AGENT_PATH = _get_project_config("NATIVE_AGENT_PATH", "").strip()
    NATIVE_AGENT_ENABLED = _get_project_bool("NATIVE_AGENT_ENABLED", False)
    NATIVE_AGENT_PI_HOME = _get_project_config("NATIVE_AGENT_PI_HOME", "").strip()
    NATIVE_AGENT_PI_COMMAND = (
        _get_project_config(
            "NATIVE_AGENT_PI_COMMAND",
            _get_project_config("NATIVE_AGENT_COMMAND", NATIVE_AGENT_PATH or "pi"),
        ).strip()
        or "pi"
    )
    NATIVE_AGENT_COMMAND = (
        _get_project_config("NATIVE_AGENT_COMMAND", "").strip()
        or NATIVE_AGENT_PATH
        or NATIVE_AGENT_PI_COMMAND
        or "pi"
    )
    NATIVE_AGENT_PROVIDER = _get_project_config("NATIVE_AGENT_PROVIDER", "").strip()
    NATIVE_AGENT_MODEL = _get_project_config("NATIVE_AGENT_MODEL", "").strip()
    NATIVE_AGENT_BASE_URL = _get_project_config("NATIVE_AGENT_BASE_URL", "").strip()
    NATIVE_AGENT_API_KEY = _get_project_config("NATIVE_AGENT_API_KEY", "").strip()
    NATIVE_AGENT_PI_AGENT = resolve_pi_agent_env(_get_project_config)
    NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED = _get_project_bool("NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS = _get_project_float("NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS", 0.0)
    NATIVE_AGENT_REASONING_EFFORT = _get_project_config("NATIVE_AGENT_REASONING_EFFORT", "").strip()
    NATIVE_AGENT_THINKING_DEPTH = _get_project_config("NATIVE_AGENT_THINKING_DEPTH", "").strip()
    CLI_MODEL_OPTIONS = _parse_cli_model_options(_get_project_config("CLI_MODEL_OPTIONS", ""))
    CLI_GLOBAL_EXTRA_ARGS = _parse_cli_global_extra_args(_get_project_config("CLI_GLOBAL_EXTRA_ARGS", "{}"))
    MODEL_PRICES_FILE = _get_project_config("MODEL_PRICES_FILE", "").strip()
    WORKING_DIR = os.path.abspath(os.path.expanduser(os.environ.get("WORKING_DIR", os.getcwd())))
    CLAUDE_DONE_DETECTOR_ENABLED = os.environ.get("CLAUDE_DONE_DETECTOR_ENABLED", "false").lower() == "true"
    CLAUDE_DONE_QUIET_SECONDS = float(os.environ.get("CLAUDE_DONE_QUIET_SECONDS", "2"))
    CLAUDE_DONE_SENTINEL_MODE = os.environ.get("CLAUDE_DONE_SENTINEL_MODE", "nonce").strip().lower()
    MANAGED_BOTS_FILE = os.environ.get("MANAGED_BOTS_FILE", "managed_bots.json")
    TCB_STORAGE_MIGRATION_WORKERS = min(4, max(1, _get_project_int("TCB_STORAGE_MIGRATION_WORKERS", 2)))

    WEB_ENABLED = os.environ.get("WEB_ENABLED", "false").lower() == "true"
    WEB_HOST = _get_project_config("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
    WEB_PORT = int(_get_project_config("WEB_PORT", "8765"))
    WEB_PUBLIC_URL = os.environ.get("WEB_PUBLIC_URL", "").strip()
    WEB_API_TOKEN = os.environ.get("WEB_API_TOKEN", "").strip()
    WEB_ALLOWED_ORIGINS = _split_csv_env(os.environ.get("WEB_ALLOWED_ORIGINS", ""))
    WEB_DEFAULT_USER_ID = ALLOWED_USER_IDS[0] if ALLOWED_USER_IDS else 1
    WEB_TERMINAL_SHELL_PATH = _get_project_config("WEB_TERMINAL_SHELL_PATH", "").strip()
    TCB_NODE_ID = _normalize_node_id(_get_project_config("TCB_NODE_ID", ""))
    WEB_BASE_PATH = _normalize_base_path(_get_project_config("WEB_BASE_PATH", ""), TCB_NODE_ID)
    EFFECTIVE_VITE_BASE_PATH = _effective_frontend_base_path("VITE_BASE_PATH", WEB_BASE_PATH)
    EFFECTIVE_VITE_API_BASE_URL = _effective_frontend_base_path("VITE_API_BASE_URL", WEB_BASE_PATH)
    WEB_FIXED_PUBLIC_FORWARD_ENABLED = _get_project_bool("WEB_FIXED_PUBLIC_FORWARD_ENABLED", False)
    WEB_FIXED_PUBLIC_FORWARD_URL = _get_project_config("WEB_FIXED_PUBLIC_FORWARD_URL", "").strip()
    TCB_HUB_FRPS_PORT = _get_project_optional_int("TCB_HUB_FRPS_PORT", 0)
    TCB_HUB_NODE_TOKEN = _get_project_config("TCB_HUB_NODE_TOKEN", "").strip()
    TCB_HUB_FRPS_TOKEN = _get_project_config("TCB_HUB_FRPS_TOKEN", "").strip()
    TCB_HUB_FRPC_PATH = _get_project_config("TCB_HUB_FRPC_PATH", "").strip()
    TCB_HUB_FRPC_AUTOSTART = _get_project_bool("TCB_HUB_FRPC_AUTOSTART", True)
    WEB_TUNNEL_MODE = os.environ.get("WEB_TUNNEL_MODE", "disabled").strip().lower() or "disabled"
    WEB_TUNNEL_AUTOSTART = os.environ.get("WEB_TUNNEL_AUTOSTART", "true").lower() == "true"
    WEB_TUNNEL_CLOUDFLARED_PATH = os.environ.get("WEB_TUNNEL_CLOUDFLARED_PATH", "").strip()
    WEB_TUNNEL_STATE_FILE = os.environ.get("WEB_TUNNEL_STATE_FILE", ".web_tunnel_state.json").strip() or ".web_tunnel_state.json"
    APP_UPDATE_REPOSITORY = _get_project_config("APP_UPDATE_REPOSITORY", DEFAULT_APP_UPDATE_REPOSITORY).strip()

    TCB_LSP_ENABLED = _get_project_bool("TCB_LSP_ENABLED", False)
    TCB_LSP_PYRIGHT_COMMAND = _get_project_config("TCB_LSP_PYRIGHT_COMMAND", "").strip()
    TCB_LSP_TYPESCRIPT_COMMAND = _get_project_config("TCB_LSP_TYPESCRIPT_COMMAND", "").strip()
    TCB_LSP_CLANGD_COMMAND = _get_project_config("TCB_LSP_CLANGD_COMMAND", "").strip()
    TCB_LSP_REQUEST_TIMEOUT_SECONDS = max(1.0, _get_project_float("TCB_LSP_REQUEST_TIMEOUT_SECONDS", 10.0))
    TCB_LSP_IDLE_TIMEOUT_SECONDS = max(30.0, _get_project_float("TCB_LSP_IDLE_TIMEOUT_SECONDS", 300.0))
    TCB_LSP_MAX_RUNTIMES = min(128, max(1, _get_project_int("TCB_LSP_MAX_RUNTIMES", 8)))
    TCB_LSP_EXTERNAL_SOURCES_ENABLED = _get_project_bool("TCB_LSP_EXTERNAL_SOURCES_ENABLED", False)

    CHAT_COMPLETION_NOTIFY_ENABLED = _get_project_bool("CHAT_COMPLETION_NOTIFY_ENABLED", True)
    PUSHPLUS_ENABLED = _get_project_bool("PUSHPLUS_ENABLED", False)
    PUSHPLUS_TOKEN = _get_project_config("PUSHPLUS_TOKEN", "").strip()
    PUSHPLUS_TOPIC = _get_project_config("PUSHPLUS_TOPIC", "").strip()
    PUSHPLUS_TEMPLATE = _get_project_config("PUSHPLUS_TEMPLATE", "markdown").strip() or "markdown"
    PUSHPLUS_CHANNEL = _get_project_config("PUSHPLUS_CHANNEL", "wechat").strip() or "wechat"
    PUSHPLUS_API_URL = _get_project_config("PUSHPLUS_API_URL", "https://www.pushplus.plus/send").strip() or "https://www.pushplus.plus/send"
    PUSHPLUS_TIMEOUT_SECONDS = _get_project_float("PUSHPLUS_TIMEOUT_SECONDS", 5.0)
    PUSHPLUS_PREVIEW_CHARS = _get_project_int("PUSHPLUS_PREVIEW_CHARS", 300)

    if CLI_TYPE not in SUPPORTED_CLI_TYPES:
        logging.warning("CLI_TYPE=%s 已不再受支持，自动回退为 codex", CLI_TYPE)
        CLI_TYPE = "codex"
        if not CLI_PATH:
            CLI_PATH = CLI_TYPE


_refresh_environment_config()


def _read_windows_registry_values(registry: Any, root: Any, subkey: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with registry.OpenKey(root, subkey) as key:
            value_count = registry.QueryInfoKey(key)[1]
            for index in range(value_count):
                name, value, _value_kind = registry.EnumValue(key, index)
                if not isinstance(name, str):
                    continue
                if isinstance(value, bytes):
                    value = value.decode(errors="replace")
                if isinstance(value, (str, int, float)):
                    values[name] = str(value)
    except FileNotFoundError:
        return {}
    return values


def _expand_windows_environment_values(values: dict[str, str]) -> dict[str, str]:
    by_key = {key.casefold(): value for key, value in os.environ.items()}
    by_key.update({key.casefold(): value for key, value in values.items()})
    expanded = dict(values)
    for _ in range(10):
        changed = False
        for key, value in expanded.items():
            next_value = _WINDOWS_ENV_REF_RE.sub(
                lambda match: by_key.get(match.group(1).casefold(), match.group(0)),
                value,
            )
            if next_value != value:
                expanded[key] = next_value
                by_key[key.casefold()] = next_value
                changed = True
        if not changed:
            break
    return expanded


def _read_windows_environment(registry: Any | None = None) -> dict[str, str] | None:
    registry = registry or _WINREG
    if registry is None:
        return None

    system_values = _read_windows_registry_values(
        registry,
        registry.HKEY_LOCAL_MACHINE,
        _WINDOWS_SYSTEM_ENV_SUBKEY,
    )
    user_values = _read_windows_registry_values(
        registry,
        registry.HKEY_CURRENT_USER,
        "Environment",
    )
    merged: dict[str, str] = {}
    merged_by_key: dict[str, str] = {}
    for name, value in system_values.items():
        merged[name] = value
        merged_by_key[name.casefold()] = name
    for name, value in user_values.items():
        normalized_name = name.casefold()
        previous_name = merged_by_key.get(normalized_name)
        if normalized_name == "path" and previous_name:
            system_path = merged[previous_name].strip()
            user_path = value.strip()
            value = os.pathsep.join(item for item in (system_path, user_path) if item)
        if previous_name and previous_name != name:
            merged.pop(previous_name, None)
        merged[name] = value
        merged_by_key[normalized_name] = name
    return _expand_windows_environment_values(merged)


def reload_project_env(env_path: str | os.PathLike[str] | None = None) -> dict[str, list[str]]:
    """Reload project dotenv values while preserving startup process overrides.

    A running process has its own environment block. Values inherited from the
    launcher are kept authoritative; values previously loaded from `.env` are
    refreshed so future child processes can see edits without a process restart.
    """
    global _DOTENV_VALUES
    if dotenv_values is None:
        return {"changed_keys": []}

    path = os.fspath(env_path) if env_path is not None else None
    parsed_values = {
        key: value
        for key, value in dotenv_values(path).items()
        if value is not None
    }
    previous_dotenv_values = dict(_DOTENV_VALUES)
    managed_keys = {
        key
        for key in (set(previous_dotenv_values) | set(parsed_values))
        if key.casefold() not in _INITIAL_PROCESS_ENV_KEYS
        and key.casefold() not in _RUNTIME_SYSTEM_ENV_NAMES
    }
    before_values = {key: os.environ.get(key) for key in managed_keys}
    try:
        for key in managed_keys:
            if key in parsed_values:
                os.environ[key] = str(parsed_values[key])
            else:
                os.environ.pop(key, None)
        _DOTENV_VALUES = parsed_values
        _refresh_environment_config()
    except Exception:
        for key, value in before_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _DOTENV_VALUES = previous_dotenv_values
        _refresh_environment_config()
        raise

    changed_keys = [
        key
        for key in managed_keys
        if before_values.get(key) != os.environ.get(key)
    ]
    return {"changed_keys": sorted(changed_keys)}


def reload_system_environment(env_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Reload Windows user/system environment values into this process."""
    global _RUNTIME_SYSTEM_ENV_NAMES
    registry_values = _read_windows_environment()
    if registry_values is None:
        return {"supported": False, "changed_keys": []}

    previous_names = dict(_RUNTIME_SYSTEM_ENV_NAMES)
    next_names = {key.casefold(): key for key in registry_values}
    all_keys = set(previous_names) | set(next_names)
    before_values = {
        key: os.environ.get(previous_names.get(key) or next_names.get(key) or key)
        for key in all_keys
    }
    try:
        _RUNTIME_SYSTEM_ENV_NAMES = next_names
        for name, value in registry_values.items():
            os.environ[name] = value
        for key, name in previous_names.items():
            if key in next_names:
                continue
            initial_name = _INITIAL_PROCESS_ENV_NAMES.get(key)
            if initial_name is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = _INITIAL_PROCESS_ENV[initial_name]
        project_result = reload_project_env(env_path)
    except Exception:
        for key in all_keys:
            name = previous_names.get(key) or next_names.get(key) or key
            previous_value = before_values.get(key)
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
        _RUNTIME_SYSTEM_ENV_NAMES = previous_names
        _refresh_environment_config()
        raise

    changed_keys = [
        next_names.get(key) or previous_names.get(key) or key
        for key in all_keys
        if before_values.get(key) != os.environ.get(next_names.get(key) or previous_names.get(key) or key)
    ]
    changed_keys.extend(project_result.get("changed_keys", []))
    return {
        "supported": True,
        "changed_keys": sorted(set(changed_keys)),
    }


def default_cli_path(cli_type: str) -> str:
    if cli_type == CLI_TYPE:
        return CLI_PATH
    if cli_type == "claude":
        return "claude"
    if cli_type == "antigravity":
        return "agy"
    if cli_type == "deepseek":
        return "dsh"
    return "codex"


DANGEROUS_COMMANDS: Set[str] = {
    "dd",
    "mkfs",
    "format",
    "del",
    "erase",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init",
    "systemctl",
    "service",
    "kill",
    "pkill",
    "killall",
}

MAIN_LOOP_RETRY_DELAY = 5

RESERVED_ALIASES = {"main"}


BOT_ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}$")

# ============ Logging 初始化 ============
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# ============ 全局可变状态 ============
RESTART_REQUESTED = False
RESTART_EVENT: Optional[asyncio.Event] = None
RESTART_EXIT_CODE = 75
RESTART_SUPERVISOR_ENV = "CLI_BRIDGE_SUPERVISOR"


# ============ 重启相关函数 ============
def build_reexec_args() -> tuple[str, list[str]]:
    """构建当前进程的重启命令，优先保留原始调用方式。"""
    python_exe = sys.executable
    orig_argv = getattr(sys, "orig_argv", None) or []
    if len(orig_argv) >= 2:
        return python_exe, [python_exe, *orig_argv[1:]]

    script = sys.argv[0] if sys.argv else "bot_advanced.py"
    if script and script != "-m":
        script = os.path.abspath(script)
    return python_exe, [python_exe, script, *sys.argv[1:]]


def is_supervised_restart() -> bool:
    """当前进程是否由外部启动器托管。"""
    return os.environ.get(RESTART_SUPERVISOR_ENV, "").strip() == "1"


def reexec_current_process() -> None:
    """用当前解释器和参数重启整个进程（可重新加载代码）。"""
    python_exe, args = build_reexec_args()

    logger.warning("正在执行进程级重启: %s", args)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os.execv(python_exe, args)


def request_restart():
    """请求主循环重启"""
    global RESTART_REQUESTED
    RESTART_REQUESTED = True
    if RESTART_EVENT is not None:
        RESTART_EVENT.set()
    logger.info("重启请求已发出")
