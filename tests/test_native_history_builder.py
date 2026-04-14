from pathlib import Path

from bot.models import BotProfile, UserSession
from bot.web.native_history_adapter import create_stream_trace_state, load_native_transcript, consume_stream_trace_chunk
from bot.web.native_history_builder import build_web_chat_history, merge_native_turns_with_overlay
from bot.web.native_history_locator import LocatedTranscript


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native_history"


def test_build_web_chat_history_maps_codex_tool_calls_and_summary():
    transcript = FIXTURE_DIR / "codex-session.jsonl"
    turns = load_native_transcript("codex", transcript, session_id="thread-1")

    assert turns[-1]["user_text"] == "列出当前目录"
    assert turns[-1]["content"] == "目录已读取完成。"
    assert turns[-1]["meta"]["summary_kind"] == "final"
    assert turns[-1]["meta"]["trace"][0]["kind"] == "commentary"
    assert turns[-1]["meta"]["trace"][1]["kind"] == "tool_call"
    assert turns[-1]["meta"]["trace"][2]["kind"] == "tool_result"


def test_build_web_chat_history_maps_claude_tool_use_and_tool_result():
    transcript = FIXTURE_DIR / "claude-session.jsonl"
    turns = load_native_transcript("claude", transcript, session_id="session-1")

    assert turns[-1]["user_text"] == "查看最近变更"
    assert turns[-1]["content"] == "最近有 1 个文件修改。"
    assert turns[-1]["meta"]["trace"][1]["raw_type"] == "tool_use"
    assert turns[-1]["meta"]["trace"][2]["raw_type"] == "tool_result"


def test_consume_stream_trace_chunk_maps_claude_events_without_type_error():
    state = create_stream_trace_state("claude")

    events = consume_stream_trace_chunk(
        "claude",
        '{"type":"assistant","message":{"content":[{"type":"text","text":"我先检查最近变更。"},{"type":"tool_use","id":"toolu_1","name":"Bash","input":{"command":"git status --short"}}]}}\n',
        state,
    )

    assert [event["kind"] for event in events] == ["commentary", "tool_call"]
    assert events[1]["raw_type"] == "tool_use"
    assert events[1]["summary"] == "git status --short"


def test_build_web_chat_history_maps_payload_style_codex_rollout_and_ignores_reasoning(tmp_path: Path):
    transcript = tmp_path / "codex-rollout.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"检查当前 rollout"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.431Z","type":"event_msg","payload":{"type":"user_message","message":"检查当前 rollout"}}',
                '{"timestamp":"2026-04-14T00:32:53.500Z","type":"response_item","payload":{"type":"reasoning","summary":[],"content":null}}',
                '{"timestamp":"2026-04-14T00:35:09.178Z","type":"event_msg","payload":{"type":"agent_message","message":"我先看一下原始 session 记录。","phase":"commentary"}}',
                '{"timestamp":"2026-04-14T00:35:09.200Z","type":"response_item","payload":{"type":"function_call","name":"shell_command","call_id":"call_1","arguments":"{\\"command\\":\\"Get-Content rollout.jsonl\\"}"}}',
                '{"timestamp":"2026-04-14T00:35:09.240Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_1","output":"LINE 1"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"已经定位到原始 tool call。"}],"phase":"final_answer"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    turns = load_native_transcript("codex", transcript, session_id="thread-1")

    assert turns[-1]["user_text"] == "检查当前 rollout"
    assert turns[-1]["content"] == "已经定位到原始 tool call。"
    assert [item["kind"] for item in turns[-1]["meta"]["trace"]] == [
        "commentary",
        "tool_call",
        "tool_result",
    ]
    assert turns[-1]["meta"]["trace"][1]["summary"] == "Get-Content rollout.jsonl"
    assert turns[-1]["meta"]["trace"][2]["summary"] == "LINE 1"
    assert not any(
        item["kind"] == "unknown" and item["summary"] == "{}"
        for item in turns[-1]["meta"]["trace"]
    )


