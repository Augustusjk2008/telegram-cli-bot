from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from bot.web.diagnostics import diag_log_event, diag_log_slow

RunSource = Literal["web", "cron", "manual"]
RunStatus = Literal["queued", "running", "completed", "failed"]
ResultExecutor = Callable[["AssistantRunRequest"], Awaitable[dict[str, Any]]]
StreamExecutor = Callable[["AssistantRunRequest"], AsyncIterator[dict[str, Any]]]

_STOP = object()
_RUNTIME_STOPPED_MESSAGE = "assistant runtime stopped"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssistantRunRequest:
    run_id: str
    source: RunSource
    bot_alias: str
    user_id: int
    text: str
    interactive: bool
    visible_text: str | None = None
    context_user_id: int | None = None
    actor_user_id: int | None = None
    actor_account_id: str | None = None
    actor_username: str | None = None
    task_mode: Literal["standard", "dream", "proposal_patch", "plan"] = "standard"
    task_payload: dict[str, Any] | None = None
    job_id: str | None = None
    job_title: str | None = None
    scheduled_at: str | None = None
    enqueued_at: str | None = None
    timeout_seconds: int | None = None


@dataclass
class _QueuedRun:
    request: AssistantRunRequest
    mode: Literal["result", "stream", "background"]
    future: asyncio.Future[dict[str, Any]]
    event_queue: asyncio.Queue[dict[str, Any] | object] | None = None
    status: RunStatus = field(default="queued")
    enqueued_monotonic: float = field(default_factory=time.perf_counter)
    finished_monotonic: float | None = None


@dataclass(frozen=True)
class AssistantRuntimePendingRunSnapshot:
    run_id: str
    source: RunSource
    status: Literal["queued", "running"]
    task_mode: Literal["standard", "dream", "proposal_patch", "plan"]
    interactive: bool
    job_id: str = ""
    job_title: str = ""
    visible_text: str = ""
    enqueued_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "status": self.status,
            "task_mode": self.task_mode,
            "interactive": self.interactive,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "visible_text": self.visible_text,
            "enqueued_at": self.enqueued_at,
        }


@dataclass(frozen=True)
class AssistantRuntimeSnapshot:
    pending_count: int
    queued_count: int
    active: AssistantRuntimePendingRunSnapshot | None = None
    queue: tuple[AssistantRuntimePendingRunSnapshot, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending_count": self.pending_count,
            "queued_count": self.queued_count,
            "active": self.active.to_dict() if self.active is not None else None,
            "queue": [item.to_dict() for item in self.queue],
        }


