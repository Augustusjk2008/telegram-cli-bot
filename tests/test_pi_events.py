from __future__ import annotations

from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.events import unwrap_event
from bot.native_agent.pi_events import (
    build_extension_ui_response,
    extract_context_usage,
    extract_session_id,
    pi_json_to_events,
)


def _payloads(raw: dict, **kwargs) -> list[dict]:
    return [event["payload"] for event in pi_json_to_events(raw, **kwargs)]


def _apply_all(raw_events: list[dict]) -> tuple[NativeAgentAggregator, list]:
    aggregator = NativeAgentAggregator(user_message_id="user-1")
    results = []
    for raw in raw_events:
        for mapped in pi_json_to_events(raw, cwd="/repo", fallback_session_id="sess-1"):
            event = unwrap_event(mapped)
            assert event is not None
            results.append(aggregator.apply(event))
    return aggregator, results


def test_pi_events_maps_text_turn_to_canonical_events() -> None:
    raw_events = [
        {"type": "agent_start", "session_id": "sess-1"},
        {"type": "turn_start", "session_id": "sess-1"},
        {"type": "message_start", "session_id": "sess-1", "message_id": "msg-1", "role": "assistant"},
        {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "delta": "你"},
        {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "delta": "好"},
        {"type": "message_end", "session_id": "sess-1", "message_id": "msg-1"},
        {"type": "turn_end", "session_id": "sess-1"},
    ]

    mapped = [payload for raw in raw_events for payload in _payloads(raw, cwd="/repo")]
    aggregator, results = _apply_all(raw_events)

    assert [payload["type"] for payload in mapped] == [
        "session.status",
        "session.status",
        "message.updated",
        "message.part.delta",
        "message.part.delta",
        "message.updated",
        "session.idle",
    ]
    assert aggregator.text() == "你好"
    assert results[-1].done is True


def test_pi_events_maps_full_text_without_duplicate_delta() -> None:
    aggregator, results = _apply_all([
        {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "content": "你"},
        {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "content": "你好"},
        {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "delta": "！"},
    ])

    assert [result.delta for result in results] == ["你", "好", "！"]
    assert aggregator.text() == "你好！"


def test_pi_events_maps_assistant_stop_error_to_native_error() -> None:
    raw = {
        "type": "message_start",
        "message": {
            "role": "assistant",
            "content": [],
            "stopReason": "error",
            "errorMessage": "403 Your request was blocked.",
        },
    }

    [mapped] = pi_json_to_events(raw, cwd="/repo", fallback_session_id="sess-1", assistant_message_id="msg-1")
    event = unwrap_event(mapped)
    assert event is not None

    result = NativeAgentAggregator(user_message_id="user-1").apply(event)

    assert mapped["payload"]["type"] == "message.updated"
    assert mapped["payload"]["message"]["state"] == "error"
    assert result.error == "403 Your request was blocked."


def test_pi_events_maps_turn_end_error_without_message_end() -> None:
    raw = {
        "type": "turn_end",
        "message": {
            "role": "assistant",
            "content": [],
            "stopReason": "error",
            "errorMessage": "403 Your request was blocked.",
        },
    }

    [payload] = _payloads(raw, cwd="/repo", fallback_session_id="sess-1", assistant_message_id="msg-1")

    assert payload["type"] == "session.error"
    assert payload["error"] == "403 Your request was blocked."


def test_pi_events_maps_tool_lifecycle_to_single_tool_part() -> None:
    raw_events = [
        {
            "type": "tool_execution_start",
            "session_id": "sess-1",
            "message_id": "msg-1",
            "call_id": "call-1",
            "tool": "shell_command",
            "args": {"command": "dir"},
        },
        {
            "type": "tool_execution_update",
            "session_id": "sess-1",
            "message_id": "msg-1",
            "toolCallId": "call-1",
            "output": "partial",
        },
        {
            "type": "tool_execution_end",
            "session_id": "sess-1",
            "message_id": "msg-1",
            "id": "call-1",
            "result": "done",
        },
    ]

    payloads = [payload for raw in raw_events for payload in _payloads(raw)]
    parts = [payload["part"] for payload in payloads]
    aggregator, results = _apply_all(raw_events)

    assert {part["id"] for part in parts} == {"call-1"}
    assert {part["callID"] for part in parts} == {"call-1"}
    assert parts[0]["tool"] == "shell_command"
    assert parts[0]["arguments"] == {"command": "dir"}
    assert parts[-1]["output"] == "done"
    assert any(trace["kind"] == "tool_call" for result in results for trace in result.trace)
    assert any(trace["kind"] == "tool_result" for result in results for trace in result.trace)
    assert aggregator.text() == ""


