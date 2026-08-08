from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from pathlib import Path

import pytest

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import api_service
from bot.web.api_service import (
    CliOutputLimitError,
    _PROCESS_STDOUT_EOF,
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


class _UsageCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int, int]] = []
        self.failure_contexts: list[tuple[bool, str | None]] = []

    async def record_once(
        self,
        sample,
        *,
        invalid_usage_count: int = 0,
        duplicate_terminal_count: int = 0,
        failed: bool = False,
        session_id: str | None = None,
    ) -> None:
        self.calls.append((sample, invalid_usage_count, duplicate_terminal_count))
        self.failure_contexts.append((failed, session_id))


class _UsageProcess(_ReaderProcess):
    def __init__(self) -> None:
        super().__init__(
            [
                '{"type":"thread.started","thread_id":"usage-thread"}\n',
                '{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n',
                '{"type":"turn.completed","usage":{"input_tokens":11,'
                '"cached_input_tokens":5,"output_tokens":4,"reasoning_output_tokens":2}}\n',
            ]
        )
        self.stdin = None

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


class _ContinuouslyRefilledOutputQueue:
    def __init__(self, max_items_before_yield: int = 512) -> None:
        self.release_eof = False
        self.get_calls = 0
        self._max_items_before_yield = max_items_before_yield

    def empty(self) -> bool:
        return False

    def get_nowait(self) -> object:
        self.get_calls += 1
        if self.release_eof:
            return _PROCESS_STDOUT_EOF
        if self.get_calls > self._max_items_before_yield:
            raise AssertionError("stdout drain did not cooperatively yield to the event loop")
        return '{"type":"item.delta","item":{"type":"assistant_message","delta":"x"}}\n'


class _ContinuousOutputReader:
    def __init__(self) -> None:
        self.done = threading.Event()

    def close_stdout(self) -> None:
        self.done.set()

    def join(self, _timeout: float | None = None) -> None:
        return None

    def stop(self) -> None:
        self.done.set()


@pytest.fixture
def usage_manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
            enabled=True,
        ),
        str(storage),
    )

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

    result = await _communicate_codex_process(process)

    assert result.text == "done"
    assert result.session_id == "thread-1"
    assert result.returncode == 0
    assert result.token_usage is None


@pytest.mark.asyncio
async def test_codex_communicate_records_usage_once_during_cleanup():
    capture = _UsageCapture()
    process = _ReaderProcess(
        [
            '{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":1}}\n',
            '{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":1}}\n',
        ]
    )

    await _communicate_codex_process(process, usage_capture=capture)

    assert len(capture.calls) == 1
    sample, invalid_count, duplicate_count = capture.calls[0]
    assert sample is not None
    assert sample.input_tokens == 3
    assert invalid_count == 0
    assert duplicate_count == 1


@pytest.mark.asyncio
async def test_codex_communicate_requests_rollout_usage_when_terminal_usage_is_missing():
    failed_capture = _UsageCapture()

    await _communicate_codex_process(
        _ReaderProcess(
            [
                '{"type":"thread.started","thread_id":"failed-thread"}\n',
                '{"type":"turn.failed","error":{"message":"boom"}}\n',
            ]
        ),
        usage_capture=failed_capture,
    )

    assert failed_capture.calls == [(None, 0, 0)]
    assert failed_capture.failure_contexts == [(True, "failed-thread")]


