from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot.native_agent.pi_events import build_extension_ui_response
from bot.native_agent.pi_rpc_client import PiRpcClient, PiRpcStartRequest


@dataclass(frozen=True)
class PiSessionRuntimeRequest:
    runtime_key: str
    owner_key: str
    conversation_id: str
    cwd: str
    command: str
    model: str = ""
    agent_id: str = ""
    reasoning_effort: str = ""
    native_session_id: str = ""
    env: dict[str, str] | None = None


@dataclass
class PiSessionRuntimeState:
    pi_runtime_id: str
    runtime_key: str
    owner_key: str
    conversation_id: str
    cwd: str
    command: str
    model: str = ""
    agent_id: str = ""
    reasoning_effort: str = ""
    native_session_id: str = ""
    linear_index: int = 0
    workspace_history_head: str = ""
    processing: bool = False
    pending_permission_ids: set[str] = field(default_factory=set)


class PiSessionRuntime:
    def __init__(self, *, client: PiRpcClient, state: PiSessionRuntimeState) -> None:
        self.client = client
        self.state = state
        self._stream_queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._reader_error: BaseException | None = None
        self._stream_closed = False

    @property
    def runtime_id(self) -> str:
        return self.state.pi_runtime_id

    @property
    def workspace_history_head(self) -> str:
        return self.state.workspace_history_head

    def is_running(self) -> bool:
        process = getattr(self.client, "process", None)
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return True
        try:
            return poll() is None
        except Exception:
            return False

    def matches(self, request: PiSessionRuntimeRequest) -> bool:
        return (
            self.is_running()
            and self.state.runtime_key == request.runtime_key
            and str(Path(self.state.cwd or ".").expanduser().resolve()) == str(Path(request.cwd or ".").expanduser().resolve())
            and self.state.command == str(request.command or "").strip()
            and self.state.model == str(request.model or "").strip()
            and self.state.agent_id == str(request.agent_id or "").strip()
            and self.state.reasoning_effort == str(request.reasoning_effort or "").strip()
        )

    async def prompt(self, text: str, *, conversation_id: str = "") -> None:
        self.state.processing = True
        self._ensure_reader()
        await self.client.prompt(
            text,
            conversation_id=conversation_id or self.state.native_session_id,
            agent_id=self.state.agent_id,
            reasoning_effort=self.state.reasoning_effort,
        )

    async def events(self):
        self._ensure_reader()
        while True:
            item = await self._stream_queue.get()
            if item is _STREAM_DONE:
                await self._stream_queue.put(_STREAM_DONE)
                self.state.processing = False
                if self._reader_error is not None:
                    raise self._reader_error
                return
            yield item

    async def abort(self) -> bool:
        try:
            await self.client.abort()
            return True
        finally:
            self.state.processing = False

    def mark_permission_pending(self, permission_id: str) -> None:
        normalized = str(permission_id or "").strip()
        if normalized:
            self.state.pending_permission_ids.add(normalized)

    async def reply_permission(
        self,
        permission_id: str,
        *,
        approved: bool,
        message: str = "",
    ) -> dict[str, Any]:
        normalized = str(permission_id or "").strip()
        if not normalized or normalized not in self.state.pending_permission_ids:
            raise RuntimeError("原生 agent 权限请求已失效，请刷新后重试")
        payload = build_extension_ui_response(
            normalized,
            accepted=bool(approved),
            value=str(message or "") if message else None,
        )
        await self.client.send(payload)
        self.state.pending_permission_ids.discard(normalized)
        return {"sent": True, "runtime_id": self.runtime_id}

    async def close(self) -> None:
        self.state.processing = False
        try:
            await self.client.close()
        finally:
            await self._drain_reader()

    async def kill(self) -> None:
        self.state.processing = False
        try:
            await self.client.kill()
        finally:
            await self._drain_reader()

    def _ensure_reader(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        try:
            async for event in self.client.events():
                await self._stream_queue.put(event)
        except Exception as exc:
            self._reader_error = exc
        finally:
            self._stream_closed = True
            self.state.processing = False
            await self._stream_queue.put(_STREAM_DONE)

    async def _drain_reader(self) -> None:
        reader = self._reader_task
        if reader is None:
            self._stream_closed = True
            return
        try:
            await reader
        except Exception:
            return


class PiSessionRuntimeRegistry:
    def __init__(self) -> None:
        self._by_key: dict[str, PiSessionRuntime] = {}
        self._by_runtime_id: dict[str, PiSessionRuntime] = {}

    async def open_or_create(self, request: PiSessionRuntimeRequest) -> PiSessionRuntime:
        normalized = _normalize_request(request)
        await self._close_owner_runtimes_except(normalized.owner_key, normalized.runtime_key)
        current = self._by_key.get(normalized.runtime_key)
        if current is not None and current.matches(normalized):
            if normalized.native_session_id and not current.state.native_session_id:
                current.state.native_session_id = normalized.native_session_id
            return current
        if current is not None:
            await self._remove(current, close=True)
        client = await PiRpcClient.start(
            PiRpcStartRequest(
                command=normalized.command,
                cwd=Path(normalized.cwd),
                env=normalized.env,
                model=normalized.model,
            )
        )
        runtime = PiSessionRuntime(
            client=client,
            state=PiSessionRuntimeState(
                pi_runtime_id=f"pir_{uuid.uuid4().hex[:12]}",
                runtime_key=normalized.runtime_key,
                owner_key=normalized.owner_key,
                conversation_id=normalized.conversation_id,
                cwd=normalized.cwd,
                command=normalized.command,
                model=normalized.model,
                agent_id=normalized.agent_id,
                reasoning_effort=normalized.reasoning_effort,
                native_session_id=normalized.native_session_id,
            ),
        )
        self._by_key[normalized.runtime_key] = runtime
        self._by_runtime_id[runtime.runtime_id] = runtime
        return runtime

    def get_by_runtime_id(self, runtime_id: str) -> PiSessionRuntime | None:
        return self._by_runtime_id.get(str(runtime_id or "").strip())

    async def close_runtime(self, runtime: PiSessionRuntime) -> None:
        await self._remove(runtime, close=True)

    async def _close_owner_runtimes_except(self, owner_key: str, runtime_key: str) -> None:
        stale = [
            runtime
            for key, runtime in list(self._by_key.items())
            if key != runtime_key and runtime.state.owner_key == owner_key
        ]
        for runtime in stale:
            await self._remove(runtime, close=True)

    async def _remove(self, runtime: PiSessionRuntime, *, close: bool) -> None:
        self._by_key.pop(runtime.state.runtime_key, None)
        self._by_runtime_id.pop(runtime.runtime_id, None)
        if close:
            await runtime.close()


def build_pi_runtime_key(*, bot_id: int, user_id: int, conversation_id: str) -> str:
    return f"{int(bot_id)}:{int(user_id)}:{str(conversation_id or '').strip()}"


def build_pi_owner_key(*, bot_id: int, user_id: int) -> str:
    return f"{int(bot_id)}:{int(user_id)}"


def _normalize_request(request: PiSessionRuntimeRequest) -> PiSessionRuntimeRequest:
    return PiSessionRuntimeRequest(
        runtime_key=str(request.runtime_key or "").strip(),
        owner_key=str(request.owner_key or "").strip(),
        conversation_id=str(request.conversation_id or "").strip(),
        cwd=str(Path(request.cwd or ".").expanduser().resolve()),
        command=str(request.command or "pi").strip() or "pi",
        model=str(request.model or "").strip(),
        agent_id=str(request.agent_id or "").strip(),
        reasoning_effort=str(request.reasoning_effort or "").strip(),
        native_session_id=str(request.native_session_id or "").strip(),
        env=dict(request.env or {}) or None,
    )


_STREAM_DONE = object()
