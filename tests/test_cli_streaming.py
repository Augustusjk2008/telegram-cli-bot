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
from unittest.mock import AsyncMock, Mock, call

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
    get_cli_params_payload,
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
        self.calls: list[str | None] = []

    async def record_once(
        self,
        *,
        session_id: str | None = None,
    ) -> None:
        self.calls.append(session_id)


class _UsageProcess(_ReaderProcess):
    def __init__(self) -> None:
        super().__init__(
            [
                '{"type":"thread.started","thread_id":"usage-thread"}\n',
                '{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n',
                '{"type":"turn.completed"}\n',
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


def test_antigravity_cli_params_include_discovered_models(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = usage_manager.main_profile
    profile.cli_type = "antigravity"
    profile.cli_path = "agy"
    monkeypatch.setattr(api_service, "CLI_MODEL_OPTIONS", {})
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "agy.exe")
    monkeypatch.setattr(
        api_service.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"},
        )(),
    )

    payload = get_cli_params_payload(usage_manager, "main")

    assert payload["schema"]["model"]["enum"] == ["gemini-3.8-flash-medium", "none"]


def test_cli_model_options_table_is_applied_per_cli_type(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    table = {
        "codex": ["codex-model"],
        "codex_server": ["server-model"],
        "claude": ["claude-model"],
        "antigravity": ["agy-model"],
        "deepseek": ["dsh-model"],
    }
    monkeypatch.setattr(api_service, "CLI_MODEL_OPTIONS", table)
    monkeypatch.setattr("bot.config.CLI_MODEL_OPTIONS", table)

    for cli_type, expected in table.items():
        usage_manager.main_profile.cli_type = cli_type
        usage_manager.main_profile.cli_path = {
            "antigravity": "agy",
            "deepseek": "dsh",
        }.get(cli_type, cli_type)
        payload = get_cli_params_payload(usage_manager, "main")
        assert payload["schema"]["model"]["enum"] == [*expected, "none"]


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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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


@pytest.mark.asyncio
async def test_codex_communicate_records_quota_once_during_cleanup():
    capture = _UsageCapture()
    process = _ReaderProcess(
        [
            '{"type":"thread.started","thread_id":"quota-thread"}\n',
            '{"type":"turn.completed"}\n',
        ]
    )

    await _communicate_codex_process(process, quota_capture=capture)

    assert capture.calls == ["quota-thread"]


@pytest.mark.asyncio
async def test_codex_communicate_records_quota_after_failed_turn():
    failed_capture = _UsageCapture()

    await _communicate_codex_process(
        _ReaderProcess(
            [
                '{"type":"thread.started","thread_id":"failed-thread"}\n',
                '{"type":"turn.failed","error":{"message":"boom"}}\n',
            ]
        ),
        quota_capture=failed_capture,
    )

    assert failed_capture.calls == ["failed-thread"]


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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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
    assert capture.calls == ["usage-thread"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cli_type", "has_context", "turn_model", "has_usage", "has_price"),
    [
        ("codex", True, "configured-model", True, True),
        ("codex", False, "configured-model", True, True),
        ("claude", True, "configured-model", True, True),
        ("claude", False, "configured-model", True, True),
        ("codex", False, "", True, True),
        ("codex", True, "configured-model", True, False),
        ("claude", False, "configured-model", True, False),
        ("codex", True, "configured-model", False, True),
    ],
)
async def test_stream_cli_chat_persists_terminal_estimated_cost_once_per_turn(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    cli_type: str,
    has_context: bool,
    turn_model: str,
    has_usage: bool,
    has_price: bool,
):
    profile = usage_manager.main_profile
    profile.cli_type = cli_type
    profile.cli_params.set_param(cli_type, "model", turn_model)
    _, _, session = api_service.get_chat_session_for_alias(usage_manager, "main", 1001)
    if cli_type == "claude":
        session.claude_session_id = "cost-session"
    context_usage = {
        "provider": cli_type,
        "model": "actual-model",
        "session_id": "cost-session",
        "context_window": 1000,
        "context_left_percent": 80,
    } if has_context else None
    scope = "turn"
    cost_model = "actual-model" if has_context else turn_model
    cost = {
        "model": cost_model,
        "currency": "USD",
        "scope": scope,
        "total": 0.04,
        "input": 0.01,
        "cache_read": 0.01,
        "cache_write": 0.0,
        "output": 0.02,
    }
    estimate = Mock(return_value=cost if has_price else None)
    monkeypatch.setattr(api_service, "estimate_usage_cost", estimate)
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: cli_type)
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: ([cli_type], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: context_usage)
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock())
    expected_calls = []

    for index in range(2):
        # 同一会话后续轮次用量可以下降，各轮直接计价。
        usage = {"input_tokens": 100 * (2 - index), "output_tokens": 20 * (2 - index)}
        if cli_type == "codex":
            usage["cached_input_tokens"] = 40 * (2 - index)
            prefix = [
                {"type": "thread.started", "thread_id": "cost-session"},
                {"type": "item.completed", "item": {"type": "assistant_message", "text": "done"}},
            ]
            terminal = {"type": "turn.completed"}
        else:
            usage.update(cache_read_input_tokens=40, cache_creation_input_tokens=10)
            prefix = [{"type": "system", "subtype": "init", "session_id": "cost-session"}]
            terminal = {"type": "result", "result": "done", "session_id": "cost-session"}
        if has_usage:
            terminal["usage"] = usage
        process = _UsageProcess()
        process.stdout = _StreamingStdout([
            json.dumps(event) + "\n" for event in [*prefix, terminal, terminal]
        ])
        monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

        events = [
            event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
        ]
        done = next(event for event in events if event["type"] == "done")
        if has_usage and cost_model:
            expected_calls.append(call(cost_model, usage, protocol=cli_type, scope=scope))
        expected_usage = context_usage
        if has_usage and cost_model and has_price:
            expected_usage = {
                **(context_usage or {
                    "provider": cli_type, "model": cost_model, "session_id": "cost-session",
                }),
                "estimated_cost": cost,
            }
        assert done["message"]["meta"].get("context_usage") == expected_usage
        for event in events:
            if event["type"] == "status":
                assert "estimated_cost" not in (event.get("context_usage") or {})
        saved_usage = await api_service._get_chat_history_service(session).get_latest_native_session_context_usage_async(
            native_provider=cli_type, native_session_id="cost-session",
        )
        assert saved_usage == expected_usage
        assert estimate.call_args_list == expected_calls


