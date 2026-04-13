"""BotProfile 和 UserSession 数据类"""

import logging
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from bot.config import CLI_TYPE, CLI_PATH, SESSION_TIMEOUT, WORKING_DIR
from bot.cli_params import CliParamsConfig

if TYPE_CHECKING:
    # 避免循环导入
    pass

logger = logging.getLogger(__name__)
PersistHook = Callable[["UserSession"], None]


@dataclass
class BotProfile:
    """Bot 配置档案"""
    alias: str
    token: str
    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    working_dir: str = WORKING_DIR
    enabled: bool = True
    bot_mode: str = "cli"  # "cli" | "assistant"
    avatar_name: str = "bot-default.png"
    cli_params: CliParamsConfig = field(default_factory=CliParamsConfig)

    def to_dict(self) -> dict:
        result = {
            "alias": self.alias,
            "token": self.token,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "bot_mode": self.bot_mode,
            "avatar_name": self.avatar_name,
        }
        # 添加 CLI 参数配置（如果有非默认配置）
        params_dict = self.cli_params.to_dict()
        # 检查是否有自定义配置
        has_custom = False
        from bot.cli_params import DEFAULT_PARAMS_MAP
        for cli_type, params in params_dict.items():
            default = DEFAULT_PARAMS_MAP.get(cli_type, {})
            if params != default:
                has_custom = True
                break
        if has_custom:
            result["cli_params"] = params_dict
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "BotProfile":
        """从字典创建 BotProfile，支持 cli_params 字段"""
        # 提取 cli_params
        cli_params_data = data.get("cli_params")
        cli_params = CliParamsConfig.from_dict(cli_params_data) if cli_params_data else CliParamsConfig()
        
        return cls(
            alias=data["alias"],
            token=data["token"],
            cli_type=data.get("cli_type", CLI_TYPE),
            cli_path=data.get("cli_path", CLI_PATH),
            working_dir=data.get("working_dir", WORKING_DIR),
            enabled=data.get("enabled", True),
            bot_mode=data.get("bot_mode", "cli"),
            avatar_name=str(data.get("avatar_name", "bot-default.png") or "bot-default.png"),
            cli_params=cli_params,
        )


@dataclass
class UserSession:
    """按 (bot_id, user_id) 隔离的用户会话状态"""

    bot_id: int
    bot_alias: str
    user_id: int
    working_dir: str
    browse_dir: Optional[str] = None
    history: List[dict] = field(default_factory=list)
    codex_session_id: Optional[str] = None
    kimi_session_id: Optional[str] = None
    claude_session_id: Optional[str] = None
    claude_session_initialized: bool = False
    process: Optional[subprocess.Popen] = None
    is_processing: bool = False
    running_user_text: Optional[str] = None
    running_preview_text: str = ""
    running_started_at: Optional[str] = None
    running_updated_at: Optional[str] = None
    stop_requested: bool = False
    last_activity: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    managed_prompt_hash_seen: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _persist_enabled: bool = field(default=True, repr=False, compare=False)
    persist_hook: Optional[PersistHook] = field(default=None, repr=False, compare=False)

    def touch(self):
        with self._lock:
            self.last_activity = datetime.now()
            self.message_count += 1
        self.persist()

    def is_expired(self) -> bool:
        elapsed = (datetime.now() - self.last_activity).total_seconds()
        return elapsed > SESSION_TIMEOUT

    def add_to_history(self, role: str, content: str, *, elapsed_seconds: Optional[int] = None):
        with self._lock:
            item = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content,
            }
            if isinstance(elapsed_seconds, int) and elapsed_seconds >= 0:
                item["elapsed_seconds"] = elapsed_seconds
            self.history.append(item)
            if len(self.history) > 100:
                self.history = self.history[-100:]
        self.persist()

    def start_running_reply(self, user_text: str):
        now = datetime.now().isoformat()
        with self._lock:
            self.running_user_text = user_text
            self.running_preview_text = ""
            self.running_started_at = now
            self.running_updated_at = now
        self.persist()

    def update_running_reply(self, preview_text: Optional[str] = None):
        now = datetime.now().isoformat()
        with self._lock:
            if self.running_started_at is None:
                self.running_started_at = now
            if preview_text is not None:
                self.running_preview_text = preview_text
            self.running_updated_at = now
        self.persist()

    def clear_running_reply(self):
        with self._lock:
            self.running_user_text = None
            self.running_preview_text = ""
            self.running_started_at = None
            self.running_updated_at = None
        self.persist()

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
            self.stop_requested = False
            self.is_processing = False
            self.running_user_text = None
            self.running_preview_text = ""
            self.running_started_at = None
            self.running_updated_at = None
        self.persist()

    def persist(self):
        """持久化当前会话状态（session_ids）
        
        在 session_id 变化时调用，确保重启后能恢复会话。
        """
        if not self._persist_enabled:
            return
        hook = self.persist_hook
        if hook is not None:
            hook(self)
            return
        # 延迟导入避免循环依赖
        try:
            from bot.sessions import _save_session_to_store
            _save_session_to_store(self)
        except ImportError:
            logger.warning("无法导入 session_store，会话将不会被持久化")

    def disable_persistence(self):
        """禁用后续持久化，用于 reset 后阻止陈旧会话对象回写状态。"""
        with self._lock:
            self._persist_enabled = False
            self.persist_hook = None

    def clear_session_ids(self):
        """清除所有 session_id 并持久化"""
        with self._lock:
            self.codex_session_id = None
            self.kimi_session_id = None
            self.claude_session_id = None
            self.claude_session_initialized = False
        self.persist()
        logger.info(f"已清除会话ID: bot={self.bot_id}, user={self.user_id}")
