from bot.platform import processes


def test_subprocess_kwargs_use_new_session_on_linux(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "posix")
    kwargs = processes.build_subprocess_group_kwargs()
    assert kwargs == {"start_new_session": True}


def test_subprocess_kwargs_are_empty_on_windows(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    assert processes.build_subprocess_group_kwargs() == {}


def test_hidden_process_kwargs_are_empty_on_linux(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "posix")
    assert processes.build_hidden_process_kwargs() == {}


def test_hidden_process_kwargs_use_create_no_window_on_windows(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(processes.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    assert processes.build_hidden_process_kwargs() == {"creationflags": 0x08000000}


def test_terminate_process_tree_uses_taskkill_on_windows_even_if_parent_exits(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    calls = []

    class FakeProcess:
        pid = 1234

        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append(("terminate",))

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            self.returncode = 0
            return 0

        def kill(self):
            calls.append(("kill",))

    def fake_run(args, **kwargs):
        calls.append(("run", args, kwargs))

    monkeypatch.setattr(processes.subprocess, "run", fake_run)

    processes.terminate_process_tree_sync(FakeProcess())

    taskkill_calls = [call for call in calls if call[0] == "run"]
    assert taskkill_calls
    assert taskkill_calls[0][1] == ["taskkill", "/F", "/T", "/PID", "1234"]
    assert ("terminate",) not in calls
