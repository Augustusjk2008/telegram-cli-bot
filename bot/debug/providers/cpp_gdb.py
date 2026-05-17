from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from bot.debug.gdb_session import GdbMiError, GdbMiSession
from bot.debug.models import DebugBreakpoint, DebugFrame, DebugProfile, DebugScope, DebugVariable

from .base import DebugProvider, DebugProviderError, DebugProviderSession


def _locals_reference(frame_id: str) -> str:
    return f"{frame_id}:locals" if frame_id else ""


class _CppGdbSession(DebugProviderSession):
    def __init__(self, profile: DebugProfile, *, gdb_session_factory=GdbMiSession):
        self._profile = profile
        self._gdb_session_factory = gdb_session_factory
        self._gdb: GdbMiSession | Any | None = None
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._current_frame_id = ""

    async def launch(self, payload: dict[str, object]) -> None:
        host = str(payload.get("remote_host") or self._profile.remote_host)
        port = int(payload.get("remote_port") or self._profile.remote_port)
        try:
            self._gdb = self._gdb_session_factory(self._profile)
            for event in self._gdb.launch(host, port) or []:
                await self._events.put(event)
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc

    async def stop(self) -> None:
        if self._gdb is None:
            return
        close = getattr(self._gdb, "close", None)
        if callable(close):
            close()
        self._gdb = None

    async def continue_execution(self) -> None:
        events = self._call("continue_execution")
        await self._emit_events(events)
        return events

    async def pause(self) -> None:
        events = self._call("pause_execution")
        await self._emit_events(events)
        return events

    async def next(self) -> None:
        events = self._call("next_instruction")
        await self._emit_events(events)
        return events

    async def step_in(self) -> None:
        events = self._call("step_in")
        await self._emit_events(events)
        return events

    async def step_out(self) -> None:
        events = self._call("step_out")
        await self._emit_events(events)
        return events

    async def set_breakpoints(self, source: str, breakpoints: list[dict[str, object]]) -> list[dict[str, object]]:
        source = str(source or "").strip()
        lines = [int(item.get("line") or 0) for item in breakpoints if int(item.get("line") or 0) > 0]
        try:
            items = self._require_gdb().replace_breakpoints(
                [DebugBreakpoint(source=source, line=line, verified=False, status="pending") for line in lines]
            )
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc
        return [item.to_api() for item in items]

    async def stack_trace(self) -> list[dict[str, object]]:
        try:
            frames = self._require_gdb().stack_trace()
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc
        self._current_frame_id = frames[0].id if frames else ""
        return [item.to_api() for item in frames]

    async def scopes(self, frame_id: str) -> list[dict[str, object]]:
        reference = _locals_reference(frame_id)
        return [DebugScope(name="Locals", variables_reference=reference).to_api()] if reference else []

    async def variables(self, variables_reference: str) -> list[dict[str, object]]:
        try:
            gdb = self._require_gdb()
            if variables_reference.endswith(":locals") and hasattr(gdb, "list_locals"):
                variables = gdb.list_locals(self._current_frame_id)
            elif hasattr(gdb, "list_variables"):
                variables = gdb.list_variables(variables_reference, self._current_frame_id)
            elif hasattr(gdb, "list_locals"):
                variables = gdb.list_locals(self._current_frame_id)
            else:
                variables = []
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc
        return [item.to_api() for item in variables]

    async def evaluate(self, expression: str, frame_id: str = "") -> dict[str, object]:
        try:
            return self._require_gdb().evaluate_expression(expression, frame_id or self._current_frame_id)
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc

    async def events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self._events.get()

    async def close(self) -> None:
        await self.stop()

    def poll_events(self) -> list[dict[str, object]]:
        if self._gdb is None:
            return []
        try:
            return self._gdb.poll_events()
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc

    def run_to_entry(self, symbol: str = "main") -> list[dict[str, object]]:
        try:
            return self._require_gdb().run_to_entry(symbol)
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc

    async def _emit_events(self, events: list[dict[str, object]]) -> None:
        for event in events or []:
            await self._events.put(event)

    def _call(self, method_name: str) -> list[dict[str, object]]:
        method = getattr(self._require_gdb(), method_name)
        try:
            return method() or []
        except GdbMiError as exc:
            raise DebugProviderError(exc.code, exc.message) from exc

    def _require_gdb(self):
        if self._gdb is None:
            raise DebugProviderError("session_not_started", "调试会话未启动")
        return self._gdb


class CppGdbProvider(DebugProvider):
    provider_id = "cpp-gdb"
    provider_label = "C++ GDB"

    def __init__(self, *, gdb_session_factory=GdbMiSession):
        self._gdb_session_factory = gdb_session_factory

    def can_handle(self, profile: DebugProfile) -> bool:
        return profile.provider_id == self.provider_id or profile.language == "cpp"

    def create_session(self, profile: DebugProfile) -> _CppGdbSession:
        return _CppGdbSession(profile, gdb_session_factory=self._gdb_session_factory)

    async def cleanup_remote(self, launch_payload: dict[str, object]) -> bool:
        host = str(launch_payload.get("remote_host") or "").strip()
        user = str(launch_payload.get("remote_user") or "").strip()
        port = int(launch_payload.get("remote_port") or 0)
        if not host or not user or port <= 0:
            return False
        command = ["ssh", f"{user}@{host}", f"pkill -f 'gdbserver :{port}' || true"]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            return False
        return True
