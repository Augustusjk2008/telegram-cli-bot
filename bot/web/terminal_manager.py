"""持久终端会话管理。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from bot.platform.terminal import PtyWrapper, create_shell_process

logger = logging.getLogger(__name__)

TERMINAL_REPLAY_MAX_BYTES = 8 * 1024 * 1024
TERMINAL_CLIENT_EOF = object()
_TERMINAL_OUTPUT_EOF = object()


@dataclass(slots=True)
class TerminalChunk:
    seq: int
    data: bytes


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
    clients: set[asyncio.Queue[bytes | object]] = field(default_factory=set)
    pump_task: asyncio.Task[None] | None = None


class TerminalNotRunningError(RuntimeError):
    """终端未启动。"""


class _TerminalOutputPump:
    def __init__(self, process: PtyWrapper, *, flush_interval_ms: int = 40, max_chunk_bytes: int = 65536) -> None:
        self._process = process
        self._queue: asyncio.Queue[bytes | object] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._flush_interval = max(flush_interval_ms, 0) / 1000
        self._max_chunk_bytes = max(max_chunk_bytes, 1)

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
        return await self._queue.get()

    def _put(self, item: bytes | object) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, item)
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
                    pending.extend(data)
                    now = time.monotonic()
                    if len(pending) >= self._max_chunk_bytes or now - last_flush_at >= self._flush_interval:
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


class TerminalSessionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, ManagedTerminalSession] = {}

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
        }

    def _notify_clients_locked(self, session: ManagedTerminalSession, item: bytes | object) -> None:
        stale: list[asyncio.Queue[bytes | object]] = []
        for queue in session.clients:
            try:
                queue.put_nowait(item)
            except Exception:
                stale.append(queue)
        for queue in stale:
            session.clients.discard(queue)

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
    ) -> tuple[asyncio.Queue[bytes | object], dict[str, Any]]:
        queue: asyncio.Queue[bytes | object] = asyncio.Queue()
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            if session is None or session.process is None or session.is_closed:
                raise TerminalNotRunningError("终端未启动")
            for chunk in session.replay:
                if chunk.seq > from_seq:
                    queue.put_nowait(chunk.data)
            session.clients.add(queue)
            snapshot = self._build_snapshot_locked(session)
        return queue, snapshot

    async def detach(self, user_id: int, owner_id: str, queue: asyncio.Queue[bytes | object]) -> None:
        async with self._lock:
            session = self._sessions.get(self._key(user_id, owner_id))
            if session is None:
                return
            session.clients.discard(queue)

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
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
        if pump_task is not None:
            await asyncio.gather(pump_task, return_exceptions=True)

    async def _pump_output(
        self,
        session: ManagedTerminalSession,
        process: PtyWrapper,
        output_pump: _TerminalOutputPump,
    ) -> None:
        try:
            while True:
                data = await output_pump.read()
                if data is _TERMINAL_OUTPUT_EOF:
                    break
                if isinstance(data, str):
                    data = data.encode("utf-8", errors="replace")
                if data:
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
