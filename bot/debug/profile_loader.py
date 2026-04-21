from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import (
    DebugCapabilities,
    DebugGdb,
    DebugGdbSetupCommand,
    DebugPrepare,
    DebugProfile,
    DebugProfileV2,
    DebugRemote,
    DebugSourceMap,
    DebugTarget,
)

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


def _coerce_setup_commands(items: object) -> tuple[list[str], list[bool], list[DebugGdbSetupCommand]]:
    commands: list[str] = []
    ignore_failures: list[bool] = []
    structured: list[DebugGdbSetupCommand] = []
    source_items = items if isinstance(items, list) else []
    for item in source_items:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("command") or "").strip()
            ignore = bool(item.get("ignoreFailures", item.get("ignore_failures", False)))
        else:
            text = str(item or "").strip()
            ignore = False
        if not text:
            continue
        commands.append(text)
        ignore_failures.append(ignore)
        structured.append(DebugGdbSetupCommand(text=text, ignore_failures=ignore))
    return commands, ignore_failures, structured


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


def _first_string(*values: object, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _coerce_int(value: object, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _coerce_float(value: object, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _expand_source_map_value(value: str, workspace: Path) -> str:
    candidate = str(value or "").replace(_WORKSPACE_TOKEN, str(workspace)).strip()
    if not candidate:
        return ""
    return str(Path(candidate)) if _WORKSPACE_TOKEN in value or candidate.startswith(".") else candidate


def _source_maps_from_config(items: object, workspace: Path) -> list[DebugSourceMap]:
    maps: list[DebugSourceMap] = []
    source_items = items if isinstance(items, list) else []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        remote = str(item.get("remote") or "").strip()
        local = _expand_source_map_value(str(item.get("local") or ""), workspace)
        if remote and local:
            maps.append(DebugSourceMap(remote=remote, local=local))
    return maps


def _capabilities_from_config(data: object) -> DebugCapabilities:
    raw = data if isinstance(data, dict) else {}
    return DebugCapabilities(
        threads=bool(raw.get("threads", False)),
        variables=bool(raw.get("variables", True)),
        evaluate=bool(raw.get("evaluate", True)),
        memory=bool(raw.get("memory", False)),
        registers=bool(raw.get("registers", False)),
        disassembly=bool(raw.get("disassembly", False)),
        function_breakpoints=bool(raw.get("functionBreakpoints", raw.get("function_breakpoints", True))),
        conditional_breakpoints=bool(raw.get("conditionalBreakpoints", raw.get("conditional_breakpoints", True))),
        logpoints=bool(raw.get("logpoints", True)),
    )


def _debug_config_candidates(root: Path) -> list[Path]:
    return [
        root / "debug.json",
        root / ".vscode" / "debug.json",
        root / ".vscode" / "launch.json",
    ]


def _find_v2_config(data: dict[str, Any]) -> dict[str, Any] | None:
    base = {key: value for key, value in data.items() if key != "configurations"}
    if int(data.get("spec_version") or data.get("specVersion") or 0) == 2 and "configurations" not in data:
        return data
    configurations = data.get("configurations")
    if isinstance(configurations, list):
        for item in configurations:
            if not isinstance(item, dict):
                continue
            if int(item.get("spec_version") or item.get("specVersion") or data.get("spec_version") or data.get("specVersion") or 0) == 2:
                return {**base, **item}
        if int(data.get("spec_version") or data.get("specVersion") or 0) == 2:
            for item in configurations:
                if isinstance(item, dict):
                    return {**base, **item}
    if int(data.get("spec_version") or data.get("specVersion") or 0) == 2:
        return data
    return None


def _load_v2_config(root: Path) -> dict[str, Any] | None:
    for path in _debug_config_candidates(root):
        if not path.is_file():
            continue
        data = _load_jsonc(path)
        config = _find_v2_config(data)
        if config is not None:
            return config
    return None


def _profile_from_v2_config(root: Path, config: dict[str, Any]) -> DebugProfileV2:
    target_raw = config.get("target") if isinstance(config.get("target"), dict) else {}
    prepare_raw = config.get("prepare") if isinstance(config.get("prepare"), dict) else {}
    remote_raw = config.get("remote") if isinstance(config.get("remote"), dict) else {}
    gdb_raw = config.get("gdb") if isinstance(config.get("gdb"), dict) else {}
    ui_raw = config.get("ui") if isinstance(config.get("ui"), dict) else {}

    program = _expand_workspace_path(_first_string(target_raw.get("program"), config.get("program")), root)
    cwd = _expand_workspace_path(_first_string(target_raw.get("cwd"), config.get("cwd"), default=_WORKSPACE_TOKEN), root)
    gdb_path = _first_string(gdb_raw.get("path"), config.get("miDebuggerPath"))
    if not program or not gdb_path:
        raise DebugProfileLoadError("launch_config_missing", "调试配置缺少 program 或 miDebuggerPath")

    setup_commands, setup_ignore, structured_setup = _coerce_setup_commands(
        gdb_raw.get("setup_commands", gdb_raw.get("setupCommands", config.get("setupCommands", [])))
    )
    remote_port = _coerce_int(remote_raw.get("port", config.get("remotePort")), 1234)
    target = DebugTarget(
        type=_first_string(target_raw.get("type"), default="remote-gdbserver"),
        architecture=_first_string(target_raw.get("architecture"), default="aarch64"),
        program=program,
        cwd=cwd,
        args=[str(item) for item in target_raw.get("args", [])] if isinstance(target_raw.get("args"), list) else [],
        env={str(key): str(value) for key, value in target_raw.get("env", {}).items()} if isinstance(target_raw.get("env"), dict) else {},
    )
    prepare = DebugPrepare(
        command=_first_string(prepare_raw.get("command"), config.get("prepareCommand"), default=_DEFAULT_PREPARE_COMMAND),
        timeout_seconds=_coerce_float(
            prepare_raw.get("timeout_seconds", prepare_raw.get("timeoutSeconds", config.get("prepareTimeoutSeconds"))),
            300,
        ),
        problem_matchers=[
            str(item)
            for item in prepare_raw.get("problem_matchers", prepare_raw.get("problemMatchers", []))
        ] if isinstance(prepare_raw.get("problem_matchers", prepare_raw.get("problemMatchers", [])), list) else [],
    )
    remote = DebugRemote(
        host=_first_string(remote_raw.get("host"), config.get("remoteHost"), default="192.168.1.29"),
        user=_first_string(remote_raw.get("user"), config.get("remoteUser"), default="root"),
        dir=_first_string(remote_raw.get("dir"), config.get("remoteDir"), default="/home/sast8/tmp"),
        gdbserver=_first_string(remote_raw.get("gdbserver"), default="/home/sast8/tmp/gdbserver"),
        port=remote_port,
    )
    gdb = DebugGdb(
        path=gdb_path,
        sysroot=_first_string(gdb_raw.get("sysroot"), default=""),
        setup_commands=structured_setup,
    )
    source_maps = _source_maps_from_config(config.get("source_maps", config.get("sourceMaps", [])), root)
    compile_commands = _first_string(config.get("compileCommands"), config.get("compile_commands"), default="")
    compile_commands = _expand_workspace_path(compile_commands, root) if compile_commands else None
    stop_at_entry = bool(ui_raw.get("stop_at_entry", ui_raw.get("stopAtEntry", config.get("stopAtEntry", True))))
    default_panels_raw = ui_raw.get("default_panels", ui_raw.get("defaultPanels", ["source", "stack", "variables", "console"]))

    return DebugProfileV2(
        kind="cpp_remote_gdb",
        workspace=str(root),
        config_name=_first_string(config.get("name"), default="C++ Remote Debug"),
        program=program,
        cwd=cwd,
        mi_mode=_first_string(config.get("MIMode"), default="gdb"),
        mi_debugger_path=gdb_path,
        compile_commands=compile_commands,
        prepare_command=prepare.command,
        stop_at_entry=stop_at_entry,
        setup_commands=setup_commands,
        setup_command_ignore_failures=setup_ignore,
        remote_host=remote.host,
        remote_user=remote.user,
        remote_dir=remote.dir,
        remote_port=remote.port,
        spec_version=2,
        language=_first_string(config.get("language"), default="cpp"),
        target=target,
        prepare=prepare,
        remote=remote,
        gdb=gdb,
        source_maps=source_maps,
        capabilities=_capabilities_from_config(config.get("capabilities", {})),
        open_source_on_pause=bool(ui_raw.get("open_source_on_pause", ui_raw.get("openSourceOnPause", True))),
        default_panels=[str(item) for item in default_panels_raw] if isinstance(default_panels_raw, list) else ["source", "stack", "variables", "console"],
    )


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


def _require_v1_debug_profile(root: Path) -> DebugProfileV2:
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

    source_maps = [DebugSourceMap(remote=str(defaults.get("RemoteDir") or "/home/sast8/tmp"), local=str(root))]
    return DebugProfileV2(
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
        spec_version=2,
        language="cpp",
        source_maps=source_maps,
    )


def require_debug_profile_v2(workspace: str | Path) -> DebugProfileV2:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise DebugProfileLoadError("workspace_not_supported", "当前工作目录不支持 C++ 调试")
    v2_config = _load_v2_config(root)
    if v2_config is not None:
        return _profile_from_v2_config(root, v2_config)
    return _require_v1_debug_profile(root)


def require_debug_profile(workspace: str | Path) -> DebugProfile:
    return require_debug_profile_v2(workspace)


def load_debug_profile_v2(workspace: str | Path) -> DebugProfileV2 | None:
    try:
        return require_debug_profile_v2(workspace)
    except DebugProfileLoadError:
        return None


def load_debug_profile(workspace: str | Path) -> DebugProfile | None:
    return load_debug_profile_v2(workspace)
