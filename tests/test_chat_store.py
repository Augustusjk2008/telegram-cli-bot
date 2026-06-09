import json
import sqlite3
from pathlib import Path

import bot.runtime_paths as runtime_paths
from bot.web import chat_store as chat_store_module
from bot.web.chat_store import ChatStore, LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH


class TrackingConnection:
    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "closed", False)

    def close(self):
        object.__setattr__(self, "closed", True)
        return self._conn.close()

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)

    def backup(self, target, *args, **kwargs):
        return self._conn.backup(getattr(target, "_conn", target), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name in {"_conn", "closed"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._conn, name, value)


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


def test_chat_store_lists_multiple_conversations_for_same_scope(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    first = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        title="修复 diff",
    )
    second = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        title="图片 payload",
    )

    assert first != second
    rows = store.list_conversations(bot_id=1, user_id=1001, working_dir=str(workspace), limit=10)

    assert [row["title"] for row in rows] == ["图片 payload", "修复 diff"]
    assert [row["id"] for row in rows] == [second, first]


def test_chat_store_conversations_are_scoped_by_agent(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    main_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="main",
        title="主会话",
    )
    reviewer_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="reviewer",
        title="审查会话",
    )

    main_rows = store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="main",
        limit=10,
    )
    reviewer_rows = store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="reviewer",
        limit=10,
    )

    assert [row["id"] for row in main_rows] == [main_id]
    assert [row["id"] for row in reviewer_rows] == [reviewer_id]
    assert main_rows[0]["agent_id"] == "main"
    assert reviewer_rows[0]["agent_id"] == "reviewer"


def test_chat_store_archives_all_bot_conversations_in_workspace(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    main_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="main",
        title="主会话",
    )
    reviewer_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="reviewer",
        title="审查会话",
    )
    store.create_conversation(
        bot_id=2,
        bot_alias="other",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        title="其它 bot",
    )
    ChatStore(other_workspace).create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(other_workspace),
        session_epoch=1,
        native_provider="codex",
        title="其它工作区",
    )

    deleted = store.archive_bot_conversations(bot_id=1, user_id=1001, working_dir=str(workspace))

    assert deleted == 2
    assert store.list_conversations(bot_id=1, user_id=1001, working_dir=str(workspace), agent_id="main") == []
    assert store.list_conversations(bot_id=1, user_id=1001, working_dir=str(workspace), agent_id="reviewer") == []
    archived_ids = {
        row["id"]
        for row in store.list_conversations(
            bot_id=1,
            user_id=1001,
            working_dir=str(workspace),
            agent_id="main",
            include_archived=True,
        )
    } | {
        row["id"]
        for row in store.list_conversations(
            bot_id=1,
            user_id=1001,
            working_dir=str(workspace),
            agent_id="reviewer",
            include_archived=True,
        )
    }
    assert archived_ids == {main_id, reviewer_id}
    assert len(store.list_conversations(bot_id=2, user_id=1001, working_dir=str(workspace))) == 1
    assert len(ChatStore(other_workspace).list_conversations(bot_id=1, user_id=1001, working_dir=str(other_workspace))) == 1


def test_chat_store_provider_scope_excludes_native_conversation_id(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    native_handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="原生",
        native_provider="native_agent",
    )
    store.complete_turn(native_handle, content="原生回复", completion_state="completed", native_session_id="native-1")

    items = store.list_active_history(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        session_epoch=1,
        conversation_id=native_handle.conversation_id,
        native_provider_exclude="native_agent",
    )

    assert items == []


def test_chat_store_list_and_archive_honor_provider_and_agent_scope(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    main_cli_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="main",
        title="CLI",
    )
    main_native_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="native_agent",
        agent_id="main",
        title="Native",
    )
    reviewer_cli_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        agent_id="reviewer",
        title="Reviewer",
    )

    cli_rows = store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="main",
        native_provider_exclude="native_agent",
        limit=10,
    )
    native_rows = store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="main",
        native_provider="native_agent",
        limit=10,
    )

    assert [row["id"] for row in cli_rows] == [main_cli_id]
    assert [row["id"] for row in native_rows] == [main_native_id]

    deleted = store.archive_bot_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="main",
        native_provider="native_agent",
    )

    assert deleted == 1
    assert {
        row["id"]
        for row in store.list_conversations(
            bot_id=1,
            user_id=1001,
            working_dir=str(workspace),
            agent_id="main",
            include_archived=True,
            limit=10,
        )
    } == {main_cli_id, main_native_id}
    assert [row["id"] for row in store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="main",
        native_provider_exclude="native_agent",
        limit=10,
    )] == [main_cli_id]
    assert [row["id"] for row in store.list_conversations(
        bot_id=1,
        user_id=1001,
        working_dir=str(workspace),
        agent_id="reviewer",
        limit=10,
    )] == [reviewer_cli_id]


