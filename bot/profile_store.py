"""Profile persistence helpers for MultiBotManager."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from bot import app_settings
from bot.cli import validate_cli_type
from bot.cli_params import CliParamsConfig
from bot.cluster.config import normalize_bot_cluster_config
from bot.config import CLI_TYPE, RESERVED_ALIASES, WORKING_DIR, default_cli_path
from bot.models import (
    AgentProfile,
    BotProfile,
    bot_profile_flags,
    normalize_execution_mode_config,
    normalize_prompt_presets,
)

logger = logging.getLogger(__name__)


def _managed_entries(storage_file: Path, *, warn_invalid: bool = False) -> list[tuple[str, dict, bool]]:
    try:
        raw = storage_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    data = json.loads(raw)
    items = data.get("bots", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("托管 Bot 配置格式无效")

    entries = []
    for item in items:
        if not isinstance(item, dict):
            continue
        alias = str(item.get("alias", "")).strip().lower()
        try:
            item["enabled"], item["archived"] = bot_profile_flags(item)
        except ValueError as exc:
            if warn_invalid:
                logger.warning("%s，已跳过这条配置", exc)
            entries.append((alias, item, False))
        else:
            entries.append((alias, item, True))
    return entries


def _working_dir(item: dict) -> str:
    return os.path.abspath(os.path.expanduser(str(item.get("working_dir", WORKING_DIR)).strip() or WORKING_DIR))


def stored_managed_workspaces(storage_file: Path) -> dict[str, str]:
    return {
        alias: _working_dir(item)
        for alias, item, _ in _managed_entries(storage_file)
        if alias and alias not in RESERVED_ALIASES
    }


def managed_rename_target_taken(storage_file: Path, source: str, target: str) -> bool:
    entries = _managed_entries(storage_file)
    source_present = any(alias == source for alias, _, _ in entries)
    # A final replace can succeed before the caller receives its acknowledgement.
    return any(
        alias == target
        and (source_present or not valid or item["archived"] or item.get("last_renamed_from") != source)
        for alias, item, valid in entries
    )


def load_managed_profiles(storage_file: Path, *, archived: bool = False) -> dict[str, BotProfile]:
    try:
        entries = _managed_entries(storage_file, warn_invalid=True)
    except Exception as exc:
        logger.error("读取托管 Bot 配置失败: %s", exc)
        if archived:
            raise
        return {}

    profiles: dict[str, BotProfile] = {}
    for alias, item, valid in entries:
        if not valid or item["archived"] != archived:
            continue
        if not alias or alias in RESERVED_ALIASES:
            continue

        raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
        try:
            cli_type = validate_cli_type(raw_cli_type)
        except ValueError:
            logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
            cli_type = CLI_TYPE

        profile_data = {
            "alias": alias,
            "cli_type": cli_type,
            "cli_path": str(item.get("cli_path") or "").strip() or default_cli_path(cli_type),
            "working_dir": _working_dir(item),
            "enabled": item["enabled"],
            "archived": archived,
            "chat_translation_enabled": item.get("chat_translation_enabled", True),
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
        if "remote_workspace" in item:
            profile_data["remote_workspace"] = item["remote_workspace"]
        profile = BotProfile.from_dict(profile_data)
        profile.pending_rename_to = str(item.get("pending_rename_to") or "").strip().lower()
        profile.pending_rename_skip_legacy = item.get("pending_rename_skip_legacy") is True
        profile.last_renamed_from = str(item.get("last_renamed_from") or "").strip().lower()
        profiles[alias] = profile

    return profiles


def save_managed_profiles(
    storage_file: Path, profiles: dict[str, BotProfile], *, removed_alias: str = "",
) -> None:
    entries = _managed_entries(storage_file)
    invalid_aliases = {alias for alias, _, valid in entries if not valid}
    # An unloaded record may have been repaired on disk since startup.
    saved = [
        (alias, item)
        for alias, item, _ in entries
        if (alias in invalid_aliases or alias not in profiles)
        and (not removed_alias or alias != removed_alias)
    ]
    for alias, profile in profiles.items():
        if alias in invalid_aliases:
            continue
        item = profile.to_dict()
        item["enabled"], item["archived"] = bot_profile_flags(item)
        if profile.pending_rename_to:
            item["pending_rename_to"] = profile.pending_rename_to
            if profile.pending_rename_skip_legacy:
                item["pending_rename_skip_legacy"] = True
        if profile.last_renamed_from:
            item["last_renamed_from"] = profile.last_renamed_from
        saved.append((alias, item))
    payload = {"bots": [item for _, item in sorted(saved, key=lambda entry: entry[0])]}
    temporary = storage_file.with_suffix(storage_file.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(storage_file)
        if os.name != "nt":
            directory = os.open(storage_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def apply_persisted_main_profile(main_profile: BotProfile, app_settings_file: Path) -> None:
    profile_data = app_settings.get_main_bot_profile(app_settings_file)
    if not profile_data:
        return

    main_profile.chat_translation_enabled = profile_data.get("chat_translation_enabled", True) is not False

    raw_cli_type = str(profile_data.get("cli_type") or "").strip()
    if raw_cli_type:
        try:
            main_profile.cli_type = validate_cli_type(raw_cli_type)
            if not str(profile_data.get("cli_path") or "").strip():
                main_profile.cli_path = default_cli_path(main_profile.cli_type)
        except ValueError:
            logger.warning("主 Bot 持久化 cli_type 无效(%s)，已忽略", raw_cli_type)

    cli_path = str(profile_data.get("cli_path") or "").strip()
    if cli_path:
        main_profile.cli_path = cli_path

    working_dir = str(profile_data.get("working_dir") or "").strip()
    if working_dir:
        main_profile.working_dir = os.path.abspath(os.path.expanduser(working_dir))

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
        )
        main_profile.supported_execution_modes = supported_execution_modes
        main_profile.default_execution_mode = default_execution_mode

    if profile_data.get("remote_workspace"):
        from bot.remote_workspace.transport import normalize_remote_workspace
        main_profile.remote_workspace = normalize_remote_workspace(profile_data["remote_workspace"])


def persist_main_profile(main_profile: BotProfile, app_settings_file: Path) -> None:
    app_settings.update_main_bot_profile(main_profile.to_dict(), app_settings_file)
