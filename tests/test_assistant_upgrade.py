import json
import subprocess
from pathlib import Path

from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.proposals import create_proposal


def _init_git_repo(repo: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True).strip()


def test_describe_upgrade_repo_marks_dirty_repo_unavailable(tmp_path):
    from bot.assistant.upgrade.targets import describe_upgrade_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "tracked.txt").write_text("new\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    result = describe_upgrade_repo(repo)

    assert result["available"] is False
    assert result["dirty"] is True
    assert result["reason"] == "upgrade_target_dirty"
    assert "tracked.txt" in "\n".join(result["dirty_paths"])
    assert "untracked.txt" in "\n".join(result["dirty_paths"])


def test_apply_approved_upgrade_runs_git_apply_check_and_marks_applied(tmp_path, monkeypatch):
    from bot.assistant.upgrade.service import apply_approved_upgrade

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal["status"] = "approved"
    proposal["status"] = "approved"
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("bot.assistant.upgrade.service.subprocess.run", fake_run)

    result = apply_approved_upgrade(home, proposal["id"], repo_root=repo)

    assert result["status"] == "applied"
    assert any(call[:3] == ["git", "apply", "--check"] for call in calls)
    assert any(call[:2] == ["git", "apply"] and "--check" not in call for call in calls)


def test_generate_pending_patch_exports_diff_and_metadata(tmp_path, monkeypatch):
    from bot.assistant.upgrade.patch_generation import generate_pending_patch

    assistant_dir = tmp_path / "assistant-root"
    assistant_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="change a")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal["status"] = "approved"

    def fake_cli(worktree_path: Path, prompt: str, metadata: dict):
        assert "Proposal:" in prompt
        (worktree_path / "a.txt").write_text("new\n", encoding="utf-8")
        return {"status": "succeeded", "elapsed_seconds": 1, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr("bot.assistant.upgrade.patch_generation._run_generator_cli", fake_cli)

    result = generate_pending_patch(
        home,
        proposal,
        target={
            "alias": "target1",
            "working_dir": str(repo),
            "repo_root": str(repo),
            "head": head,
            "cli_type": "codex",
            "cli_path": "codex",
        },
        generated_by="1001",
        regenerate=False,
    )

    assert result["state"] == "pending"
    assert (home.root / "upgrades" / "pending" / f"{proposal['id']}.patch").exists()
    assert result["target_repo_root"] == str(repo)
    assert result["base_commit"] == head
    assert result["changed_files"] == ["a.txt"]


def test_approve_pending_upgrade_patch_rejects_sensitive_paths(tmp_path):
    from bot.assistant.upgrade.service import approve_pending_upgrade_patch

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_path = home.root / "upgrades" / "pending" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/.env b/.env\n", encoding="utf-8")
    metadata_path = home.root / "upgrades" / "pending" / f"{proposal['id']}.json"
    metadata_path.write_text(
        json.dumps({"state": "pending", "sensitive_hits": [".env"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    try:
        approve_pending_upgrade_patch(home, proposal["id"], reviewer="1001")
    except PermissionError as exc:
        assert str(exc) == "sensitive_patch_path"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected sensitive_patch_path")
