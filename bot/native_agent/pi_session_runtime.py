from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot.native_agent.pi_events import build_extension_ui_response
from bot.native_agent.pi_rpc_client import PiRpcClient, PiRpcStartRequest


PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS = max(32, int(os.environ.get("TCB_PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS", "512")))
PI_RUNTIME_IDLE_TTL_SECONDS = max(60.0, float(os.environ.get("TCB_PI_RUNTIME_IDLE_TTL_SECONDS", "1800")))
PI_RUNTIME_MAX_COUNT = max(1, int(os.environ.get("TCB_PI_RUNTIME_MAX_COUNT", "32")))
_STREAM_TERMINAL_RESERVE = 3
_StreamItem = dict[str, Any] | object
_BeforeRuntimeClose = Callable[["PiSessionRuntime"], Awaitable[None]]


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
    system_prompt: str = ""
    append_system_prompt: str = ""
    native_session_id: str = ""
    config_fingerprint: str = ""
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
    system_prompt: str = ""
    append_system_prompt: str = ""
    native_session_id: str = ""
    config_fingerprint: str = ""
    env: dict[str, str] | None = None
    linear_index: int = 0
    workspace_history_head: str = ""
    processing: bool = False
    pending_permission_ids: set[str] = field(default_factory=set)


class PiSessionRuntime:
    def __init__(self, *, client: PiRpcClient, state: PiSessionRuntimeState) -> None:
        self.client = client
        self.state = state
        self._stream_queue: asyncio.Queue[_StreamItem] = asyncio.Queue(maxsize=PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS)
        self._stream_normal_limit = max(
            1,
            PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS - min(_STREAM_TERMINAL_RESERVE, PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS - 1),
        )
        self._reader_task: asyncio.Task[None] | None = None
        self._reader_error: BaseException | None = None
        self._stream_closed = False
        self._active_consumers = 0
        self.last_used_at = time.monotonic()

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
            and self.state.owner_key == request.owner_key
            and str(Path(self.state.cwd or ".").expanduser().resolve()) == str(Path(request.cwd or ".").expanduser().resolve())
        )

    def refresh_from_request(self, request: PiSessionRuntimeRequest) -> None:
        self.state.command = str(request.command or "").strip()
        self.state.model = str(request.model or "").strip()
        self.state.agent_id = str(request.agent_id or "").strip()
        self.state.reasoning_effort = str(request.reasoning_effort or "").strip()
        self.state.system_prompt = str(request.system_prompt or "").strip()
        self.state.append_system_prompt = str(request.append_system_prompt or "").strip()
        self.state.config_fingerprint = str(request.config_fingerprint or "").strip()
        self.state.env = _normalize_env(request.env)

    async def prompt(self, text: str, *, conversation_id: str = "") -> None:
        self.touch()
        self.state.processing = True
        self._ensure_reader()
        await self.client.prompt(
            text,
            conversation_id=conversation_id or self.state.native_session_id,
            agent_id=self.state.agent_id,
            reasoning_effort=self.state.reasoning_effort,
        )

    async def capture_state(self) -> dict[str, Any]:
        if self._reader_task is not None:
            return {}
        state = await self.client.get_state()
        session_id = _state_session_id(state)
        if session_id:
            self.state.native_session_id = session_id
        return state

    async def events(self):
        if self._active_consumers:
            raise RuntimeError("Pi runtime 已有活动事件消费者")
        self._active_consumers += 1
        self.touch()
        self._ensure_reader()
        try:
            while True:
                item = await self._stream_queue.get()
                if item is _STREAM_DONE:
                    self._stream_queue.put_nowait(_STREAM_DONE)
                    self.state.processing = False
                    if self._reader_error is not None:
                        raise self._reader_error
                    return
                yield item
        finally:
            self._active_consumers = max(0, self._active_consumers - 1)
            self.touch()

    def touch(self) -> None:
        self.last_used_at = time.monotonic()

    def diagnostics(self) -> dict[str, int | float | bool]:
        return {
            "stream_queue_events": self._stream_queue.qsize(),
            "stream_queue_max_events": PI_RUNTIME_STREAM_QUEUE_MAX_EVENTS,
            "processing": self.state.processing,
            "pending_permissions": len(self.state.pending_permission_ids),
            "active_consumers": self._active_consumers,
            "idle_seconds": max(0.0, time.monotonic() - self.last_used_at),
        }

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
                self._enqueue_stream_item(event)
        except Exception as exc:
            self._reader_error = exc
        finally:
            self._stream_closed = True
            self.state.processing = False
            self._enqueue_stream_item(_STREAM_DONE)

    def _enqueue_stream_item(self, item: _StreamItem) -> None:
        if _is_terminal_stream_item(item):
            terminal_key = _terminal_stream_key(item)
            self._discard_queued_item(
                lambda queued: (
                    _is_terminal_stream_item(queued)
                    and _terminal_stream_key(queued) == terminal_key
                )
            )
            if self._stream_queue.full():
                removed = self._discard_queued_item(_is_low_priority_stream_item)
                if not removed:
                    removed = self._discard_queued_item(_is_ordinary_stream_item)
                if not removed:
                    self._discard_queued_item(lambda _queued: True)
            self._stream_queue.put_nowait(item)
            return

        if _is_critical_control_stream_item(item):
            if self._stream_queue.full():
                removed = self._discard_queued_item(_is_low_priority_stream_item)
                if not removed:
                    removed = self._discard_queued_item(_is_ordinary_stream_item)
                if not removed:
                    return
            self._stream_queue.put_nowait(item)
            return

        if self._stream_queue.qsize() < self._stream_normal_limit:
            self._stream_queue.put_nowait(item)
            return
        if not _is_low_priority_stream_item(item) and self._discard_queued_item(_is_low_priority_stream_item):
            self._stream_queue.put_nowait(item)

    def _discard_queued_item(self, predicate: Callable[[_StreamItem], bool]) -> bool:
        retained: list[_StreamItem] = []
        removed = False
        while True:
            try:
                queued = self._stream_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._stream_queue.task_done()
            if not removed and predicate(queued):
                removed = True
                continue
            retained.append(queued)
        for queued in retained:
            self._stream_queue.put_nowait(queued)
        return removed

    async def _drain_reader(self) -> None:
        reader = self._reader_task
        if reader is None:
            self._stream_closed = True
            return
        if not reader.done():
            reader.cancel()
        try:
            await reader
        except BaseException:
            return


