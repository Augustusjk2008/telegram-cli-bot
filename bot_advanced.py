#!/usr/bin/env python3
"""
高级版 Telegram Bot Bridge for Kimi Code CLI / Claude Code CLI

新增能力：
- 主 Bot 动态管理多个子 Bot token
- 子 Bot 独立运行、独立会话、独立 CLI 配置
- 子 Bot token 通过主 Bot 管理命令添加（持久化到本地文件）
"""

import asyncio
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ============ 配置 ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "your_bot_token_here")

ALLOWED_USER_IDS: List[int] = []
_allowed_raw = os.environ.get("ALLOWED_USER_IDS", "")
for uid in _allowed_raw.split(","):
    uid = uid.strip()
    if uid:
        try:
            ALLOWED_USER_IDS.append(int(uid))
        except ValueError:
            logging.warning(f"忽略无效的用户ID: {uid}")

CLI_TYPE = os.environ.get("CLI_TYPE", "kimi").strip().lower()
CLI_PATH = os.environ.get("CLI_PATH", "kimi")
WORKING_DIR = os.path.abspath(os.path.expanduser(os.environ.get("WORKING_DIR", os.getcwd())))
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "3600"))
MANAGED_BOTS_FILE = os.environ.get("MANAGED_BOTS_FILE", "managed_bots.json")
SUPPORTED_CLI_TYPES = {"kimi", "claude", "codex"}

POLLING_BOOTSTRAP_RETRIES = 10
POLLING_TIMEOUT = 30
POLLING_WATCHDOG_INTERVAL = 5
MAIN_LOOP_RETRY_DELAY = 5

RESERVED_ALIASES = {"main"}
BOT_ALIAS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}$")

DANGEROUS_COMMANDS: Set[str] = {
    "rm",
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

RESTART_REQUESTED = False
RESTART_EVENT: Optional[asyncio.Event] = None


def reexec_current_process() -> None:
    """用当前解释器和参数重启整个进程（可重新加载代码）。"""
    python_exe = sys.executable
    script = sys.argv[0] if sys.argv else "bot_advanced.py"
    if script and script != "-m":
        script = os.path.abspath(script)
    args = [python_exe, script, *sys.argv[1:]]

    logger.warning("正在执行进程级重启: %s", args)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os.execv(python_exe, args)


@dataclass
class BotProfile:
    alias: str
    token: str
    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    working_dir: str = WORKING_DIR
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "token": self.token,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
        }


@dataclass
class UserSession:
    """按 (bot_id, user_id) 隔离的用户会话状态"""

    bot_id: int
    bot_alias: str
    user_id: int
    working_dir: str
    history: List[dict] = field(default_factory=list)
    codex_session_id: Optional[str] = None
    kimi_session_id: Optional[str] = None
    claude_session_id: Optional[str] = None
    claude_session_initialized: bool = False
    process: Optional[subprocess.Popen] = None
    is_processing: bool = False
    last_activity: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def touch(self):
        self.last_activity = datetime.now()
        self.message_count += 1

    def is_expired(self) -> bool:
        elapsed = (datetime.now() - self.last_activity).total_seconds()
        return elapsed > SESSION_TIMEOUT

    def add_to_history(self, role: str, content: str):
        with self._lock:
            self.history.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "role": role,
                    "content": content,
                }
            )
            if len(self.history) > 100:
                self.history = self.history[-100:]

    def terminate_process(self):
        with self._lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                self.process = None
            self.is_processing = False


# ============ 全局会话管理 ============
sessions: Dict[Tuple[int, int], UserSession] = {}
sessions_lock = threading.Lock()


def get_session(bot_id: int, bot_alias: str, user_id: int, default_working_dir: str) -> UserSession:
    key = (bot_id, user_id)
    with sessions_lock:
        if key in sessions and sessions[key].is_expired():
            sessions[key].terminate_process()
            del sessions[key]

        if key not in sessions:
            sessions[key] = UserSession(
                bot_id=bot_id,
                bot_alias=bot_alias,
                user_id=user_id,
                working_dir=default_working_dir,
            )
        return sessions[key]


def reset_session(bot_id: int, user_id: int) -> bool:
    key = (bot_id, user_id)
    with sessions_lock:
        if key in sessions:
            sessions[key].terminate_process()
            del sessions[key]
            return True
    return False


def clear_bot_sessions(bot_id: int):
    with sessions_lock:
        keys = [k for k in sessions if k[0] == bot_id]
        for key in keys:
            sessions[key].terminate_process()
            del sessions[key]


def is_bot_processing(bot_id: int) -> bool:
    """检查指定 bot 是否有正在处理消息的会话"""
    with sessions_lock:
        for key, session in sessions.items():
            if key[0] == bot_id and session.is_processing:
                return True
    return False