def test_chat_store_selectable_conversation_preserves_native_session(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    conversation_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="codex",
        title="继续旧 Codex",
    )
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        user_text="hello",
        native_provider="codex",
        conversation_id=conversation_id,
    )
    store.complete_turn(handle, content="world", completion_state="completed", native_session_id="thread-1")

    summary = store.get_conversation(conversation_id)

    assert summary["native_session_id"] == "thread-1"
    assert summary["message_count"] == 2
    assert summary["last_message_preview"] == "world"


def test_chat_store_updates_conversation_native_session_meta(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    conversation_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="native_agent",
        title="Native",
    )

    store.set_conversation_native_session(
        conversation_id,
        "sess-1",
        {"cwd": str(workspace), "model_id": "anthropic/sonnet", "opencode_agent": "reviewer"},
    )

    assert store.get_conversation_native_session(conversation_id) == {
        "session_id": "sess-1",
        "meta": {"cwd": str(workspace), "model_id": "anthropic/sonnet", "opencode_agent": "reviewer"},
    }
    assert store.get_conversation(conversation_id)["native_session_meta"]["model_id"] == "anthropic/sonnet"


def test_chat_store_upgrades_legacy_conversation_without_native_session_meta(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    store.db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                bot_alias TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL DEFAULT 'main',
                bot_mode TEXT NOT NULL,
                cli_type TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                session_epoch INTEGER NOT NULL,
                status TEXT NOT NULL,
                native_provider TEXT,
                native_session_id TEXT,
                assistant_home TEXT,
                managed_prompt_hash TEXT,
                prompt_surface_version TEXT,
                agent_prompt_hash TEXT,
                title TEXT,
                last_message_preview TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO conversations (
                id,
                bot_id,
                bot_alias,
                user_id,
                agent_id,
                bot_mode,
                cli_type,
                working_dir,
                session_epoch,
                status,
                native_provider,
                native_session_id,
                title,
                last_message_preview,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "conv-old",
                1,
                "main",
                1001,
                "main",
                "cli",
                "codex",
                str(workspace),
                1,
                "active",
                "native_agent",
                "sess-old",
                "旧会话",
                "旧回复",
                "2026-06-09T00:00:00+00:00",
                "2026-06-09T00:00:00+00:00",
            ),
        )
    chat_store_module.clear_chat_store_prepare_cache()

    summary = store.get_conversation("conv-old")

    assert summary["native_session_id"] == "sess-old"
    assert summary["native_session_meta"] == {}
    with sqlite3.connect(store.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    assert "native_session_meta_json" in columns


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


def test_chat_store_upserts_tool_result_by_call_id(monkeypatch, tmp_path: Path):
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

    store.append_trace_events(handle.turn_id, [
        {"kind": "tool_call", "summary": "dir", "tool_name": "bash", "call_id": "call_1"},
        {"kind": "tool_result", "summary": "半截", "call_id": "call_1", "payload": {"output": "半截"}},
        {"kind": "tool_result", "summary": "完整结果", "call_id": "call_1", "payload": {"output": "完整结果"}},
    ])
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [item["kind"] for item in trace["trace"]] == ["tool_call", "tool_result"]
    assert [item["ordinal"] for item in trace["trace"]] == [1, 2]
    assert trace["trace"][1]["summary"] == "完整结果"
    assert trace["trace"][1]["payload"] == {"output": "完整结果"}


def test_chat_store_normalizes_legacy_duplicate_tool_results_and_commentary_order(monkeypatch, tmp_path: Path):
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
    store.append_trace_event(handle.turn_id, kind="tool_call", summary="dir", tool_name="bash", call_id="call_1")
    store.append_trace_event(
        handle.turn_id,
        kind="tool_result",
        summary="半截",
        call_id="call_1",
        payload={"output": "半截", "state": "running"},
    )
    store.append_trace_event(
        handle.turn_id,
        kind="tool_result",
        summary="完整结果",
        call_id="call_1",
        payload={"output": "完整结果", "state": "completed"},
    )
    store.append_trace_event(
        handle.turn_id,
        kind="commentary",
        raw_type="message.text.reclassified",
        summary="我先读取文件。",
        call_id="call_1",
    )
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [item["kind"] for item in trace["trace"]] == ["commentary", "tool_call", "tool_result"]
    assert trace["trace"][0]["summary"] == "我先读取文件。"
    assert trace["trace"][2]["summary"] == "完整结果"
    assert trace["trace_count"] == 3


def test_chat_store_keeps_later_commentary_with_following_tool_call(monkeypatch, tmp_path: Path):
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
    store.append_trace_events(handle.turn_id, [
        {
            "kind": "commentary",
            "raw_type": "message.text.reclassified",
            "summary": "先读取目录。",
            "call_id": "call_1",
        },
        {"kind": "tool_call", "summary": "dir", "tool_name": "bash", "call_id": "call_1"},
        {"kind": "tool_result", "summary": "目录结果", "call_id": "call_1", "payload": {"output": "目录结果"}},
        {
            "kind": "commentary",
            "raw_type": "message.text.reclassified",
            "summary": "再读取文件。",
            "call_id": "call_2",
        },
        {"kind": "tool_call", "summary": "type README.md", "tool_name": "bash", "call_id": "call_2"},
    ])
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [(item["kind"], item["summary"]) for item in trace["trace"]] == [
        ("commentary", "先读取目录。"),
        ("tool_call", "dir"),
        ("tool_result", "目录结果"),
        ("commentary", "再读取文件。"),
        ("tool_call", "type README.md"),
    ]


def test_chat_store_deduplicates_reclassified_commentary_by_message_id(monkeypatch, tmp_path: Path):
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
    store.append_trace_events(handle.turn_id, [
        {
            "kind": "commentary",
            "raw_type": "message.text.reclassified",
            "summary": "我先读取文件。",
            "call_id": "call_1",
            "payload": {"messageID": "assistant-tool", "reason": "tool-call"},
        },
        {"kind": "tool_call", "summary": "dir", "tool_name": "bash", "call_id": "call_1"},
        {
            "kind": "commentary",
            "raw_type": "message.text.reclassified",
            "summary": "我先读取\n文件。",
            "call_id": "evt_1",
            "payload": {"messageID": "assistant-tool", "reason": "tool-calls"},
        },
    ])
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [(item["kind"], item["summary"]) for item in trace["trace"]] == [
        ("commentary", "我先读取文件。"),
        ("tool_call", "dir"),
    ]


def test_chat_store_reclassifies_legacy_file_events_as_process_events(monkeypatch, tmp_path: Path):
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
    store.append_trace_events(handle.turn_id, [
        {
            "kind": "tool_call",
            "raw_type": "file.edited",
            "summary": "file.edited",
            "call_id": "evt_file_edited",
        },
        {
            "kind": "tool_call",
            "raw_type": "file.watcher.updated",
            "summary": "file.watcher.updated",
            "call_id": "evt_file_watcher",
        },
        {"kind": "tool_call", "raw_type": "message.part.updated", "summary": "dir", "call_id": "call_1"},
    ])
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [item["kind"] for item in trace["trace"]] == ["event", "event", "tool_call"]
    assert trace["tool_call_count"] == 1
    assert trace["process_count"] == 2


def test_chat_store_moves_late_reclassified_commentary_before_matching_tool_call(monkeypatch, tmp_path: Path):
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
    store.append_trace_events(handle.turn_id, [
        {"kind": "tool_call", "summary": "dir", "tool_name": "bash", "call_id": "call_1"},
        {
            "kind": "commentary",
            "raw_type": "message.text.reclassified",
            "summary": "我先读取文件。",
            "call_id": "call_1",
        },
        {"kind": "tool_result", "summary": "目录结果", "call_id": "call_1", "payload": {"output": "目录结果"}},
    ])
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="thread-1",
    )

    trace = store.get_message_trace(handle.assistant_message_id)

    assert [(item["kind"], item["summary"]) for item in trace["trace"]] == [
        ("commentary", "我先读取文件。"),
        ("tool_call", "dir"),
        ("tool_result", "目录结果"),
    ]


def test_user_message_does_not_expose_native_trace_meta(monkeypatch, tmp_path: Path):
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
        native_provider="native_agent",
    )
    store.append_trace_event(handle.turn_id, kind="tool_call", summary="dir", tool_name="bash", call_id="call_1")
    store.complete_turn(
        handle,
        content="目录已读取完成。",
        completion_state="completed",
        native_session_id="native-1",
    )

    user_message, assistant_message = store.list_messages(handle.conversation_id)

    assert user_message["role"] == "user"
    assert "trace_count" not in user_message["meta"]
    assert "tool_call_count" not in user_message["meta"]
    assert "process_count" not in user_message["meta"]
    assert "native_source" not in user_message["meta"]
    assert assistant_message["meta"]["trace_count"] == 1
    assert assistant_message["meta"]["native_source"]["provider"] == "native_agent"


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
        "trace_recovery_attempted_at": "",
        "trace_recovery_status": "",
        "trace_count": 1,
        "tool_call_count": 0,
        "process_count": 1,
    }
