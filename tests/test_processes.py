import subprocess

import pytest

from bot.models import UserSession
from bot.platform import processes
from bot.session_runtime import terminate_session_process


def test_build_chat_cli_process_kwargs_uses_session_group_on_posix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(processes.os, "name", "posix")

    assert processes.build_chat_cli_process_kwargs() == {"start_new_session": True}


def test_build_chat_cli_process_kwargs_uses_no_window_and_process_group_on_windows(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(processes.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(processes.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)

    kwargs = processes.build_chat_cli_process_kwargs()

    assert kwargs == {"creationflags": 0x08000000 | 0x00000200}


def test_terminate_process_tree_sync_uses_taskkill_on_windows(monkeypatch: pytest.MonkeyPatch):
    calls = []

    class FakeProcess:
        pid = 1234

        def __init__(self):
            self.returncode = None
            self.wait_calls = []

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            self.returncode = -9
            return self.returncode

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    process = FakeProcess()
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(processes.subprocess, "run", fake_run)

    processes.terminate_process_tree_sync(process)

    assert calls[0][0] == ["taskkill", "/F", "/T", "/PID", "1234"]
    assert calls[0][1]["timeout"] == 5
    assert process.wait_calls == [2]


def test_terminate_session_process_closes_streams_for_live_and_exited_processes(
    monkeypatch: pytest.MonkeyPatch,
):
    class Stream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self, returncode):
            self.returncode = returncode
            self.stdout = Stream()
            self.stdin = Stream()
            self.stderr = Stream()

        def poll(self):
            return self.returncode

    terminated = []
    monkeypatch.setattr("bot.session_runtime.terminate_process_tree_sync", lambda process: terminated.append(process))

    live = FakeProcess(None)
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=".")
    session.process = live
    terminate_session_process(session)

    assert terminated == [live]
    assert live.stdout.closed is True
    assert live.stdin.closed is True
    assert live.stderr.closed is True

    exited = FakeProcess(0)
    session.process = exited
    terminate_session_process(session)

    assert terminated == [live]
    assert exited.stdout.closed is True
    assert exited.stdin.closed is True
    assert exited.stderr.closed is True
