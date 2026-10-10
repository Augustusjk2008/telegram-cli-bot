from __future__ import annotations

import asyncio
import os

import pytest

from bot.storage_runtime import AsyncStorageMigrationService


def test_storage_migration_workers_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot import config

    previous = os.environ.get("TCB_STORAGE_MIGRATION_WORKERS")
    try:
        monkeypatch.setenv("TCB_STORAGE_MIGRATION_WORKERS", "99")
        config._refresh_environment_config()
        assert config.TCB_STORAGE_MIGRATION_WORKERS == 4

        monkeypatch.setenv("TCB_STORAGE_MIGRATION_WORKERS", "0")
        config._refresh_environment_config()
        assert config.TCB_STORAGE_MIGRATION_WORKERS == 1
    finally:
        if previous is None:
            monkeypatch.delenv("TCB_STORAGE_MIGRATION_WORKERS", raising=False)
        else:
            monkeypatch.setenv("TCB_STORAGE_MIGRATION_WORKERS", previous)
        config._refresh_environment_config()


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


@pytest.mark.asyncio
async def test_storage_runtime_exposes_live_status_without_using_snapshot_lock() -> None:
    class FakeService:
        def status(self) -> dict[str, object]:
            return {"state": "copying", "completedBytes": 4, "totalBytes": 8}

    adapter = AsyncStorageMigrationService(FakeService())
    assert await adapter.status() == {"state": "copying", "completedBytes": 4, "totalBytes": 8}
