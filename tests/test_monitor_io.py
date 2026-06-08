from __future__ import annotations

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
