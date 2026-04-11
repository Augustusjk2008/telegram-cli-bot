import json

from bot.assistant_home import bootstrap_assistant_home
from bot.models import UserSession


def test_assistant_session_persist_writes_user_state_file(tmp_path):
    from bot.assistant_state import attach_assistant_persist_hook

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    session = UserSession(bot_id=1, bot_alias="assistant1", user_id=1001, working_dir=str(workdir))
    attach_assistant_persist_hook(session, home, 1001)

    session.add_to_history("user", "hello")
    session.browse_dir = str(workdir / "notes")
    session.persist()

    state_path = home.root / "state" / "users" / "1001.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["history"][-1]["content"] == "hello"
    assert data["browse_dir"] == str(workdir / "notes")
