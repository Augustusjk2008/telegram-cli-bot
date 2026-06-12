from __future__ import annotations

import os
import re
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bot.platform.executables import build_executable_invocation, resolve_cli_executable
from bot.platform.processes import build_hidden_process_kwargs
from bot.runtime_paths import TCB_DATA_DIR_ENV, get_app_data_root, normalize_workspace_dir
from bot.native_agent.config_store import get_pi_settings_path


PREFLIGHT_COMMAND_TIMEOUT_SECONDS = 15

ResolveExecutable = Callable[[str, str | None], str | None]
RunCommand = Callable[[list[str]], tuple[int, str, str]]
WritableCheck = Callable[[Path], bool]


@dataclass(frozen=True)
class PiWindowsPreflightRequest:
    cwd: Path
    pi_command: str = "pi"
    data_dir: Path | None = None
    workspace_history_enabled: bool | None = True
    settings_path: Path | None = None


def run_pi_windows_preflight(
    request: PiWindowsPreflightRequest,
    *,
    os_name: str | None = None,
    resolve_executable: ResolveExecutable = resolve_cli_executable,
    run_command: RunCommand | None = None,
    is_dir_writable: WritableCheck | None = None,
) -> dict[str, object]:
    platform_name = os_name or os.name
    cwd = Path(request.cwd or ".").expanduser().resolve()
    data_dir = Path(request.data_dir).expanduser() if request.data_dir is not None else get_app_data_root()
    settings_path = Path(request.settings_path).expanduser() if request.settings_path is not None else get_pi_settings_path()
    runner = run_command or _run_command
    writable = is_dir_writable or _is_dir_writable

    checks: list[dict[str, object]] = []
    checks.append(_check_cwd(cwd))
    checks.append(_check_node(resolve_executable, runner, str(cwd)))
    checks.append(_check_pi(request.pi_command, resolve_executable, runner, str(cwd)))
    if platform_name == "nt":
        checks.append(_check_bash(settings_path, resolve_executable, runner, str(cwd)))
    checks.append(_check_data_dir(data_dir, writable))
    tcb_data_dir_warning = _check_tcb_data_dir(cwd, data_dir)
    if tcb_data_dir_warning is not None:
        checks.append(tcb_data_dir_warning)
    checks.append(_check_workspace_history(request.workspace_history_enabled))
    error_checks = [item for item in checks if item.get("severity") == "error" and not item.get("ok")]
    warning_checks = [item for item in checks if item.get("severity") == "warning" and not item.get("ok")]
    ok = not error_checks
    message = _summary_message(error_checks, warning_checks)
    return {
        "ok": ok,
        "code": "ok" if ok else "pi_preflight_failed",
        "message": message,
        "platform": platform_name,
        "checks": checks,
    }


def _check_cwd(cwd: Path) -> dict[str, object]:
    try:
        resolved = cwd.expanduser().resolve()
    except OSError as exc:
        return _fail("cwd", f"工作目录不可访问: {exc}", "确认 Bot 工作目录存在且当前用户可访问")
    if not resolved.exists() or not resolved.is_dir():
        return _fail("cwd", f"工作目录不可访问: {resolved}", "确认 Bot 工作目录存在且当前用户可访问", path=str(resolved))
    try:
        normalized = normalize_workspace_dir(resolved)
    except OSError:
        normalized = str(resolved)
    return _ok("cwd", f"工作目录可访问: {normalized}", path=normalized)


def _check_node(resolve_executable: ResolveExecutable, run_command: RunCommand, cwd: str) -> dict[str, object]:
    node = resolve_executable("node", cwd)
    if not node:
        return _fail("node", "未找到 Node.js 22+", "安装 Node.js 22+，并确认 node 已加入 PATH")
    try:
        returncode, stdout, stderr = run_command([*build_executable_invocation(node), "--version"])
    except Exception as exc:
        return _fail("node", f"Node.js 版本检查失败: {_safe_error(exc)}", "确认 node --version 可正常执行")
    version_text = (stdout or stderr or "").strip()
    major = _node_major_version(version_text)
    if returncode != 0 or major is None:
        return _fail("node", f"无法读取 Node.js 版本: {version_text or '无输出'}", "确认 node --version 可正常执行")
    if major < 22:
        return _fail("node", f"Node.js 版本过低，当前版本 {version_text}，需要 >=22", "升级到 Node.js 22 或更高版本")
    return _ok("node", f"Node.js 版本可用: {version_text}", path=node, version=version_text)


def _check_pi(pi_command: str, resolve_executable: ResolveExecutable, run_command: RunCommand, cwd: str) -> dict[str, object]:
    command = str(pi_command or "pi").strip() or "pi"
    pi_path = resolve_executable(command, cwd)
    if not pi_path:
        return _fail(
            "pi",
            f"未找到 {command}",
            "安装 Pi CLI，或把 NATIVE_AGENT_PI_COMMAND 配成可执行文件绝对路径",
            command=command,
        )
    try:
        returncode, stdout, stderr = run_command([*build_executable_invocation(pi_path), "--version"])
    except Exception as exc:
        return _fail("pi", f"Pi CLI 版本检查失败: {_safe_error(exc)}", "确认 pi --version 可正常执行；必要时设置 NATIVE_AGENT_PI_COMMAND", path=pi_path, command=command)
    version_text = (stdout or stderr or "").strip()
    if returncode != 0:
        return _fail("pi", f"Pi CLI 版本检查失败: {version_text or f'退出码 {returncode}'}", "确认 pi --version 可正常执行；必要时设置 NATIVE_AGENT_PI_COMMAND", path=pi_path, command=command)
    return _ok("pi", f"Pi CLI 可用: {version_text or pi_path}", path=pi_path, command=command, version=version_text)


