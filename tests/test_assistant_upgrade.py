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


def test_apply_approved_upgrade_rejects_dirty_target(tmp_path):
    from bot.assistant.upgrade.service import apply_approved_upgrade

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    try:
        apply_approved_upgrade(home, proposal["id"], repo_root=repo)
    except RuntimeError as exc:
        assert str(exc).startswith("upgrade_target_dirty")
        assert "a.txt" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected dirty target rejection")


def test_apply_approved_upgrade_rejects_non_approved_proposal(tmp_path, monkeypatch):
    from bot.assistant.upgrade.service import apply_approved_upgrade

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
    monkeypatch.setattr(
        "bot.assistant.upgrade.service.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess should not run")),
    )

    try:
        apply_approved_upgrade(home, proposal["id"], repo_root=repo)
    except PermissionError as exc:
        assert str(exc) == "proposal_not_approved"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected PermissionError")


def test_write_upgrade_apply_failure_persists_audit(tmp_path):
    from bot.assistant.upgrade.service import write_upgrade_apply_failure

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    result = write_upgrade_apply_failure(
        home,
        proposal["id"],
        repo_root=repo,
        patch_path=patch_path,
        error="patch does not apply",
    )

    assert result["status"] == "failed"
    audit_path = home.root / "upgrades" / "applied" / f"{proposal['id']}.last-error.json"
    assert audit_path.exists()
    assert "patch does not apply" in audit_path.read_text(encoding="utf-8")


def test_write_upgrade_dry_run_result_updates_approved_metadata(tmp_path):
    from bot.assistant.upgrade.service import read_upgrade_metadata, write_upgrade_dry_run_result, write_upgrade_metadata

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    write_upgrade_metadata(home, proposal["id"], "approved", {"target_repo_root": str(tmp_path / "repo")})

    saved = write_upgrade_dry_run_result(
        home,
        proposal["id"],
        {
            "ok": False,
            "checked_at": "2026-04-30T00:00:00+00:00",
            "stdout": "",
            "stderr": "patch does not apply",
            "repo_root": "C:/repo",
            "patch_path": "C:/patch.diff",
        },
    )

    loaded = read_upgrade_metadata(home, proposal["id"], "approved")
    assert saved["dry_run"]["ok"] is False
    assert loaded["dry_run"]["stderr"] == "patch does not apply"
    assert loaded["dry_run"]["repo_root"] == "C:/repo"


def test_upgrade_metadata_round_trip_and_approved_resolution(tmp_path):
    from bot.assistant.upgrade.service import (
        read_upgrade_metadata,
        resolve_approved_upgrade_patch_path,
        write_upgrade_metadata,
    )

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    metadata = {
        "id": proposal["id"],
        "proposal_id": proposal["id"],
        "state": "approved",
        "target_alias": "main",
        "target_working_dir": str(target),
        "target_repo_root": str(target),
        "base_commit": "abc123",
        "worktree_path": str(home.root / "upgrades" / "worktrees" / proposal["id"]),
        "patch_path": f"upgrades/approved/{proposal['id']}.patch",
        "generated_at": "2026-04-29T00:00:00+00:00",
        "generated_by": "1001",
        "generator": {"cli_type": "codex", "cli_path": "codex", "status": "succeeded", "elapsed_seconds": 1},
        "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
        "sensitive_hits": [],
        "changed_files": ["a.txt"],
        "additions": 1,
        "deletions": 0,
    }
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    write_upgrade_metadata(home, proposal["id"], "approved", metadata)

    loaded = read_upgrade_metadata(home, proposal["id"], "approved")
    assert loaded["target_repo_root"] == str(target)
    assert resolve_approved_upgrade_patch_path(home, proposal["id"]) == patch_path


