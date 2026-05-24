from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.platform.runtime import get_runtime_platform

TERMINAL_ACTIONS_RELATIVE_PATH = Path("scripts") / "terminal-actions.json"
MAX_TERMINAL_ACTIONS = 50
MAX_COMMAND_LENGTH = 2000
MAX_LABEL_LENGTH = 40
ACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SAFE_TERMINAL_ACTION_ICONS = frozenset(
    {
        "Bolt",
        "Bug",
        "CheckCircle2",
        "Code2",
        "Download",
        "Hammer",
        "Package",
        "Play",
        "RefreshCw",
        "Rocket",
        "Server",
        "Settings",
        "SquareTerminal",
        "Terminal",
        "TestTube2",
        "Trash2",
        "Upload",
        "Wrench",
        "Zap",
    }
)
DEFAULT_TERMINAL_ACTION_ICON = "Terminal"


class TerminalActionValidationError(ValueError):
    pass


class TerminalActionConfigConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TerminalAction:
    id: str
    label: str
    icon: str
    windows_command: str
    linux_command: str
    macos_command: str
    command: str
    cwd: str
    resolved_cwd: str
    confirm: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class TerminalActionsConfig:
    schema_version: int
    actions: tuple[TerminalAction, ...]


@dataclass(frozen=True, slots=True)
class TerminalActionsConfigReadResult:
    config_path: str
    exists: bool
    mtime_ns: str
    config: TerminalActionsConfig
    errors: list[str]


def terminal_actions_config_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve() / TERMINAL_ACTIONS_RELATIVE_PATH


def _resolve_workspace_path(workspace_root: Path, candidate: str) -> Path:
    root = workspace_root.expanduser().resolve()
    raw = Path(str(candidate or "."))
    resolved = raw.expanduser().resolve() if raw.is_absolute() else (root / raw).resolve()
    if resolved != root and root not in resolved.parents:
        raise TerminalActionValidationError(f"路径越界: {candidate}")
    return resolved


def _expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TerminalActionValidationError(f"{label} 必须是对象")
    return value


def _normalize_icon(value: Any) -> str:
    icon = str(value or "").strip() or DEFAULT_TERMINAL_ACTION_ICON
    return icon if icon in SAFE_TERMINAL_ACTION_ICONS else DEFAULT_TERMINAL_ACTION_ICON


def _normalize_command(value: Any, *, label: str, allow_empty: bool) -> str:
    command = str(value or "").strip()
    if not command:
        if allow_empty:
            return ""
        raise TerminalActionValidationError(f"{label} 不能为空")
    if len(command) > MAX_COMMAND_LENGTH:
        raise TerminalActionValidationError(f"{label} 不能超过 {MAX_COMMAND_LENGTH} 字符")
    if "\r" in command or "\n" in command:
        raise TerminalActionValidationError(f"{label} 不能包含换行")
    return command


def _resolve_platform_commands(current: dict[str, Any], index: int) -> tuple[str, str, str]:
    windows_command = _normalize_command(
        current.get("windowsCommand"),
        label=f"actions[{index}].windowsCommand",
        allow_empty=True,
    )
    linux_command = _normalize_command(
        current.get("linuxCommand"),
        label=f"actions[{index}].linuxCommand",
        allow_empty=True,
    )
    macos_command = _normalize_command(
        current.get("macosCommand"),
        label=f"actions[{index}].macosCommand",
        allow_empty=True,
    )

    if not windows_command and not linux_command and not macos_command and current.get("command") is not None:
        legacy_command = _normalize_command(
            current.get("command"),
            label=f"actions[{index}].command",
            allow_empty=False,
        )
        platform = get_runtime_platform()
        if platform == "windows":
            windows_command = legacy_command
        elif platform == "macos":
            macos_command = legacy_command
        else:
            linux_command = legacy_command

    if not windows_command and not linux_command and not macos_command:
        raise TerminalActionValidationError(f"actions[{index}] 的 Windows/Linux/macOS 命令至少填一个")

    return windows_command, linux_command, macos_command


def _select_runtime_command(
    *,
    windows_command: str,
    linux_command: str,
    macos_command: str,
) -> str:
    platform = get_runtime_platform()
    if platform == "windows":
        return windows_command
    if platform == "macos":
        return macos_command or linux_command
    return linux_command


def _parse_action(workspace_root: Path, item: Any, index: int) -> TerminalAction:
    current = _expect_mapping(item, f"actions[{index}]")
    action_id = str(current.get("id") or "").strip()
    if not ACTION_ID_RE.fullmatch(action_id):
        raise TerminalActionValidationError(f"actions[{index}].id 无效")

    label = str(current.get("label") or "").strip()
    if not label or len(label) > MAX_LABEL_LENGTH:
        raise TerminalActionValidationError(f"actions[{index}].label 长度必须为 1-{MAX_LABEL_LENGTH}")

    cwd = str(current.get("cwd") or ".").strip() or "."
    resolved_cwd = _resolve_workspace_path(workspace_root, cwd)
    if not resolved_cwd.exists() or not resolved_cwd.is_dir():
        raise TerminalActionValidationError(f"actions[{index}].cwd 目录不存在: {cwd}")

    windows_command, linux_command, macos_command = _resolve_platform_commands(current, index)
    command = _select_runtime_command(
        windows_command=windows_command,
        linux_command=linux_command,
        macos_command=macos_command,
    )

    return TerminalAction(
        id=action_id,
        label=label,
        icon=_normalize_icon(current.get("icon")),
        windows_command=windows_command,
        linux_command=linux_command,
        macos_command=macos_command,
        command=command,
        cwd=cwd,
        resolved_cwd=str(resolved_cwd),
        confirm=bool(current.get("confirm", False)),
        enabled=bool(current.get("enabled", True)),
    )