def test_build_web_chat_history_maps_codex_custom_tool_calls(tmp_path: Path):
    transcript = tmp_path / "codex-custom-tool.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"改一下测试"}]}}',
                '{"timestamp":"2026-04-14T00:35:09.178Z","type":"event_msg","payload":{"type":"agent_message","message":"我先补一个测试。","phase":"commentary"}}',
                '{"timestamp":"2026-04-14T00:35:09.200Z","type":"response_item","payload":{"type":"custom_tool_call","status":"completed","call_id":"call_patch_1","name":"apply_patch","input":"*** Begin Patch\\n*** Update File: demo.txt\\n@@\\n-old\\n+new\\n*** End Patch\\n"}}',
                '{"timestamp":"2026-04-14T00:35:09.240Z","type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call_patch_1","output":"{\\"output\\":\\"Success. Updated the following files:\\\\nM demo.txt\\\\n\\",\\"metadata\\":{\\"exit_code\\":0,\\"duration_seconds\\":0.1}}"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"测试已补好。"}],"phase":"final_answer"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    turns = load_native_transcript("codex", transcript, session_id="thread-1")

    assert turns[-1]["user_text"] == "改一下测试"
    assert turns[-1]["content"] == "测试已补好。"
    assert turns[-1]["meta"]["trace"][1]["kind"] == "tool_call"
    assert turns[-1]["meta"]["trace"][1]["raw_type"] == "custom_tool_call"
    assert turns[-1]["meta"]["trace"][1]["tool_name"] == "apply_patch"
    assert "Update File: demo.txt" in turns[-1]["meta"]["trace"][1]["summary"]
    assert turns[-1]["meta"]["trace"][2]["kind"] == "tool_result"
    assert turns[-1]["meta"]["trace"][2]["raw_type"] == "custom_tool_call_output"
    assert "Success. Updated the following files" in turns[-1]["meta"]["trace"][2]["summary"]


def test_build_web_chat_history_merges_cancelled_overlay_when_native_answer_missing():
    session = UserSession(bot_id=1, bot_alias="main", user_id=100, working_dir="/srv/demo")
    session.web_turn_overlays = [
        {
            "provider": "claude",
            "native_session_id": "session-1",
            "user_text": "继续",
            "started_at": "2026-04-14T10:00:00",
            "updated_at": "2026-04-14T10:00:05",
            "summary_text": "已终止，未返回可显示内容",
            "summary_kind": "partial_preview",
            "completion_state": "cancelled",
            "trace": [{"kind": "cancelled", "summary": "用户终止输出"}],
            "locator_hint": {"cwd": "/srv/demo"},
        }
    ]

    messages = merge_native_turns_with_overlay([], session.web_turn_overlays, limit=20)
    assert messages[-1]["content"] == "已终止，未返回可显示内容"
    assert messages[-1]["meta"]["completion_state"] == "cancelled"


def test_unknown_native_items_are_preserved_as_unknown_trace_events(tmp_path: Path):
    transcript = tmp_path / "unknown.jsonl"
    transcript.write_text(
        '{"type":"response_item","item":{"type":"mystery","value":"x"}}\n',
        encoding="utf-8",
    )

    turns = load_native_transcript("codex", transcript, session_id="thread-1")
    assert turns[-1]["meta"]["trace"][0]["kind"] == "unknown"
    assert turns[-1]["meta"]["trace"][0]["raw_type"] == "mystery"


def test_build_web_chat_history_expands_turns_into_user_and_assistant_messages(monkeypatch):
    transcript = FIXTURE_DIR / "codex-session.jsonl"
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
    )

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=20, include_trace=True)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "列出当前目录"
    assert messages[1]["content"] == "目录已读取完成。"
    assert messages[1]["meta"]["trace"][1]["kind"] == "tool_call"


def test_build_web_chat_history_keeps_user_message_when_limit_is_one_turn(monkeypatch):
    transcript = FIXTURE_DIR / "codex-session.jsonl"
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
    )

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=1)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "列出当前目录"
    assert messages[1]["content"] == "目录已读取完成。"


def test_build_web_chat_history_returns_lightweight_trace_counts_by_default(monkeypatch):
    transcript = FIXTURE_DIR / "codex-session.jsonl"
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
    )

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=20)

    assert messages[1]["meta"]["trace_count"] == 3
    assert messages[1]["meta"]["tool_call_count"] == 1
    assert messages[1]["meta"]["process_count"] == 1
    assert "trace" not in messages[1]["meta"]


