"""Cross-platform path display helpers."""

import re

_SEP_RE = re.compile(r"[\\/]+")


def split_path_parts(raw_path: str) -> list[str]:
    return [part for part in _SEP_RE.split((raw_path or "").strip()) if part]


def truncate_path_for_display(raw_path: str, max_len: int = 30) -> str:
    path = (raw_path or "").strip()
    if len(path) <= max_len:
        return path

    parts = split_path_parts(path)
    if not parts:
        return path[: max_len - 3] + "..."

    drive = path[:2] if len(path) >= 2 and path[1] == ":" else ""
    separator = "\\" if ("\\" in path or drive) else "/"
    tail = parts[-1]
    prefix = f"{drive}{separator}...{separator}" if drive else f"...{separator}"
    candidate = f"{prefix}{tail}"
    if len(candidate) <= max_len:
        return candidate

    available = max_len - len(prefix)
    if available <= 3:
        return path[: max_len - 3] + "..."
    return f"{prefix}{tail[-available:]}"
