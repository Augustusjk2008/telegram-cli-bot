"""Per-turn Codex and Claude cost statistics: persistence, queries and recording."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .service import CostStatsService


_service_lock = threading.RLock()
_service: CostStatsService | None = None
logger = logging.getLogger(__name__)


def get_cost_stats_service(*, db_path: Path | str | None = None, **kwargs: Any) -> CostStatsService:
    """Return the process-wide, lazily created cost statistics service."""

    global _service
    with _service_lock:
        if _service is None:
            _service = CostStatsService(db_path=db_path, **kwargs)
        return _service


def cost_stats_enabled_snapshot(provider: str) -> bool | None:
    """Cached enable flag without I/O; ``None`` until the flags were loaded once."""

    snapshot = get_cost_stats_service().enabled_snapshot()
    return None if snapshot is None else bool(snapshot.get(provider))


async def cost_stats_enabled(provider: str) -> bool:
    """Best-effort enable check; reads the disk at most once per process."""

    try:
        return await get_cost_stats_service().is_enabled(provider)
    except Exception as exc:
        logger.warning("费用统计开关读取失败，按关闭处理: %s", exc)
        return False


async def record_turn_cost(**fields: Any) -> bool:
    """Best-effort recording shared by CLI callers; failures never reach the turn."""

    try:
        return await get_cost_stats_service().record_turn(**fields)
    except Exception as exc:
        logger.warning("费用统计写入失败，CLI 流程将继续: %s", exc)
        return False


async def close_cost_stats_service() -> None:
    """Close and clear the singleton without creating a never-used database."""

    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        await service.aclose()


def close_cost_stats_service_sync() -> None:
    """Synchronous variant for a shutdown function already running in a worker."""

    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        service.close()


__all__ = [
    "CostStatsService",
    "close_cost_stats_service",
    "close_cost_stats_service_sync",
    "cost_stats_enabled",
    "cost_stats_enabled_snapshot",
    "get_cost_stats_service",
    "record_turn_cost",
]
