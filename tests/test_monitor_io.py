from __future__ import annotations

import sys
from types import SimpleNamespace

import scripts.monitor_io as monitor_io


def test_poll_web_history_prints_message_when_existing_item_changes(monkeypatch, capsys):
    snapshots = [
        {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": "msg_assistant",
                        "role": "assistant",
                        "content": "",
                        "state": "streaming",
                        "meta": {"completion_state": "streaming"},
                    }
                ]
            },
        },
        {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": "msg_assistant",
                        "role": "assistant",
                        "content": "最终输出",
                        "state": "done",
                        "meta": {"completion_state": "completed"},
                    }
                ]
            },
        },
    ]

    def fake_request_json(*args, **kwargs):
        return snapshots.pop(0)

    monkeypatch.setattr(monitor_io, "request_json", fake_request_json)
    args = SimpleNamespace(
        web_url="http://127.0.0.1:8765",
        password="secret",
        alias="agent-test",
        limit=80,
        execution_mode="native_agent",
        agent_id="main",
        show_trace=False,
    )
    state = monitor_io.MonitorState(recorder=monitor_io.Recorder(None, "test"))

    monitor_io.poll_web_history(args, state)
    capsys.readouterr()

    monitor_io.poll_web_history(args, state)
    output = capsys.readouterr().out

    assert "WEB agent-test assistant (done, completed): 最终输出" in output


def test_poll_web_history_does_not_reprint_user_when_state_changes(monkeypatch, capsys):
    snapshots = [
        {
            "data": {
                "items": [
                    {
                        "id": "msg_user",
                        "role": "user",
                        "content": "问题",
                        "state": "done",
                        "meta": {"completion_state": "streaming"},
                    }
                ]
            },
        },
        {
            "data": {
                "items": [
                    {
                        "id": "msg_user",
                        "role": "user",
                        "content": "问题",
                        "state": "done",
                        "meta": {"completion_state": "completed"},
                    }
                ]
            },
        },
    ]

    monkeypatch.setattr(monitor_io, "request_json", lambda *args, **kwargs: snapshots.pop(0))
    args = SimpleNamespace(
        web_url="http://127.0.0.1:8765",
        password="secret",
        alias="agent-test",
        limit=80,
        execution_mode="native_agent",
        agent_id="main",
        show_trace=False,
    )
    state = monitor_io.MonitorState(recorder=monitor_io.Recorder(None, "test"))

    monitor_io.poll_web_history(args, state)
    capsys.readouterr()

    monitor_io.poll_web_history(args, state)

    assert capsys.readouterr().out == ""


def test_normalize_opencode_event_accepts_official_properties_shape():
    event = monitor_io.normalize_opencode_event(
        {
            "type": "message.part.updated",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "msg-1",
                "partID": "part-1",
                "delta": "hi",
                "status": "running",
                "toolCallId": "call-1",
                "permission": {"id": "perm-1", "state": "pending"},
                "part": {"type": "tool", "toolName": "shell_command"},
            },
        },
        alias="agent-test",
    )

    assert event["event_type"] == "message.part.updated"
    assert event["native_session_id"] == "sess-1"
    assert event["opencode_message_id"] == "msg-1"
    assert event["part_id"] == "part-1"
    assert event["delta_text"] == "hi"
    assert event["status"] == "running"
    assert event["call_id"] == "call-1"
    assert event["tool_name"] == "shell_command"
    assert event["permission"]["id"] == "perm-1"
    assert event["tool_count"] == 1


def test_monitor_opencode_once_returns_after_first_event(monkeypatch, capsys):
    events = iter([{"type": "server.connected"}, {"type": "session.idle"}])
    monkeypatch.setattr(monitor_io, "resolve_opencode_url", lambda *_args, **_kwargs: "http://127.0.0.1:4096")
    monkeypatch.setattr(monitor_io, "stream_sse", lambda *_args, **_kwargs: events)
    args = SimpleNamespace(
        opencode_url="auto",
        opencode_username="opencode",
        opencode_password="secret",
        password="",
        alias="agent-test",
        capture_opencode_sse=True,
    )
    state = monitor_io.MonitorState(recorder=monitor_io.Recorder(None, "test"))

    monitor_io.monitor_opencode(args, state, max_events=1)

    output = capsys.readouterr().out
    assert "opencode SSE connected: http://127.0.0.1:4096/global/event" in output


def test_main_once_capture_opencode_sse_fails_on_connection_error(monkeypatch, tmp_path, capsys):
    def fail_stream(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(sys, "argv", [
        "monitor_io.py",
        "--no-web",
        "--capture-opencode-sse",
        "--opencode-url",
        "http://127.0.0.1:1",
        "--opencode-password",
        "x",
        "--once",
        "--record-dir",
        str(tmp_path),
    ])
    monkeypatch.setattr(monitor_io, "stream_sse", fail_stream)

    code = monitor_io.main()

    output = capsys.readouterr().out
    assert code == 1
    assert "error: connection refused" in output
    assert "opencode SSE connected" not in output


def test_main_compare_no_web_capture_opencode_sse_fails_before_report(monkeypatch, tmp_path):
    calls: list[str] = []

    def fail_stream(*_args, **_kwargs):
        calls.append("capture")
        raise OSError("connection refused")

    def fake_report(*_args, **_kwargs):
        calls.append("report")
        return {"summary": {"issue_count": 0}}

    monkeypatch.setattr(sys, "argv", [
        "monitor_io.py",
        "--no-web",
        "--compare",
        "--record-dir",
        str(tmp_path),
        "--capture-opencode-sse",
        "--opencode-url",
        "http://127.0.0.1:1",
        "--opencode-password",
        "x",
        "--once",
    ])
    monkeypatch.setattr(monitor_io, "stream_sse", fail_stream)
    monkeypatch.setattr(monitor_io, "generate_comparison_report", fake_report)

    code = monitor_io.main()

    assert code == 1
    assert calls == ["capture"]
