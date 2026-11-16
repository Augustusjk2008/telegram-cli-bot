"""Scheduled agent tasks: open a new conversation on a Bot and send a fixed prompt."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _schedule_store():
    from bot.scheduler.service import get_active_scheduler_service

    service = get_active_scheduler_service()
    if service is not None:
        return service.store, service
    from bot.runtime_paths import get_scheduler_db_path
    from bot.scheduler.store import ScheduleStore

    path = get_scheduler_db_path()
    return (ScheduleStore(path) if path.exists() else None), None


def notify_bot_renamed(old_alias: str, new_alias: str) -> None:
    """Keep schedules pointing at a renamed Bot; never fails the rename."""
    try:
        store, service = _schedule_store()
        if store is not None and store.rename_alias(old_alias, new_alias) and service is not None:
            service.wake()
    except Exception as exc:
        logger.warning("定时任务：同步 Bot 重命名失败 (%s)", type(exc).__name__)


def notify_bot_removed(alias: str) -> None:
    """Disable schedules of a removed Bot; never fails the removal."""
    try:
        store, service = _schedule_store()
        if store is not None and store.disable_for_alias(alias, "bot_removed") and service is not None:
            service.wake()
    except Exception as exc:
        logger.warning("定时任务：停用已删除 Bot 的定时任务失败 (%s)", type(exc).__name__)


__all__ = ["notify_bot_removed", "notify_bot_renamed"]
