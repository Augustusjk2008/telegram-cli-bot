from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

RunSource = Literal["web", "cron", "manual"]
RunStatus = Literal["queued", "running", "completed", "failed"]
ResultExecutor = Callable[["AssistantRunRequest"], Awaitable[dict[str, Any]]]
StreamExecutor = Callable[["AssistantRunRequest"], AsyncIterator[dict[str, Any]]]

_STOP = object()


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
    task_mode: Literal["standard", "dream"] = "standard"
    task_payload: dict[str, Any] | None = None
    job_id: str | None = None
    scheduled_at: str | None = None
    enqueued_at: str | None = None


@dataclass
class _QueuedRun:
    request: AssistantRunRequest
    mode: Literal["result", "stream", "background"]
    future: asyncio.Future[dict[str, Any]]
    event_queue: asyncio.Queue[dict[str, Any] | object] | None = None
    status: RunStatus = field(default="queued")


class AssistantRuntimeCoordinator:
    def __init__(
        self,
        *,
        result_executor: ResultExecutor,
        stream_executor: StreamExecutor | None = None,
    ) -> None:
        self._result_executor = result_executor
        self._stream_executor = stream_executor
        self._queue: asyncio.Queue[_QueuedRun | object] = asyncio.Queue()
        self._runs: dict[str, _QueuedRun] = {}
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker(), name="assistant-runtime-coordinator")

    async def stop(self) -> None:
        task = self._worker_task
        if task is None:
            return
        await self._queue.put(_STOP)
        await task
        self._worker_task = None

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

    def _enqueue(self, request: AssistantRunRequest, *, mode: Literal["result", "stream", "background"]) -> _QueuedRun:
        if self._worker_task is None or self._worker_task.done():
            raise RuntimeError("assistant runtime coordinator is not started")
        loop = asyncio.get_running_loop()
        run = _QueuedRun(
            request=request,
            mode=mode,
            future=loop.create_future(),
            event_queue=asyncio.Queue() if mode == "stream" else None,
        )
        self._runs[request.run_id] = run
        self._queue.put_nowait(run)
        return run

    async def _worker(self) -> None:
        while True:
            queued = await self._queue.get()
            if queued is _STOP:
                break
            run = queued
            run.status = "running"
            try:
                if run.mode == "stream":
                    await self._run_stream_request(run)
                else:
                    result = await self._result_executor(run.request)
                    run.status = "completed"
                    if not run.future.done():
                        run.future.set_result(result)
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
            finally:
                if run.mode == "stream" and run.event_queue is not None:
                    await run.event_queue.put(_STOP)

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
