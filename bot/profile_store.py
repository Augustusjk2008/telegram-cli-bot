"""Profile persistence helpers for MultiBotManager."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from bot import app_settings
from bot.cli import validate_cli_type
from bot.cli_params import CliParamsConfig
from bot.cluster.config import normalize_bot_cluster_config
from bot.config import CLI_PATH, CLI_TYPE, RESERVED_ALIASES, WORKING_DIR
from bot.models import AgentProfile, BotProfile, normalize_execution_mode_config, normalize_prompt_presets

logger = logging.getLogger(__name__)


def load_managed_profiles(
    storage_file: Path,
    *,
    bootstrap_assistant_home: Callable[[str], None],
) -> dict[str, BotProfile]:
    if not storage_file.exists():
        return {}

    try:
        raw = storage_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        logger.error("读取托管 Bot 配置失败: %s", exc)
        return {}

    items = data.get("bots", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        logger.warning("托管 Bot 配置格式无效，已忽略")
        return {}

    profiles: dict[str, BotProfile] = {}
    for item in items:
        if not isinstance(item, dict):
            continue

        alias = str(item.get("alias", "")).strip().lower()
        token = str(item.get("token", "")).strip()
        if not alias or alias in RESERVED_ALIASES:
            continue

        raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
        try:
            cli_type = validate_cli_type(raw_cli_type)
        except ValueError:
            logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
            cli_type = CLI_TYPE

        bot_mode = str(item.get("bot_mode", "cli")).strip().lower() or "cli"

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
        }
        if "cli_params" in item:
            profile_data["cli_params"] = item["cli_params"]
        if "agents" in item:
            profile_data["agents"] = item["agents"]
        if "cluster" in item:
            profile_data["cluster"] = item["cluster"]
        if "prompt_presets" in item or "promptPresets" in item:
            profile_data["prompt_presets"] = item.get("prompt_presets", item.get("promptPresets"))
        if "supported_execution_modes" in item or "supportedExecutionModes" in item:
            profile_data["supported_execution_modes"] = item.get(
                "supported_execution_modes",
                item.get("supportedExecutionModes"),
            )
        if "default_execution_mode" in item or "defaultExecutionMode" in item:
            profile_data["default_execution_mode"] = item.get(
                "default_execution_mode",
                item.get("defaultExecutionMode"),
            )
        if "native_agent" in item or "nativeAgent" in item:
            profile_data["native_agent"] = item.get("native_agent", item.get("nativeAgent"))
        profiles[alias] = BotProfile.from_dict(profile_data)

    assistant_aliases = [alias for alias, profile in profiles.items() if profile.bot_mode == "assistant"]
    if len(assistant_aliases) > 1:
        raise ValueError("配置中只允许一个 assistant 型 Bot")
    if len(assistant_aliases) == 1:
        bootstrap_assistant_home(profiles[assistant_aliases[0]].working_dir)

    return profiles


def save_managed_profiles(storage_file: Path, profiles: dict[str, BotProfile]) -> None:
    payload = {"bots": [profiles[key].to_dict() for key in sorted(profiles.keys())]}
    storage_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_persisted_main_profile(main_profile: BotProfile, app_settings_file: Path) -> None:
    profile_data = app_settings.get_main_bot_profile(app_settings_file)
    if not profile_data:
        return

    raw_cli_type = str(profile_data.get("cli_type") or "").strip()
    if raw_cli_type:
        try:
            main_profile.cli_type = validate_cli_type(raw_cli_type)
        except ValueError:
            logger.warning("主 Bot 持久化 cli_type 无效(%s)，已忽略", raw_cli_type)

    cli_path = str(profile_data.get("cli_path") or "").strip()
    if cli_path:
        main_profile.cli_path = cli_path

    working_dir = str(profile_data.get("working_dir") or "").strip()
    if working_dir:
        main_profile.working_dir = os.path.abspath(os.path.expanduser(working_dir))

    bot_mode = str(profile_data.get("bot_mode") or "").strip().lower()
    if bot_mode in {"cli", "assistant"}:
        main_profile.bot_mode = bot_mode

    cli_params = profile_data.get("cli_params")
    if isinstance(cli_params, dict):
        main_profile.cli_params = CliParamsConfig.from_dict(cli_params)

    agents = profile_data.get("agents")
    if isinstance(agents, list):
        main_profile.agents = [AgentProfile.from_dict(item) for item in agents if isinstance(item, dict)]

    cluster = profile_data.get("cluster")
    if isinstance(cluster, dict):
        main_profile.cluster = normalize_bot_cluster_config(cluster)

    if "prompt_presets" in profile_data:
        main_profile.prompt_presets = normalize_prompt_presets(profile_data.get("prompt_presets"))

    if any(key in profile_data for key in ("supported_execution_modes", "supportedExecutionModes", "default_execution_mode", "defaultExecutionMode")):
        supported_execution_modes, default_execution_mode = normalize_execution_mode_config(
            profile_data.get("supported_execution_modes", profile_data.get("supportedExecutionModes")),
            profile_data.get("default_execution_mode", profile_data.get("defaultExecutionMode")),
            bot_mode=main_profile.bot_mode,
        )
        main_profile.supported_execution_modes = supported_execution_modes
        main_profile.default_execution_mode = default_execution_mode

    if any(key in profile_data for key in ("native_agent", "nativeAgent")):
        from bot.models import normalize_native_agent_config

        main_profile.native_agent = normalize_native_agent_config(
            profile_data.get("native_agent", profile_data.get("nativeAgent"))
        )


def persist_main_profile(main_profile: BotProfile, app_settings_file: Path) -> None:
    app_settings.update_main_bot_profile(main_profile.to_dict(), app_settings_file)