class PiSessionRuntimeRegistry:
    def __init__(self, *, before_runtime_close: _BeforeRuntimeClose | None = None) -> None:
        self._by_key: dict[str, PiSessionRuntime] = {}
        self._by_runtime_id: dict[str, PiSessionRuntime] = {}
        self._lock = asyncio.Lock()
        self._before_runtime_close = before_runtime_close

    async def open_or_create(self, request: PiSessionRuntimeRequest) -> PiSessionRuntime:
        async with self._lock:
            await self._evict_idle_locked()
            normalized = _normalize_request(request)
            await self._close_owner_runtimes_except(normalized.owner_key, normalized.runtime_key)
            current = self._by_key.get(normalized.runtime_key)
            if current is not None and current.matches(normalized):
                current.refresh_from_request(normalized)
                current.touch()
                if normalized.native_session_id and not current.state.native_session_id:
                    current.state.native_session_id = normalized.native_session_id
                return current
            if current is not None:
                await self._remove(current, close=True)
            await self._evict_idle_locked(max_count=max(0, PI_RUNTIME_MAX_COUNT - 1))
            if len(self._by_runtime_id) >= PI_RUNTIME_MAX_COUNT:
                raise RuntimeError("Pi runtime 数量已达上限，请稍后重试")
            client = await PiRpcClient.start(
                PiRpcStartRequest(
                    command=normalized.command,
                    cwd=Path(normalized.cwd),
                    env=normalized.env,
                    model=normalized.model,
                    system_prompt=normalized.system_prompt,
                    append_system_prompt=normalized.append_system_prompt,
                    session_id=normalized.native_session_id,
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
                    system_prompt=normalized.system_prompt,
                    append_system_prompt=normalized.append_system_prompt,
                    native_session_id=normalized.native_session_id,
                    config_fingerprint=normalized.config_fingerprint,
                    env=normalized.env,
                ),
            )
            self._by_key[normalized.runtime_key] = runtime
            self._by_runtime_id[runtime.runtime_id] = runtime
            await self._evict_idle_locked(exclude_runtime_id=runtime.runtime_id)
            return runtime

    async def evict_idle(self) -> int:
        async with self._lock:
            return await self._evict_idle_locked()

    async def _evict_idle_locked(
        self,
        *,
        exclude_runtime_id: str = "",
        max_count: int | None = None,
    ) -> int:
        now = time.monotonic()
        runtime_limit = PI_RUNTIME_MAX_COUNT if max_count is None else max(0, int(max_count))
        candidates = [
            runtime
            for runtime in self._by_runtime_id.values()
            if not runtime.state.processing
            and not runtime.state.pending_permission_ids
            and not runtime._active_consumers
            and runtime.runtime_id != exclude_runtime_id
        ]
        candidates.sort(key=lambda runtime: runtime.last_used_at)
        evict = [runtime for runtime in candidates if now - runtime.last_used_at >= PI_RUNTIME_IDLE_TTL_SECONDS]
        remaining = len(self._by_runtime_id) - len(evict)
        if remaining > runtime_limit:
            evicted_ids = {runtime.runtime_id for runtime in evict}
            additional = [
                runtime
                for runtime in candidates
                if runtime.runtime_id not in evicted_ids
            ]
            evict.extend(additional[: remaining - runtime_limit])
        unique = {runtime.runtime_id: runtime for runtime in evict}
        for runtime in unique.values():
            await self._remove(runtime, close=True)
        return len(unique)

    def diagnostics(self) -> dict[str, int]:
        return {
            "runtime_count": len(self._by_runtime_id),
            "processing_count": sum(1 for runtime in self._by_runtime_id.values() if runtime.state.processing),
            "pending_permission_count": sum(len(runtime.state.pending_permission_ids) for runtime in self._by_runtime_id.values()),
        }

    def get_by_runtime_id(self, runtime_id: str) -> PiSessionRuntime | None:
        return self._by_runtime_id.get(str(runtime_id or "").strip())

    async def close_runtime(self, runtime: PiSessionRuntime) -> None:
        async with self._lock:
            await self._remove(runtime, close=True)

    async def shutdown(self) -> None:
        async with self._lock:
            runtimes = list(self._by_runtime_id.values())
            self._by_key.clear()
            self._by_runtime_id.clear()
        for runtime in runtimes:
            try:
                await runtime.close()
            except Exception:
                pass

    async def _close_owner_runtimes_except(self, owner_key: str, runtime_key: str) -> None:
        stale = [
            runtime
            for key, runtime in list(self._by_key.items())
            if key != runtime_key and runtime.state.owner_key == owner_key
        ]
        for runtime in stale:
            await self._remove(runtime, close=True)

    async def _remove(self, runtime: PiSessionRuntime, *, close: bool) -> None:
        if close and self._before_runtime_close is not None:
            await self._before_runtime_close(runtime)
        self._by_key.pop(runtime.state.runtime_key, None)
        self._by_runtime_id.pop(runtime.runtime_id, None)
        if close:
            await runtime.close()


