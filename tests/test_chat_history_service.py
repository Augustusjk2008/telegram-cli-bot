import asyncio

import pytest

from bot.web.chat_history_service import StreamingPersistenceBuffer


class _ControlledLoop:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def create_task(self, coro):
        return asyncio.create_task(coro)

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingHistoryService:
    def __init__(self) -> None:
        self.previews: list[str] = []
        self.trace_batches: list[list[dict]] = []

    def replace_assistant_preview(self, _handle, preview: str) -> None:
        self.previews.append(preview)

    def append_trace_events(self, _handle, events: list[dict]) -> None:
        self.trace_batches.append(events)


async def _await_scheduled_flush(buffer: StreamingPersistenceBuffer) -> None:
    task = buffer._flush_task
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), timeout=1)


@pytest.mark.asyncio
async def test_streaming_preview_flushes_are_coalesced_and_duplicates_are_skipped() -> None:
    loop = _ControlledLoop()
    service = _RecordingHistoryService()
    buffer = StreamingPersistenceBuffer(
        service,
        object(),
        loop=loop,
        flush_interval_seconds=0.25,
        preview_flush_interval_seconds=2.0,
    )

    buffer.queue_preview("first")
    buffer.maybe_flush()
    assert buffer._flush_task is None

    loop.advance(1.0)
    buffer.queue_preview("latest")
    buffer.maybe_flush()
    assert buffer._flush_task is None

    loop.advance(1.0)
    buffer.maybe_flush()
    await _await_scheduled_flush(buffer)

    assert service.previews == ["latest"]
    assert buffer.preview_flush_count == 1

    loop.advance(2.0)
    buffer.queue_preview("latest")
    buffer.maybe_flush()
    await buffer.close()

    assert service.previews == ["latest"]
    assert buffer.flush_count == 1


@pytest.mark.asyncio
async def test_streaming_trace_keeps_fast_flush_interval() -> None:
    loop = _ControlledLoop()
    service = _RecordingHistoryService()
    buffer = StreamingPersistenceBuffer(
        service,
        object(),
        loop=loop,
        flush_interval_seconds=0.25,
        preview_flush_interval_seconds=5.0,
    )

    loop.advance(0.25)
    buffer.queue_trace({"kind": "tool_call", "summary": "run"})
    buffer.maybe_flush()
    await _await_scheduled_flush(buffer)

    assert service.trace_batches == [[{"kind": "tool_call", "summary": "run"}]]
    assert buffer.trace_flush_count == 1
    assert buffer.flush_count == 1
