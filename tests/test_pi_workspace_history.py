from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from bot.native_agent.pi_workspace_history import PiWorkspaceHistory
from bot.native_agent.shadow_git_history import ShadowGitHistory


class FakeRuntime:
    def __init__(self, cwd: Path, conversation_id: str = "conv-1") -> None:
        self.state = type("State", (), {
            "cwd": str(cwd),
            "conversation_id": conversation_id,
            "workspace_history_head": "",
        })()


class FakeShadowHistory:
    def __init__(self, *, error: BaseException | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay

    def status(self, **_kwargs: Any):
        return self._result("head-1")

    def snapshot(self, **_kwargs: Any):
        return self._result("head-2")

    def rollback(self, **_kwargs: Any):
        return self._result("head-1")

    def record_completed_turn(self, **_kwargs: Any):
        return self._result("head-3", linear_index=1)

    def _result(self, head: str, *, linear_index: int = 0):
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return type("Result", (), {
            "head": head,
            "clean": True,
            "manual_change_count": 0,
            "degraded": False,
            "message": "",
            "locked_file_count": 0,
            "linear_index": linear_index,
        })()


@pytest.mark.asyncio
async def test_workspace_history_checkpoint_record_and_rollback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime(workspace)
    adapter = PiWorkspaceHistory()

    before = await adapter.checkpoint(runtime, label="turn-before")
    (workspace / "a.txt").write_text("A\n", encoding="utf-8")
    after = await adapter.record_completed_turn(
        runtime,
        turn_id="turn-1",
        before_head=before.head,
        pi_session_id="pi-1",
    )
    rollback = await adapter.rollback(runtime, target_head=after.head)

    assert before.head
    assert after.head != before.head
    assert after.linear_index == 1
    assert rollback.head == after.head
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "A\n"


@pytest.mark.asyncio
async def test_workspace_history_status_counts_dirty_files_without_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = FakeRuntime(workspace)
    adapter = PiWorkspaceHistory()

    await adapter.checkpoint(runtime, label="base")
    (workspace / "secret.py").write_text("print(1)\n", encoding="utf-8")
    status = await adapter.status(runtime)

    assert status.clean is False
    assert status.manual_change_count == 1
    assert "secret.py" not in json.dumps(status.__dict__, ensure_ascii=False)


@pytest.mark.asyncio
async def test_workspace_history_error_and_timeout_map_to_degraded(tmp_path: Path):
    runtime = FakeRuntime(tmp_path)
    error_status = await PiWorkspaceHistory(shadow_history=FakeShadowHistory(error=RuntimeError("missing shadow"))).status(runtime)
    timeout_status = await PiWorkspaceHistory(
        timeout_seconds=0.01,
        shadow_history=FakeShadowHistory(delay=0.1),
    ).status(runtime)

    assert error_status.degraded is True
    assert "missing shadow" in error_status.message
    assert timeout_status.degraded is True


@pytest.mark.asyncio
async def test_workspace_history_timeout_keeps_shadow_operations_serialized(tmp_path: Path):
    runtime = FakeRuntime(tmp_path)
    adapter = PiWorkspaceHistory(
        timeout_seconds=0.01,
        shadow_history=FakeShadowHistory(delay=0.15),
    )

    started = time.perf_counter()
    first = await adapter.status(runtime)
    second = await adapter.status(runtime)
    elapsed = time.perf_counter() - started
    await asyncio.sleep(0.16)

    assert first.degraded is True
    assert second.degraded is True
    assert elapsed >= 0.12


@pytest.mark.asyncio
async def test_workspace_history_sanitizes_internal_paths(tmp_path: Path):
    runtime = FakeRuntime(tmp_path)
    status = await PiWorkspaceHistory(
        shadow_history=FakeShadowHistory(error=RuntimeError("rollback blocked: C:/repo/b.py changed_paths")),
    ).rollback(runtime, target_head="head-1")

    dumped = json.dumps(status.__dict__, ensure_ascii=False)
    assert status.degraded is True
    assert "changed_paths" not in dumped
    assert "C:/repo" not in dumped


@pytest.mark.asyncio
async def test_workspace_history_does_not_use_runtime_request_response(tmp_path: Path):
    class RuntimeWithForbiddenRequest(FakeRuntime):
        async def request_workspace_history(self, fields: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("不应调用 Pi workspace_history RPC")

        async def events(self):
            raise AssertionError("不应消费 runtime.events()")

    runtime = RuntimeWithForbiddenRequest(tmp_path)
    status = await PiWorkspaceHistory(shadow_history=FakeShadowHistory()).status(runtime)

    assert status.head == "head-1"


def test_shadow_git_history_snapshots_changes_diff_and_rollback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "smoke").mkdir()
    history_file = workspace / "smoke" / "history.txt"
    history = ShadowGitHistory()

    before_first = history.snapshot(
        cwd=workspace,
        conversation_id="conv-1",
        label="turn-1-before",
    )
    history_file.write_text("A\n", encoding="utf-8")
    after_first = history.record_completed_turn(
        cwd=workspace,
        conversation_id="conv-1",
        turn_id="turn-1",
        before_head=before_first.head,
        pi_session_id="sess-1",
    )

    before_second = history.snapshot(
        cwd=workspace,
        conversation_id="conv-1",
        label="turn-2-before",
    )
    history_file.write_text("A\nB\n", encoding="utf-8")
    (workspace / "smoke" / "new.txt").write_text("N\n", encoding="utf-8")
    after_second = history.record_completed_turn(
        cwd=workspace,
        conversation_id="conv-1",
        turn_id="turn-2",
        before_head=before_second.head,
        pi_session_id="sess-1",
    )

    changes = history.changes(cwd=workspace, conversation_id="conv-1", turn_id="turn-2")
    paths = {item["path"]: item for item in changes["files"]}

    assert after_first.head
    assert after_second.head != after_first.head
    assert changes["base_head"] == before_second.head
    assert changes["head"] == after_second.head
    assert paths["smoke/history.txt"]["additions"] == 1
    assert paths["smoke/history.txt"]["deletions"] == 0
    assert paths["smoke/new.txt"]["status"] == "added"
    assert paths["smoke/new.txt"]["additions"] == 1
    diff = history.diff(
        cwd=workspace,
        conversation_id="conv-1",
        turn_id="turn-2",
        path="smoke/history.txt",
    )
    assert diff["truncated"] is False
    assert diff["status"] == "modified"
    assert diff["old_path"] == ""
    assert diff["binary"] is False
    assert "+B" in diff["diff"]
    assert "smoke/new.txt" not in diff["diff"]

    rollback = history.rollback(cwd=workspace, conversation_id="conv-1", target_head=after_first.head)

    assert rollback.head == after_first.head
    assert history_file.read_text(encoding="utf-8") == "A\n"
    assert not (workspace / "smoke" / "new.txt").exists()


def test_shadow_git_history_reports_deleted_files_and_rejects_unlisted_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "gone.txt"
    target.write_text("A\n", encoding="utf-8")
    history = ShadowGitHistory()
    base = history.snapshot(cwd=workspace, conversation_id="conv-1", label="base")
    history.record_completed_turn(
        cwd=workspace,
        conversation_id="conv-1",
        turn_id="turn-1",
        before_head=base.head,
        pi_session_id="sess-1",
    )

    before = history.snapshot(cwd=workspace, conversation_id="conv-1", label="delete-before")
    target.unlink()
    history.record_completed_turn(
        cwd=workspace,
        conversation_id="conv-1",
        turn_id="turn-2",
        before_head=before.head,
        pi_session_id="sess-1",
    )

    changes = history.changes(cwd=workspace, conversation_id="conv-1", turn_id="turn-2")
    files = changes["files"]

    assert files == [{
        "path": "gone.txt",
        "old_path": "",
        "status": "deleted",
        "additions": 0,
        "deletions": 1,
        "binary": False,
    }]
    with pytest.raises(KeyError) as exc_info:
        history.diff(cwd=workspace, conversation_id="conv-1", turn_id="turn-2", path="other.txt")
    assert str(exc_info.value).strip("'") == "other.txt"


def test_shadow_git_history_excludes_env_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("SECRET_TOKEN=shadow-leak\n", encoding="utf-8")
    (workspace / ".env.local").write_text("SECRET_TOKEN=shadow-local-leak\n", encoding="utf-8")
    (workspace / "visible.txt").write_text("visible\n", encoding="utf-8")
    root_dir = tmp_path / "shadow"
    history = ShadowGitHistory(root_dir=root_dir)

    history.snapshot(cwd=workspace, conversation_id="conv-1", label="base")

    repo = next(root_dir.rglob("repo.git"))
    tree = subprocess.run(
        ["git", "--git-dir", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    assert "visible.txt" in tree.stdout
    assert ".env" not in tree.stdout
    assert ".env.local" not in tree.stdout
