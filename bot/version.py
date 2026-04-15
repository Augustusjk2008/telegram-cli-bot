from __future__ import annotations

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"


def _read_app_version() -> str:
    value = _VERSION_FILE.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"版本文件为空: {_VERSION_FILE}")
    return value


APP_VERSION = _read_app_version()