@pytest.mark.asyncio
async def test_stream_cli_chat_handles_antigravity_jsonl_usage_and_conversation(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = usage_manager.main_profile
    profile.cli_type = "antigravity"
    profile.cli_path = "agy"
    profile.cli_params.set_param("antigravity", "model", "gemini-3.8-flash-medium")
    process = _UsageProcess()
    process.stdout = _StreamingStdout([
        '{"event":"init","conversation_id":"agy-stream-session","init":{}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"agy-stream-session","step_type":"agent_response","text_delta":"OK"}}\n',
        '{"event":"result","result":{"conversation_id":"agy-stream-session","status":"SUCCESS","response":"OK","usage":{"input_tokens":11,"output_tokens":2,"thinking_tokens":3,"cache_read_tokens":4,"total_tokens":20}}}\n',
    ])
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "agy")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["agy"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

    events = [event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")]
    done = next(event for event in events if event["type"] == "done")
    statuses = [event for event in events if event["type"] == "status"]

    assert done["output"] == "OK"
    assert done["returncode"] == 0
    assert done["message"]["meta"]["context_usage"] == {
        "provider": "antigravity",
        "source": "antigravity_stream_json",
        "session_id": "agy-stream-session",
        "model": "gemini-3.8-flash-medium",
        "usage_scope": "conversation",
        "status_text": "CLI usage only · conversation total",
        "input_tokens": 11,
        "output_tokens": 2,
        "thinking_tokens": 3,
        "cache_read_tokens": 4,
        "total_tokens": 20,
    }
    assert any(event.get("preview_text") == "OK" for event in statuses)
    assert done["session"]["session_ids"]["antigravity_conversation_id"] == "agy-stream-session"


class _DeepSeekStdin:
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text

    def flush(self):
        pass

    def close(self):
        pass


class _DeepSeekProcess(_UsageProcess):
    def __init__(self, events, *, returncode=0, stderr=""):
        super().__init__()
        self.stdout = _StreamingStdout([
            (event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)) + "\n"
            for event in events
        ])
        self.stderr = _StreamingStdout([stderr] if stderr else [])
        self.stdin = _DeepSeekStdin()
        self.exit_code = returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode


def _deepseek_events(session_id="session-dsh", text="最终回复"):
    return [
        {"type": "session", "sessionId": session_id},
        {"type": "status", "phase": "turn_start", "turn": 1},
        {"type": "thinking", "text": "思考过程"},
        {"type": "tool_call", "callId": "read-1", "tool": "read", "input": {"file_path": "probe.txt"}},
        {"type": "tool_result", "callId": "read-1", "status": "completed", "result": "文件内容"},
        {"type": "text", "text": text},
        {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
         "usage": {"inputTokens": 134, "outputTokens": 10, "cacheReadTokens": 6016, "totalTokens": 6160}},
        {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}},
        {"type": "final", "text": text},
    ]