@pytest.mark.asyncio
async def test_stream_cli_chat_starts_capture_before_spawn_and_records_once(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    capture = _UsageCapture()
    spawned = False

    async def start_capture(*, env, command):
        assert env["CI"] == "true"
        assert command == ["codex"]
        assert spawned is False
        return capture

    def popen(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        return _UsageProcess()

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", popen)

    events = [
        event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    ]

    assert next(event for event in events if event["type"] == "done")["output"] == "done"
    assert len(capture.calls) == 1
    assert capture.calls[0][0].input_tokens == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(("include_trace", "expected_trace"), [(True, True), (False, False)])
async def test_stream_cli_chat_normalizes_slash_and_preserves_ids_on_legacy_sse_events(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    include_trace: bool,
    expected_trace: bool,
):
    capture = _UsageCapture()
    process = _UsageProcess()
    process.stdout = _StreamingStdout(
        [
            '{"type":"thread.started","thread_id":"contract-thread"}\n',
            '{"type":"item.delta","item":{"type":"assistant_message","delta":"working"}}\n',
            '{"type":"item.completed","item":{"type":"function_call","name":"shell_command",'
            '"call_id":"call-1","arguments":"{\\"command\\":\\"pwd\\"}"}}\n',
            '{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n',
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
        ]
    )
    captured_command: dict[str, object] = {}
    persisted_trace: list[dict[str, object]] = []

    async def start_capture(*, env, command):
        return capture

    def build_command(**kwargs):
        captured_command.update(kwargs)
        return ["codex"], False

    original_queue_trace = api_service.StreamingPersistenceBuffer.queue_trace

    def queue_trace(buffer, event):
        persisted_trace.append(event)
        return original_queue_trace(buffer, event)

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", build_command)
    monkeypatch.setattr(api_service.StreamingPersistenceBuffer, "queue_trace", queue_trace)
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

    events = [
        event
        async for event in api_service._stream_cli_chat(
            usage_manager,
            "main",
            1001,
            "//status",
            include_trace=include_trace,
        )
    ]

    assert captured_command["user_text"] == "/status"
    meta = next(event for event in events if event["type"] == "meta")
    assert any(event["type"] == "trace" for event in events) is expected_trace
    assert persisted_trace
    for event_type in {"meta", "status", "done"}:
        event = next(event for event in events if event["type"] == event_type)
        assert event["turn_id"] == meta["turn_id"]
        assert event["assistant_message_id"] == meta["assistant_message_id"]
    if expected_trace:
        trace = next(event for event in events if event["type"] == "trace")
        assert trace["turn_id"] == meta["turn_id"]
        assert trace["assistant_message_id"] == meta["assistant_message_id"]


@pytest.mark.asyncio
async def test_stream_cli_chat_yields_when_stdout_queue_stays_nonempty(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    output_queue = _ContinuouslyRefilledOutputQueue()
    reader = _ContinuousOutputReader()

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _UsageProcess())
    monkeypatch.setattr(api_service.queue, "Queue", lambda *_args, **_kwargs: output_queue)
    monkeypatch.setattr(api_service, "_start_process_stdout_reader", lambda *_args, **_kwargs: reader)

    stream = api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    meta = await anext(stream)
    assert meta["type"] == "meta"

    asyncio.get_running_loop().call_soon(setattr, output_queue, "release_eof", True)
    events = [meta]
    async for event in stream:
        events.append(event)

    done = next(event for event in events if event["type"] == "done")
    assert output_queue.release_eof is True
    assert done["turn_id"] == meta["turn_id"]
    assert done["assistant_message_id"] == meta["assistant_message_id"]


@pytest.mark.asyncio
async def test_stream_cli_chat_waits_for_queued_tail_before_quiet_finish_termination(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    output_queue: queue.Queue[object] = queue.Queue()
    output_queue.put('{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n')
    output_queue.put('{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n')
    for index in range(128):
        output_queue.put(f'{{"type":"thread.started","thread_id":"tail-{index}"}}\n')
    output_queue.put(_PROCESS_STDOUT_EOF)
    reader = _ContinuousOutputReader()
    reader.done.set()
    process = _UsageProcess()
    termination_queue_empty: list[bool] = []

    async def start_capture(*, env, command):
        return _UsageCapture()

    def terminate_after_drain(_process) -> None:
        termination_queue_empty.append(output_queue.empty())
        process.returncode = 0

    monkeypatch.setattr(api_service, "CODEX_DONE_QUIET_SECONDS", 0)
    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(api_service.queue, "Queue", lambda *_args, **_kwargs: output_queue)
    monkeypatch.setattr(api_service, "_start_process_stdout_reader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(api_service, "_terminate_process_sync", terminate_after_drain)

    events = [
        event
        async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    ]

    assert any(event["type"] == "done" for event in events)
    assert termination_queue_empty == [True]


@pytest.mark.asyncio
async def test_non_stream_cli_chat_records_before_chat_store_completion_failure(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    capture = _UsageCapture()

    async def start_capture(*, env, command):
        return capture

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _UsageProcess())
    monkeypatch.setattr(
        api_service.ChatHistoryService,
        "complete_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("chat store failed")),
    )

    with pytest.raises(RuntimeError, match="chat store failed"):
        await api_service.run_cli_chat(usage_manager, "main", 1001, "hello")

    assert len(capture.calls) == 1
    assert capture.calls[0][0].input_tokens == 11


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

    result = await _communicate_codex_process(process)

    assert result.text == "upstream failed"
    assert result.returncode == 1
