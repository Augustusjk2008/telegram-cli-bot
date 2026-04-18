from pathlib import Path

from bot.web.chat_store import ChatStore, LOCAL_CHAT_DB_RELATIVE_PATH


def test_begin_turn_creates_project_local_db_and_streaming_rows(tmp_path: Path):
    store = ChatStore(tmp_path)

    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(tmp_path),
        session_epoch=1,
        user_text="列出当前目录",
        native_provider="codex",
    )

    db_path = tmp_path / LOCAL_CHAT_DB_RELATIVE_PATH
    assert db_path.exists()

    items = store.list_messages(handle.conversation_id)
    assert [(item["role"], item["content"], item["state"]) for item in items] == [
        ("user", "列出当前目录", "done"),
        ("assistant", "", "streaming"),
    ]


def test_begin_turn_reuses_active_conversation_within_same_session_epoch(tmp_path: Path):
    store = ChatStore(tmp_path)

    first = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(tmp_path),
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
        working_dir=str(tmp_path),
        session_epoch=1,
        user_text="第二问",
        native_provider="codex",
    )

    assert first.conversation_id == second.conversation_id
    items = store.list_messages(first.conversation_id)
    assert [item["content"] for item in items] == ["第一问", "", "第二问", ""]


def test_finalize_turn_reuses_same_assistant_message_and_exposes_trace(tmp_path: Path):
    store = ChatStore(tmp_path)
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(tmp_path),
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
