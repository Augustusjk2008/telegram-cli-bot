from bot.assistant_home import bootstrap_assistant_home


def test_create_and_approve_proposal(tmp_path):
    from bot.assistant_proposals import create_proposal, list_proposals, set_proposal_status

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    proposal = create_proposal(home, kind="knowledge", title="Fix assistant scope", body="assistant 是单例")
    assert proposal["status"] == "proposed"

    approved = set_proposal_status(home, proposal["id"], "approved", reviewer="admin")
    assert approved["status"] == "approved"
    assert list_proposals(home, status="approved")[0]["id"] == proposal["id"]
