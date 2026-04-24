import json
import sqlite3
from pathlib import Path

import bot.runtime_paths as runtime_paths
from bot.web.chat_store import ChatStore, LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH


def test_begin_turn_creates_home_scoped_db_and_workspace_metadata(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)

    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="列出当前目录",
        native_provider="codex",
    )

    assert store.db_path == runtime_paths.get_chat_history_db_path(workspace)
    assert store.db_path.exists()
    metadata = json.loads(
        runtime_paths.get_chat_workspace_metadata_path(workspace).read_text(encoding="utf-8")
    )
    assert metadata["working_dir"] == str(workspace)
    assert metadata["migrated_from_legacy_project_store"] is False
    assert handle.conversation_id.startswith("conv_")

    items = store.list_messages(handle.conversation_id)
    assert [(item["role"], item["content"], item["state"]) for item in items] == [
        ("user", "列出当前目录", "done"),
        ("assistant", "", "streaming"),
    ]


def test_read_only_history_lookup_does_not_create_empty_home_store(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    items = store.list_active_history(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
        limit=10,
    )

    assert items == []
    assert not runtime_paths.get_chat_history_db_path(workspace).exists()
    assert not runtime_paths.get_chat_workspace_metadata_path(workspace).exists()


def test_begin_turn_reuses_active_conversation_within_same_session_epoch(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)

    first = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="第一问",
        native_provider="codex",
    )
    second = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="第二问",
        native_provider="codex",
    )

    assert first.conversation_id == second.conversation_id
    items = store.list_messages(first.conversation_id)
    assert [item["content"] for item in items] == ["第一问", "", "第二问", ""]


def test_rename_bot_identity_merges_old_history_into_new_bot_id(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    old_handle = store.begin_turn(
        bot_id=1,
        bot_alias="sub1",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="旧问题",
        native_provider="codex",
    )
    store.complete_turn(old_handle, content="旧回答", completion_state="completed")

    new_handle = store.begin_turn(
        bot_id=9,
        bot_alias="team1",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="新问题",
        native_provider="codex",
    )
    store.complete_turn(new_handle, content="新回答", completion_state="completed")

    moved = store.rename_bot_identity(old_bot_id=1, new_bot_id=9, old_alias="sub1", new_alias="team1")

    assert moved == 1
    items = store.list_active_history(
        bot_id=9,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
        limit=10,
    )
    assert [item["content"] for item in items] == ["旧问题", "旧回答", "新问题", "新回答"]
    assert store.list_active_history(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
        limit=10,
    ) == []

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT bot_id, bot_alias, COUNT(*) AS count FROM conversations GROUP BY bot_id, bot_alias"
        ).fetchone()
    assert row == (9, "team1", 1)


def test_legacy_project_store_is_migrated_to_home_store_on_first_read(monkeypatch, tmp_path: Path):
    original_home = tmp_path / "home"
    original_home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: original_home))

    seed_store = ChatStore(workspace)
    handle = seed_store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="hello",
        native_provider="codex",
    )
    seed_store.complete_turn(handle, content="world", completion_state="completed")

    legacy_db = workspace / LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH
    legacy_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(seed_store.db_path) as source, sqlite3.connect(legacy_db) as target:
        source.backup(target)

    migrated_home = tmp_path / "migrated-home"
    migrated_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: migrated_home))
    metadata_path = runtime_paths.get_chat_workspace_metadata_path(workspace)

    migrated_store = ChatStore(workspace)
    items = migrated_store.list_active_history(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
        limit=10,
    )

    assert [item["content"] for item in items] == ["hello", "world"]
    assert migrated_store.db_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["migrated_from_legacy_project_store"] is True
    assert metadata["legacy_project_db_path"] == str(legacy_db)


def test_finalize_turn_reuses_same_assistant_message_and_exposes_trace(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="列出当前目录",
        native_provider="codex",
    )

    store.replace_assistant_content(handle, "我先检查目录结构。", state="streaming")
    store.append_trace_event(
        handle.turn_id,
        kind="tool_call",
        raw_type="function_call",
        summary="Get-ChildItem -Force",
        tool_name="shell_command",
        call_id="call_1",
        payload={"command": "Get-ChildItem -Force"},
    )
    message = store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    items = store.list_messages(handle.conversation_id)
    assert items[1]["id"] == handle.assistant_message_id
    assert items[1]["content"] == "目录已读取完成。"
    assert items[1]["state"] == "done"
    assert items[1]["meta"]["completion_state"] == "completed"
    assert items[1]["meta"]["trace_count"] == 1
    assert message["id"] == handle.assistant_message_id

    trace = store.get_message_trace(handle.assistant_message_id)
    assert trace["trace_count"] == 1
    assert trace["trace"][0]["summary"] == "Get-ChildItem -Force"


def test_get_trace_recovery_context_returns_turn_native_context(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="列出当前目录",
        native_provider="codex",
    )
    store.append_trace_event(handle.turn_id, kind="commentary", summary="我先检查目录结构。")
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    context = store.get_trace_recovery_context(handle.assistant_message_id)

    assert context == {
        "message_id": handle.assistant_message_id,
        "turn_id": handle.turn_id,
        "conversation_id": handle.conversation_id,
        "role": "assistant",
        "assistant_text": "目录已读取完成。",
        "user_text": "列出当前目录",
        "working_dir": str(workspace),
        "native_provider": "codex",
        "native_session_id": "thread-1",
        "completion_state": "completed",
        "trace_count": 1,
        "tool_call_count": 0,
        "process_count": 1,
    }


def test_replace_trace_events_replaces_previous_trace_and_updates_message_stats(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="列出当前目录",
        native_provider="codex",
    )
    store.append_trace_event(handle.turn_id, kind="commentary", summary="旧 commentary")
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    store.replace_trace_events(
        handle.turn_id,
        [
            {
                "kind": "commentary",
                "raw_type": "agent_message",
                "summary": "我先检查目录结构。",
            },
            {
                "kind": "tool_call",
                "raw_type": "function_call",
                "tool_name": "shell_command",
                "call_id": "call_1",
                "summary": "Get-ChildItem -Force",
                "payload": {"arguments": {"command": "Get-ChildItem -Force"}},
            },
            {
                "kind": "tool_result",
                "raw_type": "function_call_output",
                "call_id": "call_1",
                "summary": "README.md\nbot\nfront",
                "payload": {"output": "README.md\nbot\nfront"},
            },
        ],
    )

    trace = store.get_message_trace(handle.assistant_message_id)
    message = store.get_message(handle.assistant_message_id)

    assert [item["summary"] for item in trace["trace"]] == [
        "我先检查目录结构。",
        "Get-ChildItem -Force",
        "README.md\nbot\nfront",
    ]
    assert trace["tool_call_count"] == 1
    assert trace["process_count"] == 1
    assert message["meta"]["trace_count"] == 3
    assert message["meta"]["tool_call_count"] == 1
    assert message["meta"]["process_count"] == 1