def test_load_native_transcript_dedupes_adjacent_duplicate_codex_commentary(tmp_path: Path):
    transcript = tmp_path / "codex-duplicate-commentary.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"修一下重复"}]}}',
                '{"timestamp":"2026-04-14T00:35:09.178Z","type":"event_msg","payload":{"type":"agent_message","message":"我先检查目录结构。","phase":"commentary"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"我先检查目录结构。"}]}}',
                '{"timestamp":"2026-04-14T00:35:10.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"目录已读取完成。"}],"phase":"final_answer"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    turns = load_native_transcript("codex", transcript, session_id="thread-1")

    assert [item["summary"] for item in turns[-1]["meta"]["trace"]] == [
        "我先检查目录结构。",
    ]


def test_load_native_transcript_ignores_codex_exec_instruction_preamble(tmp_path: Path):
    transcript = tmp_path / "codex-preamble.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.400Z","type":"session_meta","payload":{"id":"thread-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.405Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-0"}}',
                '{"timestamp":"2026-04-14T00:32:53.410Z","type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"<permissions instructions>danger-full-access</permissions instructions>"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.420Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"# AGENTS.md instructions for C:\\\\repo\\\\demo\\n<environment_context>cwd</environment_context>"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"修一下聊天记录"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.431Z","type":"event_msg","payload":{"type":"user_message","message":"修一下聊天记录"}}',
                '{"timestamp":"2026-04-14T00:35:09.178Z","type":"event_msg","payload":{"type":"agent_message","message":"我先看一下当前历史。","phase":"commentary"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"聊天记录已经修好。"}],"phase":"final_answer"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    turns = load_native_transcript("codex", transcript, session_id="thread-1")

    assert len(turns) == 1
    assert turns[0]["user_text"] == "修一下聊天记录"
    assert turns[0]["content"] == "聊天记录已经修好。"


def test_build_web_chat_history_ignores_active_native_turn(monkeypatch, tmp_path: Path):
    transcript = tmp_path / "codex-active-turn.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"上一轮问题"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.431Z","type":"event_msg","payload":{"type":"user_message","message":"上一轮问题"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"上一轮已经完成。"}],"phase":"final_answer"}}',
                '{"timestamp":"2026-04-14T00:36:00.000Z","type":"turn_context","payload":{"turn_id":"turn-2"}}',
                '{"timestamp":"2026-04-14T00:36:00.010Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"当前正在执行"}]}}',
                '{"timestamp":"2026-04-14T00:36:00.011Z","type":"event_msg","payload":{"type":"user_message","message":"当前正在执行"}}',
                '{"timestamp":"2026-04-14T00:36:01.000Z","type":"event_msg","payload":{"type":"agent_message","message":"我先检查一下原始 transcript。","phase":"commentary"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
        is_processing=True,
        running_user_text="当前正在执行",
        running_started_at="2026-04-14T00:36:00.000",
        running_updated_at="2026-04-14T00:36:01.000",
        running_preview_text="我先检查一下原始 transcript。",
    )

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=20, include_trace=True)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "上一轮问题"
    assert messages[1]["content"] == "上一轮已经完成。"


def test_build_web_chat_history_ignores_active_partial_turns_after_compaction(monkeypatch, tmp_path: Path):
    transcript = tmp_path / "codex-active-turn-compacted.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T00:32:53.427Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T00:32:53.430Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"上一轮问题"}]}}',
                '{"timestamp":"2026-04-14T00:32:53.431Z","type":"event_msg","payload":{"type":"user_message","message":"上一轮问题"}}',
                '{"timestamp":"2026-04-14T00:35:09.260Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"上一轮已经完成。"}],"phase":"final_answer"}}',
                '{"timestamp":"2026-04-14T00:36:00.000Z","type":"turn_context","payload":{"turn_id":"turn-2"}}',
                '{"timestamp":"2026-04-14T00:36:00.010Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"当前正在执行"}]}}',
                '{"timestamp":"2026-04-14T00:36:00.011Z","type":"event_msg","payload":{"type":"user_message","message":"当前正在执行"}}',
                '{"timestamp":"2026-04-14T00:36:01.000Z","type":"event_msg","payload":{"type":"agent_message","message":"我先检查一下原始 transcript。","phase":"commentary"}}',
                '{"timestamp":"2026-04-14T00:36:10.000Z","type":"turn_context","payload":{"turn_id":"turn-3"}}',
                '{"timestamp":"2026-04-14T00:36:11.000Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"继续恢复上下文。"}],"phase":"commentary"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
        is_processing=True,
        running_user_text="当前正在执行",
        running_started_at="2026-04-14T00:36:00.000",
        running_updated_at="2026-04-14T00:36:11.000",
        running_preview_text="继续恢复上下文。",
    )

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=20, include_trace=True)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "上一轮问题"
    assert messages[1]["content"] == "上一轮已经完成。"


