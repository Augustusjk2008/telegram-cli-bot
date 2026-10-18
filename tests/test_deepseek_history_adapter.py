from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.models import UserSession
from bot.web import chat_history_service
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer
from bot.web.chat_store import ChatStore
from bot.web.native_history_adapter import consume_stream_trace_chunk, create_stream_trace_state


def _jsonl(*events: dict) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def test_deepseek_trace_pairs_interleaved_tools_and_separates_thinking_from_body():
    state = create_stream_trace_state("deepseek")
    raw = _jsonl(
        {"type": "session", "sessionId": "session-tools", "cwd": "workspace"},
        {"type": "status", "phase": "turn_start", "turn": 1},
        {"type": "status", "phase": "step_start", "turn": 1, "step": 1},
        {"type": "thinking", "text": "先读取文件", "truncated": True},
        {"type": "tool_call", "callId": "read-1", "tool": "read", "input": {"file_path": "probe.txt"}},
        {"type": "tool_call", "callId": "shell-1", "tool": "pwsh", "input": {"command": "Get-Location"}},
        {"type": "tool_result", "callId": "shell-1", "status": "completed", "result": "workspace"},
        {"type": "tool_result", "callId": "read-1", "status": "completed", "result": {"text": "中文内容"}},
        {"type": "text", "text": "读取完成", "truncated": True},
        {"type": "final", "text": "读取完成，工作目录为 workspace"},
        {"type": "extension", "data": "ignored"},
    )
    trace = []
    for index in range(0, len(raw), 17):
        trace.extend(consume_stream_trace_chunk("deepseek", raw[index:index + 17], state))

    calls = {event["call_id"]: event for event in trace if event["kind"] == "tool_call"}
    results = {event["call_id"]: event for event in trace if event["kind"] == "tool_result"}
    assert calls.keys() == results.keys() == {"read-1", "shell-1"}
    assert calls["read-1"]["tool_name"] == "read"
    assert calls["shell-1"]["payload"]["input"] == {"command": "Get-Location"}
    assert results["read-1"]["payload"]["result"] == {"text": "中文内容"}
    assert results["shell-1"]["summary"] == "workspace"
    thinking = next(event for event in trace if event["kind"] == "reasoning")
    assert thinking["summary"] == "先读取文件"
    assert thinking["payload"]["truncated"] is True
    assert all(event["kind"] != "permission" for event in trace)
    assert all(event["payload"]["type"] not in {"session", "text", "final", "extension"} for event in trace)


def test_deepseek_trace_deduplicates_step_replay_without_losing_later_steps():
    state = create_stream_trace_state("deepseek")
    trace = []
    for step in (1, 1, 2):
        trace.extend(consume_stream_trace_chunk("deepseek", _jsonl(
            {"type": "status", "phase": "step_start", "turn": 1, "step": step},
            {"type": "thinking", "text": "检查结果"},
            {"type": "status", "phase": "step_end", "turn": 1, "step": step,
             "usage": {"inputTokens": 120, "cacheReadTokens": 384}},
        ), state))

    assert len(trace) == 6
    assert [event["payload"]["step"] for event in trace if event["kind"] == "reasoning"] == [1, 2]
    assert all(event["payload"]["usage"] == {"inputTokens": 120, "cacheReadTokens": 384}
               for event in trace if event["raw_type"] == "deepseek_step_end")