def test_pi_events_maps_interactive_extension_requests() -> None:
    for ui_kind in ("confirm", "select", "input", "editor"):
        [payload] = _payloads({
            "type": "extension_ui_request",
            "session_id": "sess-1",
            "request_id": f"req-{ui_kind}",
            "uiKind": ui_kind,
            "title": "需要输入",
            "message": "请选择",
            "options": ["a", "b"],
            "defaultValue": "a",
            "placeholder": "输入",
        })

        assert payload["type"] == "permission.updated"
        permission = payload["permission"]
        assert permission["id"] == f"req-{ui_kind}"
        assert permission["uiKind"] == ui_kind
        assert permission["options"] == ["a", "b"]
        assert permission["defaultValue"] == "a"
        assert permission["placeholder"] == "输入"
        assert permission["raw"]["type"] == "extension_ui_request"

    assert build_extension_ui_response("req-input", accepted=True, value="ok") == {
        "type": "extension_ui_response",
        "id": "req-input",
        "response": {"accepted": True, "value": "ok"},
    }


def test_pi_events_maps_notify_status_widget_as_non_permission() -> None:
    for ui_kind in ("notify", "setStatus", "setWidget"):
        [payload] = _payloads({
            "type": "extension_ui_request",
            "session_id": "sess-1",
            "id": f"req-{ui_kind}",
            "uiKind": ui_kind,
            "message": "正在处理",
        })

        assert payload["type"] == "session.status"
        assert "permission" not in payload
        assert payload["status"] == "正在处理"


def test_pi_events_maps_diagnostic_to_trace_event() -> None:
    [payload] = _payloads({
        "type": "diagnostic",
        "source": "pi_rpc_transport",
        "level": "warning",
        "message": "bad json",
        "raw": "not-json",
    })
    event = unwrap_event({"directory": "/repo", "payload": payload})
    assert event is not None

    result = NativeAgentAggregator(user_message_id="user-1").apply(event)

    assert payload["type"] == "pi.diagnostic"
    assert result.trace[0]["kind"] == "event"
    assert result.trace[0]["summary"] == "bad json"


def test_pi_events_extracts_session_id_and_context_usage() -> None:
    raw = {
        "type": "turn_end",
        "conversation_id": "sess-1",
        "usage": {
            "input_tokens": 10,
            "cache_read_tokens": 2,
            "output_tokens": 3,
            "cost": 0.01,
            "model": "pi-model",
        },
    }

    assert extract_session_id(raw) == "sess-1"
    assert extract_context_usage(raw) == {
        "input_tokens": 10,
        "cache_read_tokens": 2,
        "output_tokens": 3,
        "cost": 0.01,
        "model": "pi-model",
    }


def test_pi_events_keeps_raw_and_cwd() -> None:
    raw = {"type": "message_update", "session_id": "sess-1", "message_id": "msg-1", "delta": "ok"}
    [event] = pi_json_to_events(raw, cwd="/repo")

    assert event["directory"] == "/repo"
    assert event["payload"]["raw"] is raw


def test_pi_events_ignores_user_message_updates() -> None:
    assert pi_json_to_events({
        "type": "message_update",
        "session_id": "sess-1",
        "message_id": "user-1",
        "role": "user",
        "content": "不要进最终回答",
    }) == []


def test_pi_events_turn_end_does_not_finish_before_final_text() -> None:
    aggregator, results = _apply_all([
        {"type": "turn_start", "session_id": "sess-1"},
        {"type": "turn_end", "session_id": "sess-1"},
    ])

    assert aggregator.text() == ""
    assert results[-1].done is False