def test_approve_pending_upgrade_patch_copies_patch_and_metadata(tmp_path):
    from bot.assistant.upgrade.service import approve_pending_upgrade_patch, read_upgrade_metadata

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal["status"] = "approved"
    proposal["status"] = "approved"
    proposal["status"] = "approved"

    pending_patch = home.root / "upgrades" / "pending" / f"{proposal['id']}.patch"
    pending_patch.parent.mkdir(parents=True, exist_ok=True)
    pending_patch.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
    pending_metadata = {
        "id": proposal["id"],
        "proposal_id": proposal["id"],
        "state": "pending",
        "target_alias": "main",
        "target_working_dir": str(target),
        "target_repo_root": str(target),
        "base_commit": "abc123",
        "worktree_path": str(home.root / "upgrades" / "worktrees" / proposal["id"]),
        "patch_path": f"upgrades/pending/{proposal['id']}.patch",
        "generated_at": "2026-04-29T00:00:00+00:00",
        "generated_by": "1001",
        "generator": {"cli_type": "codex", "cli_path": "codex", "status": "succeeded", "elapsed_seconds": 1},
        "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
        "sensitive_hits": [],
        "changed_files": ["a.txt"],
        "additions": 1,
        "deletions": 0,
    }
    (home.root / "upgrades" / "pending" / f"{proposal['id']}.json").write_text(
        json.dumps(pending_metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    approved = approve_pending_upgrade_patch(home, proposal["id"], reviewer="1001")

    assert approved["state"] == "approved"
    assert (home.root / "upgrades" / "approved" / f"{proposal['id']}.patch").exists()
    assert read_upgrade_metadata(home, proposal["id"], "approved")["approved_by"] == "1001"


def test_apply_approved_upgrade_uses_metadata_target_repo(tmp_path, monkeypatch):
    from bot.assistant.upgrade.service import apply_approved_upgrade, write_upgrade_metadata

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    host_repo = tmp_path / "host"
    host_repo.mkdir()
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="code", title="patch", body="body")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal["status"] = "approved"
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
    write_upgrade_metadata(
        home,
        proposal["id"],
        "approved",
        {
            "target_repo_root": str(target_repo),
            "target_working_dir": str(target_repo),
            "target_alias": "target1",
            "base_commit": "abc123",
            "worktree_path": str(home.root / "upgrades" / "worktrees" / proposal["id"]),
            "generated_at": "2026-04-29T00:00:00+00:00",
            "generated_by": "1001",
            "generator": {"cli_type": "codex", "cli_path": "codex", "status": "succeeded", "elapsed_seconds": 1},
            "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
            "sensitive_hits": [],
            "changed_files": ["a.txt"],
            "additions": 1,
            "deletions": 0,
        },
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("cwd")))
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, "deadbeef\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("bot.assistant.upgrade.service.subprocess.run", fake_run)

    result = apply_approved_upgrade(home, proposal["id"], repo_root=host_repo)

    assert result["repo_root"] == str(target_repo.resolve())
    assert calls[1][1] == target_repo.resolve()
    assert calls[2][1] == target_repo.resolve()


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


