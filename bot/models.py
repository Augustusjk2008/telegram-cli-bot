"""BotProfile 和 UserSession 数据类"""

import logging
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from bot.config import CLI_TYPE, CLI_PATH, WORKING_DIR
from bot.cli_params import CliParamsConfig
from bot.cluster.config import (
    AgentClusterConfig,
    BotClusterConfig,
    normalize_agent_cluster_config,
    normalize_bot_cluster_config,
)

if TYPE_CHECKING:
    # 避免循环导入
    pass

logger = logging.getLogger(__name__)
PersistHook = Callable[["UserSession"], None]
SESSION_PERSIST_DEBOUNCE_SECONDS = 0.25


@dataclass
class GitCommitMessageCliConfig:
    """Git commit message 生成专用 CLI 配置。"""

    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    cli_params: CliParamsConfig = field(default_factory=CliParamsConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "cli_params": self.cli_params.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GitCommitMessageCliConfig":
        return cls(
            cli_type=str(data.get("cli_type", CLI_TYPE) or CLI_TYPE),
            cli_path=str(data.get("cli_path", CLI_PATH) or CLI_PATH),
            cli_params=CliParamsConfig.from_dict(data.get("cli_params")),
        )


@dataclass
class AgentProfile:
    """Bot 内部的 CLI 子 agent 配置。"""

    id: str
    name: str
    system_prompt: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    cluster: AgentClusterConfig = field(default_factory=AgentClusterConfig)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "system_prompt": self.system_prompt,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cluster": self.cluster.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentProfile":
        from bot.agents import normalize_agent_id, normalize_agent_name, normalize_agent_prompt

        return cls(
            id=normalize_agent_id(data.get("id"), allow_main=True),
            name=normalize_agent_name(data.get("name")),
            system_prompt=normalize_agent_prompt(data.get("system_prompt")),
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            cluster=normalize_agent_cluster_config(data.get("cluster")),
        )


@dataclass
class BotProfile:
    """Bot 配置档案"""
    alias: str
    token: str = ""
    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    working_dir: str = WORKING_DIR
    enabled: bool = True
    bot_mode: str = "cli"  # "cli" | "assistant"
    avatar_name: str = ""
    cli_params: CliParamsConfig = field(default_factory=CliParamsConfig)
    git_commit_cli_config: Optional[GitCommitMessageCliConfig] = None
    agents: List[AgentProfile] = field(default_factory=list)
    cluster: BotClusterConfig = field(default_factory=BotClusterConfig)

    def to_dict(self) -> dict:
        result = {
            "alias": self.alias,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "bot_mode": self.bot_mode,
        }
        if self.avatar_name:
            result["avatar_name"] = self.avatar_name
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
        child_agents = [agent.to_dict() for agent in self.agents if agent.id != "main"]
        if child_agents:
            result["agents"] = child_agents
        if self.cluster != BotClusterConfig():
            result["cluster"] = self.cluster.to_dict()
        return result

    def normalized_agents(self) -> list[AgentProfile]:
        main = AgentProfile(id="main", name="主 agent", enabled=True)
        children = [agent for agent in self.agents if agent.id != "main"]
        return [main, *children]

    def get_agent(self, agent_id: str) -> AgentProfile:
        normalized_id = str(agent_id or "main").strip().lower() or "main"
        for agent in self.normalized_agents():
            if agent.id == normalized_id:
                return agent
        raise KeyError(normalized_id)
    
    @classmethod
    def from_dict(cls, data: dict) -> "BotProfile":
        """从字典创建 BotProfile，支持 cli_params 字段"""
        # 提取 cli_params
        cli_params_data = data.get("cli_params")
        cli_params = CliParamsConfig.from_dict(cli_params_data) if cli_params_data else CliParamsConfig()
        agents = [
            AgentProfile.from_dict(item)
            for item in data.get("agents", [])
            if isinstance(item, dict)
        ]
        
        return cls(
            alias=data["alias"],
            token=str(data.get("token", "") or ""),
            cli_type=data.get("cli_type", CLI_TYPE),
            cli_path=data.get("cli_path", CLI_PATH),
            working_dir=data.get("working_dir", WORKING_DIR),
            enabled=data.get("enabled", True),
            bot_mode=data.get("bot_mode", "cli"),
            avatar_name=str(data.get("avatar_name", "") or ""),
            cli_params=cli_params,
            agents=agents,
            cluster=normalize_bot_cluster_config(data.get("cluster")),
        )


@dataclass
class UserSession:
    """按 (bot_id, user_id) 隔离的用户会话状态"""

    bot_id: int
    bot_alias: str
    user_id: int
    working_dir: str
    agent_id: str = "main"
    browse_dir: Optional[str] = None
    history: List[dict] = field(default_factory=list)
    codex_session_id: Optional[str] = None
    claude_session_id: Optional[str] = None
    kimi_session_id: Optional[str] = None
    claude_session_initialized: bool = False
    process: Optional[subprocess.Popen] = None
    is_processing: bool = False
    running_user_text: Optional[str] = None
    running_preview_text: str = ""
    running_started_at: Optional[str] = None
    running_updated_at: Optional[str] = None
    stop_requested: bool = False
    web_turn_overlays: List[dict] = field(default_factory=list)
    last_activity: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    managed_prompt_hash_seen: Optional[str] = None
    agent_prompt_hash_seen: Optional[str] = None
    local_history_backend: str = "local_v1"
    session_epoch: int = 0
    active_conversation_id: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _persist_enabled: bool = field(default=True, repr=False, compare=False)
    persist_hook: Optional[PersistHook] = field(default=None, repr=False, compare=False)
    _persist_timer: Optional[threading.Timer] = field(default=None, repr=False, compare=False)

    def touch(self):
        with self._lock:
            self.last_activity = datetime.now()
            self.message_count += 1
        self.persist_debounced()

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
        self.persist_debounced()

    def start_running_reply(self, user_text: str):
        now = datetime.now().isoformat()
        with self._lock:
            self.running_user_text = user_text
            self.running_preview_text = ""
            self.running_started_at = now
            self.running_updated_at = now
            self.stop_requested = False
        self.persist_debounced()

    def update_running_reply(self, preview_text: Optional[str] = None):
        now = datetime.now().isoformat()
        with self._lock:
            if self.running_started_at is None:
                self.running_started_at = now
            if preview_text is not None:
                self.running_preview_text = preview_text
            self.running_updated_at = now
        self.persist_debounced()

    def clear_running_reply(self):
        with self._lock:
            self.running_user_text = None
            self.running_preview_text = ""
            self.running_started_at = None
            self.running_updated_at = None
            self.stop_requested = False
        self.persist()

    def upsert_web_turn_overlay(self, overlay: dict, *, limit: int = 20):
        key = (
            str(overlay.get("provider") or ""),
            str(overlay.get("native_session_id") or ""),
            str(overlay.get("started_at") or ""),
        )
        with self._lock:
            kept = [
                dict(item)
                for item in self.web_turn_overlays
                if (
                    str(item.get("provider") or ""),
                    str(item.get("native_session_id") or ""),
                    str(item.get("started_at") or ""),
                ) != key
            ]
            kept.append(dict(overlay))
            self.web_turn_overlays = kept[-limit:]
        self.persist()

    def terminate_process(self):
        from bot.session_runtime import terminate_session_process

        terminate_session_process(self)
        with self._lock:
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
        self.flush_persistence()

    def persist_debounced(self):
        with self._lock:
            if not self._persist_enabled:
                return
            timer = self._persist_timer
            if timer is not None:
                timer.cancel()
            next_timer = threading.Timer(SESSION_PERSIST_DEBOUNCE_SECONDS, self._persist_now)
            next_timer.daemon = True
            self._persist_timer = next_timer
            next_timer.start()

    def flush_persistence(self):
        timer = None
        with self._lock:
            if not self._persist_enabled:
                return
            timer = self._persist_timer
            self._persist_timer = None
        if timer is not None:
            timer.cancel()
        self._persist_now()

    def _persist_now(self):
        if not self._persist_enabled:
            return
        with self._lock:
            if not self._persist_enabled:
                return
            self._persist_timer = None
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
            timer = self._persist_timer
            self._persist_timer = None
            self._persist_enabled = False
            self.persist_hook = None
        if timer is not None:
            timer.cancel()

    def clear_session_ids(self):
        """清除所有 session_id 并持久化"""
        with self._lock:
            self.codex_session_id = None
            self.claude_session_id = None
            self.kimi_session_id = None
            self.claude_session_initialized = False
            self.active_conversation_id = None
        self.persist()
        logger.info(f"已清除会话ID: bot={self.bot_id}, user={self.user_id}")
