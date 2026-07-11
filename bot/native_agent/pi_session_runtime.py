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
PI_RUNTIME_SHUTDOWN_MAX_CONCURRENCY = max(1, int(os.environ.get("TCB_PI_RUNTIME_SHUTDOWN_MAX_CONCURRENCY", "4")))
PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS = max(1.0, float(os.environ.get("TCB_PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS", "30")))
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
        self._owner_start_locks: dict[str, asyncio.Lock] = {}
        self._start_reservations: set[asyncio.Task[Any]] = set()
        self._start_tasks: set[asyncio.Task[Any]] = set()
        self._owner_start_refcounts: dict[str, int] = {}
        self._shutdown_started = False
        self._before_runtime_close = before_runtime_close
        self._closing_runtime_ids: set[str] = set()

    async def open_or_create(self, request: PiSessionRuntimeRequest) -> PiSessionRuntime:
        normalized = _normalize_request(request)
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Pi runtime 启动任务不可用")
        async with self._lock:
            if self._shutdown_started:
                raise RuntimeError("Pi runtime registry 正在关闭")
            self._start_tasks.add(task)
            owner_lock = self._owner_start_locks.setdefault(normalized.owner_key, asyncio.Lock())
            self._owner_start_refcounts[normalized.owner_key] = self._owner_start_refcounts.get(normalized.owner_key, 0) + 1
        try:
            async with owner_lock:
                return await self._open_or_create_for_owner(normalized)
        finally:
            async with self._lock:
                self._start_tasks.discard(task)
                self._start_reservations.discard(task)
                remaining_owners = self._owner_start_refcounts.get(normalized.owner_key, 1) - 1
                if remaining_owners <= 0:
                    self._owner_start_refcounts.pop(normalized.owner_key, None)
                    self._owner_start_locks.pop(normalized.owner_key, None)
                else:
                    self._owner_start_refcounts[normalized.owner_key] = remaining_owners

    async def _open_or_create_for_owner(self, normalized: PiSessionRuntimeRequest) -> PiSessionRuntime:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Pi runtime 启动任务不可用")
        async with self._lock:
            if self._shutdown_started:
                raise RuntimeError("Pi runtime registry 正在关闭")
            stale = self._detach_idle_locked()
            stale.extend(self._detach_owner_runtimes_except_locked(normalized.owner_key, normalized.runtime_key))
            current = self._by_key.get(normalized.runtime_key)
            if current is not None and current.matches(normalized):
                self._refresh_runtime(current, normalized)
                matched = current
            else:
                matched = None
            if current is not None and matched is None:
                detached = self._detach_locked(current)
                if detached is not None:
                    stale.append(detached)
            if matched is None:
                capacity_limit = max(0, PI_RUNTIME_MAX_COUNT - len(self._start_reservations) - 1)
                stale.extend(self._detach_idle_locked(max_count=capacity_limit))
                if len(self._by_runtime_id) + len(self._start_reservations) >= PI_RUNTIME_MAX_COUNT:
                    raise RuntimeError("Pi runtime 数量已达上限，请稍后重试")
                self._start_reservations.add(task)
        await self._close_many(stale)
        if matched is not None:
            return matched

        client: PiRpcClient | None = None
        try:
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
            async with self._lock:
                self._start_reservations.discard(task)
                if self._shutdown_started:
                    rejected = True
                    current = None
                else:
                    current = self._by_key.get(normalized.runtime_key)
                    rejected = current is not None and current.matches(normalized)
                    if not rejected:
                        self._by_key[normalized.runtime_key] = runtime
                        self._by_runtime_id[runtime.runtime_id] = runtime
                        return runtime
            client = None
            await runtime.close()
            if current is not None:
                self._refresh_runtime(current, normalized)
                return current
            raise RuntimeError("Pi runtime registry 正在关闭")
        except BaseException:
            async with self._lock:
                self._start_reservations.discard(task)
            if client is not None:
                try:
                    await client.close()
                except BaseException:
                    pass
            raise

    @staticmethod
    def _refresh_runtime(runtime: PiSessionRuntime, request: PiSessionRuntimeRequest) -> None:
        runtime.refresh_from_request(request)
        runtime.touch()
        if request.native_session_id and not runtime.state.native_session_id:
            runtime.state.native_session_id = request.native_session_id

    async def evict_idle(self) -> int:
        async with self._lock:
            runtimes = self._detach_idle_locked()
        await self._close_many(runtimes)
        return len(runtimes)

    def _detach_idle_locked(
        self,
        *,
        exclude_runtime_id: str = "",
        max_count: int | None = None,
    ) -> list[PiSessionRuntime]:
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
        runtimes = [self._detach_locked(runtime) for runtime in unique.values()]
        return [runtime for runtime in runtimes if runtime is not None]

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
            detached = self._detach_locked(runtime)
        if detached is not None:
            await self._persist_and_close_runtime(detached)

    async def shutdown(self) -> dict[str, int]:
        deadline = asyncio.get_running_loop().time() + PI_RUNTIME_SHUTDOWN_DEADLINE_SECONDS
        report = {
            "requested": 0,
            "persisted": 0,
            "closed": 0,
            "failed": 0,
            "timed_out": 0,
            "lock_timed_out": False,
            "start_tasks_cancelled": 0,
        }
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=remaining)
        except asyncio.TimeoutError:
            report["timed_out"] = 1
            report["lock_timed_out"] = True
            return report
        try:
            self._shutdown_started = True
            runtimes = list(self._by_runtime_id.values())
            start_tasks = [task for task in self._start_tasks if task is not asyncio.current_task()]
            self._by_key.clear()
            self._by_runtime_id.clear()
            self._start_reservations.clear()
            self._closing_runtime_ids.update(runtime.runtime_id for runtime in runtimes)
        finally:
            self._lock.release()

        report["requested"] = len(runtimes)
        for task in start_tasks:
            if not task.done():
                task.cancel()
                report["start_tasks_cancelled"] += 1
        if start_tasks:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            if remaining <= 0:
                report["timed_out"] += sum(1 for task in start_tasks if not task.done())
            else:
                done, pending = await asyncio.wait(start_tasks, timeout=remaining)
                report["timed_out"] += len(pending)
                for task in pending:
                    task.cancel()

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        close_report = await self._close_many(runtimes, deadline_seconds=remaining)
        for key in ("persisted", "closed", "failed", "timed_out"):
            report[key] += close_report[key]
        return report

    def _detach_owner_runtimes_except_locked(self, owner_key: str, runtime_key: str) -> list[PiSessionRuntime]:
        stale = [
            runtime
            for key, runtime in list(self._by_key.items())
            if key != runtime_key and runtime.state.owner_key == owner_key
        ]
        detached = [self._detach_locked(runtime) for runtime in stale]
        return [runtime for runtime in detached if runtime is not None]

    def _detach_locked(self, runtime: PiSessionRuntime) -> PiSessionRuntime | None:
        current = self._by_runtime_id.get(runtime.runtime_id)
        if current is not runtime or runtime.runtime_id in self._closing_runtime_ids:
            return None
        self._by_key.pop(runtime.state.runtime_key, None)
        self._by_runtime_id.pop(runtime.runtime_id, None)
        self._closing_runtime_ids.add(runtime.runtime_id)
        return runtime

    async def _persist_and_close_runtime(self, runtime: PiSessionRuntime) -> dict[str, bool]:
        persisted = False
        closed = False
        try:
            if self._before_runtime_close is not None:
                try:
                    await self._before_runtime_close(runtime)
                except Exception:
                    persisted = False
                else:
                    persisted = True
            else:
                persisted = True
            try:
                await runtime.close()
            except Exception:
                closed = False
            else:
                closed = True
            return {"persisted": persisted, "closed": closed}
        finally:
            self._closing_runtime_ids.discard(runtime.runtime_id)

    async def _close_many(
        self,
        runtimes: list[PiSessionRuntime],
        *,
        deadline_seconds: float | None = None,
    ) -> dict[str, int]:
        report = {"requested": len(runtimes), "persisted": 0, "closed": 0, "failed": 0, "timed_out": 0}
        if not runtimes:
            return report
        semaphore = asyncio.Semaphore(PI_RUNTIME_SHUTDOWN_MAX_CONCURRENCY)

        async def close_one(runtime: PiSessionRuntime) -> dict[str, bool]:
            async with semaphore:
                try:
                    return await self._persist_and_close_runtime(runtime)
                except Exception:
                    return {"persisted": False, "closed": False}

        tasks = [asyncio.create_task(close_one(runtime)) for runtime in runtimes]
        if deadline_seconds is None:
            done: set[asyncio.Task[dict[str, bool]]] = set(tasks)
            pending: set[asyncio.Task[dict[str, bool]]] = set()
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline_seconds))
            report["timed_out"] = len(pending)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.sleep(0)
        for task in done:
            if task.cancelled():
                report["failed"] += 1
                continue
            try:
                result = task.result()
            except BaseException:
                report["failed"] += 1
                continue
            if not isinstance(result, dict):
                report["failed"] += 1
                continue
            report["persisted"] += int(bool(result.get("persisted")))
            report["closed"] += int(bool(result.get("closed")))
            if not result.get("closed"):
                report["failed"] += 1
        return report


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
