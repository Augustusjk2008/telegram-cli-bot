"""持久终端会话管理。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from bot.platform.terminal import PtyWrapper, TerminalLaunchError, create_shell_process

logger = logging.getLogger(__name__)

TERMINAL_REPLAY_MAX_BYTES = 8 * 1024 * 1024
TERMINAL_OUTPUT_QUEUE_MAX_BYTES = 1024 * 1024
TERMINAL_CLIENT_SOFT_MAX_BYTES = 512 * 1024
TERMINAL_CLIENT_HARD_MAX_BYTES = 2 * 1024 * 1024
TERMINAL_CLIENT_MERGE_MAX_BYTES = 64 * 1024
TERMINAL_CLIENT_EOF = object()
_TERMINAL_OUTPUT_EOF = object()
TERMINAL_OUTPUT_GAP = object()
TERMINAL_GAP_NOTICE = "\r\n[终端输出已截断，请重新连接以同步最新状态]\r\n".encode("utf-8")
TERMINAL_PROCESS_CLEANUP_JOIN_SECONDS = 1.0
TERMINAL_PROCESS_CLEANUP_WARNING_SECONDS = 5.0


def _normalize_pipe_line_endings(data: bytes, *, previous_ended_with_cr: bool = False) -> tuple[bytes, bool]:
    if not data:
        return data, previous_ended_with_cr

    normalized = bytearray()
    previous_was_cr = previous_ended_with_cr
    for byte in data:
        if byte == 0x0A and not previous_was_cr:
            normalized.append(0x0D)
        normalized.append(byte)
        previous_was_cr = byte == 0x0D

    return bytes(normalized), previous_was_cr


@dataclass(slots=True)
class TerminalChunk:
    seq: int
    data: bytes
    is_gap: bool = False


@dataclass(slots=True)
class TerminalQueueState:
    queued_bytes: int = 0
    dropped_bytes: int = 0
    gap_pending: bool = False


@dataclass(slots=True)
class _TerminalClientItem:
    payload: bytes | object
    counted_bytes: int = 0


class TerminalClientQueue:
    def __init__(
        self,
        *,
        soft_max_bytes: int = TERMINAL_CLIENT_SOFT_MAX_BYTES,
        hard_max_bytes: int = TERMINAL_CLIENT_HARD_MAX_BYTES,
    ) -> None:
        self.soft_max_bytes = max(1, int(soft_max_bytes))
        self.hard_max_bytes = max(self.soft_max_bytes, int(hard_max_bytes))
        self.queued_bytes = 0
        self._queue: deque[_TerminalClientItem] = deque()
        self._available = asyncio.Event()
        self._closed = False

    async def get(self) -> bytes | object:
        while True:
            if self._queue:
                item = self._queue.popleft()
                self.queued_bytes = max(0, self.queued_bytes - item.counted_bytes)
                return item.payload
            self._available.clear()
            if self._queue:
                continue
            await self._available.wait()

    def _clear(self) -> None:
        self._queue.clear()
        self.queued_bytes = 0

    def put_control(self, payload: bytes | object) -> None:
        if self._closed and payload is not TERMINAL_CLIENT_EOF:
            return
        self._queue.append(_TerminalClientItem(payload=payload))
        self._available.set()

    def put_eof(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.put_control(TERMINAL_CLIENT_EOF)

    def put_output(self, data: bytes) -> bool:
        if self._closed:
            return False
        payload = bytes(data)
        next_bytes = self.queued_bytes + len(payload)
        if next_bytes > self.hard_max_bytes:
            self._clear()
            self.put_control(TERMINAL_GAP_NOTICE)
            self.put_eof()
            return False

        if self._queue:
            last = self._queue[-1]
            should_merge = (
                last.counted_bytes + len(payload) <= TERMINAL_CLIENT_MERGE_MAX_BYTES
                or next_bytes > self.soft_max_bytes
            )
            if isinstance(last.payload, bytes) and last.counted_bytes > 0 and should_merge:
                last.payload += payload
                last.counted_bytes += len(payload)
                self.queued_bytes = next_bytes
                self._available.set()
                return True

        self._queue.append(_TerminalClientItem(payload=payload, counted_bytes=len(payload)))
        self.queued_bytes = next_bytes
        self._available.set()
        return True

    def clear(self) -> None:
        self._closed = True
        self._clear()
        self._queue.append(_TerminalClientItem(payload=TERMINAL_CLIENT_EOF))
        self._available.set()


@dataclass(slots=True)
class ManagedTerminalSession:
    owner_key: str
    process: PtyWrapper | None = None
    output_pump: _TerminalOutputPump | None = None
    cwd: str = ""
    shell_type: str = "auto"
    is_closed: bool = False
    is_pty: bool | None = None
    next_seq: int = 1
    replay: deque[TerminalChunk] = field(default_factory=deque)
    replay_bytes: int = 0
    clients: set[TerminalClientQueue] = field(default_factory=set)
    pump_task: asyncio.Task[None] | None = None
    dropped_bytes: int = 0
    last_gap_seq: int = 0


class TerminalNotRunningError(RuntimeError):
    """终端未启动。"""


class _TerminalOutputPump:
    def __init__(
        self,
        process: PtyWrapper,
        *,
        flush_interval_ms: int = 40,
        max_chunk_bytes: int = 65536,
        max_queue_bytes: int = TERMINAL_OUTPUT_QUEUE_MAX_BYTES,
    ) -> None:
        self._process = process
        self._queue: deque[bytes | object] = deque()
        self._queue_lock = threading.Lock()
        self._available = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._flush_interval = max(flush_interval_ms, 0) / 1000
        self._max_chunk_bytes = max(max_chunk_bytes, 1)
        self._max_queue_bytes = max(1, int(max_queue_bytes))
        self.queue_state = TerminalQueueState()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None:
            return
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run,
            name=f"terminal-output-{getattr(self._process, 'pid', 'unknown')}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    async def read(self) -> bytes | object:
        while True:
            with self._queue_lock:
                if self.queue_state.gap_pending:
                    self.queue_state.gap_pending = False
                    return TERMINAL_OUTPUT_GAP
                if self._queue:
                    item = self._queue.popleft()
                    if isinstance(item, bytes):
                        self.queue_state.queued_bytes = max(
                            0,
                            self.queue_state.queued_bytes - len(item),
                        )
                    return item
                self._available.clear()
            await self._available.wait()

    def _put(self, item: bytes | object) -> None:
        with self._queue_lock:
            if isinstance(item, bytes) and len(item) > self._max_queue_bytes:
                dropped_prefix = len(item) - self._max_queue_bytes
                self.queue_state.dropped_bytes += dropped_prefix
                self.queue_state.gap_pending = True
                item = item[-self._max_queue_bytes :]
            self._queue.append(item)
            if isinstance(item, bytes):
                self.queue_state.queued_bytes += len(item)
                while self.queue_state.queued_bytes > self._max_queue_bytes:
                    removed_index = next(
                        (index for index, queued in enumerate(self._queue) if isinstance(queued, bytes)),
                        None,
                    )
                    if removed_index is None:
                        break
                    removed = self._queue[removed_index]
                    del self._queue[removed_index]
                    assert isinstance(removed, bytes)
                    self.queue_state.queued_bytes -= len(removed)
                    self.queue_state.dropped_bytes += len(removed)
                    self.queue_state.gap_pending = True
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._available.set)
        except RuntimeError:
            return

    def _run(self) -> None:
        pending = bytearray()
        last_flush_at = time.monotonic()
        try:
            while not self._stop_event.is_set():
                try:
                    data = self._process.read(timeout=20)
                except Exception as exc:
                    logger.debug("终端输出读取结束 pid=%s: %s", getattr(self._process, "pid", "unknown"), exc)
                    break

                if data:
                    if isinstance(data, str):
                        data = data.encode("utf-8", errors="replace")
                    remaining = memoryview(data)
                    while remaining:
                        available = self._max_chunk_bytes - len(pending)
                        pending.extend(remaining[:available])
                        remaining = remaining[available:]
                        if len(pending) >= self._max_chunk_bytes:
                            self._put(bytes(pending))
                            pending.clear()
                    now = time.monotonic()
                    if pending and (
                        len(pending) >= self._max_chunk_bytes
                        or now - last_flush_at >= self._flush_interval
                    ):
                        self._put(bytes(pending))
                        pending.clear()
                        last_flush_at = now
                    continue

                if pending:
                    self._put(bytes(pending))
                    pending.clear()
                    last_flush_at = time.monotonic()

                try:
                    if not self._process.isalive():
                        break
                except Exception:
                    break

                self._stop_event.wait(0.01)
        finally:
            if pending:
                self._put(bytes(pending))
            self._put(_TERMINAL_OUTPUT_EOF)


def _cleanup_terminal_process(process: PtyWrapper) -> None:
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.close()
    except Exception:
        pass


def _monitor_terminal_cleanup(thread: threading.Thread, *, pid: object, waited_seconds: float) -> None:
    warning_after_seconds = max(waited_seconds, TERMINAL_PROCESS_CLEANUP_WARNING_SECONDS)
    thread.join(max(0.0, warning_after_seconds - waited_seconds))
    if thread.is_alive():
        logger.warning(
            "终端进程清理超过 %.2f 秒仍未完成，继续后台等待: pid=%s",
            warning_after_seconds,
            pid,
        )
        return
    logger.debug("终端进程后台清理已完成: pid=%s", pid)


def _request_windows_process_tree_kill(process: PtyWrapper) -> None:
    if os.name != "nt":
        return
    pid = getattr(process, "pid", None)
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return
    if pid_int <= 0 or pid_int == os.getpid():
        return
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            ["taskkill", "/F", "/T", "/PID", str(pid_int)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception:
        pass


def _cleanup_terminal_process_without_blocking(process: PtyWrapper) -> None:
    _request_windows_process_tree_kill(process)
    pid = getattr(process, "pid", "unknown")
    thread = threading.Thread(
        target=_cleanup_terminal_process,
        args=(process,),
        name=f"terminal-cleanup-{pid}",
        daemon=True,
    )
    thread.start()
    thread.join(TERMINAL_PROCESS_CLEANUP_JOIN_SECONDS)
    if thread.is_alive():
        logger.debug(
            "终端进程清理未在 %.2f 秒内完成，已转后台继续: pid=%s",
            TERMINAL_PROCESS_CLEANUP_JOIN_SECONDS,
            pid,
        )
        monitor = threading.Thread(
            target=_monitor_terminal_cleanup,
            kwargs={"thread": thread, "pid": pid, "waited_seconds": TERMINAL_PROCESS_CLEANUP_JOIN_SECONDS},
            name=f"terminal-cleanup-monitor-{pid}",
            daemon=True,
        )
        monitor.start()


class TerminalSessionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, ManagedTerminalSession] = {}
        self._rebuild_locks: dict[str, asyncio.Lock] = {}

    def _key(self, user_id: int, owner_id: str) -> str:
        return f"{user_id}:{owner_id}"

    def _get_or_create_locked(self, user_id: int, owner_id: str) -> ManagedTerminalSession:
        key = self._key(user_id, owner_id)
        session = self._sessions.get(key)
        if session is None:
            session = ManagedTerminalSession(owner_key=key)
            self._sessions[key] = session
        return session

    def _build_snapshot_locked(self, session: ManagedTerminalSession | None) -> dict[str, Any]:
        if session is None:
            return {
                "owner_id": "",
                "started": False,
                "closed": False,
                "cwd": "",
                "pty_mode": None,
                "connection_text": "未启动",
                "last_seq": 0,
                "earliest_seq": 0,
                "gap_seq": 0,
                "dropped_bytes": 0,
                "reset_required": False,
            }

        started = session.process is not None and not session.is_closed
        if started:
            connection_text = "运行中"
        elif session.is_closed:
            connection_text = "终端已关闭"
        else:
            connection_text = "未启动"

        return {
            "owner_id": session.owner_key.split(":", 1)[1] if ":" in session.owner_key else session.owner_key,
            "started": started,
            "closed": session.is_closed,
            "cwd": session.cwd,
            "pty_mode": session.is_pty,
            "connection_text": connection_text,
            "last_seq": max(session.next_seq - 1, 0),
            "earliest_seq": session.replay[0].seq if session.replay else max(session.next_seq, 1),
            "gap_seq": session.last_gap_seq,
            "dropped_bytes": session.dropped_bytes,
            "reset_required": False,
        }

    def _notify_clients_locked(self, session: ManagedTerminalSession, item: bytes | object) -> None:
        stale: list[TerminalClientQueue] = []
        for client in session.clients:
            try:
                if item is TERMINAL_CLIENT_EOF:
                    client.put_eof()
                elif isinstance(item, bytes) and not client.put_output(item):
                    stale.append(client)
            except Exception:
                stale.append(client)
        for client in stale:
            session.clients.discard(client)

    def _trim_replay_locked(self, session: ManagedTerminalSession) -> None:
        while session.replay and session.replay_bytes > TERMINAL_REPLAY_MAX_BYTES:
            removed = session.replay.popleft()
            session.replay_bytes -= len(removed.data)

    async def get_snapshot(self, user_id: int, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            return self._build_snapshot_locked(self._sessions.get(self._key(user_id, owner_id)))

    async def rebuild(
        self,
        user_id: int,
        owner_id: str,
        *,
        cwd: str,
        shell_type: str,
        cols: int | None,
        rows: int | None,
    ) -> dict[str, Any]:
        key = self._key(user_id, owner_id)
        async with self._lock:
            rebuild_lock = self._rebuild_locks.setdefault(key, asyncio.Lock())
        async with rebuild_lock:
            return await self._rebuild_locked(
                user_id,
                owner_id,
                cwd=cwd,
                shell_type=shell_type,
                cols=cols,
                rows=rows,
            )

    async def _rebuild_locked(
        self,
        user_id: int,
        owner_id: str,
        *,
        cwd: str,
        shell_type: str,
        cols: int | None,
        rows: int | None,
    ) -> dict[str, Any]:
        async with self._lock:
            session = self._get_or_create_locked(user_id, owner_id)

        await self._terminate_process(session)

        process = create_shell_process(shell_type, cwd, use_pty=True, cols=cols, rows=rows)
        output_pump = _TerminalOutputPump(process)
        output_pump.start(asyncio.get_running_loop())
        async with self._lock:
            session.cwd = cwd
            session.shell_type = shell_type
            session.is_closed = False
            session.is_pty = process.is_pty
            session.process = process
            session.output_pump = output_pump
            session.next_seq = 1
            session.replay.clear()
            session.replay_bytes = 0
            session.dropped_bytes = 0
            session.last_gap_seq = 0
            session.pump_task = asyncio.create_task(self._pump_output(session, process, output_pump))
            return self._build_snapshot_locked(session)

    async def close(self, user_id: int, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            session = self._get_or_create_locked(user_id, owner_id)

        await self._terminate_process(session)

        async with self._lock:
            session.is_closed = True
            return self._build_snapshot_locked(session)

    async def attach(
        self,
        user_id: int,
        owner_id: str,
        *,
        from_seq: int = 0,
    ) -> tuple[TerminalClientQueue, dict[str, Any]]:
        client = TerminalClientQueue()
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            if session is None or session.process is None or session.is_closed:
                raise TerminalNotRunningError("终端未启动")
            replay_chunks = [chunk for chunk in session.replay if chunk.seq > from_seq]
            earliest_seq = session.replay[0].seq if session.replay else session.next_seq
            reset_required = from_seq < max(earliest_seq - 1, 0)
            replay_bytes = 0
            selected_reversed: list[TerminalChunk] = []
            for chunk in reversed(replay_chunks):
                if replay_bytes + len(chunk.data) > client.hard_max_bytes:
                    reset_required = True
                    break
                selected_reversed.append(chunk)
                replay_bytes += len(chunk.data)
            selected = list(reversed(selected_reversed))
            if reset_required:
                client.put_control(TERMINAL_GAP_NOTICE)
            replay_payload = b"".join(chunk.data for chunk in selected)
            if replay_payload:
                client.put_output(replay_payload)
            session.clients.add(client)
            snapshot = self._build_snapshot_locked(session)
            snapshot.update(
                {
                    "reset_required": reset_required,
                    "requested_seq": from_seq,
                    "gap_from": from_seq + 1 if reset_required else 0,
                    "gap_to": max((selected[0].seq if selected else earliest_seq) - 1, 0)
                    if reset_required
                    else 0,
                }
            )
        return client, snapshot

    async def detach(self, user_id: int, owner_id: str, queue: TerminalClientQueue) -> None:
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            if session is None:
                queue.clear()
                return
            session.clients.discard(queue)
            queue.clear()

    async def write_input(self, user_id: int, owner_id: str, data: bytes) -> None:
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            process = session.process if session is not None and not session.is_closed else None
        if process is None:
            raise TerminalNotRunningError("终端未启动")
        process.write(data)

    async def resize(self, user_id: int, owner_id: str, cols: int, rows: int) -> bool:
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            process = session.process if session is not None and not session.is_closed else None
        if process is None:
            raise TerminalNotRunningError("终端未启动")
        resize = getattr(process, "resize", None)
        if not callable(resize):
            return False
        return bool(resize(cols, rows))

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._rebuild_locks.clear()
        for session in sessions:
            await self._terminate_process(session)

    async def _terminate_process(self, session: ManagedTerminalSession) -> None:
        async with self._lock:
            process = session.process
            output_pump = session.output_pump
            pump_task = session.pump_task
            session.process = None
            session.output_pump = None
            session.pump_task = None
            self._notify_clients_locked(session, TERMINAL_CLIENT_EOF)
            session.clients.clear()
        if output_pump is not None:
            output_pump.stop()
        if pump_task is not None and not pump_task.done():
            pump_task.cancel()
        if process is not None:
            _cleanup_terminal_process_without_blocking(process)
        if pump_task is not None:
            await asyncio.gather(pump_task, return_exceptions=True)

    async def _pump_output(
        self,
        session: ManagedTerminalSession,
        process: PtyWrapper,
        output_pump: _TerminalOutputPump,
    ) -> None:
        pipe_previous_ended_with_cr = False
        try:
            while True:
                data = await output_pump.read()
                if data is _TERMINAL_OUTPUT_EOF:
                    break
                if data is TERMINAL_OUTPUT_GAP:
                    async with self._lock:
                        if session.process is not process:
                            return
                        chunk = TerminalChunk(
                            seq=session.next_seq,
                            data=TERMINAL_GAP_NOTICE,
                            is_gap=True,
                        )
                        session.next_seq += 1
                        session.last_gap_seq = chunk.seq
                        session.dropped_bytes = output_pump.queue_state.dropped_bytes
                        session.replay.append(chunk)
                        session.replay_bytes += len(chunk.data)
                        self._trim_replay_locked(session)
                        self._notify_clients_locked(session, chunk.data)
                    continue
                if isinstance(data, str):
                    data = data.encode("utf-8", errors="replace")
                if data:
                    if not process.is_pty:
                        data, pipe_previous_ended_with_cr = _normalize_pipe_line_endings(
                            data,
                            previous_ended_with_cr=pipe_previous_ended_with_cr,
                        )
                    async with self._lock:
                        if session.process is not process:
                            return
                        chunk = TerminalChunk(seq=session.next_seq, data=data)
                        session.next_seq += 1
                        session.replay.append(chunk)
                        session.replay_bytes += len(data)
                        self._trim_replay_locked(session)
                        self._notify_clients_locked(session, data)
                    continue

                try:
                    if not process.isalive():
                        break
                except Exception:
                    break
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("终端输出泵异常 %s: %s", session.owner_key, exc)
        finally:
            async with self._lock:
                if session.process is process:
                    session.process = None
                    session.pump_task = None
                    session.is_closed = True
                    self._notify_clients_locked(session, TERMINAL_CLIENT_EOF)
                    session.clients.clear()
