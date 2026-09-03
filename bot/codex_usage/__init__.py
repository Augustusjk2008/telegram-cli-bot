"""Codex quota collection, persistence and transport wiring."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from pathlib import Path
from typing import Any

from .service import CodexUsageService


_service_lock = threading.RLock()
_service: CodexUsageService | None = None
logger = logging.getLogger(__name__)


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


async def start_codex_rate_limit_capture(*, env: dict[str, str], command: list[str]) -> Any:
    """Best-effort quota capture setup shared by every Codex subprocess entry point."""

    try:
        service = get_codex_usage_service()
        starter = (
            getattr(service, "start_capture", None)
            or getattr(service, "create_capture", None)
            or getattr(service, "begin_capture", None)
        )
        if starter is None:
            return None
        if inspect.iscoroutinefunction(starter):
            capture = starter(env=env, command=command)
        else:
            capture = await asyncio.to_thread(starter, env=env, command=command)
        return await capture if inspect.isawaitable(capture) else capture
    except Exception as exc:
        logger.warning("Codex 额度采集初始化失败，CLI 流程将继续: %s", exc)
        return None


async def record_codex_rate_limit_capture(quota_capture: Any, parsed_result: Any) -> None:
    """Best-effort terminal quota recording shared by Codex CLI callers."""

    if quota_capture is None or parsed_result is None:
        return
    session_id = getattr(parsed_result, "session_id", None)
    try:
        record_once = quota_capture.record_once
        kwargs = {"session_id": session_id}
        if inspect.iscoroutinefunction(record_once):
            result = record_once(**kwargs)
        else:
            result = await asyncio.to_thread(record_once, **kwargs)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("Codex 额度记录失败，CLI 流程将继续: %s", exc)


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
    "record_codex_rate_limit_capture",
    "start_codex_rate_limit_capture",
]
