import json
import subprocess

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_proposals import create_proposal


def test_apply_approved_upgrade_runs_git_apply_check_and_marks_applied(tmp_path, monkeypatch):
    from bot.assistant_upgrade import apply_approved_upgrade

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
    patch_path = home.root / "upgrades" / "approved" / f"{proposal['id']}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("bot.assistant_upgrade.subprocess.run", fake_run)

    result = apply_approved_upgrade(home, proposal["id"], repo_root=repo)

    assert result["status"] == "applied"
    assert calls[0][:3] == ["git", "apply", "--check"]
    assert calls[1][:2] == ["git", "apply"]


def test_apply_approved_upgrade_rejects_non_approved_proposal(tmp_path, monkeypatch):
    from bot.assistant_upgrade import apply_approved_upgrade

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
        "bot.assistant_upgrade.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess should not run")),
    )

    try:
        apply_approved_upgrade(home, proposal["id"], repo_root=repo)
    except PermissionError as exc:
        assert str(exc) == "proposal_not_approved"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected PermissionError")


def test_write_upgrade_apply_failure_persists_audit(tmp_path):
    from bot.assistant_upgrade import write_upgrade_apply_failure

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
