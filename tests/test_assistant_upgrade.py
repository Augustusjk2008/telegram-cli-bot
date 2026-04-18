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
