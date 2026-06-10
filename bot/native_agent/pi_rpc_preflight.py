from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bot.platform.executables import build_executable_invocation, resolve_cli_executable
from bot.runtime_paths import get_app_data_root


ResolveExecutable = Callable[[str, str | None], str | None]
RunCommand = Callable[[list[str]], tuple[int, str, str]]
WritableCheck = Callable[[Path], bool]


@dataclass(frozen=True)
class PiWindowsPreflightRequest:
    cwd: Path
    pi_command: str = "pi"
    data_dir: Path | None = None
    workspace_history_enabled: bool | None = True


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
    runner = run_command or _run_command
    writable = is_dir_writable or _is_dir_writable

    checks: list[dict[str, object]] = []
    checks.append(_check_node(resolve_executable, runner, str(cwd)))
    checks.append(_check_pi(request.pi_command, resolve_executable, str(cwd)))
    if platform_name == "nt":
        checks.append(_check_bash(resolve_executable, str(cwd)))
    checks.append(_check_data_dir(data_dir, writable))
    checks.append(_check_workspace_history(request.workspace_history_enabled))
    return {
        "ok": all(bool(item.get("ok")) for item in checks),
        "platform": platform_name,
        "checks": checks,
    }


def _check_node(resolve_executable: ResolveExecutable, run_command: RunCommand, cwd: str) -> dict[str, object]:
    node = resolve_executable("node", cwd)
    if not node:
        return _fail("node", "未找到 node，请先安装 Node.js 22 或更高版本", "安装 Node.js 22+，并确认 node 已加入 PATH")
    try:
        returncode, stdout, stderr = run_command([*build_executable_invocation(node), "--version"])
    except Exception as exc:
        return _fail("node", f"node 版本检查失败: {exc}", "确认 node --version 可正常执行")
    version_text = (stdout or stderr or "").strip()
    major = _node_major_version(version_text)
    if returncode != 0 or major is None:
        return _fail("node", f"无法读取 node 版本: {version_text or '无输出'}", "确认 node --version 可正常执行")
    if major < 22:
        return _fail("node", f"Node.js 版本过低，当前版本 {version_text}，需要 >=22", "升级到 Node.js 22 或更高版本")
    return _ok("node", f"Node.js 版本可用: {version_text}", path=node, version=version_text)


def _check_pi(pi_command: str, resolve_executable: ResolveExecutable, cwd: str) -> dict[str, object]:
    command = str(pi_command or "pi").strip() or "pi"
    pi_path = resolve_executable(command, cwd)
    if not pi_path:
        return _fail(
            "pi",
            f"未找到 {command}",
            "安装 Pi CLI，或把 NATIVE_AGENT_PI_COMMAND 配成可执行文件绝对路径",
            command=command,
        )
    return _ok("pi", f"Pi CLI 可用: {pi_path}", path=pi_path, command=command)


def _check_bash(resolve_executable: ResolveExecutable, cwd: str) -> dict[str, object]:
    bash = resolve_executable("bash", cwd)
    if not bash:
        return _fail("bash", "未找到 bash，Windows 需 Git Bash 或兼容 bash", "安装 Git for Windows，并确认 bash 已加入 PATH")
    return _ok("bash", f"bash 可用: {bash}", path=bash)


def _check_data_dir(data_dir: Path, is_dir_writable: WritableCheck) -> dict[str, object]:
    path = data_dir.expanduser()
    if not is_dir_writable(path):
        return _fail("data_dir", f"数据目录不可写: {path}", "检查目录权限，或设置 TCB_DATA_DIR 到可写目录", path=str(path))
    return _ok("data_dir", f"数据目录可写: {path}", path=str(path))


def _check_workspace_history(enabled: bool | None) -> dict[str, object]:
    if enabled is None:
        return _fail(
            "workspace_history",
            "workspace history 状态无法判定",
            "检查 Pi agent 设置中的 workspace_history_enabled",
        )
    if enabled:
        return _ok("workspace_history", "workspace history 已开启")
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
        timeout=5,
        check=False,
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
    return {"key": key, "ok": True, "message": message, "fix": "", **extra}


def _fail(key: str, message: str, fix: str, **extra: object) -> dict[str, object]:
    return {"key": key, "ok": False, "message": message, "fix": fix, **extra}
