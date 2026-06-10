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
PROMPT_PRESET_MAX_ITEMS = 50
PROMPT_PRESET_TITLE_MAX_LENGTH = 80
PROMPT_PRESET_CONTENT_MAX_LENGTH = 12000
PROMPT_PRESET_ID_MAX_LENGTH = 128
EXECUTION_MODE_CLI = "cli"
EXECUTION_MODE_NATIVE_AGENT = "native_agent"
SUPPORTED_EXECUTION_MODES = {EXECUTION_MODE_CLI, EXECUTION_MODE_NATIVE_AGENT}


def normalize_execution_mode(value: Any, *, default: str = EXECUTION_MODE_CLI) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_EXECUTION_MODES:
        return normalized
    return default if default in SUPPORTED_EXECUTION_MODES else EXECUTION_MODE_CLI


def normalize_execution_modes(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        modes = [normalize_execution_mode(item, default="") for item in value]
    else:
        modes = [EXECUTION_MODE_CLI]
    result: list[str] = []
    for mode in modes:
        if mode in SUPPORTED_EXECUTION_MODES and mode not in result:
            result.append(mode)
    return result or [EXECUTION_MODE_CLI]


def normalize_execution_mode_config(
    supported_value: Any,
    default_value: Any,
    *,
    bot_mode: str = "cli",
) -> tuple[list[str], str]:
    if str(bot_mode or "cli").strip().lower() != "cli":
        return [EXECUTION_MODE_CLI], EXECUTION_MODE_CLI
    supported = normalize_execution_modes(supported_value)
    default = normalize_execution_mode(default_value, default=supported[0])
    if supported == [EXECUTION_MODE_NATIVE_AGENT] or default == EXECUTION_MODE_NATIVE_AGENT:
        return [EXECUTION_MODE_NATIVE_AGENT], EXECUTION_MODE_NATIVE_AGENT
    return [EXECUTION_MODE_CLI], EXECUTION_MODE_CLI


def _native_agent_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _native_agent_bool(data: dict[str, Any], *keys: str) -> bool:
    value = _native_agent_value(data, *keys)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_native_agent_provider(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_native_agent_base_url(value: Any) -> str:
    base_url = str(value or "").strip()
    if not base_url:
        return ""
    lowered = base_url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    return base_url.rstrip("/")


def mask_secret(value: Any) -> str:
    secret = str(value or "")
    if not secret:
        return ""
    suffix = secret[-4:] if len(secret) >= 4 else secret
    prefix = secret[:3] if secret.startswith("sk-") else ""
    return f"{prefix}****{suffix}"


def normalize_native_agent_config(value: Any, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    existing_config = dict(existing or {})
    provider = normalize_native_agent_provider(data.get("provider"))
    model = str(
        data.get("model")
        or data.get("modelId")
        or data.get("model_id")
        or data.get("native_agent_model")
        or data.get("nativeAgentModel")
        or data.get("selected_model")
        or data.get("selectedModel")
        or ""
    ).strip()
    if provider and model and "/" not in model:
        model = f"{provider}/{model}"
    pi_agent = str(
        data.get("pi_agent")
        or data.get("piAgent")
        or data.get("opencode_agent")
        or data.get("opencodeAgent")
        or data.get("agent")
        or ""
    ).strip()
    pi_command = str(data.get("pi_command") or data.get("piCommand") or "").strip()
    workspace_history_value = _native_agent_value(data, "workspace_history_enabled", "workspaceHistoryEnabled")
    reasoning_effort = str(
        data.get("reasoning_effort")
        or data.get("reasoningEffort")
        or ""
    ).strip()
    thinking_depth = str(
        data.get("thinking_depth")
        or data.get("thinkingDepth")
        or ""
    ).strip()
    base_url = normalize_native_agent_base_url(_native_agent_value(data, "base_url", "baseUrl"))
    clear_api_key = _native_agent_bool(data, "clear_api_key", "clearApiKey")
    has_api_key_input = "api_key" in data or "apiKey" in data
    api_key = str(_native_agent_value(data, "api_key", "apiKey") or "").strip() if has_api_key_input else ""
    result: dict[str, Any] = {}
    if data and any(
        key in data
        for key in (
            "backend",
            "model",
            "modelId",
            "model_id",
            "native_agent_model",
            "nativeAgentModel",
            "selected_model",
            "selectedModel",
            "pi_agent",
            "piAgent",
            "opencode_agent",
            "opencodeAgent",
            "agent",
            "pi_command",
            "piCommand",
            "workspace_history_enabled",
            "workspaceHistoryEnabled",
            "reasoning_effort",
            "reasoningEffort",
            "thinking_depth",
            "thinkingDepth",
        )
    ):
        result["backend"] = "pi"
    if provider:
        result["provider"] = provider
    if model:
        result["model"] = model
    if pi_agent:
        result["pi_agent"] = pi_agent
    if pi_command:
        result["pi_command"] = pi_command
    if workspace_history_value is not None:
        result["workspace_history_enabled"] = _native_agent_bool(data, "workspace_history_enabled", "workspaceHistoryEnabled")
    if reasoning_effort:
        result["reasoning_effort"] = reasoning_effort
    if thinking_depth:
        result["thinking_depth"] = thinking_depth
    if base_url:
        result["base_url"] = base_url
    if clear_api_key:
        pass
    elif has_api_key_input:
        if api_key:
            result["api_key"] = api_key
        elif existing_config.get("api_key"):
            result["api_key"] = str(existing_config.get("api_key") or "")
    elif existing_config.get("api_key"):
        result["api_key"] = str(existing_config.get("api_key") or "")
    return result


def public_native_agent_config(value: Any) -> dict[str, Any]:
    config = normalize_native_agent_config(value)
    result = {
        key: config[key]
        for key in ("backend", "model", "pi_agent", "pi_command", "reasoning_effort", "thinking_depth")
        if config.get(key)
    }
    if config.get("workspace_history_enabled") is not None:
        result["workspace_history_enabled"] = bool(config.get("workspace_history_enabled"))
    api_key = str(config.get("api_key") or "")
    if api_key:
        result["has_api_key"] = True
        result["api_key_masked"] = mask_secret(api_key)
    else:
        result["has_api_key"] = False
        result["api_key_masked"] = ""
    return result


def build_native_agent_model_id(value: Any) -> str:
    config = normalize_native_agent_config(value)
    provider = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if not model:
        return ""
    if "/" in model:
        return model
    if provider:
        return f"{provider}/{model}"
    return model


def normalize_prompt_presets(value: Any, *, strict: bool = False) -> list[dict[str, str]]:
    """规范化聊天预设提示词。"""
    if value is None:
        return []
    if not isinstance(value, list):
        if strict:
            raise ValueError("prompt_presets 必须是数组")
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if len(normalized) >= PROMPT_PRESET_MAX_ITEMS:
            break
        if not isinstance(item, dict):
            if strict:
                raise ValueError("预设提示词必须是对象")
            continue

        preset_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not preset_id:
            if strict:
                raise ValueError("预设 ID 不能为空")
            continue
        if not title:
            if strict:
                raise ValueError("预设标题不能为空")
            continue
        if not content:
            if strict:
                raise ValueError("预设内容不能为空")
            continue

        normalized.append(
            {
                "id": preset_id[:PROMPT_PRESET_ID_MAX_LENGTH],
                "title": title[:PROMPT_PRESET_TITLE_MAX_LENGTH],
                "content": content[:PROMPT_PRESET_CONTENT_MAX_LENGTH],
            }
        )
    return normalized


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
    prompt_presets: List[dict[str, str]] = field(default_factory=list)
    supported_execution_modes: List[str] = field(default_factory=lambda: ["cli"])
    default_execution_mode: str = "cli"
    native_agent: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        supported_execution_modes, default_execution_mode = normalize_execution_mode_config(
            self.supported_execution_modes,
            self.default_execution_mode,
            bot_mode=self.bot_mode,
        )
        result = {
            "alias": self.alias,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "bot_mode": self.bot_mode,
            "supported_execution_modes": supported_execution_modes,
            "default_execution_mode": default_execution_mode,
            "native_agent": normalize_native_agent_config(self.native_agent),
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
        prompt_presets = normalize_prompt_presets(self.prompt_presets)
        if prompt_presets:
            result["prompt_presets"] = prompt_presets
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
        bot_mode = data.get("bot_mode", "cli")
        supported_execution_modes, default_execution_mode = normalize_execution_mode_config(
            data.get("supported_execution_modes", data.get("supportedExecutionModes")),
            data.get("default_execution_mode", data.get("defaultExecutionMode", "cli")),
            bot_mode=str(bot_mode or "cli"),
        )
        
        return cls(
            alias=data["alias"],
            token=str(data.get("token", "") or ""),
            cli_type=data.get("cli_type", CLI_TYPE),
            cli_path=data.get("cli_path", CLI_PATH),
            working_dir=data.get("working_dir", WORKING_DIR),
            enabled=data.get("enabled", True),
            bot_mode=bot_mode,
            avatar_name=str(data.get("avatar_name", "") or ""),
            cli_params=cli_params,
            agents=agents,
            cluster=normalize_bot_cluster_config(data.get("cluster")),
            prompt_presets=normalize_prompt_presets(data.get("prompt_presets", data.get("promptPresets"))),
            supported_execution_modes=supported_execution_modes,
            default_execution_mode=default_execution_mode,
            native_agent=normalize_native_agent_config(data.get("native_agent", data.get("nativeAgent"))),
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
    native_agent_session_id: Optional[str] = None
    native_agent_run_id: Optional[str] = None
    native_agent_server_key: Optional[str] = None
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
    _lock: threading.RLock = field(default_factory=threading.RLock)
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
            self.native_agent_run_id = None
            self.native_agent_server_key = None
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
            self.native_agent_session_id = None
            self.native_agent_run_id = None
            self.native_agent_server_key = None
            self.claude_session_initialized = False
            self.active_conversation_id = None
        self.persist()
        logger.info(f"已清除会话ID: bot={self.bot_id}, user={self.user_id}")
