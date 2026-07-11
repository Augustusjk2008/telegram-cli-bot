from __future__ import annotations

import subprocess

from bot.native_agent.shadow_git_history import ShadowGitHistory


def test_record_completed_turn_skips_after_snapshot_when_workspace_is_clean(monkeypatch, tmp_path) -> None:
    history = ShadowGitHistory(root_dir=tmp_path / "history")
    monkeypatch.setattr(history, "_ensure_repo", lambda _context: None)
    monkeypatch.setattr(history, "_manual_change_count", lambda _context: 0)
    monkeypatch.setattr(
        history,
        "snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("clean turn must not snapshot again")),
    )

    result = history.record_completed_turn(
        cwd=tmp_path / "workspace",
        conversation_id="conversation-1",
        turn_id="turn-1",
        before_head="before-head",
        pi_session_id="pi-session",
    )

    assert result.head == "before-head"
    assert result.clean is True
    state = history._read_state(history._context(tmp_path / "workspace", "conversation-1"))
    assert state["turns"][0]["before_head"] == "before-head"
    assert state["turns"][0]["after_head"] == "before-head"


def test_snapshot_degrades_before_git_add_when_single_file_exceeds_budget(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "large.bin").write_bytes(b"x" * 32)
    history = ShadowGitHistory(
        root_dir=tmp_path / "history",
        max_file_bytes=16,
        max_total_bytes=64,
    )
    monkeypatch.setattr(history, "_ensure_repo", lambda _context: None)
    monkeypatch.setattr(history, "_head", lambda _context: "before-head")
    monkeypatch.setattr(
        history,
        "_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("budget failure must skip git add")),
    )

    result = history.snapshot(cwd=workspace, conversation_id="conversation-1", label="before")

    assert result.degraded is True
    assert result.head == "before-head"
    assert result.message == "workspace history 单文件大小超过预算"


def test_workspace_budget_excludes_release_artifacts(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    artifact_dir = workspace / ".release-local" / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "bundle.zip").write_bytes(b"x" * 128)
    (workspace / "source.py").write_text("print('ok')\n", encoding="utf-8")
    history = ShadowGitHistory(
        root_dir=tmp_path / "history",
        max_file_bytes=64,
        max_total_bytes=64,
    )

    budget = history._workspace_budget(history._context(workspace, "conversation-1"))

    assert budget.message == ""
    assert budget.file_count == 1


def test_shadow_git_records_command_duration(monkeypatch, tmp_path) -> None:
    history = ShadowGitHistory(root_dir=tmp_path / "history")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr=""),
    )

    history._run(("git", "--version"), cwd=tmp_path)

    diagnostics = history.diagnostics()
    assert diagnostics["command_count"] == 1
    assert diagnostics["latest_command_ms"] >= 0
