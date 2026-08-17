from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import replace
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


async def _collect_stream_events(stream) -> list[dict[str, object]]:
    return [event async for event in stream]


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


@pytest.mark.asyncio
async def test_run_cli_chat_consumes_stream_until_done(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    observed: dict[str, object] = {}
    done_event = {
        "type": "done",
        "turn_id": "turn-1",
        "assistant_message_id": "message-1",
        "output": "done",
        "message": {"id": "message-1", "content": "done"},
        "elapsed_seconds": 3,
        "returncode": 0,
        "session": {"is_processing": False},
    }

    async def fake_stream(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        try:
            yield {"type": "meta"}
            yield {"type": "status", "preview_text": "working"}
            yield done_event
            pytest.fail("run_cli_chat 不应继续消费 done 后的事件")
        finally:
            observed["closed"] = True

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: None)

    result = await api_service.run_cli_chat(
        usage_manager,
        "main",
        1001,
        "hello",
        allow_unsafe_cli=True,
        cluster_run_id="clr_test",
        cluster_mentions=[{"agent_id": "worker"}],
    )

    assert observed["args"] == (usage_manager, "main", 1001, "hello")
    assert observed["kwargs"] == {
        "request": None,
        "agent_id": "main",
        "cli_params_override": None,
        "allow_unsafe_cli": True,
        "cluster_run_id": "clr_test",
        "cluster_mentions": [{"agent_id": "worker"}],
        "include_trace": False,
    }
    assert observed["closed"] is True
    assert result == {
        "output": "done",
        "message": {"id": "message-1", "content": "done"},
        "elapsed_seconds": 3,
        "returncode": 0,
        "session": {"is_processing": False},
    }


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
async def test_cli_lifecycle_cleanup_continues_after_caller_is_cancelled(monkeypatch):
    terminate_started = threading.Event()
    release_terminate = threading.Event()
    tree_closed = threading.Event()
    streams_closed = threading.Event()

    class BlockingProcessTree:
        def terminate(self) -> None:
            terminate_started.set()
            release_terminate.wait(timeout=2)

        def close(self) -> None:
            tree_closed.set()

    lifecycle = api_service._CliProcessLifecycle(
        process=object(),
        process_tree=BlockingProcessTree(),
    )
    monkeypatch.setattr(
        api_service,
        "close_process_streams",
        lambda _process: streams_closed.set(),
    )
    cleanup_task = asyncio.create_task(
        api_service._cleanup_cli_process_lifecycle(lifecycle, abort=True)
    )
    assert await asyncio.to_thread(terminate_started.wait, 1)

    cleanup_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cleanup_task
    release_terminate.set()

    assert await asyncio.to_thread(tree_closed.wait, 1)
    assert await asyncio.to_thread(streams_closed.wait, 1)


@pytest.mark.asyncio
async def test_stream_cli_chat_resets_session_after_repeated_cancellation(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    terminate_started = threading.Event()
    release_terminate = threading.Event()
    reader_started = threading.Event()

    class BlockingStdout:
        def __init__(self) -> None:
            self.closed = False
            self.release = threading.Event()

        def readline(self, _size: int = -1) -> str:
            reader_started.set()
            self.release.wait(timeout=2)
            return ""

        def close(self) -> None:
            self.closed = True
            self.release.set()

    class BlockingProcess:
        def __init__(self) -> None:
            self.stdout = BlockingStdout()
            self.stdin = None
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if not self.stdout.release.wait(timeout=timeout):
                raise subprocess.TimeoutExpired("blocking", timeout)
            return self.returncode

    class BlockingProcessTree:
        is_contained = True

        def __init__(self, process: BlockingProcess) -> None:
            self.process = process

        def terminate(self) -> None:
            terminate_started.set()
            release_terminate.wait(timeout=2)
            self.process.returncode = -15
            self.process.stdout.release.set()

        def close(self) -> None:
            return None

    process = BlockingProcess()

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        api_service,
        "attach_process_tree",
        lambda _process, **_kwargs: BlockingProcessTree(process),
    )

    stream = api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    meta = await anext(stream)
    assert meta["type"] == "meta"
    next_event = asyncio.create_task(anext(stream))
    assert await asyncio.to_thread(reader_started.wait, 1)

    next_event.cancel()
    assert await asyncio.to_thread(terminate_started.wait, 1)
    next_event.cancel()
    release_terminate.set()
    with pytest.raises(asyncio.CancelledError):
        await next_event

    _profile, _agent, session = api_service.get_chat_session_for_alias(
        usage_manager,
        "main",
        1001,
        "main",
    )
    assert session.process is None
    assert session.is_processing is False
    assert session.stop_requested is False


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_cli_chat_reconciles_history_when_process_isolation_fails(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
):
    process = _UsageProcess()
    reconciled_sessions: list[object] = []
    original_reconcile = api_service.ChatHistoryService.reconcile_idle_streaming_turns

    def reconcile(service, session):
        reconciled_sessions.append(session)
        return original_reconcile(service, session)

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        api_service,
        "resume_suspended_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("job unavailable")),
    )
    monkeypatch.setattr(
        api_service.ChatHistoryService,
        "reconcile_idle_streaming_turns",
        reconcile,
    )

    with pytest.raises(api_service.WebApiError) as exc_info:
        if streaming:
            _ = [
                event
                async for event in api_service._stream_cli_chat(
                    usage_manager,
                    "main",
                    1001,
                    "hello",
                )
            ]
        else:
            await api_service.run_cli_chat(usage_manager, "main", 1001, "hello")

    assert exc_info.value.code == "cli_process_isolation_failed"
    assert len(reconciled_sessions) == 1
    session = reconciled_sessions[0]
    assert session.process is None
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_cli_stream_cleanup_keeps_event_loop_responsive_with_inherited_stdout_pipe(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    release_path = tmp_path / "release-grandchild"
    done_path = tmp_path / "grandchild-done"
    grandchild_code = (
        "import pathlib,sys,time\n"
        "release = pathlib.Path(sys.argv[1])\n"
        "done = pathlib.Path(sys.argv[2])\n"
        "deadline = time.monotonic() + 10\n"
        "while time.monotonic() < deadline and not release.exists():\n"
        "    time.sleep(0.02)\n"
        "done.write_text('done', encoding='utf-8')\n"
    )
    parent_code = (
        "import subprocess,sys\n"
        f"subprocess.Popen([sys.executable, '-I', '-c', {grandchild_code!r}, "
        f"{str(release_path)!r}, {str(done_path)!r}], "
        "stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr, close_fds=False)\n"
        "print('{\"type\":\"thread.started\",\"thread_id\":\"pipe-thread\"}', flush=True)\n"
        "print('{\"type\":\"item.completed\",\"item\":{\"type\":\"assistant_message\",\"text\":\"done\"}}', flush=True)\n"
        "print('{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":1,\"output_tokens\":1}}', flush=True)\n"
    )
    command = [sys.executable, "-I", "-c", parent_code]
    blocked_read_entered = threading.Event()
    captured_process: dict[str, subprocess.Popen] = {}
    captured_popen_kwargs: dict[str, object] = {}
    captured_reader: dict[str, object] = {}
    timer_holder: dict[str, threading.Timer] = {}
    loop = asyncio.get_running_loop()
    probe_ran = asyncio.Event()
    probe_times: dict[str, float] = {}

    def record_probe() -> None:
        probe_times["ran"] = time.perf_counter()
        probe_ran.set()

    def send_probe() -> None:
        probe_times["sent"] = time.perf_counter()
        loop.call_soon_threadsafe(record_probe)

    class ObservedPipeStdout:
        def __init__(self, raw_stdout) -> None:
            self.raw_stdout = raw_stdout
            self.readline_calls = 0

        def readline(self, size: int = -1) -> str:
            self.readline_calls += 1
            if self.readline_calls == 4:
                probe_times["blocked"] = time.perf_counter()
                blocked_read_entered.set()
                timer = threading.Timer(0.4, send_probe)
                timer_holder["timer"] = timer
                timer.start()
            return self.raw_stdout.readline(size)

        def close(self) -> None:
            self.raw_stdout.close()

        @property
        def closed(self) -> bool:
            return self.raw_stdout.closed

    original_popen = subprocess.Popen

    def popen(*args, **kwargs):
        captured_popen_kwargs.update(kwargs)
        process = original_popen(*args, **kwargs)
        assert process.stdout is not None
        process.stdout = ObservedPipeStdout(process.stdout)
        captured_process["process"] = process
        return process

    original_start_reader = api_service._start_process_stdout_reader

    def start_reader(*args, **kwargs):
        reader = original_start_reader(*args, **kwargs)
        captured_reader["reader"] = reader
        return reader

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "CODEX_DONE_QUIET_SECONDS", 0.1)
    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (command, False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", popen)
    monkeypatch.setattr(api_service, "_start_process_stdout_reader", start_reader)

    stream_task = asyncio.create_task(
        asyncio.wait_for(
            _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")),
            timeout=5,
        )
    )
    try:
        assert await asyncio.to_thread(blocked_read_entered.wait, 2), "未形成后代继承 stdout 的阻塞读取"
        process = captured_process["process"]
        assert await asyncio.to_thread(process.wait, 1) == 0
        reader = captured_reader["reader"]
        assert reader.done.is_set() is False
        assert done_path.exists() is False

        events = await stream_task
        await asyncio.wait_for(probe_ran.wait(), timeout=1)

        probe_delay = probe_times["ran"] - probe_times["sent"]
        assert probe_delay < 0.5, (
            f"event loop blocked {probe_delay:.3f}s while closing inherited stdout pipe"
        )
        assert any(event["type"] == "done" for event in events)
        assert time.perf_counter() - probe_times["blocked"] < 3
        if sys.platform == "win32":
            assert int(captured_popen_kwargs["creationflags"]) & 0x00000004
        assert reader.done.is_set() is True
        await asyncio.to_thread(reader.join, 0.5)
        assert process.stdout.closed is True
        _profile, _agent, session = api_service.get_chat_session_for_alias(
            usage_manager,
            "main",
            1001,
            "main",
        )
        assert session.process is None
        assert session.is_processing is False
        assert session.stop_requested is False
    finally:
        release_path.touch(exist_ok=True)
        timer = timer_holder.get("timer")
        if timer is not None:
            timer.cancel()
            if timer.is_alive():
                await asyncio.to_thread(timer.join, 1)
        if not stream_task.done():
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        process = captured_process.get("process")
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 1)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not done_path.exists():
            await asyncio.sleep(0.02)


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
@pytest.mark.parametrize(("stream_protocol_version", "expects_output"), [(1, True), (2, False)])
async def test_stream_cli_chat_starts_capture_before_spawn_and_records_once(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    stream_protocol_version: int,
    expects_output: bool,
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
        event
        async for event in api_service._stream_cli_chat(
            usage_manager,
            "main",
            1001,
            "hello",
            stream_protocol_version=stream_protocol_version,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["message"]["content"] == "done"
    assert ("output" in done) is expects_output
    if expects_output:
        assert done["output"] == "done"
    assert done["turn_id"]
    assert done["assistant_message_id"]
    assert isinstance(done["elapsed_seconds"], int)
    assert done["returncode"] == 0
    assert isinstance(done["session"], dict)
    assert len(capture.calls) == 1
    assert capture.calls[0][0].input_tokens == 11


@pytest.mark.parametrize(
    ("stream_protocol_version", "output", "message_content", "expects_output"),
    [
        (1, "same", "same", True),
        (2, "same", "same", False),
        (2, "", "", True),
        (2, "fallback", "", True),
        (3, "same", "same", True),
    ],
)
def test_compact_cli_done_event_preserves_v1_empty_and_mismatched_output(
    stream_protocol_version: int,
    output: str,
    message_content: str,
    expects_output: bool,
):
    event = {
        "type": "done",
        "turn_id": "turn-compact",
        "assistant_message_id": "assistant-compact",
        "output": output,
        "message": {
            "id": "assistant-compact",
            "content": message_content,
            "state": "error",
            "meta": {"completion_state": "error"},
        },
    }

    compacted = api_service._compact_cli_done_event(event, stream_protocol_version)

    assert ("output" in compacted) is expects_output
    assert compacted["message"]["content"] == message_content
    assert compacted["message"]["state"] == "error"
    assert compacted["message"]["meta"]["completion_state"] == "error"
    assert compacted["turn_id"] == "turn-compact"
    assert compacted["assistant_message_id"] == "assistant-compact"


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
async def test_stream_cli_chat_reuses_cluster_guidance_but_refreshes_run_id(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    usage_manager.main_profile.cluster = replace(usage_manager.main_profile.cluster, enabled=True)
    prompts: list[str] = []
    processes = iter([_UsageProcess(), _UsageProcess()])

    async def start_capture(*, env, command):
        return _UsageCapture()

    def build_command(**kwargs):
        prompts.append(str(kwargs["user_text"]))
        return ["codex"], False

    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", build_command)
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: next(processes))

    for run_id in ("run-1", "run-2"):
        events = [
            event
            async for event in api_service._stream_cli_chat(
                usage_manager,
                "main",
                1001,
                "hello",
                cluster_run_id=run_id,
            )
        ]
        assert any(event["type"] == "done" for event in events)

    assert "简单、不可并行或委派成本更高" in prompts[0]
    assert "当前 run_id: run-1" in prompts[0]
    assert "简单、不可并行或委派成本更高" not in prompts[1]
    assert "沿用本会话此前的集群规则" in prompts[1]
    assert "当前 run_id: run-2" in prompts[1]


@pytest.mark.asyncio
async def test_stream_cli_chat_coalesces_status_and_flushes_latest_before_done(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    process = _UsageProcess()
    process.stdout = _StreamingStdout([
        '{"type":"thread.started","thread_id":"status-thread"}\n',
        *[
            f'{{"type":"item.delta","item":{{"type":"assistant_message","delta":"{index}"}}}}\n'
            for index in range(20)
        ],
        '{"type":"item.completed","item":{"type":"function_call","name":"shell_command",'
        '"call_id":"status-call","arguments":"{\\"command\\":\\"pwd\\"}"}}\n',
        '{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n',
        '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
    ])

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "CLI_STATUS_MIN_INTERVAL_SECONDS", 5.0)
    monkeypatch.setattr(api_service, "_CLI_STREAM_DRAIN_BATCH_SIZE", 1)
    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

    async def collect_events():
        return [
            event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
        ]

    events = await asyncio.wait_for(collect_events(), timeout=2.0)
    statuses = [event for event in events if event["type"] == "status"]
    meta = next(event for event in events if event["type"] == "meta")

    assert len(statuses) == 2
    assert statuses[-1]["preview_text"].endswith("1819")
    assert events[-2] == statuses[-1]
    assert events[-1]["type"] == "done"
    assert any(event["type"] == "trace" for event in events)
    for event in statuses:
        assert event["turn_id"] == meta["turn_id"]
        assert event["assistant_message_id"] == meta["assistant_message_id"]


@pytest.mark.asyncio
async def test_stream_cli_chat_flushes_pending_status_before_error(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    output_queue: queue.Queue[object] = queue.Queue()
    output_queue.put('{"type":"thread.started","thread_id":"error-thread"}\n')
    output_queue.put('{"type":"item.delta","item":{"type":"assistant_message","delta":"first"}}\n')
    output_queue.put('{"type":"item.delta","item":{"type":"assistant_message","delta":"latest"}}\n')
    output_queue.put(RuntimeError("stream failed"))
    reader = _ContinuousOutputReader()
    reader.done.set()
    process = _UsageProcess()

    async def start_capture(*, env, command):
        return _UsageCapture()

    monkeypatch.setattr(api_service, "CLI_STATUS_MIN_INTERVAL_SECONDS", 5.0)
    monkeypatch.setattr(api_service, "_CLI_STREAM_DRAIN_BATCH_SIZE", 1)
    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(api_service.queue, "Queue", lambda *_args, **_kwargs: output_queue)
    monkeypatch.setattr(api_service, "_start_process_stdout_reader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(api_service, "_terminate_process_sync", lambda current: setattr(current, "returncode", -1))

    events: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="stream failed"):
        async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"):
            events.append(event)

    statuses = [event for event in events if event["type"] == "status"]
    meta = next(event for event in events if event["type"] == "meta")
    assert len(statuses) == 2
    assert statuses[-1]["preview_text"] == "firstlatest"
    assert events[-1] == statuses[-1]
    assert statuses[-1]["turn_id"] == meta["turn_id"]
    assert statuses[-1]["assistant_message_id"] == meta["assistant_message_id"]


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
async def test_stream_cli_chat_drains_tail_enqueued_while_terminating(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    output_queue: queue.Queue[object] = queue.Queue()
    output_queue.put('{"type":"thread.started","thread_id":"tail-thread"}\n')
    output_queue.put('{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n')
    capture = _UsageCapture()
    process = _UsageProcess()
    process.returncode = 0

    class TailReader:
        def __init__(self) -> None:
            self.done = threading.Event()
            self.stop_requested = False

        def request_stop(self) -> None:
            self.stop_requested = True

        def stop(self) -> None:
            self.request_stop()

        def join(self, _timeout: float | None = None) -> None:
            return None

    reader = TailReader()

    async def start_capture(*, env, command):
        return capture

    def terminate_with_tail(_process) -> None:
        output_queue.put(
            '{"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":3}}\n'
        )
        output_queue.put(_PROCESS_STDOUT_EOF)
        reader.done.set()

    monkeypatch.setattr(api_service, "CODEX_DONE_QUIET_SECONDS", 0)
    monkeypatch.setattr(api_service, "_start_codex_usage_capture", start_capture, raising=False)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(api_service.queue, "Queue", lambda *_args, **_kwargs: output_queue)
    monkeypatch.setattr(api_service, "_start_process_stdout_reader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(api_service, "_terminate_process_sync", terminate_with_tail)

    events = [
        event
        async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    ]

    usage_sample = capture.calls[0][0]
    assert usage_sample is not None
    assert usage_sample.input_tokens == 9
    assert any(event["type"] == "done" for event in events)


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
