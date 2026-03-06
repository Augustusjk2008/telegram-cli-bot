"""BotProfile 和 UserSession 数据类"""

import logging
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bot.config import CLI_TYPE, CLI_PATH, SESSION_TIMEOUT, WORKING_DIR

logger = logging.getLogger(__name__)


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

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "token": self.token,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "bot_mode": self.bot_mode,
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
