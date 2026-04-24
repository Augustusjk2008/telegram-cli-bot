"""全局配置、常量、日志初始化"""

import asyncio
import logging
import os
import re
import sys
from typing import List, Optional, Set

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


def _get_project_config(name: str, default: str = "") -> str:
    """读取项目配置，优先使用当前进程显式环境变量，其次回退到仓库 .env。"""
    env_value = os.environ.get(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value)
    dotenv_value = _DOTENV_VALUES.get(name)
    if dotenv_value is not None and str(dotenv_value).strip():
        return str(dotenv_value)
    return default


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
CLI_MODEL_OPTIONS = _split_csv_env(_get_project_config("CLI_MODEL_OPTIONS", ""))
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
WEB_TUNNEL_MODE = os.environ.get("WEB_TUNNEL_MODE", "disabled").strip().lower() or "disabled"
WEB_TUNNEL_AUTOSTART = os.environ.get("WEB_TUNNEL_AUTOSTART", "true").lower() == "true"
# 可选：指定 cloudflared 的完整路径；若已在 PATH 中可留空。
WEB_TUNNEL_CLOUDFLARED_PATH = os.environ.get("WEB_TUNNEL_CLOUDFLARED_PATH", "").strip()
WEB_TUNNEL_STATE_FILE = os.environ.get("WEB_TUNNEL_STATE_FILE", ".web_tunnel_state.json").strip() or ".web_tunnel_state.json"
APP_UPDATE_REPOSITORY = _get_project_config(
    "APP_UPDATE_REPOSITORY",
    DEFAULT_APP_UPDATE_REPOSITORY,
).strip()

# ============ 常量定义 ============
SUPPORTED_CLI_TYPES = {"claude", "codex"}
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