def test_deepseek_context_usage_merges_projection_and_turn_usage():
    result = api_service._build_deepseek_context_usage(
        {
            "input_tokens": 134,
            "output_tokens": 10,
            "cache_read_input_tokens": 6016,
            "total_tokens": 6160,
        },
        session_id="session-dsh",
        context_usage={
            "provider": "deepseek",
            "source": "deepseek_context_pressure",
            "session_id": "session-dsh",
            "usage_scope": "conversation",
            "used_tokens": 6150,
            "context_window": 1_000_000,
            "context_left_percent": 99,
            "status_text": "99% context left · 6.2K / 1000K",
        },
    )

    assert result is not None
    assert result["source"] == "deepseek_context_pressure"
    assert result["usage_scope"] == "conversation"
    assert result["context_left_percent"] == 99
    assert result["input_tokens"] == 134
    assert result["total_tokens"] == 6160


def test_deepseek_context_usage_keeps_projection_without_turn_usage():
    result = api_service._build_deepseek_context_usage(
        None,
        session_id="session-dsh",
        context_usage={
            "provider": "deepseek",
            "source": "deepseek_context_pressure",
            "used_tokens": 6150,
            "context_window": 1_000_000,
            "context_left_percent": 99,
        },
    )

    assert result == {
        "provider": "deepseek",
        "source": "deepseek_context_pressure",
        "session_id": "session-dsh",
        "usage_scope": "conversation",
        "used_tokens": 6150,
        "context_window": 1_000_000,
        "context_left_percent": 99,
        "status_text": "上下文占用",
    }


@pytest.mark.asyncio
async def test_deepseek_stream_publishes_context_pressure_with_turn_usage(usage_manager, monkeypatch):
    observed = _patch_deepseek_runtime(
        usage_manager,
        monkeypatch,
        [_DeepSeekProcess(_deepseek_events())],
    )
    context_usage = {
        "provider": "deepseek",
        "source": "deepseek_context_pressure",
        "session_id": "session-dsh",
        "usage_scope": "conversation",
        "used_tokens": 6150,
        "context_window": 1_000_000,
        "context_left_percent": 99,
        "used_display": "6.2K",
        "window_display": "1000K",
        "status_text": "99% context left · 6.2K / 1000K",
    }
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: context_usage)
    monkeypatch.setattr(api_service, "estimate_usage_cost", Mock(return_value=None))

    events = [event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")]
    done = events[-1]
    published = done["message"]["meta"]["context_usage"]

    assert observed["commands"]
    assert published["context_left_percent"] == 99
    assert published["usage_scope"] == "conversation"
    assert published["input_tokens"] == 134
    assert published["total_tokens"] == 6160


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allow_unsafe_cli", "expected_mode"),
    [(False, "workspace-write"), (True, "danger-full-access")],
)
async def test_deepseek_stream_applies_permission_mode(usage_manager, monkeypatch, allow_unsafe_cli, expected_mode):
    usage_manager.main_profile.cli_params.set_param("deepseek", "permission_mode", "danger-full-access")
    observed = _patch_deepseek_runtime(
        usage_manager,
        monkeypatch,
        [_DeepSeekProcess(_deepseek_events())],
    )

    await _collect_stream_events(
        api_service._stream_cli_chat(
            usage_manager,
            "main",
            1001,
            "hello",
            allow_unsafe_cli=allow_unsafe_cli,
        )
    )

    assert observed["kwargs"][0]["env"]["DSH_PERMISSION_MODE"] == expected_mode


@pytest.mark.asyncio
async def test_deepseek_windows_process_is_not_nested_in_orbit_job(usage_manager, monkeypatch):
    observed = _patch_deepseek_runtime(
        usage_manager,
        monkeypatch,
        [_DeepSeekProcess(_deepseek_events())],
    )

    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"))

    creationflags = int(observed["kwargs"][0].get("creationflags", 0) or 0)
    assert creationflags & 0x00000004 == 0
    assert creationflags & 0x01000000 != 0


