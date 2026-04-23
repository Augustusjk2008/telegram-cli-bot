from types import SimpleNamespace

from bot.platform.terminal import PosixPtyProcess, PtyWrapper


def test_pty_wrapper_resize_uses_setwinsize_for_winpty_like_process():
    calls: list[tuple[int, int]] = []

    process = SimpleNamespace(
        setwinsize=lambda rows, cols: calls.append((rows, cols)),
        pid=1234,
    )

    wrapper = PtyWrapper(process, is_pty=True)

    assert wrapper.resize(120, 40) is True
    assert calls == [(40, 120)]


def test_pty_wrapper_resize_returns_false_for_pipe_process():
    process = SimpleNamespace(pid=1234)

    wrapper = PtyWrapper(process, is_pty=False)

    assert wrapper.resize(120, 40) is False


def test_posix_pty_process_resize_uses_ioctl(monkeypatch):
    calls: list[tuple[int, int, tuple[str, int, int, int, int]]] = []

    monkeypatch.setattr(
        "bot.platform.terminal.fcntl",
        SimpleNamespace(ioctl=lambda fd, op, data: calls.append((fd, op, data))),
    )
    monkeypatch.setattr(
        "bot.platform.terminal.struct",
        SimpleNamespace(pack=lambda fmt, rows, cols, x, y: (fmt, rows, cols, x, y)),
    )
    monkeypatch.setattr(
        "bot.platform.terminal.termios",
        SimpleNamespace(TIOCSWINSZ=21524),
    )

    process = SimpleNamespace(pid=99)
    pty_process = PosixPtyProcess(process, 77)

    pty_process.resize(120, 40)

    assert calls == [(77, 21524, ("HHHH", 40, 120, 0, 0))]
