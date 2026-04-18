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
    assert "history" not in data
    assert data["message_count"] == 0
    assert data["browse_dir"] == str(workdir / "notes")


def test_clear_assistant_runtime_state_deletes_user_state_only(tmp_path):
    from bot.assistant_state import clear_assistant_runtime_state, save_assistant_runtime_state

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    save_assistant_runtime_state(home, 1001, {"history": [{"role": "user", "content": "hello"}]})
    working_file = home.root / "memory" / "working" / "current_goal.md"
    working_file.write_text("保留 working memory\n", encoding="utf-8")

    removed = clear_assistant_runtime_state(home, 1001)

    assert removed is True
    assert not (home.root / "state" / "users" / "1001.json").exists()
    assert working_file.read_text(encoding="utf-8") == "保留 working memory\n"


def test_assistant_runtime_state_roundtrips_managed_prompt_hash_seen(tmp_path):
    from bot.assistant_state import attach_assistant_persist_hook, restore_assistant_runtime_state

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    session = UserSession(
        bot_id=1,
        bot_alias="assistant1",
        user_id=1001,
        working_dir=str(workdir),
        managed_prompt_hash_seen="hash-before",
    )
    attach_assistant_persist_hook(session, home, 1001)
    session.persist()

    restored = UserSession(bot_id=1, bot_alias="assistant1", user_id=1001, working_dir=str(workdir))
    restore_assistant_runtime_state(restored, home, 1001)

    assert restored.managed_prompt_hash_seen == "hash-before"
