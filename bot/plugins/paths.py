from __future__ import annotations

from pathlib import Path


def default_plugins_root() -> Path:
    return Path.home() / ".tcb" / "plugins"
