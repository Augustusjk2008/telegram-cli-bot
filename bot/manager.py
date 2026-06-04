"""多 Bot 生命周期管理器（Web-only）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot import app_settings
from bot.assistant.cron.service import AssistantCronService
from bot.assistant.docs import sync_managed_prompt_files
from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.runtime import AssistantRunRequest, AssistantRuntimeCoordinator
from bot.cli import resolve_cli_executable, validate_cli_type
from bot.cli_params import CliParamsConfig, coerce_param_value
from bot.cluster.config import normalize_agent_cluster_config, normalize_bot_cluster_config
from bot.config import BOT_ALIAS_RE, CLI_PATH, CLI_TYPE, NATIVE_AGENT_ENABLED, RESERVED_ALIASES, WORKING_DIR, _DOTENV_VALUES
from bot.agents import normalize_agent_id, normalize_agent_name, normalize_agent_prompt, now_iso
from bot.models import (
    AgentProfile,
    BotProfile,
    EXECUTION_MODE_NATIVE_AGENT,
    GitCommitMessageCliConfig,
    normalize_execution_mode,
    normalize_execution_mode_config,
    normalize_execution_modes,
    normalize_native_agent_config,
    normalize_prompt_presets,
)
from bot.native_agent.server_manager import SERVER_MANAGER as NATIVE_AGENT_SERVER_MANAGER
from bot.plugins.service import PluginService
from bot.platform.paths import truncate_path_for_display
from bot.profile_store import (
    apply_persisted_avatar_names,
    apply_persisted_main_profile,
    load_managed_profiles,
    persist_main_profile,
    save_managed_profiles,
)
from bot.sessions import clear_bot_sessions, is_bot_processing, terminate_bot_processes, update_bot_alias, update_bot_working_dir

logger = logging.getLogger(__name__)
REMOVED_LEGACY_CLI_TYPES: set[str] = set()


class MultiBotManager:
    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.main_profile = main_profile
        self.storage_file = Path(storage_file)
        self.repo_root = self.storage_file.resolve().parent
        self.app_settings_file = app_settings.APP_SETTINGS_FILE
        self.git_commit_cli_config_file = self.repo_root / ".git_commit_cli_config.json"
        self._git_commit_cli_config: GitCommitMessageCliConfig | None = None
        self.plugin_service = PluginService(
            self.repo_root,
            workspace_root_for=lambda alias: Path(
                (self.main_profile if alias == self.main_profile.alias else self.managed_profiles.get(alias) or self.main_profile).working_dir
            ),
        )
        self.managed_profiles: Dict[str, BotProfile] = {}
        # Web-only 运行时保留该字段做兼容，不再持有 Telegram Application。
        self.applications: Dict[str, object] = {}
        self.bot_id_to_alias: Dict[int, str] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.assistant_runtime: AssistantRuntimeCoordinator | None = None
        self.assistant_cron_service: Any | None = None
        self._assistant_result_executor: Callable[[AssistantRunRequest], Awaitable[dict[str, Any]]] | None = None
        self._assistant_stream_executor: Callable[[AssistantRunRequest], AsyncIterator[dict[str, Any]]] | None = None

        self._load_profiles()
        self._apply_persisted_main_profile()
        self._apply_persisted_avatar_names()
        self._apply_persisted_git_commit_cli_configs()

    @staticmethod
    def _bootstrap_and_sync_assistant_home(working_dir: str) -> None:
        home = bootstrap_assistant_home(working_dir)
        sync_managed_prompt_files(home)

    def _load_profiles(self) -> None:
        self.managed_profiles, migrated_legacy_mode = load_managed_profiles(
            self.storage_file,
            removed_legacy_cli_types=REMOVED_LEGACY_CLI_TYPES,
            bootstrap_assistant_home=self._bootstrap_and_sync_assistant_home,
        )
        if migrated_legacy_mode:
            self._save_profiles()

    def _save_profiles(self) -> None:
        save_managed_profiles(self.storage_file, self.managed_profiles)

    def _apply_persisted_avatar_names(self) -> None:
        apply_persisted_avatar_names(self.main_profile, self.managed_profiles, self.app_settings_file)

    def _apply_persisted_main_profile(self) -> None:
        apply_persisted_main_profile(self.main_profile, self.app_settings_file)

    def _persist_main_profile(self) -> None:
        persist_main_profile(self.main_profile, self.app_settings_file)

    def _load_git_commit_cli_config_store(self) -> GitCommitMessageCliConfig | None:
        try:
            raw = self.git_commit_cli_config_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("读取 Git commit CLI 配置失败: %s", exc)
            return None
        if not isinstance(data, dict):
            return None

        candidates: list[tuple[str, dict[str, Any]]] = []
        global_data = data.get("global")
        if isinstance(global_data, dict):
            candidates.append(("global", global_data))

        legacy_items = data.get("bots")
        if isinstance(legacy_items, dict):
            main_data = legacy_items.get(self.main_profile.alias)
            if isinstance(main_data, dict):
                candidates.append((self.main_profile.alias, main_data))
            for alias, value in sorted(legacy_items.items()):
                normalized_alias = str(alias or "").strip().lower()
                if normalized_alias == self.main_profile.alias:
                    continue
                if isinstance(value, dict):
                    candidates.append((normalized_alias, value))

        for label, value in candidates:
            try:
                return GitCommitMessageCliConfig.from_dict(value)
            except Exception as exc:
                logger.warning("加载 Git commit CLI 配置失败 scope=%s error=%s", label, exc)
        return None

    def _save_git_commit_cli_config_store(self, config: GitCommitMessageCliConfig | None) -> None:
        if config is None:
            try:
                self.git_commit_cli_config_file.unlink()
            except FileNotFoundError:
                pass
            return
        payload = {"global": config.to_dict()}
        self.git_commit_cli_config_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _apply_persisted_git_commit_cli_configs(self) -> None:
        self._git_commit_cli_config = self._load_git_commit_cli_config_store()

    def _persist_git_commit_cli_config(self, config: GitCommitMessageCliConfig | None) -> None:
        self._save_git_commit_cli_config_store(config)

    def get_profile(self, alias: str) -> BotProfile:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            return self.main_profile
        if normalized_alias not in self.managed_profiles:
            raise KeyError(f"未知的 bot alias: `{normalized_alias}`")
        return self.managed_profiles[normalized_alias]

    def _get_profile_for_update(self, alias: str) -> BotProfile:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            return self.main_profile
        if normalized_alias not in self.managed_profiles:
            raise ValueError(f"不存在 alias `{normalized_alias}`")
        return self.managed_profiles[normalized_alias]

    def _validate_alias(self, alias: str) -> None:
        if not BOT_ALIAS_RE.fullmatch(alias):
            raise ValueError("alias 仅允许字母/数字/_/-，长度 2-32")
        if alias in RESERVED_ALIASES:
            raise ValueError(f"alias `{alias}` 为保留名称")

    def _count_assistant_profiles(self) -> int:
        return sum(1 for profile in self.managed_profiles.values() if profile.bot_mode == "assistant")

    def _default_cli_path_for_type(self, cli_type: str) -> str:
        normalized_cli_type = validate_cli_type(cli_type or CLI_TYPE)
        env_cli_path = str(os.environ.get("CLI_PATH") or _DOTENV_VALUES.get("CLI_PATH") or "").strip()
        env_cli_type = validate_cli_type(os.environ.get("CLI_TYPE") or _DOTENV_VALUES.get("CLI_TYPE") or CLI_TYPE)
        if env_cli_type == normalized_cli_type and env_cli_path:
            return env_cli_path

        profiles = [self.main_profile, *[self.managed_profiles[alias] for alias in sorted(self.managed_profiles.keys())]]
        default_cli_path = normalized_cli_type
        for profile in profiles:
            profile_cli_path = str(profile.cli_path or "").strip()
            if profile.cli_type == normalized_cli_type and profile_cli_path and profile_cli_path != default_cli_path:
                return profile_cli_path
        for profile in profiles:
            profile_cli_path = str(profile.cli_path or "").strip()
            if profile.cli_type == normalized_cli_type and profile_cli_path:
                return profile_cli_path

        return normalized_cli_type

    def assistant_alias(self) -> str | None:
        if self.main_profile.bot_mode == "assistant":
            return self.main_profile.alias
        for alias, profile in self.managed_profiles.items():
            if profile.bot_mode == "assistant":
                return alias
        return None

    def _agent_to_summary(self, profile: BotProfile, agent: AgentProfile) -> dict[str, Any]:
        return {
            **agent.to_dict(),
            "is_main": agent.id == "main",
        }

    def list_bot_agents(self, alias: str) -> list[dict[str, Any]]:
        profile = self.get_profile(alias)
        return [self._agent_to_summary(profile, agent) for agent in profile.normalized_agents()]

    def _ensure_cli_agent_profile(self, alias: str) -> BotProfile:
        profile = self._get_profile_for_update(alias)
        if profile.bot_mode != "cli":
            raise ValueError("仅 CLI Bot 支持 agent")
        return profile

    def get_git_commit_cli_config(self, alias: str) -> GitCommitMessageCliConfig:
        self.get_profile(alias)
        if self._git_commit_cli_config is not None:
            return GitCommitMessageCliConfig.from_dict(self._git_commit_cli_config.to_dict())
        profile = self.main_profile
        return GitCommitMessageCliConfig(
            cli_type=profile.cli_type,
            cli_path=profile.cli_path,
            cli_params=CliParamsConfig.from_dict(profile.cli_params.to_dict()),
        )

    def _persist_profile_agents(self, profile: BotProfile) -> None:
        if profile.alias == self.main_profile.alias:
            self._persist_main_profile()
        else:
            self._save_profiles()

    async def create_bot_agent(self, alias: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            profile = self._ensure_cli_agent_profile(alias)
            agent_id = normalize_agent_id(data.get("id"), allow_main=False)
            if any(agent.id == agent_id for agent in profile.normalized_agents()):
                raise ValueError("agent id 已存在")
            now = now_iso()
            agent = AgentProfile(
                id=agent_id,
                name=normalize_agent_name(data.get("name")),
                system_prompt=normalize_agent_prompt(data.get("system_prompt")),
                enabled=bool(data.get("enabled", True)),
                created_at=now,
                updated_at=now,
                cluster=normalize_agent_cluster_config(data.get("cluster")),
            )
            profile.agents.append(agent)
            self._persist_profile_agents(profile)
            return self._agent_to_summary(profile, agent)

    async def update_bot_agent(self, alias: str, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            profile = self._ensure_cli_agent_profile(alias)
            normalized_agent_id = normalize_agent_id(agent_id, allow_main=True)
            if normalized_agent_id == "main":
                raise ValueError("主 agent 不支持编辑")
            agent = next((item for item in profile.agents if item.id == normalized_agent_id), None)
            if agent is None:
                raise KeyError(normalized_agent_id)
            if "name" in data:
                agent.name = normalize_agent_name(data.get("name"))
            if "system_prompt" in data or "systemPrompt" in data:
                agent.system_prompt = normalize_agent_prompt(data.get("system_prompt", data.get("systemPrompt")))
            if "enabled" in data:
                agent.enabled = bool(data.get("enabled"))
            if "cluster" in data and isinstance(data.get("cluster"), dict):
                agent.cluster = normalize_agent_cluster_config(data.get("cluster"))
            agent.updated_at = now_iso()
            self._persist_profile_agents(profile)
            return self._agent_to_summary(profile, agent)

    async def update_bot_cluster(self, alias: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            if profile.bot_mode != "cli":
                raise ValueError("仅 CLI Bot 支持集群模式")
            profile.cluster = normalize_bot_cluster_config(data)
            if profile.alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()
            return profile.cluster.to_dict()

    async def delete_bot_agent(self, alias: str, agent_id: str) -> None:
        async with self._lock:
            profile = self._ensure_cli_agent_profile(alias)
            normalized_agent_id = normalize_agent_id(agent_id, allow_main=True)
            if normalized_agent_id == "main":
                raise ValueError("主 agent 不能删除")
            before = len(profile.agents)
            profile.agents = [item for item in profile.agents if item.id != normalized_agent_id]
            if len(profile.agents) == before:
                raise KeyError(normalized_agent_id)
            self._persist_profile_agents(profile)

    async def replace_bot_cluster_bundle(
        self,
        alias: str,
        cluster: dict[str, Any],
        agents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._lock:
            profile = self._ensure_cli_agent_profile(alias)
            profile.cluster = normalize_bot_cluster_config(cluster)
            now = now_iso()
            replaced_agents: list[AgentProfile] = []
            for item in agents:
                normalized_id = normalize_agent_id(item.get("id"), allow_main=False)
                replaced_agents.append(
                    AgentProfile(
                        id=normalized_id,
                        name=normalize_agent_name(item.get("name")),
                        system_prompt=normalize_agent_prompt(item.get("system_prompt", item.get("systemPrompt"))),
                        enabled=bool(item.get("enabled", True)),
                        created_at=str(item.get("created_at") or now),
                        updated_at=str(item.get("updated_at") or now),
                        cluster=normalize_agent_cluster_config(item.get("cluster")),
                    )
                )
            profile.agents = replaced_agents
            self._persist_profile_agents(profile)
            return {
                "cluster": profile.cluster.to_dict(),
                "agents": [self._agent_to_summary(profile, agent) for agent in profile.normalized_agents() if agent.id != "main"],
            }

    async def _ensure_assistant_runtime(self) -> None:
        if self._assistant_result_executor is None:
            return
        if self.assistant_alias() is None:
            if self.assistant_runtime is not None:
                await self.assistant_runtime.stop()
                self.assistant_runtime = None
            return
        if self.assistant_runtime is not None:
            return
        self.assistant_runtime = AssistantRuntimeCoordinator(
            result_executor=self._assistant_result_executor,
            stream_executor=self._assistant_stream_executor,
        )
        await self.assistant_runtime.start()

    async def _ensure_assistant_cron_service(self) -> None:
        assistant_alias = self.assistant_alias()
        if assistant_alias is None or self.assistant_runtime is None:
            if self.assistant_cron_service is not None:
                await self.assistant_cron_service.stop()
                self.assistant_cron_service = None
            return

        profile = self.get_profile(assistant_alias)
        assistant_home = bootstrap_assistant_home(profile.working_dir)
        current_service = self.assistant_cron_service
        if (
            current_service is not None
            and current_service.bot_alias == assistant_alias
            and current_service.assistant_home.root == assistant_home.root
            and current_service.coordinator is self.assistant_runtime
        ):
            return

        if current_service is not None:
            await current_service.stop()

        self.assistant_cron_service = AssistantCronService(
            assistant_home=assistant_home,
            bot_alias=assistant_alias,
            coordinator=self.assistant_runtime,
        )
        await self.assistant_cron_service.start()

    async def _ensure_assistant_services(self) -> None:
        await self._ensure_assistant_runtime()
        await self._ensure_assistant_cron_service()

    async def _start_profile(self, profile: BotProfile, is_main: bool = False) -> object | None:
        existing = self.applications.get(profile.alias)
        if existing is not None:
            return existing
        logger.info("Web-only 模式不再启动独立聊天运行时 alias=%s is_main=%s", profile.alias, is_main)
        return None

    async def _stop_application(self, alias: str) -> None:
        app = self.applications.pop(alias, None)
        bot_id = None
        if app is not None:
            bot_data = getattr(app, "bot_data", None)
            if isinstance(bot_data, dict):
                value = bot_data.get("bot_id")
                if isinstance(value, int):
                    bot_id = value

        if isinstance(bot_id, int):
            self.bot_id_to_alias.pop(bot_id, None)
            clear_bot_sessions(bot_id)

    async def start_all(self) -> None:
        return None

    async def start_background_services(
        self,
        *,
        result_executor: Callable[[AssistantRunRequest], Awaitable[dict[str, Any]]],
        stream_executor: Callable[[AssistantRunRequest], AsyncIterator[dict[str, Any]]] | None = None,
    ) -> None:
        self._assistant_result_executor = result_executor
        self._assistant_stream_executor = stream_executor
        if NATIVE_AGENT_ENABLED:
            await NATIVE_AGENT_SERVER_MANAGER.ensure_started()
        await self._ensure_assistant_services()

    async def start_watchdog(self) -> None:
        self._watchdog_task = None

    async def stop_watchdog(self) -> None:
        self._watchdog_task = None

    async def stop_background_services(self) -> None:
        try:
            assistant_alias = self.assistant_alias()
            wait_for_watch_tasks = self.assistant_runtime is not None
            if assistant_alias is not None:
                terminate_bot_processes(assistant_alias)
            if self.assistant_runtime is not None:
                await self.assistant_runtime.stop()
                self.assistant_runtime = None
            if self.assistant_cron_service is not None:
                stop = getattr(self.assistant_cron_service, "stop", None)
                if callable(stop):
                    if isinstance(self.assistant_cron_service, AssistantCronService):
                        await stop(cancel_watch_tasks=not wait_for_watch_tasks)
                    else:
                        await stop()
                self.assistant_cron_service = None
        finally:
            await NATIVE_AGENT_SERVER_MANAGER.stop_all()

    async def shutdown_all(self) -> None:
        await self.stop_background_services()
        await self.stop_watchdog()
        for alias in list(self.applications.keys()):
            await self._stop_application(alias)
        self.bot_id_to_alias.clear()

    async def add_bot(
        self,
        alias: str,
        token: str = "",
        cli_type: Optional[str] = None,
        cli_path: Optional[str] = None,
        working_dir: Optional[str] = None,
        bot_mode: Optional[str] = None,
        avatar_name: Optional[str] = None,
        supported_execution_modes: Any = None,
        default_execution_mode: Any = None,
        native_agent: Any = None,
    ) -> BotProfile:
        normalized_alias = str(alias or "").strip().lower()
        normalized_token = str(token or "").strip()
        self._validate_alias(normalized_alias)

        resolved_cli_type = validate_cli_type(cli_type or CLI_TYPE)
        resolved_cli_path = str(cli_path or "").strip() or self._default_cli_path_for_type(resolved_cli_type)
        resolved_bot_mode = str(bot_mode or "cli").strip().lower()

        if resolved_bot_mode == "webcli":
            raise ValueError("webcli 模式已弃用，请使用 'cli' 或 'assistant'")
        if resolved_bot_mode not in {"cli", "assistant"}:
            raise ValueError(f"bot_mode 必须是 'cli' 或 'assistant'，当前值: {resolved_bot_mode}")
        requested_supported_execution_modes = normalize_execution_modes(supported_execution_modes)
        requested_default_execution_mode = normalize_execution_mode(
            default_execution_mode,
            default=requested_supported_execution_modes[0],
        )
        if resolved_bot_mode != "cli" and (
            EXECUTION_MODE_NATIVE_AGENT in requested_supported_execution_modes
            or requested_default_execution_mode == EXECUTION_MODE_NATIVE_AGENT
        ):
            raise ValueError("仅 CLI Bot 支持原生 agent")
        resolved_supported_execution_modes, resolved_default_execution_mode = normalize_execution_mode_config(
            requested_supported_execution_modes,
            default_execution_mode,
            bot_mode=resolved_bot_mode,
        )
        resolved_native_agent = normalize_native_agent_config(native_agent)

        if resolved_bot_mode == "assistant":
            if working_dir is None or not str(working_dir).strip():
                raise ValueError("assistant 型 Bot 必须显式提供工作目录")
            resolved_working_dir = os.path.abspath(os.path.expanduser(str(working_dir).strip()))
        else:
            resolved_working_dir = os.path.abspath(os.path.expanduser((working_dir or WORKING_DIR).strip()))

        if not os.path.isdir(resolved_working_dir):
            raise ValueError(f"工作目录不存在: {resolved_working_dir}")
        if (
            resolved_default_execution_mode != EXECUTION_MODE_NATIVE_AGENT
            and resolve_cli_executable(resolved_cli_path, resolved_working_dir) is None
        ):
            raise ValueError(
                f"未找到 CLI 可执行文件: {resolved_cli_path} "
                f"(请在设置页填写可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
            )

        async with self._lock:
            if normalized_alias in self.managed_profiles:
                raise ValueError(f"alias `{normalized_alias}` 已存在")
            if resolved_bot_mode == "assistant" and self._count_assistant_profiles() >= 1:
                raise ValueError("当前机器只允许一个 assistant 型 Bot")

            profile = BotProfile(
                alias=normalized_alias,
                token=normalized_token,
                cli_type=resolved_cli_type,
                cli_path=resolved_cli_path,
                working_dir=resolved_working_dir,
                enabled=True,
                bot_mode=resolved_bot_mode,
                avatar_name=str(avatar_name or "").strip(),
                supported_execution_modes=resolved_supported_execution_modes,
                default_execution_mode=resolved_default_execution_mode,
                native_agent=resolved_native_agent,
            )

            if resolved_bot_mode == "assistant":
                self._bootstrap_and_sync_assistant_home(resolved_working_dir)

            self.managed_profiles[normalized_alias] = profile
            app_settings.update_bot_avatar_name(normalized_alias, profile.avatar_name, self.app_settings_file)
            self._save_profiles()
            await self._start_profile(profile, is_main=False)
            await self._ensure_assistant_services()
            return profile

    async def set_bot_avatar(self, alias: str, avatar_name: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        normalized_avatar_name = str(avatar_name or "").strip()

        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            profile.avatar_name = normalized_avatar_name
            app_settings.update_bot_avatar_name(normalized_alias, normalized_avatar_name, self.app_settings_file)
            if normalized_alias != self.main_profile.alias:
                self._save_profiles()

    async def set_bot_prompt_presets(self, alias: str, presets: Any) -> list[dict[str, str]]:
        normalized_alias = str(alias or "").strip().lower()
        normalized_presets = normalize_prompt_presets(presets, strict=True)

        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            profile.prompt_presets = normalized_presets
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()
            return [dict(item) for item in normalized_presets]

    async def remove_bot(self, alias: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            raise ValueError(f"无法移除主 Bot `{normalized_alias}`")

        async with self._lock:
            if normalized_alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{normalized_alias}`")
            await self._stop_application(normalized_alias)
            del self.managed_profiles[normalized_alias]
            app_settings.remove_bot_avatar_name(normalized_alias, self.app_settings_file)
            self._save_profiles()
            await self._ensure_assistant_services()

    async def start_bot(self, alias: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{normalized_alias}` 已在运行，无需启动")

        async with self._lock:
            if normalized_alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{normalized_alias}`")
            profile = self.managed_profiles[normalized_alias]
            profile.enabled = True
            self._save_profiles()
            await self._start_profile(profile, is_main=False)

    async def stop_bot(self, alias: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{normalized_alias}` 无法通过此接口停止，请使用系统级管理")

        async with self._lock:
            if normalized_alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{normalized_alias}`")
            profile = self.managed_profiles[normalized_alias]
            profile.enabled = False
            self._save_profiles()
            await self._stop_application(normalized_alias)

    async def set_bot_cli(self, alias: str, cli_type: str, cli_path: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        resolved_cli_type = validate_cli_type(cli_type)
        resolved_cli_path = str(cli_path or "").strip()
        if not resolved_cli_path:
            raise ValueError("cli_path 不能为空")

        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            if resolve_cli_executable(resolved_cli_path, profile.working_dir) is None:
                raise ValueError(
                    f"未找到 CLI 可执行文件: {resolved_cli_path} "
                    f"(请在设置页填写可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )
            profile.cli_type = resolved_cli_type
            profile.cli_path = resolved_cli_path
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()

    async def set_bot_execution_config(
        self,
        alias: str,
        data: dict[str, Any],
    ) -> None:
        normalized_alias = str(alias or "").strip().lower()
        requested_supported_execution_modes = normalize_execution_modes(
            data.get("supported_execution_modes", data.get("supportedExecutionModes"))
        )
        requested_default_execution_mode = normalize_execution_mode(
            data.get("default_execution_mode", data.get("defaultExecutionMode")),
            default=requested_supported_execution_modes[0],
        )
        raw_native_agent = data.get("native_agent", data.get("nativeAgent"))

        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            if profile.bot_mode != "cli" and (
                EXECUTION_MODE_NATIVE_AGENT in requested_supported_execution_modes
                or requested_default_execution_mode == EXECUTION_MODE_NATIVE_AGENT
            ):
                raise ValueError("仅 CLI Bot 支持原生 agent")
            supported, default_mode = normalize_execution_mode_config(
                requested_supported_execution_modes,
                requested_default_execution_mode,
                bot_mode=profile.bot_mode,
            )
            native_agent = normalize_native_agent_config(raw_native_agent)
            profile.supported_execution_modes = supported
            profile.default_execution_mode = default_mode
            profile.native_agent = native_agent
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()

    async def rename_bot(self, alias: str, new_alias: str) -> BotProfile:
        normalized_alias = str(alias or "").strip().lower()
        normalized_new_alias = str(new_alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{normalized_alias}` 不支持改名")
        self._validate_alias(normalized_new_alias)

        async with self._lock:
            if normalized_alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{normalized_alias}`")
            if normalized_new_alias == normalized_alias:
                raise ValueError("新旧 alias 不能相同")
            if normalized_new_alias == self.main_profile.alias or normalized_new_alias in self.managed_profiles:
                raise ValueError(f"alias `{normalized_new_alias}` 已存在")

            profile = self.managed_profiles.pop(normalized_alias)
            profile.alias = normalized_new_alias
            self.managed_profiles[normalized_new_alias] = profile

            app = self.applications.pop(normalized_alias, None)
            if app is not None:
                self.applications[normalized_new_alias] = app
                bot_data = getattr(app, "bot_data", None)
                if isinstance(bot_data, dict):
                    bot_data["bot_alias"] = normalized_new_alias
                    bot_id = bot_data.get("bot_id")
                    if isinstance(bot_id, int):
                        self.bot_id_to_alias[bot_id] = normalized_new_alias

            update_bot_alias(normalized_alias, normalized_new_alias)
            app_settings.rename_bot_avatar_name(normalized_alias, normalized_new_alias, self.app_settings_file)
            self._save_profiles()
            await self._ensure_assistant_services()
            return profile

    async def set_bot_workdir(self, alias: str, working_dir: str, *, update_sessions: bool = False) -> None:
        normalized_alias = str(alias or "").strip().lower()
        resolved_working_dir = os.path.abspath(os.path.expanduser(str(working_dir or "").strip()))
        if not os.path.isdir(resolved_working_dir):
            raise ValueError(f"工作目录不存在: {resolved_working_dir}")

        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            if profile.bot_mode == "assistant":
                raise ValueError("assistant 型 Bot 不允许修改默认工作目录")
            profile.working_dir = resolved_working_dir
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()
            if update_sessions:
                update_bot_working_dir(normalized_alias, resolved_working_dir)

    async def get_bot_cli_params(self, alias: str, cli_type: Optional[str] = None) -> dict:
        normalized_alias = str(alias or "").strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            if cli_type:
                return profile.cli_params.get_params(cli_type)
            return profile.cli_params.to_dict()

    async def set_bot_cli_param(self, alias: str, cli_type: str, key: str, value) -> None:
        normalized_alias = str(alias or "").strip().lower()
        normalized_cli_type = str(cli_type or "").strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            coerced_value = coerce_param_value(normalized_cli_type, key, value)
            profile.cli_params.set_param(normalized_cli_type, key, coerced_value)
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()

    async def reset_bot_cli_params(self, alias: str, cli_type: Optional[str] = None) -> None:
        normalized_alias = str(alias or "").strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            profile.cli_params.reset_to_default(cli_type)
            if normalized_alias == self.main_profile.alias:
                self._persist_main_profile()
            else:
                self._save_profiles()

    async def set_git_commit_cli_config(
        self,
        alias: str,
        *,
        cli_type: str | None = None,
        cli_path: str | None = None,
        cli_params: CliParamsConfig | None = None,
    ) -> GitCommitMessageCliConfig:
        normalized_alias = str(alias or "").strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            current = self.get_git_commit_cli_config(normalized_alias)
            next_config = GitCommitMessageCliConfig(
                cli_type=validate_cli_type(cli_type or current.cli_type or profile.cli_type),
                cli_path=str(cli_path if cli_path is not None else current.cli_path or profile.cli_path).strip(),
                cli_params=cli_params or current.cli_params,
            )
            if not next_config.cli_path:
                raise ValueError("cli_path 不能为空")
            if resolve_cli_executable(next_config.cli_path, profile.working_dir) is None:
                raise ValueError(
                    f"未找到 CLI 可执行文件: {next_config.cli_path} "
                    f"(请填写可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )
            self._git_commit_cli_config = next_config
            self._persist_git_commit_cli_config(next_config)
            return GitCommitMessageCliConfig.from_dict(next_config.to_dict())

    async def reset_git_commit_cli_config(self, alias: str) -> GitCommitMessageCliConfig:
        normalized_alias = str(alias or "").strip().lower()
        async with self._lock:
            self._get_profile_for_update(normalized_alias)
            self._git_commit_cli_config = None
            self._persist_git_commit_cli_config(None)
            return self.get_git_commit_cli_config(normalized_alias)

    def get_status_lines(self) -> List[str]:
        lines: List[str] = []
        lines.append("<b>📊 Bot 状态概览</b>\n")

        def status_badge(status: str) -> str:
            badges = {
                "running": "🟢 <code>运行中</code>",
                "working": "🔵 <code>处理中</code>",
                "stopped": "🔴 <code>已停止</code>",
                "enabled": "✅ 已启用",
                "disabled": "⚪ 已禁用",
            }
            return badges.get(status, status)

        main_app = self.applications.get(self.main_profile.alias)
        if main_app is not None:
            bot_data = getattr(main_app, "bot_data", None)
            main_bot_id = bot_data.get("bot_id") if isinstance(bot_data, dict) else None
            main_working = is_bot_processing(main_bot_id) if isinstance(main_bot_id, int) else False
            main_status = "working" if main_working else "running"
            main_username = (bot_data.get("bot_username") if isinstance(bot_data, dict) else "") or "unknown"
        else:
            main_status = "stopped"
            main_username = "unknown"

        lines.append(
            f"<b>👑 主 Bot</b>\n"
            f"  <b>别名:</b> <code>main</code>\n"
            f"  <b>用户名:</b> @{main_username}\n"
            f"  <b>状态:</b> {status_badge(main_status)}\n"
            f"  <b>CLI:</b> <code>{self.main_profile.cli_type}</code>\n"
            f"  <b>工作目录:</b> <code>{truncate_path_for_display(self.main_profile.working_dir, 30)}</code>\n"
        )

        if self.managed_profiles:
            lines.append(f"<b>🤖 托管 Bot</b> (<code>{len(self.managed_profiles)}</code> 个)\n")
            for alias in sorted(self.managed_profiles.keys()):
                profile = self.managed_profiles[alias]
                app = self.applications.get(alias)
                if app is not None:
                    bot_data = getattr(app, "bot_data", None)
                    bot_id = bot_data.get("bot_id") if isinstance(bot_data, dict) else None
                    is_working = is_bot_processing(bot_id) if isinstance(bot_id, int) else False
                    run_status = "working" if is_working else "running"
                    username = (bot_data.get("bot_username") if isinstance(bot_data, dict) else "") or "unknown"
                else:
                    run_status = "stopped"
                    username = "unknown"

                enable_status = "enabled" if profile.enabled else "disabled"
                lines.append(
                    f"  ┌ <b>别名:</b> <code>{alias}</code>\n"
                    f"  ├ <b>用户名:</b> @{username}\n"
                    f"  ├ <b>运行状态:</b> {status_badge(run_status)}\n"
                    f"  ├ <b>启用状态:</b> {status_badge(enable_status)}\n"
                    f"  ├ <b>CLI:</b> <code>{profile.cli_type}</code>\n"
                    f"  └ <b>工作目录:</b> <code>{truncate_path_for_display(profile.working_dir, 28)}</code>\n"
                )
        else:
            lines.append("<i>💤 暂无托管 Bot</i>")

        return lines