def build_pi_runtime_key(*, bot_id: int, user_id: int, conversation_id: str, agent_id: str = "") -> str:
    agent_scope = str(agent_id or "").strip().lower()
    base = f"{int(bot_id)}:{int(user_id)}:{str(conversation_id or '').strip()}"
    return f"{base}:{agent_scope}" if agent_scope and agent_scope != "main" else base


def build_pi_owner_key(*, bot_id: int, user_id: int, agent_id: str = "") -> str:
    agent_scope = str(agent_id or "").strip().lower()
    base = f"{int(bot_id)}:{int(user_id)}"
    return f"{base}:{agent_scope}" if agent_scope and agent_scope != "main" else base


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
        system_prompt=str(request.system_prompt or "").strip(),
        append_system_prompt=str(request.append_system_prompt or "").strip(),
        native_session_id=str(request.native_session_id or "").strip(),
        config_fingerprint=str(request.config_fingerprint or "").strip(),
        env=_normalize_env(request.env),
    )


def _normalize_env(env: dict[str, str] | None) -> dict[str, str] | None:
    normalized = {
        str(key): str(value)
        for key, value in dict(env or {}).items()
        if str(key)
    }
    return normalized or None


def _state_session_id(state: dict[str, Any]) -> str:
    for key in ("sessionId", "sessionID", "session_id"):
        value = state.get(key)
        if value:
            return str(value).strip()
    return ""


