import asyncio
import copy
import json
from dataclasses import replace

import pytest

from bot.cli_params import CliParamsConfig, clamp_unsafe_cli_params, get_cli_output_limits
from bot.codex_server.client import CodexServerError
from bot.codex_server.runtime import CodexServerRegistry, CodexServerRuntimeRequest
from bot.codex_server.params import convert_params


class FakeClient:
    instances = []

    def __init__(self):
        self.alive = True
        self.calls = []
        self.incoming = asyncio.Queue()
        self.limits = get_cli_output_limits({})
        self.thread_id = ""
        self.turn_count = 0
        self.auto_complete = True
        self.instances.append(self)

    @classmethod
    async def start(cls, *args, **kwargs):
        return cls()

    def emit(self, method, **params):
        self.incoming.put_nowait({"method": method, "params": {"threadId": self.thread_id, **params}})

    async def request(self, method, params, **kwargs):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "config/read":
            return {"config": {"model": "default-model", "model_reasoning_effort": "medium"}}
        if method.startswith("thread/"):
            self.thread_id = params.get("threadId") or f"thread-{len(self.instances)}"
            return {"thread": {"id": self.thread_id, "sessionId": "root-not-thread"}, "model": "default-model"}
        if method == "turn/start":
            self.turn_count += 1
            turn = {"id": f"turn-{self.turn_count}", "status": "inProgress", "items": []}
            self.emit("turn/started", turn=turn)
            self.emit("item/agentMessage/delta", turnId=turn["id"], itemId="answer", delta="partial")
            if self.auto_complete:
                self.emit("thread/tokenUsage/updated", turnId=turn["id"], tokenUsage={
                    "total": {"inputTokens": self.turn_count * 10, "outputTokens": self.turn_count * 2},
                    "last": {"inputTokens": 10, "outputTokens": 2},
                })
                self.emit("turn/completed", turn={**turn, "status": "completed"})
            return {"turn": turn}
        if method == "turn/interrupt":
            self.emit("turn/completed", turn={"id": params["turnId"], "status": "interrupted", "items": []})
            return {}
        return {}

    async def events(self):
        while self.alive:
            event = await self.incoming.get()
            if isinstance(event, Exception):
                raise event
            yield event

    async def close(self):
        self.alive = False

    def close_sync(self):
        self.alive = False


@pytest.fixture
def runtime_setup(monkeypatch, tmp_path):
    FakeClient.instances = []
    monkeypatch.setattr("bot.codex_server.runtime.CodexServerClient", FakeClient)
    monkeypatch.setattr("bot.codex_server.params.resolve_cli_executable", lambda *args: "codex.exe")
    config = CliParamsConfig.from_dict({"codex_server": {"model": "first", "reasoning_effort": "high"}})
    request = CodexServerRuntimeRequest((1, 2, "main"), "conversation", "codex", str(tmp_path), {}, config)
    return CodexServerRegistry(), request


async def collect(runtime):
    return [event async for event in runtime.stream_turn("hello")]


@pytest.mark.asyncio
async def test_process_reuse_per_turn_parameters_usage_and_sync_release(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    try:
        first = await collect(runtime)
        request.params_config.codex_server.update(model="second", reasoning_effort="low")
        reused = await registry.open_or_create(request)
        assert reused is runtime
        second = await collect(reused)
        turns = [params for method, params in runtime.client.calls if method == "turn/start"]
        assert [(p["model"], p["effort"]) for p in turns] == [("first", "high"), ("second", "low")]
        assert all("collaborationMode" not in p for p in turns)
        assert first[-1]["usage"]["input_tokens"] == second[-1]["usage"]["input_tokens"] == 10
        assert first[0]["thread_id"] == runtime.thread_id != "root-not-thread"
        future = await asyncio.to_thread(registry.release_owner, request.owner_key)
        await asyncio.wrap_future(future)
        assert not runtime.alive
    finally:
        await registry.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["cwd", "env", "home", "mcp", "config_file", "conversation", "thread"])
