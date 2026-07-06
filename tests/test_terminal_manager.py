import logging
import threading
import time


def test_terminal_cleanup_does_not_warn_for_short_background_cleanup(monkeypatch, caplog):
    import bot.web.terminal_manager as terminal_manager

    finished = threading.Event()

    class SlowCleanupProcess:
        pid = 12345

        def terminate(self) -> None:
            time.sleep(0.1)
            finished.set()

        def close(self) -> None:
            pass

    monkeypatch.setattr(terminal_manager, "_request_windows_process_tree_kill", lambda _process: None)
    caplog.set_level(logging.WARNING, logger="bot.web.terminal_manager")

    terminal_manager._cleanup_terminal_process_without_blocking(SlowCleanupProcess())

    assert finished.wait(1.0)
    assert "终端进程清理未在" not in caplog.text


def test_pty_wrapper_terminate_uses_process_tree_for_plain_popen(monkeypatch):
    import bot.platform.terminal as terminal

    calls = []

    class FakeProcess:
        pid = 12345

        def terminate(self) -> None:
            raise AssertionError("plain terminate should not be called directly")

        def kill(self) -> None:
            raise AssertionError("plain kill should not be called directly")

    process = FakeProcess()
    monkeypatch.setattr(terminal, "terminate_process_tree_sync", lambda current: calls.append(current), raising=False)

    terminal.PtyWrapper(process, is_pty=False).terminate()

    assert calls == [process]


def test_pipe_line_ending_normalizer_adds_cr_before_lone_lf():
    from bot.web.terminal_manager import _normalize_pipe_line_endings

    output, previous_cr = _normalize_pipe_line_endings(b"A\nB\r\nC\r", previous_ended_with_cr=False)

    assert output == b"A\r\nB\r\nC\r"
    assert previous_cr is True

    output, previous_cr = _normalize_pipe_line_endings(b"\nD\n", previous_ended_with_cr=previous_cr)

    assert output == b"\nD\r\n"
    assert previous_cr is False


def test_pipe_line_ending_normalizer_preserves_carriage_return_updates():
    from bot.web.terminal_manager import _normalize_pipe_line_endings

    output, previous_cr = _normalize_pipe_line_endings(
        b"\r\x1b[K| scanning\r\x1b[K* done\n",
        previous_ended_with_cr=False,
    )

    assert output == b"\r\x1b[K| scanning\r\x1b[K* done\r\n"
    assert previous_cr is False