_STREAM_DONE = object()


def _stream_event_type(item: _StreamItem) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("type") or item.get("event") or item.get("name") or "").strip().lower()


def _is_terminal_stream_item(item: _StreamItem) -> bool:
    if item is _STREAM_DONE:
        return True
    if not isinstance(item, dict):
        return False
    if _stream_event_type(item) in {
        "agent_end",
        "done",
        "eof",
        "error",
        "extension_error",
        "session.error",
        "session.idle",
        "turn_end",
    }:
        return True
    return _stream_item_has_error(item)


def _is_low_priority_stream_item(item: _StreamItem) -> bool:
    if not isinstance(item, dict):
        return False
    event_type = _stream_event_type(item)
    if event_type in {"delta", "progress", "status", "tool_execution_update"}:
        return True
    assistant_event = item.get("assistantMessageEvent")
    if not isinstance(assistant_event, dict):
        return False
    return str(assistant_event.get("type") or "").strip().lower().endswith("_delta")


def _is_critical_control_stream_item(item: _StreamItem) -> bool:
    if _is_terminal_stream_item(item) or not isinstance(item, dict):
        return _is_terminal_stream_item(item)
    event_type = _stream_event_type(item)
    if event_type == "extension_ui_request" or "permission" in event_type:
        return True
    if event_type in {"session_state", "session_start", "session_started", "session_created"}:
        return True
    return any(
        item.get(key)
        for key in (
            "sessionId",
            "sessionID",
            "session_id",
            "turnId",
            "turnID",
            "turn_id",
        )
    )


def _is_ordinary_stream_item(item: _StreamItem) -> bool:
    return not _is_terminal_stream_item(item) and not _is_critical_control_stream_item(item)


def _terminal_stream_key(item: _StreamItem) -> str:
    if item is _STREAM_DONE:
        return "eof"
    event_type = _stream_event_type(item)
    if event_type == "eof":
        return "eof"
    if _stream_item_has_error(item):
        return "error"
    if event_type in {"agent_end", "done", "session.idle", "turn_end"}:
        return "done"
    return event_type or "terminal"


def _stream_item_has_error(item: _StreamItem) -> bool:
    if not isinstance(item, dict):
        return False
    if _stream_event_type(item) in {"error", "extension_error", "session.error"}:
        return True
    if item.get("success") is False or item.get("error"):
        return True
    message = item.get("message")
    if isinstance(message, dict) and message.get("error"):
        return True
    finish = str(
        item.get("finish")
        or item.get("finish_reason")
        or item.get("finishReason")
        or (message.get("finish") if isinstance(message, dict) else "")
        or (message.get("finish_reason") if isinstance(message, dict) else "")
        or (message.get("finishReason") if isinstance(message, dict) else "")
        or ""
    ).strip().lower()
    return finish in {"error", "failed", "failure"}
