from __future__ import annotations

import asyncio
import queue
import threading
import time

import pytest

from bot.web.api_service import (
    CliOutputLimitError,
    _PROCESS_STDOUT_EOF,
    _StreamPreviewState,
    _communicate_claude_process,
    _communicate_codex_process,
    _communicate_process,
    _start_process_stdout_reader,
)


class _StreamingStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.closed = False

    def readline(self, _size: int = -1) -> str:
        if self.closed:
            return ""
        return next(self._lines, "")

    def close(self) -> None:
        self.closed = True


class _ReaderProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _StreamingStdout(lines)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_stdout_reader_blocks_on_bounded_queue_without_losing_eof():
    process = _ReaderProcess(["one\n", "two\n", "three\n"])
    output_queue: queue.Queue[object] = queue.Queue(maxsize=1)

    reader = _start_process_stdout_reader(
        process,
        output_queue,
        max_line_bytes=1024,
        max_total_bytes=4096,
    )

    time.sleep(0.05)
    assert output_queue.qsize() == 1
    assert reader.done.is_set() is False

    received: list[object] = []
    while True:
        item = output_queue.get(timeout=1)
        received.append(item)
        if item is _PROCESS_STDOUT_EOF:
            break

    reader.join(timeout=1)
    assert received[:-1] == ["one\n", "two\n", "three\n"]
    assert reader.done.is_set() is True


def test_stdout_reader_delivers_limit_error_before_eof():
    process = _ReaderProcess(["x" * 17])
    output_queue: queue.Queue[object] = queue.Queue(maxsize=1)

    reader = _start_process_stdout_reader(
        process,
        output_queue,
        max_line_bytes=16,
        max_total_bytes=64,
    )

    error = output_queue.get(timeout=1)
    eof = output_queue.get(timeout=1)
    reader.join(timeout=1)

    assert isinstance(error, CliOutputLimitError)
    assert eof is _PROCESS_STDOUT_EOF


def test_codex_terminal_snapshot_is_not_published_as_stream_preview():
    preview = _StreamPreviewState("codex")

    preview.consume(
        '{"type":"event_msg","payload":{"type":"agent_message","message":"最终答复"}}\n'
    )

    assert "preview_text" not in preview.status_event(elapsed_seconds=1)
    assert preview.result().final_text == "最终答复"


@pytest.mark.asyncio
async def test_communicate_cancellation_stops_reader_and_process(monkeypatch):
    class BlockingStdout:
        def __init__(self) -> None:
            self.closed = False
            self._closed = threading.Event()

        def readline(self, _size: int = -1) -> str:
            self._closed.wait(2)
            return ""

        def close(self) -> None:
            self.closed = True
            self._closed.set()

    class BlockingProcess:
        def __init__(self) -> None:
            self.stdout = BlockingStdout()
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

    process = BlockingProcess()

    def terminate(current) -> None:
        current.terminated = True
        current.returncode = -15
        current.stdout.close()

    monkeypatch.setattr("bot.web.api_service._terminate_process_sync", terminate)
    monkeypatch.setattr("bot.web.api_service.close_process_streams", lambda _process: None)

    task = asyncio.create_task(_communicate_process(process))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert process.stdout.closed is True


@pytest.mark.asyncio
async def test_codex_communicate_parses_jsonl_incrementally():
    process = _ReaderProcess(
        [
            '{"type":"thread.started","thread_id":"thread-1"}\n',
            *[
                f'{{"type":"item.delta","item":{{"type":"assistant_message","delta":"{index}"}}}}\n'
                for index in range(100)
            ],
            '{"type":"event_msg","payload":{"type":"agent_message","message":"done"}}\n',
        ]
    )

    response, thread_id, returncode = await _communicate_codex_process(process)

    assert response == "done"
    assert thread_id == "thread-1"
    assert returncode == 0


@pytest.mark.asyncio
async def test_claude_communicate_prefers_final_result_incrementally():
    process = _ReaderProcess(
        [
            '{"type":"stream_event","session_id":"session-1","event":{"type":"content_block_delta",'
            '"delta":{"type":"text_delta","text":"partial"}}}\n',
            '{"type":"result","session_id":"session-1","subtype":"success","result":"complete"}\n',
        ]
    )

    response, session_id, returncode = await _communicate_claude_process(process)

    assert response == "complete"
    assert session_id == "session-1"
    assert returncode == 0


@pytest.mark.asyncio
async def test_codex_communicate_preserves_error_event():
    process = _ReaderProcess(
        ['{"type":"error","message":"upstream failed"}\n']
    )
    process.returncode = 1

    response, _, returncode = await _communicate_codex_process(process)

    assert response == "upstream failed"
    assert returncode == 1
