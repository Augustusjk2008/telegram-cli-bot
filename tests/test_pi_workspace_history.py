from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from bot.native_agent.pi_workspace_history import PiWorkspaceHistory


class FakeWorkspaceRuntime:
    def __init__(self, responses: list[dict[str, Any]] | None = None, *, delay: float = 0.0, error: BaseException | None = None) -> None:
        self.responses = list(responses or [])
        self.delay = delay
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def request_workspace_history(self, fields: dict[str, Any]) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        self.requests.append(dict(fields))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.responses:
            return dict(self.responses.pop(0))
        return {"head": "head-default", "clean": True, "manual_change_count": 0}

    async def events(self):
        raise AssertionError("workspace history 不应直接消费 runtime.events()")


@pytest.mark.asyncio
async def test_workspace_history_status_clean():
    runtime = FakeWorkspaceRuntime([{"head": "head-1", "clean": True, "manual_change_count": 0}])

    status = await PiWorkspaceHistory().status(runtime)

    assert status.head == "head-1"
    assert status.clean is True
    assert status.manual_change_count == 0
    assert runtime.requests[0]["action"] == "status"


@pytest.mark.asyncio
async def test_workspace_history_dirty_returns_count_not_paths():
    runtime = FakeWorkspaceRuntime([{
        "head": "head-1",
        "clean": False,
        "changed_paths": ["C:/repo/a.py", "C:/repo/b.py"],
    }])

    status = await PiWorkspaceHistory().status(runtime)

    assert status.manual_change_count == 2
    assert "a.py" not in json.dumps(status.__dict__, ensure_ascii=False)


@pytest.mark.asyncio
async def test_workspace_history_checkpoint_and_rollback():
    runtime = FakeWorkspaceRuntime([
        {"head": "head-2", "clean": True},
        {"head": "head-2", "clean": True},
    ])
    adapter = PiWorkspaceHistory()

    checkpoint = await adapter.checkpoint(runtime, label="manual-before-turn")
    rollback = await adapter.rollback(runtime, target_head="head-1")

    assert checkpoint.head == "head-2"
    assert runtime.requests[0]["label"] == "manual-before-turn"
    assert rollback.head == "head-2"
    assert runtime.requests[1]["target_head"] == "head-1"


@pytest.mark.asyncio
async def test_workspace_history_error_and_timeout_map_to_degraded():
    error_status = await PiWorkspaceHistory().status(FakeWorkspaceRuntime(error=RuntimeError("missing plugin")))
    timeout_status = await PiWorkspaceHistory(timeout_seconds=0.1).status(FakeWorkspaceRuntime(delay=1))

    assert error_status.degraded is True
    assert "missing plugin" in error_status.message
    assert timeout_status.degraded is True


@pytest.mark.asyncio
async def test_workspace_history_locked_count_is_sanitized():
    runtime = FakeWorkspaceRuntime([{
        "ok": False,
        "error": {"code": "locked", "message": "rollback blocked: C:/repo/b.py"},
        "locked_files": ["C:/repo/a.py", "C:/repo/b.py", "C:/repo/c.py"],
    }])

    status = await PiWorkspaceHistory().rollback(runtime, target_head="head-1")

    assert status.degraded is True
    assert status.locked_file_count == 3
    dumped = json.dumps(status.__dict__, ensure_ascii=False)
    assert "locked_files" not in dumped
    assert "C:/repo" not in dumped


@pytest.mark.asyncio
async def test_workspace_history_uses_runtime_request_response():
    runtime = FakeWorkspaceRuntime([{"head": "head-9", "clean": True, "manual_change_count": 0}])

    status = await PiWorkspaceHistory().status(runtime)

    assert status.head == "head-9"
    assert runtime.requests == [{"action": "status"}]
