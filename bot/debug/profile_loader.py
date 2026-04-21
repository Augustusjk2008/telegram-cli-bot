from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import DebugProfile

_TARGET_CONFIG_NAME = "(gdb) Remote Debug"
_WORKSPACE_TOKEN = "${workspaceFolder}"
_DEFAULT_PREPARE_COMMAND = r".\debug.bat"
_JSON_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_JSON_TRAILING_COMMA_RE = re.compile(r",(?=\s*[}\]])")
_PS_STRING_DEFAULT_RE = re.compile(
    r"""\[(?:string)\]\s*\$(\w+)\s*=\s*(["'])(.*?)\2""",
    re.IGNORECASE | re.DOTALL,
)
_PS_INT_DEFAULT_RE = re.compile(
    r"""\[(?:int|int32|long)\]\s*\$(\w+)\s*=\s*(-?\d+)""",
    re.IGNORECASE,
)


class DebugProfileLoadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _strip_jsonc(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        kept: list[str] = []
        in_string = False
        escaped = False
        index = 0
        while index < len(line):
            char = line[index]
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if in_string:
                kept.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                kept.append(char)
                index += 1
                continue
            if char == "/" and next_char == "/":
                break
            kept.append(char)
            index += 1
        cleaned_lines.append("".join(kept))
    cleaned = "\n".join(cleaned_lines)
    cleaned = _JSON_BLOCK_COMMENT_RE.sub("", cleaned)
    cleaned = _JSON_TRAILING_COMMA_RE.sub("", cleaned)
    return cleaned


def _load_jsonc(path: Path) -> dict[str, Any]:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8-sig")))


def _expand_workspace_path(value: str, workspace: Path) -> str:
    candidate = value.replace(_WORKSPACE_TOKEN, str(workspace)).strip()
    if not candidate:
        return ""
    return str(Path(candidate))


def _parse_debug_defaults(path: Path) -> dict[str, str]:
    defaults = {
        "RemoteHost": "192.168.1.29",
        "RemoteUser": "root",
        "RemoteDir": "/home/sast8/tmp",
        "RemoteGdbPort": "1234",
    }
    text = path.read_text(encoding="utf-8-sig")
    for key, _, value in _PS_STRING_DEFAULT_RE.findall(text):
        defaults[key] = value
    for key, value in _PS_INT_DEFAULT_RE.findall(text):
        defaults[key] = value
    return defaults


def _extract_setup_commands(config: dict[str, Any]) -> tuple[list[str], list[bool]]:
    commands: list[str] = []
    ignore_failures: list[bool] = []
    for item in config.get("setupCommands", []):
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                commands.append(text)
                ignore_failures.append(bool(item.get("ignoreFailures", False)))
            continue
        text = str(item or "").strip()
        if text:
            commands.append(text)
            ignore_failures.append(False)
    return commands, ignore_failures


def _extract_compile_commands(cpp_json: dict[str, Any], workspace: Path) -> str | None:
    configurations = cpp_json.get("configurations", [])
    if not isinstance(configurations, list):
        return None
    for config in configurations:
        if not isinstance(config, dict):
            continue
        raw_value = config.get("compileCommands")
        if isinstance(raw_value, str) and raw_value.strip():
            return _expand_workspace_path(raw_value.strip(), workspace)
        if isinstance(raw_value, list):
            for item in raw_value:
                if isinstance(item, str) and item.strip():
                    return _expand_workspace_path(item.strip(), workspace)
    return None


def _resolve_remote_server(
    value: str,
    *,
    default_host: str,
    default_port: int,
) -> tuple[str, int]:
    candidate = str(value or "").strip()
    if not candidate:
        return default_host, default_port
    if ":" not in candidate:
        return candidate, default_port
    host_part, port_part = candidate.rsplit(":", 1)
    try:
        port = int(port_part)
    except ValueError:
        port = default_port
    return host_part or default_host, port


def _find_launch_config(launch_json: dict[str, Any]) -> dict[str, Any]:
    configurations = launch_json.get("configurations", [])
    if not isinstance(configurations, list):
        raise DebugProfileLoadError("launch_config_missing", "launch.json 缺少 configurations")
    for item in configurations:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == _TARGET_CONFIG_NAME:
            return item
    raise DebugProfileLoadError("launch_config_missing", f"缺少 {_TARGET_CONFIG_NAME} 配置")


def _require_file(path: Path, code: str, message: str) -> None:
    if not path.is_file():
        raise DebugProfileLoadError(code, message)


def require_debug_profile(workspace: str | Path) -> DebugProfile:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise DebugProfileLoadError("workspace_not_supported", "当前工作目录不支持调试")

    debug_script_path = root / "debug.ps1"
    launch_path = root / ".vscode" / "launch.json"
    cpp_props_path = root / ".vscode" / "c_cpp_properties.json"

    _require_file(debug_script_path, "debug_script_missing", "缺少 debug.ps1")
    _require_file(launch_path, "launch_json_missing", "缺少 .vscode/launch.json")

    launch_json = _load_jsonc(launch_path)
    config = _find_launch_config(launch_json)
    defaults = _parse_debug_defaults(debug_script_path)
    default_port = int(defaults.get("RemoteGdbPort", "1234"))
    remote_host, remote_port = _resolve_remote_server(
        str(config.get("miDebuggerServerAddress") or "").strip(),
        default_host=str(defaults.get("RemoteHost") or "192.168.1.29"),
        default_port=default_port,
    )

    program = str(config.get("program") or "").strip()
    mi_debugger_path = str(config.get("miDebuggerPath") or "").strip()
    if not program or not mi_debugger_path:
        raise DebugProfileLoadError("launch_config_missing", "调试配置缺少 program 或 miDebuggerPath")

    compile_commands = None
    if cpp_props_path.is_file():
        compile_commands = _extract_compile_commands(_load_jsonc(cpp_props_path), root)

    setup_commands, setup_command_ignore_failures = _extract_setup_commands(config)

    return DebugProfile(
        kind="mbddf_remote_gdb",
        workspace=str(root),
        config_name=_TARGET_CONFIG_NAME,
        program=_expand_workspace_path(program, root),
        cwd=_expand_workspace_path(str(config.get("cwd") or _WORKSPACE_TOKEN), root),
        mi_mode=str(config.get("MIMode") or "gdb"),
        mi_debugger_path=mi_debugger_path,
        compile_commands=compile_commands,
        prepare_command=_DEFAULT_PREPARE_COMMAND,
        stop_at_entry=bool(config.get("stopAtEntry", False)),
        setup_commands=setup_commands,
        setup_command_ignore_failures=setup_command_ignore_failures,
        remote_host=remote_host,
        remote_user=str(defaults.get("RemoteUser") or "root"),
        remote_dir=str(defaults.get("RemoteDir") or "/home/sast8/tmp"),
        remote_port=remote_port,
    )


def load_debug_profile(workspace: str | Path) -> DebugProfile | None:
    try:
        return require_debug_profile(workspace)
    except DebugProfileLoadError:
        return None
