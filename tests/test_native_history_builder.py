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

    messages = build_web_chat_history(profile, session, limit=20)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "列出当前目录"
    assert messages[1]["content"] == "目录已读取完成。"
    assert messages[1]["meta"]["trace"][1]["kind"] == "tool_call"