def _patch_deepseek_runtime(manager, monkeypatch, processes):
    profile = manager.main_profile
    profile.cli_type, profile.cli_path = "deepseek", "dsh"
    pending = iter(processes)
    observed = {"commands": [], "kwargs": [], "completions": []}

    def spawn(command, **kwargs):
        observed["commands"].append(command)
        observed["kwargs"].append(kwargs)
        return next(pending)

    original_complete = api_service.ChatHistoryService.complete_turn

    def complete(service, handle, **kwargs):
        observed["completions"].append(handle.turn_id)
        return original_complete(service, handle, **kwargs)

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_: "dsh")
    monkeypatch.setattr(
        "bot.cli_params.build_deepseek_invocation",
        lambda _resolved, _params: [
            "DeepSeek Harness.exe", "--expose-internals", "deepseek_launch.mjs",
            "desktop", "DeepSeek Harness.exe", "dsh-entry", "desktop-host", "{}",
        ],
    )
    monkeypatch.setattr(api_service.subprocess, "Popen", spawn)
    monkeypatch.setattr(api_service.ChatHistoryService, "complete_turn", complete)
    monkeypatch.setattr(api_service, "estimate_usage_cost", Mock(side_effect=AssertionError("unknown model price")))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", Mock(side_effect=AssertionError("no native log import")))
    return observed


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro"])
@pytest.mark.parametrize("inherit_model", [False, True])
async def test_deepseek_stream_prices_each_turn_and_persists_cost(usage_manager, monkeypatch, model, inherit_model):
    from bot import config
    from bot.model_pricing import DEFAULT_PRICES_PATH, estimate_usage_cost

    events = _deepseek_events()
    step = events[-3]
    events[-2:-2] = [step, {**step, "step": 2}]
    metadata = [{"type": "orbit_model", "model": model}] if inherit_model else []
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [
        _DeepSeekProcess([*metadata, *events]), _DeepSeekProcess([*metadata, *_deepseek_events()]),
    ])
    usage_manager.main_profile.cli_params.set_param("deepseek", "model", "none" if inherit_model else model)
    monkeypatch.setattr(api_service, "estimate_usage_cost", estimate_usage_cost)
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(DEFAULT_PRICES_PATH))
    monkeypatch.setattr(api_service, "build_cli_command", lambda *_args, **_kwargs: (["dsh"], True))
    totals = []
    for prompt in ("hello", "continue"):
        result = await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, prompt))
        done = result[-1]
        assert done["message"]["state"] == "done"
        usage = done["message"]["meta"]["context_usage"]
        cost = usage["estimated_cost"]
        assert cost["model"] == model and cost["currency"] == "CNY" and cost["scope"] == "turn"
        assert not cost.get("is_partial")
        totals.append(cost["total"])
        session = api_service.get_session_for_alias(usage_manager, "main", 1001)
        saved = await api_service._get_chat_history_service(session).get_latest_native_session_context_usage_async(
            native_provider="deepseek", native_session_id="session-dsh",
        )
        assert saved["estimated_cost"] == cost
    expected = 0.00058864 if model == "deepseek-flash" else 0.0032808
    assert totals == pytest.approx([2 * expected, expected])
    assert len(observed["completions"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", [
    "missing_final", "nonzero_exit", "output_limit", "stopped", "missing_usage", "missing_cache", "missing_model",
])
async def test_deepseek_partial_or_unknown_cost(usage_manager, monkeypatch, ending):
    from bot import config
    from bot.model_pricing import DEFAULT_PRICES_PATH, estimate_usage_cost

    events = _deepseek_events()
    if ending == "missing_final":
        events = events[:-1]
    elif ending == "output_limit":
        events[-2:] = [{"type": "text", "text": "x" * 600}]
    elif ending == "stopped":
        events = events[:-2]
    elif ending == "missing_usage":
        events.insert(-2, {"type": "status", "phase": "step_end", "turn": 1, "step": 2})
    elif ending == "missing_cache":
        events.insert(-2, {"type": "status", "phase": "step_end", "turn": 1, "step": 2,
                           "usage": {"inputTokens": 1, "outputTokens": 1}})
    if ending != "missing_model":
        events.insert(0, {"type": "orbit_model", "model": "deepseek-flash"})
    process = _DeepSeekProcess(events, returncode=1 if ending == "nonzero_exit" else 0)
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [process])
    monkeypatch.setattr(api_service, "estimate_usage_cost", estimate_usage_cost)
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(DEFAULT_PRICES_PATH))
    if ending == "output_limit":
        start_reader = api_service._start_process_stdout_reader
        monkeypatch.setattr(api_service, "_start_process_stdout_reader",
                            lambda proc, output_queue: start_reader(proc, output_queue, max_line_bytes=300))
    session = api_service.get_session_for_alias(usage_manager, "main", 1001)
    result = []
    async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"):
        result.append(event)
        if ending == "stopped" and event["type"] == "meta":
            session.stop_requested = True
    usage = result[-1]["message"]["meta"].get("context_usage") or {}
    if ending in {"missing_usage", "missing_cache", "missing_model"}:
        assert "estimated_cost" not in usage
    else:
        assert usage["estimated_cost"]["total"] == pytest.approx(0.00058864)
        assert usage["estimated_cost"]["is_partial"] is True
    assert len(observed["completions"]) == 1