def test_build_web_chat_history_strips_assistant_reread_notice_and_merges_overlay(monkeypatch, tmp_path: Path):
    transcript = tmp_path / "codex-assistant-reread.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-14T06:34:58.784Z","type":"turn_context","payload":{"turn_id":"turn-1"}}',
                '{"timestamp":"2026-04-14T06:34:58.786Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"AGENTS.md 和 CLAUDE.md 已更新，请重新读取。\\r\\n\\r\\ncodex现在能自动调用rg了吗\\r\\n"}]}}',
                '{"timestamp":"2026-04-14T06:34:58.788Z","type":"event_msg","payload":{"type":"user_message","message":"AGENTS.md 和 CLAUDE.md 已更新，请重新读取。\\r\\n\\r\\ncodex现在能自动调用rg了吗\\r\\n"}}',
                '{"timestamp":"2026-04-14T06:36:18.249Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"能，现在会优先直接用 rg。"}],"phase":"final_answer"}}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir="/srv/demo",
        bot_mode="assistant",
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=100,
        working_dir="/srv/demo",
        codex_session_id="thread-1",
    )
    session.web_turn_overlays = [
        {
            "provider": "codex",
            "native_session_id": "thread-1",
            "user_text": "codex现在能自动调用rg了吗",
            "started_at": "2026-04-14T14:34:58.145661",
            "updated_at": "2026-04-14T14:36:18.249453",
            "summary_text": "overlay summary",
            "summary_kind": "final",
            "completion_state": "completed",
            "trace": [],
            "locator_hint": {"cwd": "/srv/demo"},
        }
    ]

    def locate_transcript(session_id: str):
        return LocatedTranscript(
            provider="codex",
            session_id=session_id,
            path=transcript,
            cwd_hint="/srv/demo",
        )

    monkeypatch.setattr("bot.web.native_history_builder.locate_codex_transcript", locate_transcript)

    messages = build_web_chat_history(profile, session, limit=20, include_trace=True)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "codex现在能自动调用rg了吗"
    assert messages[1]["content"] == "能，现在会优先直接用 rg。"


def test_merge_native_turns_with_overlay_sorts_mixed_utc_and_local_timestamps():
    native_turns = [
        {
            "id": "codex-thread-1-1",
            "role": "assistant",
            "content": "later",
            "created_at": "2026-04-14T06:56:28.798Z",
            "updated_at": "2026-04-14T07:11:51.745Z",
            "user_text": "later-question",
            "meta": {
                "completion_state": "completed",
                "summary_kind": "final",
                "trace_version": 1,
                "trace_count": 0,
                "tool_call_count": 0,
                "process_count": 0,
                "native_source": {"provider": "codex", "session_id": "thread-1"},
            },
        }
    ]
    overlays = [
        {
            "provider": "codex",
            "native_session_id": "thread-1",
            "user_text": "earlier-question",
            "started_at": "2026-04-14T14:34:58.145661",
            "updated_at": "2026-04-14T14:36:18.249453",
            "summary_text": "earlier",
            "summary_kind": "final",
            "completion_state": "completed",
            "trace": [],
            "locator_hint": {"cwd": "/srv/demo"},
        }
    ]

    merged = merge_native_turns_with_overlay(native_turns, overlays, limit=20, include_trace=True)

    assert [item["user_text"] for item in merged] == [
        "earlier-question",
        "later-question",
    ]
