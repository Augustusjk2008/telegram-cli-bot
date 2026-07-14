import asyncio
import logging
import queue
import threading
import time

import pytest


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


@pytest.mark.asyncio
async def test_terminal_output_pump_drops_old_output_and_emits_gap_without_blocking():
    from bot.web.terminal_manager import (
        TERMINAL_OUTPUT_GAP,
        _TerminalOutputPump,
    )

    class BurstProcess:
        pid = 9

        def read(self, timeout=20):
            return b""

    pump = _TerminalOutputPump(BurstProcess(), max_queue_bytes=10)

    pump._put(b"12345678")
    pump._put(b"abcdefgh")

    assert pump.queue_state.queued_bytes <= 10
    assert pump.queue_state.dropped_bytes == 8
    assert await pump.read() is TERMINAL_OUTPUT_GAP
    assert await pump.read() == b"abcdefgh"


@pytest.mark.asyncio
async def test_terminal_output_pump_flushes_blocking_reader_without_waiting_for_next_chunk():
    from bot.platform.terminal import PtyWrapper
    from bot.web.terminal_manager import _TerminalOutputPump

    class BlockingReadProcess:
        pid = 10

        def __init__(self):
            self.items = queue.Queue()

        def read(self, size=1024):
            return self.items.get()

        def isalive(self):
            return True

    raw_process = BlockingReadProcess()
    pump = _TerminalOutputPump(PtyWrapper(raw_process, is_pty=True), flush_interval_ms=40)
    pump.start(asyncio.get_running_loop())

    try:
        raw_process.items.put(b"first")

        assert await asyncio.wait_for(pump.read(), timeout=0.5) == b"first"
    finally:
        pump.stop()
        raw_process.items.put(b"")
        if pump._thread is not None:
            pump._thread.join(timeout=1.0)


@pytest.mark.asyncio
async def test_slow_terminal_client_gets_gap_then_eof_without_affecting_peer():
    from bot.web.terminal_manager import (
        TERMINAL_CLIENT_EOF,
        TERMINAL_GAP_NOTICE,
        TerminalClientQueue,
    )

    slow = TerminalClientQueue(soft_max_bytes=8, hard_max_bytes=12)
    healthy = TerminalClientQueue(soft_max_bytes=8, hard_max_bytes=64)

    assert slow.put_output(b"12345678") is True
    assert healthy.put_output(b"12345678") is True
    assert slow.put_output(b"abcdefgh") is False
    assert healthy.put_output(b"abcdefgh") is True

    assert await slow.get() == TERMINAL_GAP_NOTICE
    assert await slow.get() is TERMINAL_CLIENT_EOF
    assert await healthy.get() == b"12345678abcdefgh"


@pytest.mark.asyncio
async def test_terminal_client_preserves_normal_output_before_close_eof():
    from bot.web.terminal_manager import TERMINAL_CLIENT_EOF, TerminalClientQueue

    client = TerminalClientQueue(soft_max_bytes=8, hard_max_bytes=64)
    client.put_output(b"pending")
    client.put_eof()

    assert await client.get() == b"pending"
    assert await client.get() is TERMINAL_CLIENT_EOF


@pytest.mark.asyncio
async def test_attach_from_expired_sequence_reports_reset_and_replays_tail():
    from bot.web.terminal_manager import (
        TERMINAL_CLIENT_EOF,
        TERMINAL_GAP_NOTICE,
        ManagedTerminalSession,
        TerminalChunk,
        TerminalSessionManager,
    )

    class AliveProcess:
        is_pty = True

        def isalive(self):
            return True

    manager = TerminalSessionManager()
    session = ManagedTerminalSession(owner_key="1:main", process=AliveProcess())
    session.next_seq = 5
    session.replay.extend(
        [
            TerminalChunk(seq=3, data=b"three"),
            TerminalChunk(seq=4, data=b"four"),
        ]
    )
    session.replay_bytes = 9
    manager._sessions["1:main"] = session

    client, snapshot = await manager.attach(1, "main", from_seq=1)

    assert snapshot["reset_required"] is True
    assert snapshot["earliest_seq"] == 3
    assert snapshot["gap_from"] == 2
    assert snapshot["gap_to"] == 2
    assert await client.get() == TERMINAL_GAP_NOTICE
    assert await client.get() == b"threefour"

    client.put_output(b"pending")
    await manager.detach(1, "main", client)
    assert client.queued_bytes == 0
    assert await client.get() is TERMINAL_CLIENT_EOF


@pytest.mark.asyncio
async def test_terminal_replay_preserves_stream_and_chunk_sequences():
    from bot.web.terminal_manager import (
        ManagedTerminalSession,
        TerminalChunk,
        TerminalDelivery,
        TerminalSessionManager,
    )

    class AliveProcess:
        is_pty = True

        def isalive(self):
            return True

    manager = TerminalSessionManager()
    session = ManagedTerminalSession(owner_key="1:main", process=AliveProcess(), stream_id="term-stream")
    session.next_seq = 4
    session.replay.extend(
        [
            TerminalChunk(seq=1, data=b"one"),
            TerminalChunk(seq=2, data=b"two"),
            TerminalChunk(seq=3, data=b"three"),
        ]
    )
    session.replay_bytes = 11
    manager._sessions["1:main"] = session

    client, snapshot = await manager.attach(1, "main", from_seq=1, protocol_version=2)
    first = await client.get()
    second = await client.get()

    assert snapshot["stream_id"] == "term-stream"
    assert isinstance(first, TerminalDelivery)
    assert isinstance(second, TerminalDelivery)
    assert [(first.sequence, first.payload), (second.sequence, second.payload)] == [
        (2, b"two"),
        (3, b"three"),
    ]


def test_terminal_v2_binary_header_carries_version_flags_and_sequence():
    from bot.web.terminal_manager import (
        TERMINAL_WS_V2_HEADER,
        TERMINAL_WS_V2_MAGIC,
        TerminalDelivery,
        encode_terminal_ws_v2,
    )

    encoded = encode_terminal_ws_v2(
        TerminalDelivery(
            stream_id="stream",
            kind="output",
            sequence=42,
            payload=b"payload",
        )
    )
    magic, version, flags, sequence = TERMINAL_WS_V2_HEADER.unpack(
        encoded[: TERMINAL_WS_V2_HEADER.size]
    )

    assert magic == TERMINAL_WS_V2_MAGIC
    assert (version, flags, sequence) == (2, 0, 42)
    assert encoded[TERMINAL_WS_V2_HEADER.size :] == b"payload"