@pytest.mark.asyncio
async def test_deepseek_stream_persists_trace_and_restores_conversation_binding(usage_manager, monkeypatch):
    processes = [_DeepSeekProcess(_deepseek_events()), _DeepSeekProcess(_deepseek_events()),
                 _DeepSeekProcess(_deepseek_events("session-new"))]
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, processes)
    all_events = [event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "中文\n第二行")]
    done = all_events[-1]
    session = api_service.get_session_for_alias(usage_manager, "main", 1001)
    first_conversation = session.active_conversation_id
    assert done["output"] == "最终回复"
    assert processes[0].stdin.text == "中文\n第二行\n"
    assert all(event["turn_id"] == done["turn_id"] and event["assistant_message_id"] == done["assistant_message_id"]
               for event in all_events if event["type"] in {"meta", "status", "trace", "done"})
    assert any(event.get("preview_text") == "最终回复" for event in all_events)
    trace = api_service.get_history_trace(usage_manager, "main", 1001, done["assistant_message_id"])["trace"]
    assert {(e["kind"], e["call_id"]) for e in trace if e["kind"].startswith("tool_")} == {
        ("tool_call", "read-1"), ("tool_result", "read-1"),
    }
    usage = done["message"]["meta"]["context_usage"]
    assert usage == {"provider": "deepseek", "source": "deepseek_headless", "session_id": "session-dsh",
                     "usage_scope": "turn", "status_text": "本轮用量", "input_tokens": 134,
                     "output_tokens": 10, "cache_read_tokens": 6016, "total_tokens": 6160}
    assert done["session"]["session_ids"]["deepseek_session_id"] == "session-dsh"
    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "继续"))
    await api_service.create_conversation(usage_manager, "main", 1001)
    assert session.deepseek_session_id is None
    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "新会话"))
    await api_service.select_conversation(usage_manager, "main", 1001, first_conversation)
    assert session.deepseek_session_id == "session-dsh"
    assert "--session-id" not in observed["commands"][0]
    assert observed["commands"][1][-3:] == ["--session-id", "session-dsh", "-"]
    assert "--session-id" not in observed["commands"][2]
    assert all(kwargs["stderr"] == subprocess.PIPE for kwargs in observed["kwargs"])
    assert len(observed["completions"]) == len(set(observed["completions"])) == 3


def test_deepseek_model_schema_keeps_own_options_and_saved_custom_model(usage_manager, monkeypatch):
    monkeypatch.setattr(api_service, "CLI_MODEL_OPTIONS", ["gpt-host-model"])
    usage_manager.main_profile.cli_type = "deepseek"
    usage_manager.main_profile.cli_params.set_param("deepseek", "model", "my-deepseek-model")
    payload = get_cli_params_payload(usage_manager, "main")
    assert payload["schema"]["model"]["enum"] == ["none", "deepseek-flash", "deepseek-v4-pro", "my-deepseek-model"]
    assert payload["schema"]["reasoning_effort"]["enum"] == ["none", "off", "low", "high", "max"]
    assert payload["defaults"]["model"] is None
    assert payload["defaults"]["reasoning_effort"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stderr", "missing_final", "exit_after_final", "invalid_json"])
async def test_deepseek_failure_never_succeeds_or_replays(usage_manager, monkeypatch, failure):
    events, returncode, stderr = _deepseek_events(), 0, ""
    if failure == "stderr":
        events, returncode, stderr = [], 1, "dsh: startup failed\n"
    elif failure == "missing_final":
        events = events[:-1]
    elif failure == "exit_after_final":
        returncode, stderr = 1, "dsh: provider failed\n"
    else:
        events.insert(1, "invalid diagnostic on stdout")
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [_DeepSeekProcess(events, returncode=returncode, stderr=stderr)])
    result = await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"))
    done = result[-1]
    assert done["type"] == "done" and done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "error"
    if stderr:
        assert stderr.strip() in done["output"]
    assert len(observed["commands"]) == len(observed["completions"]) == 1
    assert done["session"]["is_processing"] is False