async def test_binding_changes_rebuild_and_resume(runtime_setup, tmp_path, changed):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    old_thread = runtime.thread_id
    if changed == "cwd":
        directory = tmp_path / "new"
        directory.mkdir()
        request = replace(request, cwd=str(directory))
    elif changed in {"env", "home"}:
        request = replace(request, env={"CODEX_HOME" if changed == "home" else "REMOTE_ENDPOINT": "changed"})
    elif changed == "mcp":
        request.params_config.codex_server["extra_args"] = ["-c", 'mcp_servers.bridge.command="new-launcher"']
    elif changed == "config_file":
        directory = tmp_path / ".codex"
        directory.mkdir()
        (directory / "config.toml").write_text('model="changed"', encoding="utf-8")
    elif changed == "conversation":
        request = replace(request, conversation_id="new-conversation")
    else:
        request = replace(request, thread_id="saved-thread")
    replacement = await registry.open_or_create(request)
    try:
        assert replacement is not runtime
        assert not runtime.alive
        if changed == "conversation":
            assert replacement.thread_id != old_thread
            assert replacement.client.calls[1][0] == "thread/start"
        else:
            assert replacement.client.calls[1][0] == "thread/resume"
            assert replacement.thread_id == ("saved-thread" if changed == "thread" else old_thread)
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_one_turn_interrupt_then_reuse_and_isolation(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)
    with pytest.raises(CodexServerError, match="活动 turn"):
        await collect(runtime)
    with pytest.raises(CodexServerError, match="尚未完成"):
        await registry.open_or_create(request)
    other = await registry.open_or_create(replace(request, owner_key=(1, 2, "child")))
    assert other.thread_id != runtime.thread_id
    with pytest.raises(CodexServerError, match="另一个 owner"):
        await registry.open_or_create(replace(request, owner_key=(2, 2, "main"), thread_id=runtime.thread_id))
    await runtime.interrupt()
    events = await task
    assert events[-1]["status"] == "interrupted"
    assert runtime.returncode == 130
    runtime.client.auto_complete = True
    assert (await collect(runtime))[-1]["type"] == "turn.completed"
    await registry.close_bot(1)
    assert not runtime.alive and not other.alive


@pytest.mark.asyncio
async def test_exception_partial_usage_and_next_request_recovery(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)
    runtime.client.emit("thread/tokenUsage/updated", turnId=runtime._turn_id, tokenUsage={
        "total": {"inputTokens": 5, "outputTokens": 2}, "last": {"inputTokens": 5, "outputTokens": 2}})
    runtime.client.incoming.put_nowait(CodexServerError("child died"))
    events = await task
    assert events[-1]["type"] == "turn.failed"
    assert events[-1]["usage"]["input_tokens"] == 5
    assert any(event.get("type") == "response_item" for event in events)
    recovered = await registry.open_or_create(request)
    assert recovered.thread_id == runtime.thread_id
    assert recovered.client.calls[1][0] == "thread/resume"
    await registry.aclose()


