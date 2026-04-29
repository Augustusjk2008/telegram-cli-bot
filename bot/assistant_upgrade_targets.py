from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from bot.manager import MultiBotManager
from bot.models import BotProfile


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _profiles(manager: MultiBotManager) -> list[BotProfile]:
    items = [manager.main_profile]
    items.extend(manager.managed_profiles[key] for key in sorted(manager.managed_profiles.keys()))
    seen: set[str] = set()
    unique: list[BotProfile] = []
    for profile in items:
        alias = str(profile.alias or "").strip().lower()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        unique.append(profile)
    return unique


def list_upgrade_targets(manager: MultiBotManager) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for profile in _profiles(manager):
        working_dir = Path(str(profile.working_dir or "")).expanduser()
        item = {
            "alias": str(profile.alias or "").strip().lower(),
            "working_dir": str(working_dir),
            "repo_root": "",
            "head": "",
            "dirty": False,
            "bot_mode": str(profile.bot_mode or "cli"),
            "cli_type": str(profile.cli_type or ""),
            "cli_path": str(profile.cli_path or ""),
            "available": False,
            "reason": "",
        }
        if not working_dir.exists():
            item["reason"] = "working_dir_not_found"
            items.append(item)
            continue
        root = _run_git(working_dir, ["rev-parse", "--show-toplevel"])
        if root.returncode != 0:
            item["reason"] = "upgrade_target_not_git_repo"
            items.append(item)
            continue
        repo_root = Path(root.stdout.strip()).resolve()
        head = _run_git(repo_root, ["rev-parse", "HEAD"])
        if head.returncode != 0:
            item["repo_root"] = str(repo_root)
            item["reason"] = "upgrade_target_no_head"
            items.append(item)
            continue
        status = _run_git(repo_root, ["status", "--porcelain"])
        item.update(
            {
                "repo_root": str(repo_root),
                "head": head.stdout.strip(),
                "dirty": bool(status.stdout.strip()),
                "available": True,
                "reason": "",
            }
        )
        items.append(item)
    return items


def resolve_upgrade_target(manager: MultiBotManager, target_alias: str) -> dict[str, Any]:
    normalized = str(target_alias or "").strip().lower()
    for item in list_upgrade_targets(manager):
        if item["alias"] == normalized:
            return item
    raise KeyError(normalized)
