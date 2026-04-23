import asyncio

import pytest

from bot.web.server import _TERMINAL_OUTPUT_EOF, _TerminalOutputPump


@pytest.mark.asyncio
async def test_terminal_output_pump_coalesces_bursty_chunks():
    class FakeProcess:
        pid = 99

        def __init__(self):
            self._reads = [b"a", b"b", b"c", b""]

        def read(self, timeout: int = 1000) -> bytes:
            return self._reads.pop(0) if self._reads else b""

        def isalive(self) -> bool:
            return bool(self._reads)

    pump = _TerminalOutputPump(FakeProcess(), flush_interval_ms=50, max_chunk_bytes=65536)
    pump.start(asyncio.get_running_loop())

    first = await asyncio.wait_for(pump.read(), timeout=1)
    second = await asyncio.wait_for(pump.read(), timeout=1)

    assert first == b"abc"
    assert second is _TERMINAL_OUTPUT_EOF