def test_generate_pending_patch_writes_lf_patch_bytes(tmp_path, monkeypatch):
    from bot.assistant.upgrade.patch_generation import generate_pending_patch

    assistant_dir = tmp_path / "assistant-root"
    assistant_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.txt").write_text("old\n", encoding="utf-8", newline="\n")
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
        (worktree_path / "a.txt").write_text("new\n", encoding="utf-8", newline="\n")
        return {"status": "succeeded", "elapsed_seconds": 1, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr("bot.assistant.upgrade.patch_generation._run_generator_cli", fake_cli)

    generate_pending_patch(
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

    patch_path = home.root / "upgrades" / "pending" / f"{proposal['id']}.patch"
    data = patch_path.read_bytes()
    assert b"\r\n" not in data
    assert b"\n" in data
    subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=repo, check=True)


def test_patch_generator_cli_applies_global_extra_args(tmp_path, monkeypatch):
    from bot.assistant.upgrade import patch_generation

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    captured = {}

    def fake_build_cli_command(**kwargs):
        captured["extra_args"] = kwargs["params_config"].codex["extra_args"]
        return ["codex"], True

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(patch_generation.config, "CLI_GLOBAL_EXTRA_ARGS", {"codex": ["--global"]})
    monkeypatch.setattr("bot.assistant.upgrade.patch_generation.resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr("bot.assistant.upgrade.patch_generation.build_cli_command", fake_build_cli_command)
    monkeypatch.setattr("bot.assistant.upgrade.patch_generation.subprocess.run", fake_run)

    result = patch_generation._run_generator_cli(
        worktree,
        "apply proposal",
        {"cli_type": "codex", "cli_path": "codex"},
    )

    assert result["status"] == "succeeded"
    assert captured["extra_args"] == ["--global"]
    assert captured["cmd"] == ["codex"]
    assert captured["input"] == "apply proposal\n"


def test_generate_pending_patch_marks_sensitive_hits(tmp_path, monkeypatch):
    from bot.assistant.upgrade.patch_generation import generate_pending_patch

    assistant_dir = tmp_path / "assistant-root"
    assistant_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    home = bootstrap_assistant_home(assistant_dir)
    proposal = create_proposal(home, kind="code", title="patch", body="add env")
    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    proposal["status"] = "approved"

    def fake_cli(worktree_path: Path, prompt: str, metadata: dict):
        (worktree_path / ".env").write_text("TOKEN=x\n", encoding="utf-8")
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

    assert result["sensitive_hits"] == [".env"]


def test_generate_pending_patch_recovers_stale_running_metadata_and_worktree(tmp_path, monkeypatch):
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

    pending_dir = home.root / "upgrades" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    stale_metadata_path = pending_dir / f"{proposal['id']}.json"
    stale_metadata_path.write_text(
        json.dumps(
            {
                "id": proposal["id"],
                "proposal_id": proposal["id"],
                "state": "pending",
                "lifecycle": "running",
                "target_alias": "target1",
                "target_repo_root": str(repo),
                "base_commit": head,
                "worktree_path": str(home.root / "upgrades" / "worktrees" / proposal["id"]),
                "patch_path": f"upgrades/pending/{proposal['id']}.patch",
                "generated_at": "2026-04-29T00:00:00+00:00",
                "generated_by": "1001",
                "generator": {"cli_type": "codex", "cli_path": "codex", "status": "running", "elapsed_seconds": 0},
                "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
                "sensitive_hits": [],
                "changed_files": [],
                "additions": 0,
                "deletions": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    stale_worktree = home.root / "upgrades" / "worktrees" / proposal["id"]
    stale_worktree.mkdir(parents=True, exist_ok=True)
    (stale_worktree / "stale.txt").write_text("stale\n", encoding="utf-8")

    def fake_cli(worktree_path: Path, prompt: str, metadata: dict):
        assert worktree_path.exists()
        assert "Proposal:" in prompt
        assert not (worktree_path / "stale.txt").exists()
        (worktree_path / "a.txt").write_text("new\n", encoding="utf-8")
        return {
            "status": "succeeded",
            "elapsed_seconds": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "assistant_text": "done",
        }

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
    assert result["lifecycle"] == "pending"
    assert (home.root / "upgrades" / "pending" / f"{proposal['id']}.patch").exists()
    assert not stale_worktree.exists()


def test_generate_pending_patch_writes_failed_metadata_on_cli_error(tmp_path, monkeypatch):
    from bot.assistant.upgrade.patch_generation import generate_pending_patch
    from bot.assistant.upgrade.service import read_upgrade_metadata

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
        raise subprocess.CalledProcessError(1, ["codex"], output="", stderr="cli failed")

    monkeypatch.setattr("bot.assistant.upgrade.patch_generation._run_generator_cli", fake_cli)

    try:
        generate_pending_patch(
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
    except subprocess.CalledProcessError as exc:
        assert exc.stderr == "cli failed"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected CalledProcessError")

    metadata = read_upgrade_metadata(home, proposal["id"], "pending")
    assert metadata is not None
    assert metadata["lifecycle"] == "failed"
    assert metadata["generator"]["status"] == "failed"
    assert metadata["error"] == "cli failed"
    assert not (home.root / "upgrades" / "worktrees" / proposal["id"]).exists()


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
