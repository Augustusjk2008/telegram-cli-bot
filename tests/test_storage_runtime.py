from __future__ import annotations

import asyncio

import pytest

from bot.storage_runtime import AsyncStorageMigrationService


@pytest.mark.asyncio
async def test_storage_runtime_restarts_only_after_commit() -> None:
    committed = asyncio.Event()

    class FakeService:
        def execute(self, _plan_id: str) -> dict[str, str]:
            return {"state": "awaiting_restart"}

        def finalize_startup(self) -> dict[str, str]:
            return {"state": "completed"}

        def retry_cleanup(self) -> dict[str, str]:
            return {"state": "completed"}

    adapter = AsyncStorageMigrationService(FakeService(), on_committed=committed.set)
    assert await adapter.execute("plan") == {"state": "awaiting_restart"}
    await asyncio.wait_for(committed.wait(), timeout=1)
    assert await adapter.finalize_startup() == {"state": "completed"}


@pytest.mark.asyncio
async def test_storage_runtime_restarts_after_copy_failure_to_restore_source() -> None:
    failed = asyncio.Event()

    class FakeService:
        def execute(self, _plan_id: str) -> dict[str, str]:
            raise OSError("target is unavailable")

    adapter = AsyncStorageMigrationService(FakeService(), on_failed=failed.set)
    with pytest.raises(OSError, match="target is unavailable"):
        await adapter.execute("plan")
    await asyncio.wait_for(failed.wait(), timeout=1)