@pytest.mark.parametrize(("reason", "kind"), [("error", "error"), ("aborted", "cancelled")])
def test_deepseek_trace_preserves_failure_and_stop(reason, kind):
    trace = consume_stream_trace_chunk("deepseek", _jsonl(
        {"type": "error", "message": "Session directory mismatch", "code": "cwd_mismatch"},
        {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": reason}},
    ), create_stream_trace_state("deepseek"))

    assert trace[0]["kind"] == "error"
    assert trace[0]["summary"] == "Session directory mismatch"
    assert trace[0]["payload"]["code"] == "cwd_mismatch"
    assert trace[1]["kind"] == kind
    assert trace[1]["payload"]["reason"] == {"kind": reason}


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_state", ["completed", "error", "cancelled"])
async def test_deepseek_history_refresh_preserves_saved_trace_usage_and_session(
    tmp_path, monkeypatch, completion_state,
):
    profile = SimpleNamespace(alias="main", cli_type="deepseek", cli_path="dsh")
    session = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(tmp_path), _persist_enabled=False)
    service = ChatHistoryService(ChatStore(tmp_path))
    handle = service.start_turn(profile=profile, session=session, user_text="读取文件", native_provider="deepseek")
    trace = consume_stream_trace_chunk("deepseek", _jsonl(
        {"type": "thinking", "text": "读取中", "truncated": True},
        {"type": "tool_call", "callId": "call-1", "tool": "read", "input": {"file_path": "probe.txt"}},
        {"type": "tool_result", "callId": "call-1", "status": "completed", "result": "文件内容"},
    ), create_stream_trace_state("deepseek"))
    buffer = StreamingPersistenceBuffer(service, handle, loop=asyncio.get_running_loop())
    buffer.queue_preview("部分回复")
    for event in trace:
        buffer.queue_trace(event)
    await buffer.close()
    usage = {"provider": "deepseek", "source": "deepseek_step_usage", "session_id": "session-saved",
             "input_tokens": 5928, "output_tokens": 158, "cache_read_tokens": 6656,
             "cache_write_tokens": 0, "total_tokens": 12742}
    service.complete_turn(handle, content="文件内容", completion_state=completion_state,
                          native_session_id="session-saved", context_usage=usage)

    restored = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(tmp_path), _persist_enabled=False)
    restored.deepseek_session_id = "stale-session"
    reopened = ChatHistoryService(ChatStore(tmp_path))
    native_scan = Mock(side_effect=AssertionError("DeepSeek history must use project records"))
    monkeypatch.setattr(chat_history_service, "resolve_native_trace_for_turn", native_scan)
    history = reopened.list_history(profile, restored)
    snapshot = reopened.build_session_snapshot(profile, restored)
    saved_trace = reopened.get_message_trace(profile, restored, handle.assistant_message_id)

    assert [message["content"] for message in history] == ["读取文件", "文件内容"]
    assert history[-1]["meta"]["context_usage"] == usage
    assert snapshot["session_ids"]["deepseek_session_id"] == "session-saved"
    assert snapshot["active_conversation_id"] == handle.conversation_id
    assert snapshot["running_reply"] is None
    assert [(event["kind"], event["summary"]) for event in saved_trace["trace"]] == [
        (event["kind"], event["summary"]) for event in trace
    ]
    assert saved_trace["trace"][0]["payload"]["truncated"] is True
    assert reopened.store.get_conversation(handle.conversation_id)["native_provider"] == "deepseek"
    assert native_scan.call_count == 0


@pytest.mark.parametrize(("user_id", "agent_id"), [(3, "main"), (2, "reviewer")])
def test_deepseek_history_restore_keeps_user_and_agent_scope(tmp_path, user_id, agent_id):
    profile = SimpleNamespace(alias="main", cli_type="deepseek", cli_path="dsh")
    service = ChatHistoryService(ChatStore(tmp_path))
    owner = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(tmp_path), _persist_enabled=False)
    handle = service.start_turn(profile=profile, session=owner, user_text="private", native_provider="deepseek")
    service.complete_turn(handle, content="private reply", completion_state="completed", native_session_id="owner-session")

    other = UserSession(bot_id=1, bot_alias="main", user_id=user_id, agent_id=agent_id,
                        working_dir=str(tmp_path), _persist_enabled=False)
    assert service.list_history(profile, other) == []
    assert service.build_session_snapshot(profile, other)["session_ids"]["deepseek_session_id"] is None
