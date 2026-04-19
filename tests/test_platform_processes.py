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