class AssistantRuntimeCoordinator:
    def __init__(
        self,
        *,
        result_executor: ResultExecutor,
        stream_executor: StreamExecutor | None = None,
        max_retained_runs: int = 50,
        retained_run_ttl_seconds: float = 3600.0,
    ) -> None:
        self._result_executor = result_executor
        self._stream_executor = stream_executor
        self._queue: asyncio.Queue[_QueuedRun | object] = asyncio.Queue()
        self._runs: dict[str, _QueuedRun] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._max_retained_runs = max(0, int(max_retained_runs))
        self._retained_run_ttl_seconds = max(0.0, float(retained_run_ttl_seconds))

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker(), name="assistant-runtime-coordinator")

    async def stop(self) -> None:
        task = self._worker_task
        if task is None:
            return
        self._stopping = True
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._worker_task = None
        self._fail_pending_runs(_RUNTIME_STOPPED_MESSAGE)

    async def submit_interactive(self, request: AssistantRunRequest) -> dict[str, Any]:
        run = self._enqueue(request, mode="result")
        return await run.future

    async def stream_interactive(self, request: AssistantRunRequest) -> AsyncIterator[dict[str, Any]]:
        run = self._enqueue(request, mode="stream")
        assert run.event_queue is not None
        while True:
            event = await run.event_queue.get()
            if event is _STOP:
                break
            yield event
        try:
            await run.future
        except Exception:
            return

    async def submit_background(self, request: AssistantRunRequest) -> dict[str, Any]:
        run = self._enqueue(request, mode="background")
        return {"run_id": request.run_id, "status": run.status}

    async def wait_for_run(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id: {run_id}")
        return await run.future

    def has_run(self, run_id: str) -> bool:
        return run_id in self._runs

    @staticmethod
    def _excerpt(text: str | None, *, limit: int = 80) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def _snapshot_item(self, run: _QueuedRun) -> AssistantRuntimePendingRunSnapshot:
        request = run.request
        return AssistantRuntimePendingRunSnapshot(
            run_id=request.run_id,
            source=request.source,
            status="running" if run.status == "running" else "queued",
            task_mode=request.task_mode,
            interactive=request.interactive,
            job_id=str(request.job_id or ""),
            job_title=self._excerpt(request.job_title),
            visible_text=self._excerpt(request.visible_text or request.text),
            enqueued_at=str(request.enqueued_at or ""),
        )

    def snapshot_for_bot(self, bot_alias: str, *, queue_limit: int = 5) -> dict[str, Any]:
        pending_runs = [
            run
            for run in self._runs.values()
            if run.request.bot_alias == bot_alias and run.status in {"queued", "running"}
        ]
        active_run = next((run for run in pending_runs if run.status == "running"), None)
        queued_runs = [run for run in pending_runs if run.status == "queued"]
        snapshot = AssistantRuntimeSnapshot(
            pending_count=len(pending_runs),
            queued_count=len(queued_runs),
            active=self._snapshot_item(active_run) if active_run is not None else None,
            queue=tuple(self._snapshot_item(run) for run in queued_runs[: max(0, int(queue_limit))]),
        )
        return snapshot.to_dict()

    def _mark_finished(self, run: _QueuedRun) -> None:
        run.finished_monotonic = time.monotonic()
        self._cleanup_finished_runs()

    def _cleanup_finished_runs(self) -> None:
        pending_ids = {
            run_id
            for run_id, run in self._runs.items()
            if run.status in {"queued", "running"} or run.finished_monotonic is None
        }
        finished = [
            (run_id, run)
            for run_id, run in self._runs.items()
            if run_id not in pending_ids
        ]
        if not finished:
            return
        now = time.monotonic()
        expired_ids = {
            run_id
            for run_id, run in finished
            if self._retained_run_ttl_seconds > 0
            and run.finished_monotonic is not None
            and now - run.finished_monotonic > self._retained_run_ttl_seconds
        }
        finished.sort(key=lambda item: item[1].finished_monotonic or 0)
        overflow = max(0, len(finished) - self._max_retained_runs)
        evict_ids = expired_ids | {run_id for run_id, _run in finished[:overflow]}
        for run_id in evict_ids:
            self._runs.pop(run_id, None)

    def _enqueue(self, request: AssistantRunRequest, *, mode: Literal["result", "stream", "background"]) -> _QueuedRun:
        if self._stopping or self._worker_task is None or self._worker_task.done():
            raise RuntimeError("assistant runtime coordinator is not started")
        if not request.enqueued_at:
            request = AssistantRunRequest(
                **{
                    **request.__dict__,
                    "enqueued_at": self._now_iso(),
                }
            )
        loop = asyncio.get_running_loop()
        run = _QueuedRun(
            request=request,
            mode=mode,
            future=loop.create_future(),
            event_queue=asyncio.Queue() if mode == "stream" else None,
        )
        self._runs[request.run_id] = run
        self._queue.put_nowait(run)
        diag_log_event(
            logger,
            "assistant_runtime_queued",
            run_id=request.run_id,
            alias=request.bot_alias,
            source=request.source,
            task_mode=request.task_mode,
            interactive=request.interactive,
            mode=mode,
            queued_count=self._queue.qsize(),
        )
        return run

    def _fail_run(self, run: _QueuedRun, message: str) -> None:
        run.status = "failed"
        run.finished_monotonic = time.monotonic()
        if run.mode == "stream" and run.event_queue is not None:
            run.event_queue.put_nowait(
                {
                    "type": "error",
                    "code": "assistant_runtime_stopped",
                    "message": message,
                }
            )
            run.event_queue.put_nowait(_STOP)
        if not run.future.done():
            run.future.set_exception(RuntimeError(message))

    def _fail_pending_runs(self, message: str) -> None:
        while True:
            try:
                queued = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if queued is _STOP:
                continue
            self._fail_run(queued, message)

    async def _worker(self) -> None:
        current_run: _QueuedRun | None = None
        try:
            while True:
                queued = await self._queue.get()
                if queued is _STOP:
                    break
                run = queued
                current_run = run
                run.status = "running"
                started_at = time.perf_counter()
                queue_wait_ms = int(round((started_at - run.enqueued_monotonic) * 1000))
                diag_log_slow(
                    logger,
                    "assistant_runtime_queue_wait",
                    queue_wait_ms,
                    run_id=run.request.run_id,
                    alias=run.request.bot_alias,
                    source=run.request.source,
                    task_mode=run.request.task_mode,
                    interactive=run.request.interactive,
                    mode=run.mode,
                )
                diag_log_event(
                    logger,
                    "assistant_runtime_running",
                    run_id=run.request.run_id,
                    alias=run.request.bot_alias,
                    source=run.request.source,
                    task_mode=run.request.task_mode,
                    interactive=run.request.interactive,
                    mode=run.mode,
                    queue_wait_ms=queue_wait_ms,
                )
                try:
                    if run.mode == "stream":
                        await self._run_stream_request(run)
                    else:
                        result = await self._run_result_request(run)
                        run.status = "completed"
                        if not run.future.done():
                            run.future.set_result(result)
                    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
                    diag_log_event(
                        logger,
                        "assistant_runtime_done",
                        run_id=run.request.run_id,
                        alias=run.request.bot_alias,
                        source=run.request.source,
                        task_mode=run.request.task_mode,
                        interactive=run.request.interactive,
                        mode=run.mode,
                        status=run.status,
                        elapsed_ms=elapsed_ms,
                        queue_wait_ms=queue_wait_ms,
                    )
                    diag_log_slow(
                        logger,
                        "assistant_runtime_run",
                        elapsed_ms,
                        run_id=run.request.run_id,
                        alias=run.request.bot_alias,
                        source=run.request.source,
                        task_mode=run.request.task_mode,
                        interactive=run.request.interactive,
                        mode=run.mode,
                        status=run.status,
                    )
                except asyncio.CancelledError:
                    run.status = "failed"
                    if run.mode == "stream" and run.event_queue is not None:
                        await run.event_queue.put(
                            {
                                "type": "error",
                                "code": "assistant_runtime_stopped",
                                "message": _RUNTIME_STOPPED_MESSAGE,
                            }
                        )
                    if not run.future.done():
                        run.future.set_exception(RuntimeError(_RUNTIME_STOPPED_MESSAGE))
                    diag_log_slow(
                        logger,
                        "assistant_runtime_run",
                        int(round((time.perf_counter() - started_at) * 1000)),
                        run_id=run.request.run_id,
                        alias=run.request.bot_alias,
                        source=run.request.source,
                        task_mode=run.request.task_mode,
                        interactive=run.request.interactive,
                        mode=run.mode,
                        status="cancelled",
                    )
                    raise
                except Exception as exc:
                    run.status = "failed"
                    if run.mode == "stream" and run.event_queue is not None:
                        await run.event_queue.put(
                            {
                                "type": "error",
                                "code": "assistant_runtime_failed",
                                "message": str(exc),
                            }
                        )
                    if not run.future.done():
                        run.future.set_exception(exc)
                    diag_log_slow(
                        logger,
                        "assistant_runtime_run",
                        int(round((time.perf_counter() - started_at) * 1000)),
                        run_id=run.request.run_id,
                        alias=run.request.bot_alias,
                        source=run.request.source,
                        task_mode=run.request.task_mode,
                        interactive=run.request.interactive,
                        mode=run.mode,
                        status="failed",
                    )
                finally:
                    if run.mode == "stream" and run.event_queue is not None:
                        await run.event_queue.put(_STOP)
                    self._mark_finished(run)
                current_run = None
        except asyncio.CancelledError:
            if current_run is not None and not current_run.future.done():
                self._fail_run(current_run, _RUNTIME_STOPPED_MESSAGE)
            raise

    async def _run_result_request(self, run: _QueuedRun) -> dict[str, Any]:
        timeout_seconds = run.request.timeout_seconds
        coro = self._result_executor(run.request)
        if timeout_seconds is None or int(timeout_seconds) <= 0:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout=float(timeout_seconds))
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"assistant run timed out after {int(timeout_seconds)}s") from exc

    async def _run_stream_request(self, run: _QueuedRun) -> None:
        if self._stream_executor is None:
            raise RuntimeError("assistant stream executor is not configured")
        assert run.event_queue is not None
        result: dict[str, Any] | None = None
        async for event in self._stream_executor(run.request):
            await run.event_queue.put(event)
            if isinstance(event, dict) and event.get("type") == "done":
                result = dict(event)
        run.status = "completed"
        if result is None:
            result = {"run_id": run.request.run_id, "status": "completed"}
        if not run.future.done():
            run.future.set_result(result)
