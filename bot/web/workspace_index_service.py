"""Short-lived workspace file index for quick-open."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class _IndexEntry:
    files: list[str]
    expires_at: float


_CACHE: dict[str, _IndexEntry] = {}
_LOCK = threading.RLock()
DEFAULT_TTL_SECONDS = 5.0


def _cache_key(workspace: Path | str) -> str:
    return str(Path(workspace).expanduser().resolve())


def get_workspace_files(
    workspace: Path | str,
    loader: Callable[[Path], list[str]],
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> list[str]:
    root = Path(workspace).expanduser().resolve()
    key = str(root)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.expires_at > now:
            return list(cached.files)

    files = loader(root)
    with _LOCK:
        _CACHE[key] = _IndexEntry(files=list(files), expires_at=now + max(0.1, ttl_seconds))
    return list(files)


def invalidate_workspace_index(workspace: Path | str) -> None:
    try:
        key = _cache_key(workspace)
    except OSError:
        return
    with _LOCK:
        _CACHE.pop(key, None)


def clear_workspace_indexes() -> None:
    with _LOCK:
        _CACHE.clear()