def _check_bash(settings_path: Path, resolve_executable: ResolveExecutable, run_command: RunCommand, cwd: str) -> dict[str, object]:
    configured = _read_shell_path(settings_path)
    if configured:
        bash = resolve_executable(configured, cwd)
        if not bash:
            return _fail("bash", f"shellPath 不可用: {configured}", "安装 Git for Windows，或在 ~/.pi/agent/settings.json 设置 shellPath", command=configured)
    else:
        bash = resolve_executable("bash", cwd)
        if not bash:
            for candidate in _common_windows_bash_paths():
                if candidate.is_file():
                    bash = str(candidate)
                    break
    if not bash:
        return _fail("bash", "未找到 bash", "安装 Git for Windows，或在 ~/.pi/agent/settings.json 设置 shellPath")
    try:
        returncode, stdout, stderr = run_command([*build_executable_invocation(bash), "--version"])
    except Exception as exc:
        return _fail("bash", f"bash 版本检查失败: {_safe_error(exc)}", "安装 Git for Windows，或在 ~/.pi/agent/settings.json 设置 shellPath", path=bash)
    version_text = (stdout or stderr or "").splitlines()[0].strip() if (stdout or stderr) else ""
    if returncode != 0:
        return _fail("bash", f"bash 版本检查失败: {version_text or f'退出码 {returncode}'}", "安装 Git for Windows，或在 ~/.pi/agent/settings.json 设置 shellPath", path=bash)
    return _ok("bash", f"bash 可用: {version_text or bash}", path=bash, version=version_text)


def _check_data_dir(data_dir: Path, is_dir_writable: WritableCheck) -> dict[str, object]:
    path = data_dir.expanduser().resolve()
    if not is_dir_writable(path):
        return _fail("data_dir", f"数据目录不可写: {path}", "检查目录权限，或设置 TCB_DATA_DIR 到可写目录", path=str(path))
    return _ok("data_dir", f"数据目录可写: {path}", path=str(path))


def _check_tcb_data_dir(cwd: Path, data_dir: Path) -> dict[str, object] | None:
    if not _has_tcb_data_dir_override():
        return None
    try:
        normalized_cwd = normalize_workspace_dir(cwd)
        normalized_data_dir = normalize_workspace_dir(data_dir)
    except OSError:
        return None
    if normalized_data_dir == normalized_cwd or normalized_data_dir.startswith(normalized_cwd + os.sep):
        return _warn(
            "tcb_data_dir",
            "TCB_DATA_DIR 位于当前工作区内，workspace rollback 可能影响运行状态",
            "建议把 TCB_DATA_DIR 移到工作区外",
            path=str(data_dir),
        )
    return None


def _check_workspace_history(enabled: bool | None) -> dict[str, object]:
    if enabled is None:
        return _warn(
            "workspace_history",
            "workspace history 状态无法判定",
            "检查 Pi agent 设置中的 workspace_history_enabled",
        )
    if enabled:
        return _ok(
            "workspace_history",
            "workspace history 已启用，插件和锁文件改在运行时校验",
        )
    return _ok("workspace_history", "workspace history 已关闭")


def _node_major_version(text: str) -> int | None:
    match = re.search(r"v?(\d+)(?:\.|$)", str(text or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _run_command(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PREFLIGHT_COMMAND_TIMEOUT_SECONDS,
        check=False,
        **build_hidden_process_kwargs(),
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _is_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path, delete=True) as handle:
            handle.write("ok")
            handle.flush()
        return True
    except OSError:
        return False


def _ok(key: str, message: str, **extra: object) -> dict[str, object]:
    return {"key": key, "ok": True, "severity": "info", "message": message, "fix": "", **extra}


def _fail(key: str, message: str, fix: str, **extra: object) -> dict[str, object]:
    return {"key": key, "ok": False, "severity": "error", "message": message, "fix": fix, **extra}


def _warn(key: str, message: str, fix: str, **extra: object) -> dict[str, object]:
    return {"key": key, "ok": False, "severity": "warning", "message": message, "fix": fix, **extra}


def _summary_message(error_checks: list[dict[str, object]], warning_checks: list[dict[str, object]]) -> str:
    if error_checks:
        return f"Pi 运行前置检查失败：{error_checks[0].get('message') or '存在失败项'}"
    if warning_checks:
        return f"Pi 运行前置检查通过，存在警告：{warning_checks[0].get('message') or '需关注'}"
    return "Pi 运行前置检查通过"


def _read_shell_path(settings_path: Path) -> str:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("shellPath") or payload.get("shell_path") or "").strip()


def _common_windows_bash_paths() -> list[Path]:
    return [
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
    ]


def _has_tcb_data_dir_override() -> bool:
    override = os.environ.get(TCB_DATA_DIR_ENV, "").strip()
    return bool(override)


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "命令执行超时"
    return str(exc) or type(exc).__name__
