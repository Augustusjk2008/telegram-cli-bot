"""Platform-aware script discovery and execution helpers."""

from pathlib import Path

from .runtime import get_runtime_platform


def allowed_script_extensions() -> set[str]:
    if get_runtime_platform() == "windows":
        return {".bat", ".cmd", ".ps1", ".py", ".exe"}
    return {".sh", ".py"}


def build_script_command(script_path: Path) -> tuple[list[str] | str, bool]:
    ext = script_path.suffix.lower()
    if ext == ".exe":
        return [str(script_path)], False
    if ext == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ], False
    if ext == ".py":
        return ["python", str(script_path)], False
    if ext == ".sh":
        return ["bash", str(script_path)], False
    return str(script_path), True