def _parse_config(workspace_root: Path, payload: Any) -> TerminalActionsConfig:
    current = _expect_mapping(payload, "terminal-actions.json")
    schema_version = int(current.get("schemaVersion") or 0)
    if schema_version != 1:
        raise TerminalActionValidationError(f"不支持的 schemaVersion: {current.get('schemaVersion')}")

    actions_raw = current.get("actions") or []
    if not isinstance(actions_raw, list):
        raise TerminalActionValidationError("actions 必须是数组")
    if len(actions_raw) > MAX_TERMINAL_ACTIONS:
        raise TerminalActionValidationError(f"actions 不能超过 {MAX_TERMINAL_ACTIONS} 个")

    seen_ids: set[str] = set()
    actions: list[TerminalAction] = []
    for index, item in enumerate(actions_raw):
        action = _parse_action(workspace_root, item, index)
        if action.id in seen_ids:
            raise TerminalActionValidationError(f"重复的 action id: {action.id}")
        seen_ids.add(action.id)
        actions.append(action)

    return TerminalActionsConfig(schema_version=schema_version, actions=tuple(actions))


def load_terminal_actions_config(workspace_root: str | Path) -> TerminalActionsConfigReadResult:
    root = Path(workspace_root).expanduser().resolve()
    path = terminal_actions_config_path(root)
    empty = TerminalActionsConfig(schema_version=1, actions=())
    if not path.exists():
        return TerminalActionsConfigReadResult(str(path), False, "", empty, [])

    exists = True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stat = path.stat()
        return TerminalActionsConfigReadResult(str(path), exists, str(stat.st_mtime_ns), _parse_config(root, payload), [])
    except json.JSONDecodeError as exc:
        return TerminalActionsConfigReadResult(str(path), exists, str(path.stat().st_mtime_ns), empty, [f"无法解析 JSON: {exc.msg}"])
    except (OSError, ValueError, TerminalActionValidationError) as exc:
        mtime_ns = str(path.stat().st_mtime_ns) if path.exists() else ""
        return TerminalActionsConfigReadResult(str(path), path.exists(), mtime_ns, empty, [str(exc)])


def _serialize_action(action: TerminalAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "label": action.label,
        "icon": action.icon,
        "windowsCommand": action.windows_command,
        "linuxCommand": action.linux_command,
        "macosCommand": action.macos_command,
        "cwd": action.cwd,
        "confirm": action.confirm,
        "enabled": action.enabled,
    }


def serialize_terminal_actions_config(result: TerminalActionsConfigReadResult, *, editable: bool) -> dict[str, Any]:
    return {
        "schemaVersion": result.config.schema_version,
        "configPath": result.config_path,
        "exists": result.exists,
        "mtimeNs": result.mtime_ns,
        "editable": editable,
        "errors": list(result.errors),
        "runtimePlatform": get_runtime_platform(),
        "actions": [_serialize_action(action) for action in result.config.actions],
    }


def save_terminal_actions_config(
    workspace_root: str | Path,
    payload: dict[str, Any],
    *,
    expected_mtime_ns: str,
) -> TerminalActionsConfigReadResult:
    root = Path(workspace_root).expanduser().resolve()
    path = terminal_actions_config_path(root)
    if path.exists():
        current_mtime = str(path.stat().st_mtime_ns)
        if expected_mtime_ns and expected_mtime_ns != current_mtime:
            raise TerminalActionConfigConflict("配置文件已被其他进程修改")
    elif expected_mtime_ns:
        raise TerminalActionConfigConflict("配置文件不存在，无法按旧版本保存")

    config = _parse_config(root, payload)
    normalized = {
        "schemaVersion": config.schema_version,
        "actions": [_serialize_action(action) for action in config.actions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_terminal_actions_config(root)


def resolve_terminal_action(workspace_root: str | Path, action_id: str, *, confirmed: bool) -> TerminalAction:
    result = load_terminal_actions_config(workspace_root)
    if result.errors:
        raise TerminalActionValidationError(result.errors[0])

    normalized_id = str(action_id or "").strip()
    for action in result.config.actions:
        if action.id != normalized_id:
            continue
        if not action.enabled:
            raise TerminalActionValidationError(f"快捷命令已禁用: {normalized_id}")
        if not action.command:
            raise TerminalActionValidationError("当前平台未配置命令")
        if action.confirm and not confirmed:
            raise TerminalActionValidationError("快捷命令需要确认")
        return action
    raise KeyError(f"未知快捷命令: {normalized_id}")