@pytest.mark.asyncio
async def test_deepseek_provider_switch_uses_selected_conversations_binding(usage_manager, monkeypatch):
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [
        _DeepSeekProcess(_deepseek_events("session-a")),
        _DeepSeekProcess(_deepseek_events("session-b")),
        _DeepSeekProcess(_deepseek_events("session-b")),
    ])
    profile = usage_manager.main_profile
    session = api_service.get_session_for_alias(usage_manager, "main", 1001)
    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "A"))
    conversation_a = session.active_conversation_id
    await api_service.create_conversation(usage_manager, "main", 1001)
    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "B"))
    conversation_b = session.active_conversation_id
    await api_service.select_conversation(usage_manager, "main", 1001, conversation_a)
    assert session.deepseek_session_id == "session-a"
    profile.cli_type = "codex"
    history = api_service._get_chat_history_service(session)
    codex_turn = history.start_turn(profile=profile, session=session, user_text="codex", native_provider="codex")
    history.complete_turn(codex_turn, content="codex", completion_state="completed", native_session_id="codex-thread")
    profile.cli_type = "deepseek"
    await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "back"))
    assert session.active_conversation_id == conversation_b
    assert observed["commands"][-1][-3:] == ["--session-id", "session-b", "-"]
    assert history.store.get_conversation(conversation_a)["native_session_id"] == "session-a"
    assert history.store.get_conversation(conversation_b)["native_session_id"] == "session-b"


@pytest.mark.asyncio
async def test_deepseek_cluster_launches_with_mcp_patch_but_other_entry_points_fail(usage_manager, monkeypatch, tmp_path):
    from bot.web import git_service

    patch_path = tmp_path / "dsh-cluster-mcp.patch.json"
    patch_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(api_service, "prepare_cluster_mcp_launcher", lambda **_kwargs: None)
    monkeypatch.setattr(api_service, "write_deepseek_mcp_patch", lambda **_kwargs: patch_path)
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [_DeepSeekProcess(_deepseek_events())])
    profile = usage_manager.main_profile
    cluster_events = await _collect_stream_events(
        api_service._stream_cli_chat(usage_manager, "main", 1001, "hello", cluster_run_id="cluster")
    )
    assert cluster_events[-1]["output"] == "最终回复"
    assert "--patch" in observed["commands"][0]
    assert str(patch_path) in observed["commands"][0]
    profile.remote_workspace = {"root": "/remote"}
    with pytest.raises(api_service.WebApiError, match="本地工作区"):
        await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"))
    profile.remote_workspace = None
    profile.supported_execution_modes = ["cli", "native_agent"]
    with pytest.raises(api_service.WebApiError, match="CLI 执行模式"):
        api_service._resolve_chat_execution_mode(profile, "native_agent")
    with pytest.raises(api_service.WebApiError, match="DeepSeek Harness"):
        await git_service._generate_git_commit_message_from_context(
            usage_manager, "main", 1001, repo_root=profile.working_dir, context={},
        )
    assert len(observed["commands"]) == 1


