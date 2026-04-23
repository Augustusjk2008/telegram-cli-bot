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
from bot.assistant_cron import AssistantCronService
from bot.assistant_docs import sync_managed_prompt_files
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_runtime import AssistantRunRequest, AssistantRuntimeCoordinator
from bot.cli import resolve_cli_executable, validate_cli_type
from bot.cli_params import coerce_param_value
from bot.config import BOT_ALIAS_RE, CLI_PATH, CLI_TYPE, RESERVED_ALIASES, WORKING_DIR
from bot.models import BotProfile
from bot.plugins.service import PluginService
from bot.platform.paths import truncate_path_for_display
from bot.sessions import clear_bot_sessions, is_bot_processing, update_bot_alias, update_bot_working_dir

logger = logging.getLogger(__name__)
REMOVED_LEGACY_CLI_TYPES = {"ki" "mi"}


class MultiBotManager:
    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.main_profile = main_profile
        self.storage_file = Path(storage_file)
        self.repo_root = self.storage_file.resolve().parent
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
        self._apply_persisted_avatar_names()

    @staticmethod
    def _bootstrap_and_sync_assistant_home(working_dir: str) -> None:
        home = bootstrap_assistant_home(working_dir)
        sync_managed_prompt_files(home)

    def _load_profiles(self) -> None:
        self.managed_profiles = {}
        if not self.storage_file.exists():
            return

        try:
            raw = self.storage_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            logger.error("读取托管 Bot 配置失败: %s", exc)
            return

        items = data.get("bots", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            logger.warning("托管 Bot 配置格式无效，已忽略")
            return

        migrated_legacy_mode = False
        for item in items:
            if not isinstance(item, dict):
                continue

            alias = str(item.get("alias", "")).strip().lower()
            token = str(item.get("token", "")).strip()
            if not alias or alias in RESERVED_ALIASES:
                continue

            raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
            if raw_cli_type.lower() in REMOVED_LEGACY_CLI_TYPES:
                raise ValueError(f"子Bot `{alias}` 使用了已移除的 legacy cli_type: {raw_cli_type}")
            try:
                cli_type = validate_cli_type(raw_cli_type)
            except ValueError:
                logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
                cli_type = CLI_TYPE

            bot_mode = str(item.get("bot_mode", "cli")).strip().lower() or "cli"
            if bot_mode == "webcli":
                logger.warning("子Bot `%s` 的 webcli 模式已弃用，自动回退为 cli", alias)
                bot_mode = "cli"
                migrated_legacy_mode = True

            profile_data = {
                "alias": alias,
                "token": token,
                "cli_type": cli_type,
                "cli_path": str(item.get("cli_path", CLI_PATH)).strip() or CLI_PATH,
                "working_dir": os.path.abspath(
                    os.path.expanduser(str(item.get("working_dir", WORKING_DIR)).strip() or WORKING_DIR)
                ),
                "enabled": bool(item.get("enabled", True)),
                "bot_mode": bot_mode,
                "avatar_name": str(item.get("avatar_name", "") or ""),
            }
            if "cli_params" in item:
                profile_data["cli_params"] = item["cli_params"]
            self.managed_profiles[alias] = BotProfile.from_dict(profile_data)

        assistant_aliases = [
            alias for alias, profile in self.managed_profiles.items() if profile.bot_mode == "assistant"
        ]
        if len(assistant_aliases) > 1:
            raise ValueError("配置中只允许一个 assistant 型 Bot")
        if len(assistant_aliases) == 1:
            self._bootstrap_and_sync_assistant_home(self.managed_profiles[assistant_aliases[0]].working_dir)

        if migrated_legacy_mode:
            self._save_profiles()

    def _save_profiles(self) -> None:
        payload = {
            "bots": [self.managed_profiles[key].to_dict() for key in sorted(self.managed_profiles.keys())]
        }
        self.storage_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _apply_persisted_avatar_names(self) -> None:
        main_avatar_name = app_settings.get_bot_avatar_name(self.main_profile.alias)
        if main_avatar_name:
            self.main_profile.avatar_name = main_avatar_name

        for alias, profile in self.managed_profiles.items():
            avatar_name = app_settings.get_bot_avatar_name(alias)
            if avatar_name:
                profile.avatar_name = avatar_name

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

    def assistant_alias(self) -> str | None:
        if self.main_profile.bot_mode == "assistant":
            return self.main_profile.alias
        for alias, profile in self.managed_profiles.items():
            if profile.bot_mode == "assistant":
                return alias
        return None

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
        await self._ensure_assistant_services()

    async def start_watchdog(self) -> None:
        self._watchdog_task = None

    async def stop_watchdog(self) -> None:
        self._watchdog_task = None

    async def stop_background_services(self) -> None:
        if self.assistant_cron_service is not None:
            stop = getattr(self.assistant_cron_service, "stop", None)
            if callable(stop):
                await stop()
            self.assistant_cron_service = None
        if self.assistant_runtime is not None:
            await self.assistant_runtime.stop()
            self.assistant_runtime = None

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
    ) -> BotProfile:
        normalized_alias = str(alias or "").strip().lower()
        normalized_token = str(token or "").strip()
        self._validate_alias(normalized_alias)

        resolved_cli_type = validate_cli_type(cli_type or CLI_TYPE)
        resolved_cli_path = str(cli_path or CLI_PATH).strip()
        resolved_bot_mode = str(bot_mode or "cli").strip().lower()

        if resolved_bot_mode == "webcli":
            raise ValueError("webcli 模式已弃用，请使用 'cli' 或 'assistant'")
        if resolved_bot_mode not in {"cli", "assistant"}:
            raise ValueError(f"bot_mode 必须是 'cli' 或 'assistant'，当前值: {resolved_bot_mode}")

        if resolved_bot_mode == "assistant":
            if working_dir is None or not str(working_dir).strip():
                raise ValueError("assistant 型 Bot 必须显式提供工作目录")
            resolved_working_dir = os.path.abspath(os.path.expanduser(str(working_dir).strip()))
        else:
            resolved_working_dir = os.path.abspath(os.path.expanduser((working_dir or WORKING_DIR).strip()))

        if not os.path.isdir(resolved_working_dir):
            raise ValueError(f"工作目录不存在: {resolved_working_dir}")
        if resolve_cli_executable(resolved_cli_path, resolved_working_dir) is None:
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
            )

            if resolved_bot_mode == "assistant":
                self._bootstrap_and_sync_assistant_home(resolved_working_dir)

            self.managed_profiles[normalized_alias] = profile
            app_settings.update_bot_avatar_name(normalized_alias, profile.avatar_name)
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
            app_settings.update_bot_avatar_name(normalized_alias, normalized_avatar_name)
            if normalized_alias != self.main_profile.alias:
                self._save_profiles()

    async def remove_bot(self, alias: str) -> None:
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias == self.main_profile.alias:
            raise ValueError(f"无法移除主 Bot `{normalized_alias}`")

        async with self._lock:
            if normalized_alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{normalized_alias}`")
            await self._stop_application(normalized_alias)
            del self.managed_profiles[normalized_alias]
            app_settings.remove_bot_avatar_name(normalized_alias)
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
            app_settings.rename_bot_avatar_name(normalized_alias, normalized_new_alias)
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
            self._save_profiles()

    async def reset_bot_cli_params(self, alias: str, cli_type: Optional[str] = None) -> None:
        normalized_alias = str(alias or "").strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(normalized_alias)
            profile.cli_params.reset_to_default(cli_type)
            self._save_profiles()

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
