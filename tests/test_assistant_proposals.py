import json

from bot.assistant.home import bootstrap_assistant_home


def test_create_and_approve_proposal(tmp_path):
    from bot.assistant.proposals import create_proposal, list_proposals, set_proposal_status

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    proposal = create_proposal(home, kind="knowledge", title="Fix assistant scope", body="assistant 是单例")
    assert proposal["status"] == "proposed"

    approved = set_proposal_status(home, proposal["id"], "approved", reviewer="admin")
    assert approved["status"] == "approved"
    assert list_proposals(home, status="approved")[0]["id"] == proposal["id"]


def test_list_proposals_refreshes_changed_file_without_relisting_dir(tmp_path, monkeypatch):
    from bot.assistant.proposals import create_proposal, list_proposals

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    proposal = create_proposal(home, kind="knowledge", title="Fix assistant scope", body="assistant 是单例")
    first = list_proposals(home)

    proposal_path = home.root / "proposals" / f"{proposal['id']}.json"
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    saved["status"] = "approved"
    proposal_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    proposal_dir = home.root / "proposals"
    original_glob = type(proposal_dir).glob
    calls = {"count": 0}

    def tracked_glob(self, pattern):
        if self == proposal_dir:
            calls["count"] += 1
        return original_glob(self, pattern)

    monkeypatch.setattr(type(proposal_dir), "glob", tracked_glob)

    second = list_proposals(home)

    assert first[0]["status"] == "proposed"
    assert second[0]["status"] == "approved"
    assert calls["count"] == 0