# ============ 通用工具 ============
def check_auth(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def is_dangerous_command(command: str) -> bool:
    command_lower = command.lower().strip()
    first_word = command_lower.split()[0] if command_lower else ""

    if first_word in DANGEROUS_COMMANDS:
        return True

    dangerous_patterns = [";rm ", "|rm ", "`rm ", "$(rm ", "&rm ", "&&rm "]
    return any(pattern in command_lower for pattern in dangerous_patterns)


def truncate_for_markdown(text: str, max_len: int = 3900) -> str:
    """截断文本（用于非流式输出的场景）"""
    if len(text) <= max_len:
        return text

    truncated = text[: max_len - 20]

    if truncated.count("```") % 2 != 0:
        last_block = truncated.rfind("\n```")
        if last_block > max_len * 0.5:
            truncated = truncated[:last_block]

    while truncated.endswith("`") and not truncated.endswith("```"):
        truncated = truncated[:-1]

    if truncated.count("```") % 2 != 0:
        truncated += "\n```"

    return truncated + "\n\n... (已截断)"


def split_text_into_chunks(text: str, max_len: int = 3800) -> List[str]:
    """
    将长文本分割成多个块，尽量在代码块边界处分割。
    每个块都会正确处理代码块标记。
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split('\n')
    current_chunk_lines = []
    current_len = 0
    in_code_block = False

    def close_code_block(lines_list: List[str]) -> None:
        """如果当前在代码块内，添加关闭标记"""
        if in_code_block and (not lines_list or not lines_list[-1].rstrip().endswith('```')):
            lines_list.append('```')

    def reopen_code_block(lines_list: List[str]) -> None:
        """为新块添加代码块开启标记"""
        if in_code_block:
            lines_list.insert(0, '```')

    for line in lines:
        line_len = len(line) + 1  # +1 for newline

        # 检查是否需要分割
        if current_len + line_len > max_len and current_chunk_lines:
            # 关闭当前代码块（如果在代码块内）
            close_code_block(current_chunk_lines)
            chunks.append('\n'.join(current_chunk_lines))

            # 开始新块
            current_chunk_lines = []
            current_len = 0

            # 如果在代码块内，新块需要重新开启代码块
            reopen_code_block(current_chunk_lines)

        current_chunk_lines.append(line)
        current_len += line_len

        # 检测代码块边界
        stripped = line.strip()
        if stripped.startswith('```') and not stripped[3:].strip():
            in_code_block = not in_code_block

    # 处理最后一个块
    if current_chunk_lines:
        chunks.append('\n'.join(current_chunk_lines))

    return chunks


async def safe_edit_text(message, text: str, parse_mode: Optional[str] = None):
    """安全编辑消息：Markdown 失败时自动降级为纯文本"""
    try:
        if parse_mode:
            await message.edit_text(text, parse_mode=parse_mode)
        else:
            await message.edit_text(text)
        return
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        if parse_mode and (
            "can't parse entities" in err
            or "parse entities" in err
            or "markdown" in err
            or "entity" in err
        ):
            try:
                await message.edit_text(text)
            except Exception:
                pass
            return
        raise


def is_safe_filename(filename: str) -> bool:
    forbidden = ["\\", "..", "\x00", ":", "*", "?", '"', "<", ">", "|"]
    for char in forbidden:
        if char in filename:
            return False
    return filename.strip() not in ("", ".")


def resolve_cli_executable(cli_path: str, working_dir: Optional[str] = None) -> Optional[str]:
    """解析 CLI 可执行文件路径，兼容 Windows 下 cmd/bat 可执行项。"""
    path = (cli_path or "").strip().strip('"').strip("'")
    if not path:
        return None

    def _existing_file(p: str) -> Optional[str]:
        if os.path.isfile(p):
            return os.path.abspath(p)
        return None

    # 1) 绝对路径或显式相对路径
    if os.path.isabs(path):
        found = _existing_file(path)
        if found:
            return found
    if any(sep in path for sep in ("/", "\\")):
        candidates = []
        if working_dir:
            candidates.append(os.path.join(working_dir, path))
        candidates.append(path)
        for c in candidates:
            found = _existing_file(os.path.abspath(os.path.expanduser(c)))
            if found:
                return found

    # 2) PATH 搜索
    found = shutil.which(path)
    if found:
        return found

    # 3) Windows: 自动补扩展名
    if os.name == "nt" and not os.path.splitext(path)[1]:
        for ext in (".cmd", ".bat", ".exe", ".com"):
            found = shutil.which(path + ext)
            if found:
                return found

    # 4) Windows: npm 全局目录兜底（PATH 未包含时）
    if os.name == "nt" and not any(sep in path for sep in ("/", "\\")):
        appdata = os.getenv("APPDATA")
        userprofile = os.getenv("USERPROFILE")
        npm_dirs: List[str] = []
        if appdata:
            npm_dirs.append(os.path.join(appdata, "npm"))
        if userprofile:
            npm_dirs.append(os.path.join(userprofile, "AppData", "Roaming", "npm"))
        # 去重并保持顺序
        seen = set()
        npm_dirs = [d for d in npm_dirs if not (d in seen or seen.add(d))]

        if os.path.splitext(path)[1]:
            names = [path]
        else:
            names = [path + ext for ext in (".cmd", ".bat", ".exe", ".com", ".ps1")]

        for npm_dir in npm_dirs:
            for name in names:
                found = _existing_file(os.path.join(npm_dir, name))
                if found:
                    return found

    return None


def normalize_cli_type(cli_type: str) -> str:
    return (cli_type or "").strip().lower()


def validate_cli_type(cli_type: str) -> str:
    normalized = normalize_cli_type(cli_type)
    if normalized not in SUPPORTED_CLI_TYPES:
        supported = ", ".join(sorted(SUPPORTED_CLI_TYPES))
        raise ValueError(f"不支持的 cli_type: {cli_type} (支持: {supported})")
    return normalized


def build_cli_command(
    cli_type: str,
    resolved_cli: str,
    user_text: str,
    env: Dict[str, str],
    session_id: Optional[str] = None,
    resume_session: bool = False,
    json_output: bool = False,
) -> Tuple[List[str], bool]:
    """构建不同 CLI 的命令行。所有支持的 CLI 均强制 yolo 模式。"""
    kind = validate_cli_type(cli_type)

    # 检测 CLI 原生子命令（以 / 开头且为单个词）
    is_cli_subcommand = user_text.startswith("/") and len(user_text.split()) == 1

    if kind == "kimi":
        # 处理 Kimi 原生子命令，如 //version 等
        # Kimi 不支持 /command 格式，而是直接将子命令作为参数，如 kimi version
        if is_cli_subcommand:
            subcmd = user_text[1:]  # 去掉开头的 /
            # 处理 help/usage 请求，映射到 --help
            if subcmd in ("help", "usage"):
                return [resolved_cli, "--help"], False
            return [resolved_cli, subcmd], False
        # 使用 Kimi 原生 session 机制续聊，不做本地历史拼接。
        cmd = [resolved_cli, "--quiet", "-y", "--thinking"]
        if session_id:
            cmd.extend(["-S", session_id])
        cmd.extend(["-p", user_text])
        return cmd, False

    if kind == "claude":
        # 使用 Claude 原生 session 机制续聊，不做本地历史拼接。
        env["CLAUDE_CODE_DISABLE_PROMPTS"] = "1"
        cmd = [
            resolved_cli,
            "-p",
            "--dangerously-skip-permissions",
            "--effort",
            "high",
        ]
        if session_id:
            if resume_session:
                cmd.extend(["-r", session_id])
            else:
                cmd.extend(["--session-id", session_id])
        cmd.append(user_text)
        return cmd, False

    # Codex yolo: --dangerously-bypass-approvals-and-sandbox; 最大思考：xhigh
    # 注意：这些参数只适用于 'codex exec' 子命令
    codex_exec_options = [
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-c",
        'model_reasoning_effort="xhigh"',
    ]
    if json_output:
        codex_exec_options.append("--json")

    # 处理 Codex 原生子命令，如 //status, //logs 等
    # Codex 子命令在非终端环境可能失败，添加 CI 环境变量抑制 TTY 检查
    if is_cli_subcommand:
        subcmd = user_text[1:]  # 去掉开头的 /
        # 处理 help/usage 请求
        if subcmd in ("help", "usage"):
            return [resolved_cli, "--help"], False
        return [resolved_cli, subcmd], False

    if session_id:
        return [
            resolved_cli,
            "exec",
            "resume",
            *codex_exec_options,
            session_id,
            user_text,
        ], False

    return [
        resolved_cli,
        "exec",
        *codex_exec_options,
        user_text,
    ], False

# ============ 多Bot管理 ============
class MultiBotManager:
    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.main_profile = main_profile
        self.storage_file = Path(storage_file)
        self.managed_profiles: Dict[str, BotProfile] = {}
        self.applications: Dict[str, Application] = {}
        self.bot_id_to_alias: Dict[int, str] = {}
        self._polling_restart_locks: Dict[str, asyncio.Lock] = {}
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        self._load_profiles()

    def _make_polling_error_callback(self, alias: str):
        def _on_polling_error(error: Exception) -> None:
            logger.warning("轮询异常 alias=%s: %s", alias, error)

        return _on_polling_error

    async def _start_updater_polling(self, app: Application, alias: str):
        if app.updater is None:
            raise RuntimeError("Application.updater 不可用，无法启动轮询")
        await app.updater.start_polling(
            poll_interval=0.0,
            timeout=POLLING_TIMEOUT,
            bootstrap_retries=POLLING_BOOTSTRAP_RETRIES,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            error_callback=self._make_polling_error_callback(alias),
        )

    async def _restart_polling_if_needed(self, alias: str, app: Application):
        if alias not in self.applications:
            return
        if bool(app.bot_data.get("stopping", False)):
            return
        if app.updater is None or not app.running:
            return
        if app.updater.running:
            return

        lock = self._polling_restart_locks.setdefault(alias, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            current = self.applications.get(alias)
            if current is not app:
                return
            if bool(app.bot_data.get("stopping", False)):
                return
            if app.updater is None or not app.running or app.updater.running:
                return

            try:
                logger.warning("检测到轮询已停止，正在自动重启 alias=%s", alias)
                await self._start_updater_polling(app, alias)
                logger.info("轮询自动恢复成功 alias=%s", alias)
            except Exception as e:
                logger.error("轮询自动恢复失败 alias=%s: %s", alias, e)

    async def _watchdog_loop(self):
        stop_event = self._watchdog_stop_event
        if stop_event is None:
            return

        while not stop_event.is_set():
            await asyncio.sleep(POLLING_WATCHDOG_INTERVAL)
            apps_snapshot = list(self.applications.items())
            for alias, app in apps_snapshot:
                try:
                    await self._restart_polling_if_needed(alias, app)
                except Exception as e:
                    logger.debug("watchdog 检查异常 alias=%s: %s", alias, e)

    async def start_watchdog(self):
        if self._watchdog_task and not self._watchdog_task.done():
            return
        self._watchdog_stop_event = asyncio.Event()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop_watchdog(self):
        task = self._watchdog_task
        event = self._watchdog_stop_event
        self._watchdog_task = None
        self._watchdog_stop_event = None
        if event:
            event.set()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _load_profiles(self):
        self.managed_profiles = {}
        if not self.storage_file.exists():
            return

        try:
            raw = self.storage_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as e:
            logger.error(f"读取托管Bot配置失败: {e}")
            return

        items = data.get("bots", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            logger.warning("托管Bot配置格式无效，已忽略")
            return

        for item in items:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip().lower()
            token = str(item.get("token", "")).strip()
            if not alias or not token or alias in RESERVED_ALIASES:
                continue
            raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
            try:
                cli_type = validate_cli_type(raw_cli_type)
            except ValueError:
                logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
                cli_type = CLI_TYPE
            self.managed_profiles[alias] = BotProfile(
                alias=alias,
                token=token,
                cli_type=cli_type,
                cli_path=str(item.get("cli_path", CLI_PATH)).strip() or CLI_PATH,
                working_dir=os.path.abspath(
                    os.path.expanduser(str(item.get("working_dir", WORKING_DIR)).strip() or WORKING_DIR)
                ),
                enabled=bool(item.get("enabled", True)),
            )

    def _save_profiles(self):
        payload = {
            "bots": [
                self.managed_profiles[k].to_dict()
                for k in sorted(self.managed_profiles.keys())
            ]
        }
        self.storage_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_profile(self, alias: str) -> BotProfile:
        if alias == self.main_profile.alias:
            return self.main_profile
        return self.managed_profiles.get(alias, self.main_profile)

    def _validate_alias(self, alias: str):
        if not BOT_ALIAS_RE.fullmatch(alias):
            raise ValueError("alias 仅允许字母/数字/_/-，长度 2-32")
        if alias in RESERVED_ALIASES:
            raise ValueError(f"alias `{alias}` 为保留名称")

    async def _send_startup_greeting(self, app: Application, profile: BotProfile):
        """向所有授权用户发送启动问候消息"""
        if not ALLOWED_USER_IDS:
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        greeting = (
            f"🤖 *Bot 已上线！*\n\n"
            f"⏰ 当前时间: `{now}`\n"
            f"🔧 Coding CLI: `{profile.cli_type}` (`{profile.cli_path}`)\n"
            f"📁 工作目录: `{profile.working_dir}`\n\n"
            f"发送 /start 查看帮助"
        )

        for user_id in ALLOWED_USER_IDS:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=greeting,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"向用户 {user_id} 发送问候消息失败: {e}")

    async def _start_profile(self, profile: BotProfile, is_main: bool = False) -> Application:
        if profile.alias in self.applications:
            return self.applications[profile.alias]

        app = Application.builder().token(profile.token).build()
        app.bot_data["manager"] = self
        app.bot_data["bot_alias"] = profile.alias
        app.bot_data["is_main"] = is_main

        register_handlers(app, include_admin=is_main)

        initialized = False
        started = False
        updater_started = False
        try:
            await app.initialize()
            initialized = True
            me = await app.bot.get_me()
            app.bot_data["bot_id"] = me.id
            app.bot_data["bot_username"] = me.username or ""
            app.bot_data["stopping"] = False

            await app.start()
            started = True

            await self._start_updater_polling(app, profile.alias)
            updater_started = True

            self.applications[profile.alias] = app
            self.bot_id_to_alias[int(me.id)] = profile.alias
            logger.info(
                "Bot已启动 alias=%s username=@%s",
                profile.alias,
                app.bot_data.get("bot_username") or "unknown",
            )

            # 发送启动问候消息（使用 shield 保护，防止被取消）
            asyncio.shield(asyncio.create_task(self._send_startup_greeting(app, profile)))

            return app
        except Exception:
            if updater_started and app.updater:
                try:
                    await app.updater.stop()
                except Exception:
                    pass
            if started:
                try:
                    await app.stop()
                except Exception:
                    pass
            if initialized:
                try:
                    await app.shutdown()
                except Exception:
                    pass
            raise

    async def _stop_application(self, alias: str):
        app = self.applications.get(alias)
        if not app:
            return

        app.bot_data["stopping"] = True
        bot_id = app.bot_data.get("bot_id")
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
        except Exception as e:
            logger.warning(f"停止 updater 失败 alias={alias}: {e}")

        try:
            if app.running:
                await app.stop()
        except Exception as e:
            logger.warning(f"停止 app 失败 alias={alias}: {e}")

        try:
            await app.shutdown()
        except Exception as e:
            logger.warning(f"关闭 app 失败 alias={alias}: {e}")

        self.applications.pop(alias, None)
        self._polling_restart_locks.pop(alias, None)
        if isinstance(bot_id, int):
            self.bot_id_to_alias.pop(bot_id, None)
            clear_bot_sessions(bot_id)

        logger.info("Bot已停止 alias=%s", alias)

    async def start_all(self):
        await self._start_profile(self.main_profile, is_main=True)
        for alias, profile in list(self.managed_profiles.items()):
            if not profile.enabled:
                continue
            try:
                await self._start_profile(profile, is_main=False)
            except Exception as e:
                logger.error(f"启动子Bot失败 alias={alias}: {e}")

    async def shutdown_all(self):
        await self.stop_watchdog()
        aliases = list(self.applications.keys())
        for alias in aliases:
            if alias != self.main_profile.alias:
                await self._stop_application(alias)
        if self.main_profile.alias in self.applications:
            await self._stop_application(self.main_profile.alias)

    async def add_bot(
        self,
        alias: str,
        token: str,
        cli_type: Optional[str] = None,
        cli_path: Optional[str] = None,
        working_dir: Optional[str] = None,
    ) -> BotProfile:
        alias = alias.strip().lower()
        token = token.strip()
        self._validate_alias(alias)

        if not token:
            raise ValueError("token 不能为空")

        cli_type = validate_cli_type(cli_type or CLI_TYPE)
        cli_path = (cli_path or CLI_PATH).strip()
        working_dir = os.path.abspath(os.path.expanduser((working_dir or WORKING_DIR).strip()))

        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        if resolve_cli_executable(cli_path, working_dir) is None:
            raise ValueError(
                f"未找到CLI可执行文件: {cli_path} "
                f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
            )

        async with self._lock:
            if alias in self.managed_profiles:
                raise ValueError(f"alias `{alias}` 已存在")
            if token == self.main_profile.token or any(p.token == token for p in self.managed_profiles.values()):
                raise ValueError("该 token 已被使用")

            profile = BotProfile(
                alias=alias,
                token=token,
                cli_type=cli_type,
                cli_path=cli_path,
                working_dir=working_dir,
                enabled=True,
            )

            await self._start_profile(profile, is_main=False)
            self.managed_profiles[alias] = profile
            self._save_profiles()
            return profile

    async def remove_bot(self, alias: str):
        alias = alias.strip().lower()
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            await self._stop_application(alias)
            del self.managed_profiles[alias]
            self._save_profiles()

    async def start_bot(self, alias: str):
        alias = alias.strip().lower()
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.enabled = True
            self._save_profiles()
            await self._start_profile(profile, is_main=False)

    async def stop_bot(self, alias: str):
        alias = alias.strip().lower()
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.enabled = False
            self._save_profiles()
            await self._stop_application(alias)

    async def set_bot_cli(self, alias: str, cli_type: str, cli_path: str):
        alias = alias.strip().lower()
        cli_type = validate_cli_type(cli_type)
        cli_path = cli_path.strip()
        if not cli_path:
            raise ValueError("cli_path 不能为空")

        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            if resolve_cli_executable(cli_path, profile.working_dir) is None:
                raise ValueError(
                    f"未找到CLI可执行文件: {cli_path} "
                    f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )
            profile.cli_type = cli_type
            profile.cli_path = cli_path
            self._save_profiles()

    async def set_bot_workdir(self, alias: str, working_dir: str):
        alias = alias.strip().lower()
        working_dir = os.path.abspath(os.path.expanduser(working_dir.strip()))
        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.working_dir = working_dir
            self._save_profiles()

    def get_status_lines(self) -> List[str]:
        lines: List[str] = []

        main_app = self.applications.get(self.main_profile.alias)
        if main_app:
            main_bot_id = main_app.bot_data.get("bot_id")
            main_working = is_bot_processing(main_bot_id) if isinstance(main_bot_id, int) else False
            main_running = "working" if main_working else "running"
        else:
            main_running = "stopped"
        main_username = (main_app.bot_data.get("bot_username") if main_app else "") or "unknown"
        lines.append(
            f"[main] @{main_username} | {main_running} | cli={self.main_profile.cli_type}:{self.main_profile.cli_path}"
        )

        for alias in sorted(self.managed_profiles.keys()):
            profile = self.managed_profiles[alias]
            app = self.applications.get(alias)
            if app:
                bot_id = app.bot_data.get("bot_id")
                is_working = is_bot_processing(bot_id) if isinstance(bot_id, int) else False
                running = "working" if is_working else "running"
            else:
                running = "stopped"
            username = (app.bot_data.get("bot_username") if app else "") or "unknown"
            enabled = "enabled" if profile.enabled else "disabled"
            lines.append(
                f"[{alias}] @{username} | {running}/{enabled} | cli={profile.cli_type}:{profile.cli_path}"
            )

        return lines


# ============ 上下文辅助 ============
def get_manager(context: ContextTypes.DEFAULT_TYPE) -> MultiBotManager:
    return context.application.bot_data["manager"]


def get_bot_alias(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str(context.application.bot_data.get("bot_alias", "main"))


def is_main_application(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.application.bot_data.get("is_main", False))


def get_bot_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bot_id = context.application.bot_data.get("bot_id")
    if isinstance(bot_id, int):
        return bot_id
    if update.effective_chat:
        return int(update.effective_chat.id)
    return 0


def get_current_profile(context: ContextTypes.DEFAULT_TYPE) -> BotProfile:
    manager = get_manager(context)
    return manager.get_profile(get_bot_alias(context))


def get_current_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> UserSession:
    profile = get_current_profile(context)
    return get_session(
        bot_id=get_bot_id(update, context),
        bot_alias=get_bot_alias(context),
        user_id=update.effective_user.id,
        default_working_dir=profile.working_dir,
    )


async def ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_main_application(context):
        await update.message.reply_text("⛔ 该命令仅主Bot可用")
        return False

    user_id = update.effective_user.id
    if not check_auth(user_id):
        await update.message.reply_text("⛔ 未授权的用户")
        return False

    return True


def request_restart() -> None:
    global RESTART_REQUESTED
    RESTART_REQUESTED = True
    if RESTART_EVENT and not RESTART_EVENT.is_set():
        RESTART_EVENT.set()

# ============ 命令处理器 ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        await update.message.reply_text("⛔ 未授权的用户")
        return

    profile = get_current_profile(context)
    session = get_current_session(update, context)
    alias = get_bot_alias(context)

    admin_block = ""
    if is_main_application(context):
        admin_block = (
            "\n\n🛠 主Bot管理命令:\n"
            "   /bot_help - 显示多Bot管理帮助\n"
            "   /bot_list - 列出所有Bot状态\n"
            "   /restart - 重启整个程序（重载代码）\n"
            "   /bot_add <alias> <token> [cli_type] [cli_path] [workdir]\n"
            "   /bot_remove <alias>\n"
            "   /bot_start <alias> / /bot_stop <alias>\n"
            "   /bot_set_cli <alias> <cli_type> <cli_path>\n"
            "   /bot_set_workdir <alias> <workdir>"
        )

    native_session_block = ""
    current_cli = normalize_cli_type(profile.cli_type)
    if current_cli == "codex":
        session_id = session.codex_session_id or "(未创建，收到首条消息后自动生成)"
        native_session_block = f"   Codex会话ID: {session_id}\n"
    elif current_cli == "kimi":
        session_id = session.kimi_session_id or "(未创建，收到首条消息后自动生成)"
        native_session_block = f"   Kimi会话ID: {session_id}\n"
    elif current_cli == "claude":
        session_id = session.claude_session_id or "(未创建，收到首条消息后自动生成)"
        status = "已初始化" if session.claude_session_initialized else "待初始化"
        native_session_block = f"   Claude会话ID: {session_id} ({status})\n"

    await update.message.reply_text(
        f"👋 CLI Bridge Bot ({alias})\n\n"
        f"📌 当前配置:\n"
        f"   CLI: {profile.cli_type}\n"
        f"   CLI路径: {profile.cli_path}\n"
        f"   工作目录: {session.working_dir}\n"
        f"   消息数: {session.message_count}\n"
        f"{native_session_block}\n"
        f"📝 基本用法:\n"
        f"   直接发送消息 - 与 AI 对话\n"
        f"   //xxx - 转发为 /xxx 给 CLI\n"
        f"   发送文件 - 供 AI 分析\n\n"
        f"🔧 命令列表:\n"
        f"   /start - 显示此帮助\n"
        f"   /reset - 重置当前会话\n"
        f"   /cd <路径> - 切换工作目录\n"
        f"   /pwd - 显示当前目录\n"
        f"   /ls - 列出目录内容\n"
        f"   /exec <cmd> - 执行 Shell 命令\n"
        f"   /history - 查看会话历史\n"
        f"   /upload - 上传文件\n"
        f"   /download <文件> - 下载文件"
        f"{admin_block}"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    removed = reset_session(get_bot_id(update, context), user_id)
    if removed:
        await update.message.reply_text("🔄 会话已完全重置")
    else:
        await update.message.reply_text("ℹ️ 当前没有可重置的会话")


async def change_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /cd <路径>")
        return

    session = get_current_session(update, context)
    new_path = " ".join(context.args)

    if not os.path.isabs(new_path):
        new_path = os.path.join(session.working_dir, new_path)
    new_path = os.path.abspath(os.path.expanduser(new_path))

    if os.path.isdir(new_path):
        session.working_dir = new_path
        await update.message.reply_text(f"📁 目录已切换:\n<code>{html.escape(new_path)}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ 目录不存在:\n<code>{html.escape(new_path)}</code>", parse_mode="HTML")


async def print_working_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    await update.message.reply_text(f"📂 当前目录:\n<code>{html.escape(session.working_dir)}</code>", parse_mode="HTML")


async def list_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)

    try:
        items = []
        for item in os.listdir(session.working_dir):
            full_path = os.path.join(session.working_dir, item)
            if os.path.isdir(full_path):
                items.append(f"📁 {item}/")
            else:
                size = os.path.getsize(full_path)
                if size < 1024:
                    size_str = f"{size:,} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                items.append(f"📄 {item} ({size_str})")

        content = "\n".join(items[:50])
        if len(items) > 50:
            content += f"\n\n... 还有 {len(items) - 50} 项"

        safe_content = truncate_for_markdown(content or "(空目录)", 3800)
        await update.message.reply_text(
            f"📂 <code>{html.escape(session.working_dir)}</code>\n\n<pre>{html.escape(safe_content)}</pre>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 错误: {str(e)}")


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)

    if not session.history:
        await update.message.reply_text("📭 暂无历史记录")
        return

    recent = session.history[-20:]
    lines = []
    for msg in recent:
        icon = "👤" if msg["role"] == "user" else "🤖"
        content = msg["content"]
        if len(content) > 100:
            content = content[:100] + "..."
        lines.append(f"{icon} {content}")

    await update.message.reply_text("📜 最近历史:\n\n" + "\n".join(lines))


async def execute_shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /exec <命令>\n例: /exec ls -la")
        return

    command = " ".join(context.args)
    if is_dangerous_command(command):
        await update.message.reply_text("⛔ 该命令被禁止执行（安全风险）")
        return

    session = get_current_session(update, context)
    msg = await update.message.reply_text(f"🚀 执行: <code>{html.escape(command)}</code>", parse_mode="HTML")

    def run_shell_sync():
        return subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=session.working_dir,
            timeout=60,
        )

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_shell_sync)

        output = result.stdout or ""
        if result.stderr:
            output += f"\n\n[stderr]\n{result.stderr}"
        if not output:
            output = "(无输出)"

        safe_output = truncate_for_markdown(output, 3800)
        icon = "✅" if result.returncode == 0 else "❌"
        await safe_edit_text(msg, f"{icon} <code>{html.escape(command)}</code>\n<pre>{html.escape(safe_output)}</pre>", parse_mode="HTML")
    except subprocess.TimeoutExpired:
        await safe_edit_text(msg, "⏱️ 命令执行超时 (60秒)")
    except Exception as e:
        await safe_edit_text(msg, f"❌ 执行失败: {str(e)}")


async def upload_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    await update.message.reply_text(
        "📤 上传文件帮助:\n\n"
        "方法1: 直接拖拽文件到聊天窗口发送\n"
        "方法2: 点击附件按钮选择文件发送\n\n"
        "⚠️ 文件限制: 最大 20MB"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    document = update.message.document

    if not is_safe_filename(document.file_name):
        await update.message.reply_text("⛔ 文件名包含非法字符")
        return

    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ 文件太大，请发送小于 20MB 的文件")
        return

    msg = await update.message.reply_text("📥 正在接收文件...")

    try:
        file = await context.bot.get_file(document.file_id)
        file_path = os.path.join(session.working_dir, document.file_name)
        await file.download_to_drive(file_path)
        await safe_edit_text(
            msg,
            f"✅ 文件已保存:\n<code>{html.escape(file_path)}</code>\n\n可以发送消息让 AI 分析此文件",
            parse_mode="HTML",
        )
    except Exception as e:
        await safe_edit_text(msg, f"❌ 文件处理失败: {str(e)}")


async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /download <文件名>\n例: /download output.txt")
        return

    filename = " ".join(context.args)
    if not is_safe_filename(filename):
        await update.message.reply_text("⛔ 文件名包含非法字符")
        return

    session = get_current_session(update, context)
    file_path = os.path.join(session.working_dir, filename)

    real_path = os.path.abspath(file_path)
    real_working = os.path.abspath(session.working_dir)
    if not real_path.startswith(real_working):
        await update.message.reply_text("⛔ 无效的文件路径")
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(f"❌ 文件不存在: {filename}")
        return

    if os.path.getsize(file_path) > 50 * 1024 * 1024:
        await update.message.reply_text("❌ 文件太大 (>50MB)，无法通过 Telegram 发送")
        return

    try:
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f)
    except Exception as e:
        await update.message.reply_text(f"❌ 发送失败: {str(e)}")

# ============ AI对话 ============
async def stream_cli_output(process: subprocess.Popen, update: Update) -> Tuple[str, int]:
    """非流式读取CLI输出并发送到Telegram，每秒刷新等待提示。"""

    loop = asyncio.get_running_loop()
    message = await update.message.reply_text("⏳ 处理中...")
    sent_messages = [message]
    start_time = loop.time()

    def communicate_sync() -> Tuple[str, int]:
        stdout, _ = process.communicate()
        return stdout or "", process.returncode if process.returncode is not None else -1

    reader_future = loop.run_in_executor(None, communicate_sync)
    last_elapsed = -1

    try:
        while not reader_future.done():
            await asyncio.sleep(3.0)
            elapsed = int(loop.time() - start_time)
            if elapsed == last_elapsed:
                continue
            last_elapsed = elapsed
            await safe_edit_text(sent_messages[0], f"⏳ 处理中，已等待 {elapsed} 秒...")

        raw_output, returncode = await reader_future
        final_text = raw_output if raw_output.strip() else "(无输出)"

        chunks = split_text_into_chunks(final_text, max_len=3800)
        icon = "✅" if returncode == 0 else "⚠️"

        # 发送新消息，不覆盖等待消息
        for i, chunk in enumerate(chunks):
            prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
            formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>"
            new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
            sent_messages.append(new_msg)
            await asyncio.sleep(0.3)

        return final_text, returncode
    except Exception as e:
        logger.error(f"非流式处理错误: {e}")
        await safe_edit_text(sent_messages[0], f"❌ 处理出错: {str(e)}")
        return "", -1


def _extract_nested_nonempty_str(payload: Dict[str, Any], *path: str) -> Optional[str]:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str) and node.strip():
        return node.strip()
    return None


def _extract_codex_thread_id(event: Dict[str, Any]) -> Optional[str]:
    candidate_paths = (
        ("thread_id",),
        ("session_id",),
        ("conversation_id",),
        ("thread", "id"),
        ("session", "id"),
        ("conversation", "id"),
        ("data", "thread_id"),
        ("data", "session_id"),
        ("data", "conversation_id"),
    )
    for path in candidate_paths:
        value = _extract_nested_nonempty_str(event, *path)
        if value:
            return value
    return None


def _extract_codex_error_text(event: Dict[str, Any]) -> Optional[str]:
    for key in ("message", "error", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _extract_nested_nonempty_str(value, "message")
            if nested:
                return nested
            nested = _extract_nested_nonempty_str(value, "detail")
            if nested:
                return nested
            nested = _extract_nested_nonempty_str(value, "error")
            if nested:
                return nested
    return None


def should_reset_codex_session(session_id: Optional[str], response: str, returncode: int) -> bool:
    """仅在明确是会话失效错误时清空 session_id。"""
    if not session_id or returncode == 0:
        return False

    lower = (response or "").lower()
    if not lower:
        return False

    invalid_markers = (
        "session not found",
        "thread not found",
        "conversation not found",
        "unknown session",
        "unknown thread",
        "invalid session",
        "invalid thread",
        "no such session",
        "no such thread",
        "failed to resume",
        "cannot resume",
        "could not resume",
        "not a valid session",
        "not a valid thread",
    )
    return any(marker in lower for marker in invalid_markers)


def should_reset_claude_session(response: str, returncode: int) -> bool:
    """Claude 会话失效时重置 session_id。"""
    if returncode == 0:
        return False
    lower = (response or "").lower()
    if not lower:
        return False
    reset_markers = (
        "session not found",
        "invalid session",
        "no such session",
        "not a valid session",
        "could not resume",
        "failed to resume",
    )
    return any(marker in lower for marker in reset_markers)


def should_mark_claude_session_initialized(response: str, returncode: int) -> bool:
    """识别会话已存在但本次调用模式不对（session-id already in use）场景。"""
    if returncode == 0:
        return True
    lower = (response or "").lower()
    return "session id" in lower and "already in use" in lower


def parse_codex_json_line(line: str) -> Dict[str, Optional[str]]:
    """解析 codex --json 的单行事件。"""
    result: Dict[str, Optional[str]] = {
        "thread_id": None,
        "completed_text": None,
        "delta_text": None,
        "error_text": None,
    }
    try:
        event: Any = json.loads(line)
    except json.JSONDecodeError:
        return result

    if not isinstance(event, dict):
        return result

    result["thread_id"] = _extract_codex_thread_id(event)
    event_type = str(event.get("type", "")).strip()

    if event_type == "error":
        result["error_text"] = _extract_codex_error_text(event)
        return result

    if not event_type.startswith("item."):
        return result

    item = event.get("item")
    if not isinstance(item, dict):
        return result

    item_type = str(item.get("type", "")).strip()
    if item_type not in ("agent_message", "assistant_message"):
        return result

    text_value = item.get("text")
    delta_value = item.get("delta")

    if event_type == "item.completed":
        if isinstance(text_value, str) and text_value:
            result["completed_text"] = text_value
        return result

    if event_type == "item.delta":
        if isinstance(delta_value, str) and delta_value:
            result["delta_text"] = delta_value
        elif isinstance(text_value, str) and text_value:
            result["delta_text"] = text_value
        return result

    return result


def parse_codex_json_output(raw_output: str) -> Tuple[str, Optional[str]]:
    """解析 codex --json 的完整输出文本，提取 assistant 文本和 thread_id。"""
    raw_lines: List[str] = []
    completed_parts: List[str] = []
    delta_parts: List[str] = []
    error_parts: List[str] = []
    thread_id: Optional[str] = None

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_lines.append(stripped)
        parsed = parse_codex_json_line(stripped)
        if parsed["thread_id"]:
            thread_id = parsed["thread_id"]
        if parsed["completed_text"]:
            completed_parts.append(parsed["completed_text"])
        if parsed["delta_text"]:
            delta_parts.append(parsed["delta_text"])
        if parsed["error_text"]:
            error_parts.append(parsed["error_text"])

    if completed_parts:
        final_text = "\n\n".join(part for part in completed_parts if part.strip()).strip()
    else:
        final_text = "".join(delta_parts).strip()

    if not final_text and error_parts:
        final_text = "\n".join(error_parts).strip()
    if not final_text:
        final_text = "\n".join(raw_lines).strip()
    if not final_text:
        final_text = "(无输出)"

    return final_text, thread_id


async def stream_codex_json_output(process: subprocess.Popen, update: Update) -> Tuple[str, Optional[str], int]:
    """非流式读取 codex --json 输出，每秒刷新等待提示。"""
    loop = asyncio.get_running_loop()
    message = await update.message.reply_text("⏳ Codex处理中...")
    sent_messages = [message]
    start_time = loop.time()

    def communicate_sync() -> Tuple[str, int]:
        stdout, _ = process.communicate()
        return stdout or "", process.returncode if process.returncode is not None else -1

    reader_future = loop.run_in_executor(None, communicate_sync)
    last_elapsed = -1

    try:
        while not reader_future.done():
            await asyncio.sleep(3.0)
            elapsed = int(loop.time() - start_time)
            if elapsed == last_elapsed:
                continue
            last_elapsed = elapsed
            await safe_edit_text(sent_messages[0], f"⏳ Codex处理中，已等待 {elapsed} 秒...")

        raw_output, returncode = await reader_future
        final_text, thread_id = parse_codex_json_output(raw_output)

        chunks = split_text_into_chunks(final_text, max_len=3800)
        icon = "✅" if returncode == 0 else "⚠️"

        # 发送新消息，不覆盖等待消息
        for i, chunk in enumerate(chunks):
            prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
            formatted = f"{icon} {prefix}<pre>{html.escape(chunk)}</pre>"
            new_msg = await update.message.reply_text(formatted, parse_mode="HTML")
            sent_messages.append(new_msg)
            await asyncio.sleep(0.3)

        return final_text, thread_id, returncode
    except Exception as e:
        logger.error(f"Codex JSON 非流式处理错误: {e}")
        await safe_edit_text(sent_messages[0], f"❌ 处理出错: {str(e)}")
        return "", None, -1


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    profile = get_current_profile(context)
    session = get_current_session(update, context)

    user_text = update.message.text
    if user_text.startswith("//"):
        user_text = "/" + user_text[2:]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

    cli_type = normalize_cli_type(profile.cli_type)
    cli_path = profile.cli_path
    resolved_cli = resolve_cli_executable(cli_path, session.working_dir)
    if resolved_cli is None:
        await update.message.reply_text(
            f"❌ 未找到CLI可执行文件: {cli_path}\n"
            "请用 /bot_set_cli 配置正确路径（Windows 常见为 claude.cmd）"
        )
        return

    # Codex 需要 CI=true 环境变量来避免 "stdout is not a terminal" 错误
    if cli_type == "codex":
        env["CI"] = "true"

    is_busy = False
    with session._lock:
        if session.is_processing:
            is_busy = True
        else:
            session.is_processing = True
            codex_session_id: Optional[str] = None
            cli_session_id: Optional[str] = None
            resume_session = False

            if cli_type == "codex":
                codex_session_id = session.codex_session_id
                cli_session_id = codex_session_id
                resume_session = bool(codex_session_id)
            elif cli_type == "kimi":
                if not session.kimi_session_id:
                    session.kimi_session_id = f"kimi-{uuid.uuid4().hex}"
                cli_session_id = session.kimi_session_id
            elif cli_type == "claude":
                if not session.claude_session_id:
                    session.claude_session_id = str(uuid.uuid4())
                    session.claude_session_initialized = False
                cli_session_id = session.claude_session_id
                resume_session = session.claude_session_initialized

    if is_busy:
        await update.message.reply_text("⏳ 当前会话正在处理上一条消息，请稍后再试。")
        return

    try:
        session.touch()

        # 所有 CLI 都直接发送当前输入，不做本地历史拼接。
        full_prompt = user_text

        try:
            cmd, use_stdin = build_cli_command(
                cli_type=cli_type,
                resolved_cli=resolved_cli,
                user_text=full_prompt,
                env=env,
                session_id=cli_session_id,
                resume_session=resume_session,
                json_output=(cli_type == "codex"),
            )
        except ValueError as e:
            await update.message.reply_text(f"❌ {str(e)}")
            return

        # 命令构造成功后再写入用户消息历史，避免无效输入污染上下文
        session.add_to_history("user", user_text)

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
            )

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(full_prompt + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as e:
                    logger.error(f"CLI stdin 写入失败: {e}")
                    await update.message.reply_text("❌ CLI 进程启动失败")
                    process.wait()
                    return

            with session._lock:
                session.process = process

            if cli_type == "codex":
                response, thread_id, returncode = await stream_codex_json_output(process, update)
                if thread_id:
                    with session._lock:
                        session.codex_session_id = thread_id
                elif should_reset_codex_session(codex_session_id, response, returncode):
                    # 仅在明确会话失效时清空，避免网络/运行错误导致会话丢失。
                    with session._lock:
                        session.codex_session_id = None
            else:
                response, returncode = await stream_cli_output(process, update)
                if cli_type == "claude":
                    with session._lock:
                        if should_mark_claude_session_initialized(response, returncode):
                            session.claude_session_initialized = True
                        elif should_reset_claude_session(response, returncode):
                            session.claude_session_id = None
                            session.claude_session_initialized = False
            session.add_to_history("assistant", response)
        except FileNotFoundError:
            await update.message.reply_text(f"❌ 未找到CLI可执行文件: {cli_path}")
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            await update.message.reply_text(f"❌ 错误: {str(e)}")
    finally:
        with session._lock:
            session.process = None
            session.is_processing = False

# ============ 主Bot管理命令 ============
async def bot_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    await update.message.reply_text(
        "🛠 多Bot管理命令:\n\n"
        "0) 重启整个程序（重载代码）:\n"
        "   /restart\n\n"
        "1) 添加并启动子Bot:\n"
        "   /bot_add <alias> <token> [cli_type] [cli_path] [workdir]\n"
        "   cli_type 支持: kimi / claude / codex\n"
        "   例: /bot_add team1 123:abc codex codex C:/work/project\n\n"
        "2) 查看状态:\n"
        "   /bot_list\n\n"
        "3) 停止/启动:\n"
        "   /bot_stop <alias>\n"
        "   /bot_start <alias>\n\n"
        "4) 修改CLI配置:\n"
        "   /bot_set_cli <alias> <cli_type> <cli_path>\n"
        "   /bot_set_workdir <alias> <workdir>\n\n"
        "5) 删除子Bot:\n"
        "   /bot_remove <alias>"
    )


async def bot_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    manager = get_manager(context)
    lines = manager.get_status_lines()
    await update.message.reply_text("🤖 Bot状态:\n\n" + "\n".join(lines))


async def restart_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    await update.message.reply_text("🔄 正在重启整个程序并重载代码...")
    # 给消息发送留一点时间，确保消息能到达 Telegram 服务器
    await asyncio.sleep(1)
    request_restart()


async def bot_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "用法: /bot_add <alias> <token> [cli_type] [cli_path] [workdir]"
        )
        return

    alias = context.args[0].strip().lower()
    token = context.args[1].strip()
    cli_type = context.args[2].strip() if len(context.args) >= 3 else CLI_TYPE
    cli_path = context.args[3].strip() if len(context.args) >= 4 else CLI_PATH
    workdir = " ".join(context.args[4:]).strip() if len(context.args) >= 5 else WORKING_DIR

    manager = get_manager(context)
    msg = await update.message.reply_text(f"⏳ 正在添加子Bot <code>{html.escape(alias)}</code> ...", parse_mode="HTML")

    try:
        profile = await manager.add_bot(alias, token, cli_type, cli_path, workdir)
        app = manager.applications.get(profile.alias)
        username = app.bot_data.get("bot_username", "") if app else ""
        await safe_edit_text(
            msg,
            (
                f"✅ 子Bot已添加并启动\n"
                f"alias: <code>{html.escape(profile.alias)}</code>\n"
                f"username: @{html.escape(username or 'unknown')}\n"
                f"cli: <code>{html.escape(profile.cli_type)}</code> / <code>{html.escape(profile.cli_path)}</code>\n"
                f"workdir: <code>{html.escape(profile.working_dir)}</code>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        await safe_edit_text(msg, f"❌ 添加失败: {str(e)}")


async def bot_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("用法: /bot_remove <alias>")
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)

    try:
        await manager.remove_bot(alias)
        await update.message.reply_text(f"✅ 已删除子Bot: <code>{html.escape(alias)}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ 删除失败: {str(e)}")


async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("用法: /bot_start <alias>")
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)
    try:
        await manager.start_bot(alias)
        await update.message.reply_text(f"✅ 已启动子Bot: <code>{html.escape(alias)}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ 启动失败: {str(e)}")


async def bot_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("用法: /bot_stop <alias>")
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)
    try:
        await manager.stop_bot(alias)
        await update.message.reply_text(f"✅ 已停止子Bot: <code>{html.escape(alias)}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ 停止失败: {str(e)}")


async def bot_set_cli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 3:
        await update.message.reply_text("用法: /bot_set_cli <alias> <cli_type> <cli_path>")
        return

    alias = context.args[0].strip().lower()
    cli_type = context.args[1].strip()
    cli_path = " ".join(context.args[2:]).strip()

    manager = get_manager(context)
    try:
        await manager.set_bot_cli(alias, cli_type, cli_path)
        await update.message.reply_text(
            f"✅ 已更新CLI配置: <code>{html.escape(alias)}</code> -> <code>{html.escape(cli_type)}</code> / <code>{html.escape(cli_path)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 更新失败: {str(e)}")


async def bot_set_workdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text("用法: /bot_set_workdir <alias> <workdir>")
        return

    alias = context.args[0].strip().lower()
    workdir = " ".join(context.args[1:]).strip()

    manager = get_manager(context)
    try:
        await manager.set_bot_workdir(alias, workdir)
        await update.message.reply_text(
            f"✅ 已更新工作目录: <code>{html.escape(alias)}</code> -> <code>{html.escape(os.path.abspath(os.path.expanduser(workdir)))}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 更新失败: {str(e)}")


def register_handlers(application: Application, include_admin: bool = False):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("cd", change_directory))
    application.add_handler(CommandHandler("pwd", print_working_directory))
    application.add_handler(CommandHandler("ls", list_directory))
    application.add_handler(CommandHandler("exec", execute_shell))
    application.add_handler(CommandHandler("history", show_history))
    application.add_handler(CommandHandler("upload", upload_help))
    application.add_handler(CommandHandler("download", download_file))

    if include_admin:
        application.add_handler(CommandHandler("restart", restart_main))
        application.add_handler(CommandHandler("bot_help", bot_help))
        application.add_handler(CommandHandler("bot_list", bot_list))
        application.add_handler(CommandHandler("bot_add", bot_add))
        application.add_handler(CommandHandler("bot_remove", bot_remove))
        application.add_handler(CommandHandler("bot_start", bot_start))
        application.add_handler(CommandHandler("bot_stop", bot_stop))
        application.add_handler(CommandHandler("bot_set_cli", bot_set_cli))
        application.add_handler(CommandHandler("bot_set_workdir", bot_set_workdir))

    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))


# ============ 主程序 ============
async def run_all_bots():
    global RESTART_EVENT
    RESTART_EVENT = asyncio.Event()
    main_profile = BotProfile(
        alias="main",
        token=TELEGRAM_BOT_TOKEN,
        cli_type=CLI_TYPE,
        cli_path=CLI_PATH,
        working_dir=WORKING_DIR,
        enabled=True,
    )

    manager = MultiBotManager(main_profile=main_profile, storage_file=MANAGED_BOTS_FILE)
    await manager.start_all()
    await manager.start_watchdog()

    logger.info("主Bot与已启用子Bot已启动")
    logger.info("托管配置文件: %s", MANAGED_BOTS_FILE)

    try:
        await RESTART_EVENT.wait()
    finally:
        await manager.shutdown_all()
        RESTART_EVENT = None


def main():
    global RESTART_REQUESTED

    if TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("错误: 请设置 TELEGRAM_BOT_TOKEN 环境变量")
        sys.exit(1)

    try:
        validate_cli_type(CLI_TYPE)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    print("启动高级版 Telegram CLI Bridge (多Bot模式)...")
    print(f"   主Bot CLI类型: {CLI_TYPE}")
    print(f"   主Bot工作目录: {WORKING_DIR}")
    print(f"   会话超时: {SESSION_TIMEOUT}秒")
    print(f"   托管配置文件: {MANAGED_BOTS_FILE}")

    while True:
        RESTART_REQUESTED = False
        try:
            asyncio.run(run_all_bots())
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            logger.exception("运行异常，%s秒后自动重试: %s", MAIN_LOOP_RETRY_DELAY, e)
            print(f"运行异常，将在 {MAIN_LOOP_RETRY_DELAY} 秒后自动重试: {e}")
            time.sleep(MAIN_LOOP_RETRY_DELAY)
            continue

        if RESTART_REQUESTED:
            print("检测到 /restart，正在重启整个程序（重载代码）...")
            # 短暂等待让启动问候消息的发送任务完成
            time.sleep(0.5)
            try:
                reexec_current_process()
            except Exception as e:
                print(f"进程级重启失败: {e}")
                break
        break


if __name__ == "__main__":
    main()
