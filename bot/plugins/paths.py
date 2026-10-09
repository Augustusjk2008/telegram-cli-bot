from __future__ import annotations

from pathlib import Path

from bot.runtime_paths import get_tcb_home_root


def default_plugins_root() -> Path:
    return get_tcb_home_root() / "plugins"
