import asyncio
import threading
import time

import pytest

from bot.web.terminal_manager import TerminalSessionManager


@pytest.mark.asyncio
async def test_terminal_shutdown_does_not_wait_for_blocking_process_cleanup() -> None:
    manager = TerminalSessionManager()

    class BlockingProcess:
        is_pty = True
        pid = 12345
        terminated = False
        closed = False
        close_event = threading.Event()

        def read(self, timeout: int = 1000) -> bytes:
            return b""

        def write(self, data: bytes) -> None:
            pass

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            self.terminated = True
            time.sleep(0.2)

        def close(self) -> None:
            self.closed = True
            self.close_event.set()

    process = BlockingProcess()
    session = manager._get_or_create_locked(1001, "test-terminal")
    session.process = process
    session.is_closed = False

    try:
        started_at = time.perf_counter()
        await manager.shutdown()
        elapsed = time.perf_counter() - started_at

        assert elapsed < 0.2
        assert process.terminated is True
    finally:
        assert await asyncio.to_thread(process.close_event.wait, 1.0)
    assert process.closed is True