@pytest.mark.asyncio
async def test_failed_turn_retires_owned_process_and_next_request_resumes_thread(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    other = await registry.open_or_create(replace(request, owner_key=(1, 2, "child")))
    runtime.client.auto_complete = False
    try:
        task = asyncio.create_task(collect(runtime))
        while not runtime._turn_id:
            await asyncio.sleep(0)
        runtime.client.emit("thread/tokenUsage/updated", turnId=runtime._turn_id, tokenUsage={
            "total": {"inputTokens": 5, "outputTokens": 2}, "last": {"inputTokens": 5, "outputTokens": 2}})
        runtime.client.emit("turn/completed", turn={"id": runtime._turn_id, "status": "failed", "items": [],
                                                  "error": {"message": "stream disconnected"}})
        events = await asyncio.wait_for(task, 2)
        assert events[-1]["type"] == "turn.failed" and events[-1]["usage"]["input_tokens"] == 5
        assert any(event.get("type") == "response_item" for event in events)
        assert runtime.returncode == 1 and not runtime.alive and not runtime.client.alive
        assert not runtime.active and runtime._reader.done()
        assert other.alive
        assert [method for method, _ in runtime.client.calls].count("turn/start") == 1

        recovered = await registry.open_or_create(request)
        assert recovered is not runtime and recovered.thread_id == runtime.thread_id
        assert recovered.client.calls[1][0] == "thread/resume"
        assert (await collect(recovered))[-1]["type"] == "turn.completed"
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_cancelled_consumer_interrupts_and_next_turn_is_usable(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.alive and not runtime.active
    assert any(method == "turn/interrupt" for method, _ in runtime.client.calls)
    runtime.client.auto_complete = True
    assert (await collect(runtime))[-1]["type"] == "turn.completed"
    await registry.aclose()


@pytest.mark.asyncio
async def test_steer_uses_current_turn_and_preserves_runtime_state(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)
    mapper = runtime._mapper
    outgoing = runtime._outgoing
    total_usage = runtime._total_usage

    await registry.steer_owner(request.owner_key, runtime._turn_id, "follow-up")

    assert runtime.client.calls[-1] == ("turn/steer", {
        "threadId": runtime.thread_id,
        "expectedTurnId": runtime._turn_id,
        "input": [{"type": "text", "text": "follow-up"}],
    })
    assert runtime._mapper is mapper
    assert runtime._outgoing is outgoing
    assert runtime._total_usage is total_usage
    assert runtime.active

    await runtime.interrupt()
    await task
    await registry.aclose()


@pytest.mark.asyncio
async def test_steer_requests_are_serialized(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)

    order = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    original_request = runtime.client.request

    async def request_with_gate(method, params, **kwargs):
        if method == "turn/steer":
            order.append(("start", params["input"][0]["text"]))
            if params["input"][0]["text"] == "first":
                first_started.set()
                await release_first.wait()
            order.append(("end", params["input"][0]["text"]))
        return await original_request(method, params, **kwargs)

    runtime.client.request = request_with_gate
    first = asyncio.create_task(runtime.steer("first"))
    await first_started.wait()
    second = asyncio.create_task(runtime.steer("second"))
    await asyncio.sleep(0)
    assert not second.done()
    release_first.set()
    await asyncio.gather(first, second)
    assert order == [("start", "first"), ("end", "first"), ("start", "second"), ("end", "second")]

    await runtime.interrupt()
    await task
    await registry.aclose()


@pytest.mark.asyncio
async def test_steer_rejects_no_active_wrong_turn_and_closed_runtime(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    with pytest.raises(CodexServerError, match="活动 turn"):
        await runtime.steer("follow-up")

    runtime.client.auto_complete = False
    task = asyncio.create_task(collect(runtime))
    while not runtime._turn_id:
        await asyncio.sleep(0)
    with pytest.raises(CodexServerError, match="turn 不匹配"):
        await registry.steer_owner(request.owner_key, "stale-turn", "follow-up")
    await runtime.interrupt()
    await task

    await runtime.close()
    with pytest.raises(CodexServerError, match="已关闭"):
        await runtime.steer("follow-up")
    await registry.aclose()


@pytest.mark.asyncio
async def test_starting_next_turn_clears_previous_compaction_and_reset_params(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(request)
    await collect(runtime)
    runtime.context_usage = {"compaction_count": 1}
    request.params_config.codex_server.update(model=None, reasoning_effort=None)
    assert await registry.open_or_create(request) is runtime
    stream = runtime.stream_turn("next")
    await anext(stream)
    assert runtime.context_usage == {}
    await anext(stream)
    call = next(params for method, params in reversed(runtime.client.calls) if method == "turn/start")
    assert (call["model"], call["effort"]) == ("default-model", "medium")
    await stream.aclose()
    await registry.aclose()


@pytest.mark.asyncio
async def test_mcp_config_content_change_at_same_path_rebuilds(runtime_setup, tmp_path):
    registry, request = runtime_setup
    bridge = tmp_path / "bridge.json"
    bridge.write_text('{"port":1}', encoding="utf-8")
    request.params_config.codex_server["extra_args"] = ["-c", "mcp_servers.bridge.args=" + json.dumps(["--config", str(bridge)])]
    first = await registry.open_or_create(request)
    bridge.write_text('{"port":2}', encoding="utf-8")
    second = await registry.open_or_create(request)
    assert first is not second and first.thread_id == second.thread_id
    await registry.aclose()


@pytest.mark.asyncio
async def test_voice_subscriber_receives_idle_events_from_single_reader(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(replace(request, experimental_api=True))
    queue = runtime.subscribe_voice()
    reader = runtime._reader
    try:
        runtime.client.emit("thread/realtime/started", realtimeSessionId="realtime-1")
        event = await asyncio.wait_for(queue.get(), 1)
        assert event["name"] == "thread/realtime/started"
        assert event["realtime_session_id"] == "realtime-1"
        assert runtime._reader is reader and not runtime.active
        runtime.client.emit("thread/realtime/closed", threadId="other-thread")
        await asyncio.sleep(0)
        assert queue.empty()
        runtime.unsubscribe_voice(queue)
        runtime.client.emit("thread/realtime/closed")
        await asyncio.sleep(0)
        assert queue.empty()
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_start_realtime_selects_avas_compatible_v3(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(replace(request, experimental_api=True))
    try:
        await runtime.start_realtime("v=0\r\n")
        method, params = runtime.client.calls[-1]
        assert method == "thread/realtime/start"
        assert params["version"] == "v3"
        assert params["transport"]["type"] == "webrtc"
    finally:
        await registry.aclose()


async def _wait_for_voice_state(runtime, state):
    for _ in range(50):
        if runtime.voice_task_state == state:
            return
        await asyncio.sleep(0)
    assert runtime.voice_task_state == state


@pytest.mark.asyncio
@pytest.mark.parametrize("status, expected", [("completed", "completed"), ("failed", "failed"), ("interrupted", "interrupted")])
async def test_voice_turn_state_is_recorded_by_the_single_reader(runtime_setup, status, expected):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(replace(request, experimental_api=True))
    queue = runtime.subscribe_voice()
    try:
        runtime.client.emit("turn/started", turn={"id": "voice-turn", "status": "inProgress"})
        await asyncio.wait_for(queue.get(), 1)
        await _wait_for_voice_state(runtime, "active")
        runtime.client.emit("turn/completed", turn={"id": "voice-turn", "status": status})
        await asyncio.wait_for(queue.get(), 1)
        await _wait_for_voice_state(runtime, expected)
        assert runtime.voice_turn_id == "voice-turn"
        assert runtime._reader is not None and not runtime._reader.done()
    finally:
        runtime.unsubscribe_voice(queue)
        await registry.aclose()


@pytest.mark.asyncio
async def test_regular_runtime_switch_does_not_destroy_active_voice_turn(runtime_setup):
    registry, request = runtime_setup
    runtime = await registry.open_or_create(replace(request, experimental_api=True))
    try:
        runtime.client.emit("turn/started", turn={"id": "voice-turn", "status": "inProgress"})
        await _wait_for_voice_state(runtime, "active")
        with pytest.raises(CodexServerError, match="语音任务尚未完成"):
            await registry.open_or_create(request)
        assert runtime.alive
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_experimental_api_change_rebuilds_runtime(runtime_setup):
    registry, request = runtime_setup
    first = await registry.open_or_create(request)
    second = await registry.open_or_create(replace(request, experimental_api=True))
    try:
        assert second is not first
        assert second.request.experimental_api is True
        assert not first.alive
    finally:
        await registry.aclose()


def test_independent_params_and_filtered_permissions(monkeypatch, tmp_path):
    monkeypatch.setattr("bot.codex_server.params.resolve_cli_executable", lambda *args: "codex.exe")
    config = CliParamsConfig.from_dict({"codex": {"model": "exec-only"}, "codex_server": {
        "model": "server-model", "yolo": True, "reasoning_effort": "high",
        "extra_args": ["-c", 'mcp_servers.bridge.command="bridge"', "--sandbox", "workspace-write"],
    }})
    params = convert_params("codex", str(tmp_path), config)
    assert params.model == "server-model" and params.effort == "high"
    assert params.thread == {"approvalPolicy": "never", "sandbox": "workspace-write"}
    assert "exec" not in params.argv and "app-server" in params.argv
    assert 'mcp_servers.bridge.command="bridge"' in params.argv
    safe = convert_params("codex", str(tmp_path), clamp_unsafe_cli_params(config, allow_unsafe_cli=False))
    assert safe.thread == {}
    assert 'mcp_servers.bridge.command="bridge"' not in safe.argv


@pytest.mark.parametrize("extra", [["--timeout", "120"], ["--output-last-message", "out.txt"], ["resume", "id"], ["--profile", "custom"]])
def test_unsupported_arguments_are_explicit_errors(monkeypatch, tmp_path, extra):
    monkeypatch.setattr("bot.codex_server.params.resolve_cli_executable", lambda *args: "codex.exe")
    config = CliParamsConfig.from_dict({"codex_server": {"extra_args": extra}})
    with pytest.raises(CodexServerError, match="不会回退"):
        convert_params("codex", str(tmp_path), config)