@pytest.mark.asyncio
async def test_deepseek_output_limit_preserves_partial_reply_and_finishes_once(usage_manager, monkeypatch):
    process = _DeepSeekProcess([
        {"type": "session", "sessionId": "session-limit"},
        {"type": "text", "text": "已收到的正文"},
        {"type": "text", "text": "x" * 500},
    ])
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [process])
    start_reader = api_service._start_process_stdout_reader
    monkeypatch.setattr(api_service, "_start_process_stdout_reader",
                        lambda proc, output_queue: start_reader(proc, output_queue, max_line_bytes=200))
    done = (await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")))[-1]
    assert done["message"]["state"] == "error"
    assert "单行输出超过" in done["output"] and "已收到的正文" in done["output"]
    assert len(observed["completions"]) == 1
    assert done["session"]["is_processing"] is False


@pytest.mark.asyncio
async def test_deepseek_stop_preserves_partial_reply_and_allows_next_turn(usage_manager, monkeypatch):
    first = _DeepSeekProcess([
        {"type": "session", "sessionId": "session-stopped"},
        {"type": "text", "text": "停止前的正文"},
    ])
    observed = _patch_deepseek_runtime(usage_manager, monkeypatch, [first, _DeepSeekProcess(_deepseek_events("session-stopped"))])
    session = api_service.get_session_for_alias(usage_manager, "main", 1001)
    result = []
    async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "hello"):
        result.append(event)
        if event["type"] == "meta":
            with session._lock:
                session.stop_requested = True
    done = result[-1]
    assert done["message"]["meta"]["completion_state"] == "cancelled"
    assert done["output"] == "停止前的正文"
    assert session.is_processing is False and session.stop_requested is False
    next_done = (await _collect_stream_events(api_service._stream_cli_chat(usage_manager, "main", 1001, "continue")))[-1]
    assert next_done["message"]["meta"]["completion_state"] == "completed"
    assert observed["commands"][1][-3:] == ["--session-id", "session-stopped", "-"]
    assert len(observed["completions"]) == len(set(observed["completions"])) == 2


@pytest.mark.asyncio
async def test_stream_cli_chat_antigravity_remote_uses_workspace_mcp_and_private_env(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from bot.remote_workspace import chat as remote_chat

    profile = usage_manager.main_profile
    profile.cli_type = "antigravity"
    profile.cli_path = "agy"
    profile.cli_params.set_param("antigravity", "model", "gemini-3.8-flash-medium")
    profile.remote_workspace = {
        "connection_id": "ssh-remote",
        "host": "remote.example",
        "port": 22,
        "username": "builder",
        "root": "/work/project",
        "host_key_fingerprint": "SHA256:remote-host-key",
        "key_filename": "/private/key",
    }
    usage_manager.remote_bridge_url = "http://127.0.0.1:8765"
    monkeypatch.setattr(remote_chat, "get_app_data_root", lambda: tmp_path / "app")
    process = _UsageProcess()
    process.stdout = _StreamingStdout([
        '{"event":"init","conversation_id":"remote-agy-session","init":{}}\n',
        '{"event":"result","result":{"conversation_id":"remote-agy-session","status":"SUCCESS","response":"remote OK"}}\n',
    ])
    observed: dict[str, object] = {}

    def fake_build_cli_command(**kwargs):
        observed.update(kwargs)
        return ["agy"], False

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "agy")
    monkeypatch.setattr(api_service, "build_cli_command", fake_build_cli_command)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *args, **kwargs: (observed.update(popen_kwargs=kwargs) or process))

    events = [event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "remote task")]
    done = next(event for event in events if event["type"] == "done")
    workspace_path = Path(profile.working_dir) / ".agents" / "mcp_config.json"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    entry = workspace["mcpServers"]["tcb-remote"]
    process_kwargs = observed["popen_kwargs"]

    assert done["output"] == "remote OK"
    assert done["session"]["session_ids"]["antigravity_conversation_id"] == "remote-agy-session"
    assert process_kwargs["cwd"] == profile.working_dir
    assert process_kwargs["env"]["TCB_REMOTE_MCP_CONFIG"]
    assert observed["params_config"].get_params("antigravity")["extra_args"] == []
    assert entry["cwd"] == str(Path(profile.working_dir).resolve())
    assert entry["args"][0].endswith("bot\\remote_workspace\\mcp_stdio.py") or entry["args"][0].endswith("bot/remote_workspace/mcp_stdio.py")
    assert "remote-host-key" not in json.dumps(workspace)
    assert "private/key" not in json.dumps(workspace)


