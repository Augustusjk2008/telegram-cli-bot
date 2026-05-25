from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class DesktopOpenError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _runtime_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform or "unknown"


def open_directory_in_desktop(path: str | os.PathLike[str]) -> dict[str, Any]:
    directory = Path(path).expanduser()
    try:
        directory = directory.resolve()
    except OSError as exc:
        raise DesktopOpenError(404, "working_dir_not_found", "工作目录不存在") from exc
    if not directory.exists() or not directory.is_dir():
        raise DesktopOpenError(404, "working_dir_not_found", "工作目录不存在")

    platform_name = _runtime_platform()
    try:
        if platform_name == "windows":
            startfile = getattr(os, "startfile", None)
            if callable(startfile):
                startfile(str(directory))
            else:
                subprocess.Popen(["explorer.exe", str(directory)])
        elif platform_name == "macos":
            subprocess.Popen(["open", str(directory)])
        elif platform_name == "linux":
            if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                raise DesktopOpenError(409, "desktop_open_unavailable", "当前 Linux 环境未检测到桌面显示会话")
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if not opener:
                raise DesktopOpenError(409, "desktop_open_unavailable", "当前系统未找到可用文件夹打开命令")
            argv = [opener, str(directory)] if Path(opener).name != "gio" else [opener, "open", str(directory)]
            subprocess.Popen(argv)
        else:
            raise DesktopOpenError(409, "desktop_open_unavailable", "当前系统不支持打开系统文件夹")
    except DesktopOpenError:
        raise
    except OSError as exc:
        raise DesktopOpenError(500, "desktop_open_failed", "系统文件夹打开失败") from exc

    return {"opened": True, "path": str(directory), "platform": platform_name}
