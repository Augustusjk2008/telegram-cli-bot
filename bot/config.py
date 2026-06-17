"""全局配置、常量、日志初始化"""

import asyncio
import json
import logging
import os
import re
import sys
from typing import Any, List, Optional, Set

from bot.cli_params import normalize_cli_model_options
from bot.native_agent.legacy_migration import resolve_pi_agent_env

# 加载 .env 文件中的环境变量
try:
    from dotenv import dotenv_values, load_dotenv
    _DOTENV_VALUES = {
        key: value
        for key, value in dotenv_values().items()
        if value is not None
    }
    load_dotenv()
except ImportError:
    _DOTENV_VALUES = {}
    pass  # python-dotenv 未安装时跳过

# ============ 环境变量读取 ============
def _split_csv_env(raw_value: str) -> List[str]:
    return [item.strip() for item in (raw_value or "").split(",") if item.strip()]


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
        if cli_type not in {"codex", "claude", "kimi"}:
            logging.warning("忽略无效的 CLI_GLOBAL_EXTRA_ARGS.%s：不支持的 CLI 类型", key)
            return {}
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
        return float(raw_value)
    except ValueError:
        logging.warning("忽略无效的浮点配置 %s=%s，使用默认值 %s", name, raw_value, default)
        return default


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

ALLOWED_USER_IDS: List[int] = []
_allowed_raw = os.environ.get("ALLOWED_USER_IDS", "")
for uid in _allowed_raw.split(","):
    uid = uid.strip()
    if uid:
        try:
            ALLOWED_USER_IDS.append(int(uid))
        except ValueError:
            logging.warning(f"忽略无效的用户ID: {uid}")

CLI_TYPE = _get_project_config("CLI_TYPE", "codex").strip().lower()
CLI_PATH = _get_project_config("CLI_PATH", "codex")
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
NATIVE_AGENT_REASONING_EFFORT = _get_project_config("NATIVE_AGENT_REASONING_EFFORT", "").strip()
NATIVE_AGENT_THINKING_DEPTH = _get_project_config("NATIVE_AGENT_THINKING_DEPTH", "").strip()
CLI_MODEL_OPTIONS = normalize_cli_model_options(_split_csv_env(_get_project_config("CLI_MODEL_OPTIONS", "")))
CLI_GLOBAL_EXTRA_ARGS = _parse_cli_global_extra_args(_get_project_config("CLI_GLOBAL_EXTRA_ARGS", "{}"))
WORKING_DIR = os.path.abspath(os.path.expanduser(os.environ.get("WORKING_DIR", os.getcwd())))
CLAUDE_DONE_DETECTOR_ENABLED = os.environ.get("CLAUDE_DONE_DETECTOR_ENABLED", "false").lower() == "true"
CLAUDE_DONE_QUIET_SECONDS = float(os.environ.get("CLAUDE_DONE_QUIET_SECONDS", "2"))
CLAUDE_DONE_SENTINEL_MODE = os.environ.get("CLAUDE_DONE_SENTINEL_MODE", "nonce").strip().lower()
MANAGED_BOTS_FILE = os.environ.get("MANAGED_BOTS_FILE", "managed_bots.json")

# Claude API 配置（用于助手模式）
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Web / legacy tunnel 配置
NGROK_DIR = ""
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").strip()  # 代理商 API 地址
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
# 可选：指定 cloudflared 的完整路径；若已在 PATH 中可留空。
WEB_TUNNEL_CLOUDFLARED_PATH = os.environ.get("WEB_TUNNEL_CLOUDFLARED_PATH", "").strip()
WEB_TUNNEL_STATE_FILE = os.environ.get("WEB_TUNNEL_STATE_FILE", ".web_tunnel_state.json").strip() or ".web_tunnel_state.json"
APP_UPDATE_REPOSITORY = _get_project_config(
    "APP_UPDATE_REPOSITORY",
    DEFAULT_APP_UPDATE_REPOSITORY,
).strip()

# Chat completion notifications.
CHAT_COMPLETION_NOTIFY_ENABLED = _get_project_bool("CHAT_COMPLETION_NOTIFY_ENABLED", True)
PUSHPLUS_ENABLED = _get_project_bool("PUSHPLUS_ENABLED", False)
PUSHPLUS_TOKEN = _get_project_config("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOPIC = _get_project_config("PUSHPLUS_TOPIC", "").strip()
PUSHPLUS_TEMPLATE = _get_project_config("PUSHPLUS_TEMPLATE", "markdown").strip() or "markdown"
PUSHPLUS_CHANNEL = _get_project_config("PUSHPLUS_CHANNEL", "wechat").strip() or "wechat"
PUSHPLUS_API_URL = _get_project_config("PUSHPLUS_API_URL", "https://www.pushplus.plus/send").strip() or "https://www.pushplus.plus/send"
PUSHPLUS_TIMEOUT_SECONDS = _get_project_float("PUSHPLUS_TIMEOUT_SECONDS", 5.0)
PUSHPLUS_PREVIEW_CHARS = _get_project_int("PUSHPLUS_PREVIEW_CHARS", 300)

# ============ 常量定义 ============
SUPPORTED_CLI_TYPES = {"claude", "codex", "kimi"}
if CLI_TYPE not in SUPPORTED_CLI_TYPES:
    logging.warning("CLI_TYPE=%s 已不再受支持，自动回退为 codex", CLI_TYPE)
    CLI_TYPE = "codex"
    if not CLI_PATH:
        CLI_PATH = CLI_TYPE

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

POLLING_BOOTSTRAP_RETRIES = -1  # -1 表示无限重试

# 网络错误重试配置
NETWORK_ERROR_MAX_RETRIES = 10  # 最大重试次数（指数退避）
NETWORK_ERROR_BASE_DELAY = 1.0  # 基础延迟（秒）
NETWORK_ERROR_MAX_DELAY = 60.0  # 最大延迟（秒）

# 网络错误日志抑制配置（适用于网络不稳定环境）
# 在指定时间窗口内，相同类型的网络错误只记录一次 WARNING，其余用 DEBUG
NETWORK_ERROR_LOG_SUPPRESS_WINDOW = int(os.environ.get("NETWORK_ERROR_LOG_SUPPRESS_WINDOW", "60"))  # 秒，设为0禁用抑制

# CLI 超时检测间隔（秒）
CLI_TIMEOUT_CHECK_INTERVAL = 10

# 进度更新间隔（秒）- 每N秒更新一次等待提示并发送已输出的内容
CLI_PROGRESS_UPDATE_INTERVAL = int(os.environ.get("CLI_PROGRESS_UPDATE_INTERVAL", "3"))
POLLING_TIMEOUT = 30
POLLING_WATCHDOG_INTERVAL = 5
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
