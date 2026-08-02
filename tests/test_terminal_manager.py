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
async def test_terminal_output_pump_yields_during_continuous_ready_data_and_gaps():
    from bot.web.terminal_manager import (
        TERMINAL_OUTPUT_GAP,
        _TERMINAL_OUTPUT_EOF,
        ManagedTerminalSession,
        TerminalSessionManager,
    )

    class AlwaysReadyProcess:
        is_pty = True

        def isalive(self):
            return True

    class AlwaysReadyPump:
        def __init__(self) -> None:
            self.queue_state = type("QueueState", (), {"dropped_bytes": 0})()
            self.items = [
                item
                for _ in range(128)
                for item in (TERMINAL_OUTPUT_GAP, b"x")
            ] + [_TERMINAL_OUTPUT_EOF]

        async def read(self):
            return self.items.pop(0)

    manager = TerminalSessionManager()
    process = AlwaysReadyProcess()
    session = ManagedTerminalSession(owner_key="1:main", process=process)
    pump_task = asyncio.create_task(manager._pump_output(session, process, AlwaysReadyPump()))
    observer_saw_active_pump: list[bool] = []

    async def observe_ready_task() -> None:
        await asyncio.sleep(0)
        observer_saw_active_pump.append(not pump_task.done())

    observer_task = asyncio.create_task(observe_ready_task())
    await asyncio.wait_for(asyncio.gather(pump_task, observer_task), timeout=1.0)

    assert observer_saw_active_pump == [True]
    assert len(session.replay) == 256
    assert session.replay[0].is_gap is True
    assert session.replay[-1].data == b"x"
    assert session.last_gap_seq == 255
    assert session.next_seq == 257
    assert session.is_closed is True


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


@pytest.mark.asyncio
async def test_terminal_create_and_close_are_isolated_by_owner(monkeypatch):
    import bot.web.terminal_manager as terminal_manager

    class FakeProcess:
        is_pty = True

    class FakePump:
        def __init__(self, _process):
            self._stop_event = asyncio.Event()

        def start(self, _loop):
            pass

        def stop(self):
            self._stop_event.set()

        async def read(self):
            await self._stop_event.wait()
            return terminal_manager.TERMINAL_OUTPUT_EOF

    monkeypatch.setattr(terminal_manager, "create_shell_process", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(terminal_manager, "_TerminalOutputPump", FakePump)
    monkeypatch.setattr(terminal_manager, "_cleanup_terminal_process_without_blocking", lambda _process: None)

    manager = terminal_manager.TerminalSessionManager()
    first = await manager.create(1, "owner-a", cwd="C:/one", shell_type="auto", cols=None, rows=None)
    second = await manager.create(1, "owner-b", cwd="C:/two", shell_type="auto", cols=None, rows=None)

    assert first["started"] is True
    assert second["started"] is True
    closed = await manager.close(1, "owner-a")
    active = await manager.get_snapshot(1, "owner-b")

    assert closed["closed"] is True
    assert closed["started"] is False
    assert active["started"] is True
    assert active["closed"] is False
    await manager.shutdown()


@pytest.mark.asyncio
async def test_terminal_close_releases_session_replay_memory_and_unknown_owner_is_not_retained():
    from bot.web.terminal_manager import (
        ManagedTerminalSession,
        TerminalChunk,
        TerminalSessionManager,
    )

    manager = TerminalSessionManager()
    key = "1:owner-a"
    session = ManagedTerminalSession(owner_key=key)
    session.replay.append(TerminalChunk(seq=1, data=b"remembered output"))
    session.replay_bytes = len(b"remembered output")
    manager._sessions[key] = session

    closed = await manager.close(1, "owner-a")

    assert closed["closed"] is True
    assert closed["started"] is False
    assert key not in manager._sessions
    assert manager.diagnostics()["sessions"] == 0
    assert manager.diagnostics()["replay_bytes"] == 0

    missing = await manager.close(1, "owner-missing")

    assert missing["closed"] is True
    assert manager.diagnostics()["sessions"] == 0


@pytest.mark.asyncio
async def test_terminal_close_waits_for_inflight_create_before_releasing_session(monkeypatch):
    from bot.web.terminal_manager import TerminalSessionManager

    manager = TerminalSessionManager()
    create_started = asyncio.Event()
    allow_create = asyncio.Event()

    async def blocked_rebuild(
        user_id,
        owner_id,
        *,
        cwd,
        shell_type,
        cols,
        rows,
    ):
        create_started.set()
        await allow_create.wait()
        async with manager._lock:
            session = manager._get_or_create_locked(user_id, owner_id)
            session.cwd = cwd
            session.is_closed = False
            return manager._build_snapshot_locked(session)

    monkeypatch.setattr(manager, "_rebuild_locked", blocked_rebuild)
    create_task = asyncio.create_task(
        manager.create(
            1,
            "owner-a",
            cwd="C:/one",
            shell_type="auto",
            cols=None,
            rows=None,
        )
    )
    await create_started.wait()
    close_task = asyncio.create_task(manager.close(1, "owner-a"))
    await asyncio.sleep(0)

    assert close_task.done() is False

    allow_create.set()
    await create_task
    closed = await close_task

    assert closed["closed"] is True
    assert manager.diagnostics()["sessions"] == 0


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
