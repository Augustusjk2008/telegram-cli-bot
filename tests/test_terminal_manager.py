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