@pytest.mark.asyncio
async def test_stream_cli_chat_treats_antigravity_soft_denial_as_error(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = usage_manager.main_profile
    profile.cli_type = "antigravity"
    profile.cli_path = "agy"
    process = _UsageProcess()
    process.stdout = _StreamingStdout([
        '{"event":"init","conversation_id":"agy-denied-session","init":{}}\n',
        '{"event":"result","result":{"conversation_id":"agy-denied-session","status":"SUCCESS","response":"","denied_actions":[{"action":"command","display_name":"RunCommand"}]}}\n',
    ])
    process.stderr = _StreamingStdout(["permission denied: RunCommand\n"])
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "agy")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["agy"], False))
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

    events = [event async for event in api_service._stream_cli_chat(usage_manager, "main", 1001, "run a command")]
    done = next(event for event in events if event["type"] == "done")

    assert done["returncode"] == 0
    assert done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "error"
    assert "RunCommand" in done["output"]
    assert "permission denied" in done["output"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cli_type", ["codex", "claude"])
@pytest.mark.parametrize("exit_kind", ["error", "cancelled", "reader_error"])
async def test_stream_cli_chat_preserves_partial_cost_on_abnormal_exit(
    usage_manager, monkeypatch, tmp_path, cli_type, exit_kind,
):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from bot import config
    from bot.web import cli_turn_cost

    price_path = tmp_path / "prices.csv"
    price_path.write_text(
        "model,currency,input_per_million,cache_read_per_million,cache_write_per_million,output_per_million\n"
        "test-model,USD,2,0.2,2.5,10\n", encoding="utf-8",
    )
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(price_path))
    profile = usage_manager.main_profile
    profile.cli_type = cli_type
    profile.cli_params.set_param(cli_type, "model", "test-model")
    _, _, session = api_service.get_chat_session_for_alias(usage_manager, "main", 1001)
    session.claude_session_id = "partial-cost-session"
    usage = {"input_tokens": 1000, "output_tokens": 100}
    events = [
        {"type": "thread.started", "thread_id": "partial-cost-session"},
        {"type": "item.delta", "item": {"type": "assistant_message", "delta": "working"}},
    ] if cli_type == "codex" else [
        {"type": "assistant", "session_id": "partial-cost-session", "message": {
            "id": "response-1", "model": "test-model", "role": "assistant", "usage": usage,
            "content": [{"type": "text", "text": "working"}],
        }},
    ]

    class Output(_StreamingStdout):
        def readline(self, _size=-1):
            value = super().readline(_size)
            if not value and not self.closed and exit_kind == "reader_error":
                raise OSError("read failed")
            return value

    process = _UsageProcess()
    process.stdout = Output([json.dumps(event) + "\n" for event in events])
    process.returncode = 1
    path = tmp_path / "rollout.jsonl"

    def spawn(*_args, **_kwargs):
        if exit_kind == "cancelled":
            session.stop_requested = True
        timestamp = datetime.now(timezone.utc).isoformat()
        path.write_text("\n".join(json.dumps({
            "timestamp": timestamp, "type": "event_msg", "payload": payload,
        }) for payload in [
            {"type": "task_started"},
            {"type": "token_count", "info": {"total_token_usage": usage}},
        ]), encoding="utf-8")
        return process

    monkeypatch.setattr(cli_turn_cost, "locate_codex_transcript", lambda _session: SimpleNamespace(path=path))
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: cli_type)
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: ([cli_type], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock())
    monkeypatch.setattr(api_service.subprocess, "Popen", spawn)
    stream = api_service._stream_cli_chat(usage_manager, "main", 1001, "hello")
    if exit_kind == "reader_error":
        with pytest.raises(OSError, match="read failed"):
            await _collect_stream_events(stream)
    else:
        result = await _collect_stream_events(stream)
        done = next(event for event in result if event["type"] == "done")
        assert done["message"]["meta"]["completion_state"] == exit_kind
        assert done["message"]["meta"]["context_usage"]["estimated_cost"]["total"] == 0.003

    history = api_service._get_chat_history_service(session).list_history(profile, session)
    cost = history[-1]["meta"]["context_usage"]["estimated_cost"]
    assert cost["total"] == 0.003
    assert cost["is_partial"] is True


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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" in prompts[0]
    assert "Current run_id: run-1" in prompts[0]
    assert "Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate" not in prompts[1]
    assert "continue following the cluster rules established earlier in this conversation" in prompts[1]
    assert "Current run_id: run-2" in prompts[1]


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
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    assert capture.calls == ["tail-thread"]
    assert any(event["type"] == "done" for event in events)


@pytest.mark.asyncio
async def test_non_stream_cli_chat_records_before_chat_store_completion_failure(
    usage_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    capture = _UsageCapture()

    async def start_capture(*, env, command):
        return capture

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", start_capture)
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

    assert capture.calls == ["usage-thread"]


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
