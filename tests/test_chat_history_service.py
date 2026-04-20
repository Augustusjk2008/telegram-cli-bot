from pathlib import Path

import bot.runtime_paths as runtime_paths
from bot.models import BotProfile, UserSession
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


def test_history_service_lists_local_messages_and_running_snapshot(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    service = ChatHistoryService(store)
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(workspace))
    session.session_epoch = 1
    profile = BotProfile(alias="main", cli_type="codex", working_dir=str(workspace))

    handle = service.start_turn(
        profile=profile,
        session=session,
        user_text="列出当前目录",
        native_provider="codex",
    )
    service.replace_assistant_preview(handle, "我先检查目录结构。")

    items = service.list_history(profile, session, limit=10)
    assert [(item["role"], item["content"], item["state"]) for item in items] == [
        ("user", "列出当前目录", "done"),
        ("assistant", "我先检查目录结构。", "streaming"),
    ]

    snapshot = service.build_session_snapshot(profile, session)
    assert snapshot["history_count"] == 2
    assert snapshot["running_reply"]["preview_text"] == "我先检查目录结构。"


def test_build_session_snapshot_does_not_materialize_empty_store(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    service = ChatHistoryService(ChatStore(workspace))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(workspace))
    session.session_epoch = 1
    profile = BotProfile(alias="main", cli_type="codex", working_dir=str(workspace))

    snapshot = service.build_session_snapshot(profile, session)

    assert snapshot["history_count"] == 0
    assert snapshot["running_reply"] is None
    assert not runtime_paths.get_chat_history_db_path(workspace).exists()


def test_history_service_reloads_streaming_row_after_restart(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    profile = BotProfile(alias="main", cli_type="codex", working_dir=str(workspace))
    first_session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(workspace))
    first_session.session_epoch = 1
    first_service = ChatHistoryService(ChatStore(workspace))
    handle = first_service.start_turn(
        profile=profile,
        session=first_session,
        user_text="列出当前目录",
        native_provider="codex",
    )
    first_service.replace_assistant_preview(handle, "我先检查目录结构。")

    restored_session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(workspace))
    restored_session.session_epoch = 1
    restored_service = ChatHistoryService(ChatStore(workspace))
    items = restored_service.list_history(profile, restored_session, limit=10)

    assert items[-1]["content"] == "我先检查目录结构。"
    assert items[-1]["state"] == "streaming"
