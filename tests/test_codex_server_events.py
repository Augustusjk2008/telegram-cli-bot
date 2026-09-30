import json

from bot.cli import CodexJsonStreamParser
from bot.codex_server.events import CodexServerEventMapper, tokens
from bot.web.native_history_adapter import consume_stream_trace_chunk


def packet(method, **params):
    return {"method": method, "params": {"threadId": "thread", "turnId": "turn", **params}}


def usage(input_tokens, output_tokens, *, last_input=10, last_output=2):
    return packet("thread/tokenUsage/updated", tokenUsage={
        "total": {"inputTokens": input_tokens, "outputTokens": output_tokens,
                  "cachedInputTokens": input_tokens // 2, "totalTokens": input_tokens + output_tokens},
        "last": {"inputTokens": last_input, "outputTokens": last_output, "totalTokens": last_input + last_output},
        "modelContextWindow": 128000,
    })


def test_commentary_final_tools_compaction_and_once_only_completion():
    mapper = CodexServerEventMapper("thread", tokens({}))
    items = [
        {"id": "comment", "type": "agentMessage", "phase": "commentary", "text": "checking"},
        {"id": "cmd", "type": "commandExecution", "command": "echo hello", "aggregatedOutput": "hello", "exitCode": 0},
        {"id": "patch", "type": "fileChange", "changes": [{"path": "a.py", "diff": "+1"}], "status": "completed"},
        {"id": "mcp", "type": "mcpToolCall", "server": "cluster", "tool": "status", "arguments": {}, "result": {"ok": True}},
        {"id": "web", "type": "webSearch", "query": "test"},
        {"id": "compact", "type": "contextCompaction"},
        {"id": "final", "type": "agentMessage", "phase": "final_answer", "text": "finished"},
        {"id": "late", "type": "agentMessage", "phase": "commentary", "text": "late commentary"},
    ]
    output = []
    for item in items:
        output.extend(mapper.consume(packet("item/started", item=item)))
        if item["type"] == "agentMessage":
            output.extend(mapper.consume(packet("item/agentMessage/delta", itemId=item["id"], delta=item["text"])))
        output.extend(mapper.consume(packet("item/completed", item=item)))
        assert mapper.consume(packet("item/completed", item=item)) == []
    terminal = packet("turn/completed", turn={"id": "turn", "status": "completed", "items": items})
    output.extend(mapper.consume(terminal))
    assert mapper.consume(terminal) == []
    parser = CodexJsonStreamParser(raw_tail_max_bytes=100000, final_text_max_bytes=10000)
    trace, state = [], {"seen": set()}
    for event in output:
        line = json.dumps(event) + "\n"
        parser.consume_line(line)
        trace.extend(consume_stream_trace_chunk("codex", line, state))
    assert parser.result().final_text == "finished"
    assert "checkingchecking" not in parser.preview_text
    assert [e["type"] for e in output].count("turn.completed") == 1
    assert {e.get("tool_name") for e in trace} >= {"command_execution", "apply_patch", "mcp__cluster__status", "web_search"}
    assert any(e.get("kind") == "commentary" and e.get("summary") == "checking" for e in trace)
    assert mapper.context_usage["compaction_count"] == 1
    assert not any(e.get("summary") == "finished" for e in trace)


def test_cumulative_usage_delta_duplicates_stale_and_failure_preserved():
    mapper = CodexServerEventMapper("thread", tokens({"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 50}))
    mapper.turn_id = "turn"
    assert mapper.consume(packet("item/agentMessage/delta", threadId="other", itemId="bad", delta="wrong")) == []
    assert mapper.consume(packet("item/agentMessage/delta", turnId="other", itemId="bad", delta="wrong")) == []
    mapper.consume(usage(120, 15))
    mapper.consume(usage(140, 20))
    mapper.consume(usage(140, 20))
    mapper.consume(usage(120, 15))
    mapper.consume(packet("item/agentMessage/delta", itemId="partial", delta="partial answer"))
    result = mapper.finish(error="process exited")
    assert result[-1]["usage"]["input_tokens"] == 40
    assert result[-1]["usage"]["output_tokens"] == 10
    assert result[-1]["usage"]["cached_input_tokens"] == 20
    assert result[0]["payload"]["content"][0]["text"] == "partial answer"
    assert mapper.context_usage["used_tokens"] == 12
    assert mapper.finish() == []


def test_resume_without_transcript_excludes_historical_prefix():
    mapper = CodexServerEventMapper("thread", None)
    mapper.consume(usage(1020, 102, last_input=20, last_output=2))
    mapper.consume(usage(1040, 106, last_input=20, last_output=4))
    assert mapper.usage["input_tokens"] == 40
    assert mapper.usage["output_tokens"] == 6
