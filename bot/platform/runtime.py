"""Runtime platform helpers."""

import os
import sys


def get_runtime_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def get_default_shell() -> str:
    platform = get_runtime_platform()
    if platform == "windows":
        return "powershell"
    if platform == "macos":
        return os.environ.get("SHELL") or "/bin/zsh"
    return "bash"
