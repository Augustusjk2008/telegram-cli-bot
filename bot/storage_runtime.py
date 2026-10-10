"""Async boundary for the synchronous storage migration engine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


class AsyncStorageMigrationService:
    """Run filesystem migration work off the Web event loop.

    The migration engine deliberately stays synchronous so its lock and file
    operations are easy to reason about.  This adapter keeps the Web API
    responsive and requests the normal supervised process restart only after
    the new target has been fully verified and the locator has been committed.
    """

    def __init__(
        self,
        service: Any,
        *,
        on_committed: Callable[[], object] | None = None,
        on_failed: Callable[[], object] | None = None,
    ) -> None:
        self._service = service
        self._on_committed = on_committed
        self._on_failed = on_failed

    async def snapshot(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._service.snapshot)
        if not int(result.get("totalBytes", 0) or 0):
            result["totalBytes"] = sum(
                int(item.get("bytes", item.get("sizeBytes", 0)) or 0)
                for item in result.get("sources", [])
                if isinstance(item, dict)
            )
        return result

    async def status(self) -> dict[str, Any]:
        """Read the live migration journal without contending with its lock."""
        method = getattr(self._service, "status", None)
        if not callable(method):
            return {}
        return await asyncio.to_thread(method)

    async def preview(self, target_root: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._service.preview, target_root)

    async def begin(self, plan_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._service.begin, plan_id)

    async def execute(self, plan_id: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._service.execute, plan_id)
        except BaseException:
            if self._on_failed:
                asyncio.get_running_loop().call_soon(self._on_failed)
            raise
        if str(result.get("state") or "").strip().lower() == "awaiting_restart" and self._on_committed:
            asyncio.get_running_loop().call_soon(self._on_committed)
        return result

    async def finalize_startup(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._service.finalize_startup)

    async def finalize(self, _plan_id: str = "") -> dict[str, Any]:
        return await self.finalize_startup()

    async def retry_cleanup(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._service.retry_cleanup)
