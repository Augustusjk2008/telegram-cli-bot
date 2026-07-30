"""Codex provider usage aggregation core.

The package deliberately keeps collection, storage and transport wiring separate so
the chat runtime can treat usage accounting as a best-effort side effect.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .service import CodexUsageService


_service_lock = threading.RLock()
_service: CodexUsageService | None = None


def get_codex_usage_service(
    *,
    db_path: Path | str | None = None,
    **kwargs: Any,
) -> CodexUsageService:
    """Return the process-wide, lazily created usage service."""

    global _service
    with _service_lock:
        if _service is None:
            _service = CodexUsageService(db_path=db_path, **kwargs)
        return _service


async def close_codex_usage_service() -> None:
    """Close and clear the singleton without creating a never-used database."""

    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        await service.aclose()


def close_codex_usage_service_sync() -> None:
    """Synchronous variant for a shutdown function already running in a worker."""

    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        service.close()


__all__ = [
    "CodexUsageService",
    "close_codex_usage_service",
    "close_codex_usage_service_sync",
    "get_codex_usage_service",
]
