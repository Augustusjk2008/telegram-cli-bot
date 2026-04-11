"""Runtime platform helpers."""

import os


def get_runtime_platform() -> str:
    return "windows" if os.name == "nt" else "linux"


def get_default_shell() -> str:
    return "powershell" if get_runtime_platform() == "windows" else "bash"
