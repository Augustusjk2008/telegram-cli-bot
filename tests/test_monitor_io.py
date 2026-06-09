from __future__ import annotations

import json
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


def test_normalize_web_stream_event_reads_top_level_native_turn_fields():
    event = monitor_io.normalize_web_stream_event(
        "agent-test",
        "问题",
        {
            "type": "meta",
            "native_session_id": "sess-1",
            "turn_id": "turn-1",
            "assistant_message_id": "msg-web-1",
            "native_assistant_message_id": "oc-a1",
        },
    )

    assert event["native_session_id"] == "sess-1"
    assert event["turn_id"] == "turn-1"
    assert event["assistant_message_id"] == "msg-web-1"
    assert event["web_message_id"] == "msg-web-1"
    assert event["native_assistant_message_id"] == "oc-a1"


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


def test_generate_comparison_report_keeps_two_turns_in_same_session_separate(tmp_path):
    history_record = {
        "items": [
            {
                "id": "msg-web-1",
                "turn_id": "turn-1",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "答1",
                "state": "done",
                "meta": {"completion_state": "completed", "native_session_id": "sess-1"},
            },
            {
                "id": "msg-web-2",
                "turn_id": "turn-2",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "答2",
                "state": "done",
                "meta": {"completion_state": "completed", "native_session_id": "sess-1"},
            },
        ],
        "ts_mono_ms": 3000,
    }
    stream_records = [
        {
            "kind": "web_stream_event",
            "event_type": "done",
            "turn_id": "turn-1",
            "assistant_message_id": "msg-web-1",
            "web_message_id": "msg-web-1",
            "native_session_id": "sess-1",
            "native_assistant_message_id": "oc-a1",
            "history_content": "答1",
            "ts_mono_ms": 1000,
        },
        {
            "kind": "web_stream_event",
            "event_type": "done",
            "turn_id": "turn-2",
            "assistant_message_id": "msg-web-2",
            "web_message_id": "msg-web-2",
            "native_session_id": "sess-1",
            "native_assistant_message_id": "oc-a2",
            "history_content": "答2",
            "ts_mono_ms": 2000,
        },
    ]
    (tmp_path / "web_history_snapshots.jsonl").write_text(json.dumps(history_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "web_stream_events.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in stream_records) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "opencode_sessions").mkdir()
    (tmp_path / "opencode_sessions" / "sess-1.messages.json").write_text(
        json.dumps(
            {
                "native_session_id": "sess-1",
                "messages": [
                    {"id": "oc-a1", "role": "assistant", "content": "答1"},
                    {"id": "oc-a2", "role": "assistant", "content": "答2"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = monitor_io.generate_comparison_report(tmp_path, "run-1")

    assert report["summary"]["turns_compared"] == 2
    assert report["summary"]["issue_count"] == 0
    assert report["turns"]["turn:turn-1"]["opencode"]["final_assistant_text"] == "答1"
    assert report["turns"]["turn:turn-2"]["opencode"]["final_assistant_text"] == "答2"


def test_compare_conversation_session_consistency_reports_changed_session():
    issues = monitor_io.compare_conversation_session_consistency(
        [
            {
                "items": [
                    {
                        "id": "msg-1",
                        "turn_id": "turn-1",
                        "conversation_id": "conv-1",
                        "role": "assistant",
                        "content": "答1",
                        "meta": {"native_session_id": "sess-1"},
                    },
                    {
                        "id": "msg-2",
                        "turn_id": "turn-2",
                        "conversation_id": "conv-1",
                        "role": "assistant",
                        "content": "答2",
                        "meta": {"native_session_id": "sess-2"},
                    },
                ]
            }
        ]
    )

    assert issues[0]["code"] == "conversation_session_changed"
    assert issues[0]["evidence"]["native_session_ids"] == ["sess-1", "sess-2"]


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
