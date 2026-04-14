from pathlib import Path

from bot.models import BotProfile, UserSession
from bot.web.native_history_adapter import load_native_transcript
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
