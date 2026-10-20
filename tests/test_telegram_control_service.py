from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot.cluster.runtime import AskAgentRequest, ClusterRunRequest, ClusterRuntime, derive_cluster_run_id
from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.native_agent.service import NativeAgentService
from bot.web import api_service as api
from bot.web.api_common import WebApiError


@pytest.fixture
def control(tmp_path, monkeypatch):
    profile = BotProfile(
        alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path),
        supported_execution_modes=["cli", "native_agent"],
        agents=[AgentProfile(id="worker", name="Worker")],
    )
    manager = MultiBotManager(profile, str(tmp_path / "managed_bots.json"))
    manager.managed_profiles["other"] = BotProfile(alias="other", working_dir=str(tmp_path))
    session = api.get_session_for_alias(manager, "main", 42)
    session.disable_persistence()
    monkeypatch.setattr(api, "_CLUSTER_RUNTIME", ClusterRuntime())
    monkeypatch.setattr(api, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api, "_terminate_process_sync", Mock(side_effect=AssertionError("unexpected process stop")))
    monkeypatch.setattr(api, "close_process_streams", Mock())
    return SimpleNamespace(manager=manager, profile=profile, session=session)


async def snapshot(c):
    return await api.get_conversation_control_snapshot(c.manager, "main", 42)


async def create(c, **kwargs):
    return await api.create_conversation(c.manager, "main", 42, **kwargs)


async def stop(c, **kwargs):
    return await api.kill_user_process(c.manager, "main", 42, **kwargs)


async def send(c, **kwargs):
    return [event async for event in api.stream_chat(c.manager, "main", 42, "hello", **kwargs)]


@pytest.mark.asyncio
async def test_expected_none_and_omitted_create_have_distinct_meanings(control):
    c = control
    await create(c, expected_conversation_id=None)
    first = c.session.active_conversation_id
    with pytest.raises(WebApiError) as err:
        await create(c, expected_conversation_id=None)
    assert err.value.code == "conversation_changed"
    assert c.session.active_conversation_id == first
    await create(c, expected_conversation_id=first)
    assert c.session.active_conversation_id != first
    await create(c)
    assert api._get_chat_store(c.session).get_conversation(first)["id"] == first


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cli", "native_agent"])
async def test_bound_send_checks_conversation_before_mode_and_preserves_web_default(control, monkeypatch, mode):
    c = control
    await create(c, execution_mode=mode)
    current = c.session.active_conversation_id
    selected = []

    async def fake_stream(*args, **kwargs):
        selected.append(c.session._execution_mode)
        assert c.session._lifecycle_operation == "chat"
        yield {"type": "done"}

    monkeypatch.setattr(api, "_stream_cli_chat", fake_stream)
    monkeypatch.setattr(api, "_stream_native_agent_chat", fake_stream)
    for expected in (None, "old-conversation"):
        result = await send(c, expected_conversation_id=expected, follow_current_conversation=True)
        assert result[0]["code"] == "conversation_changed"
    assert not selected
    await send(c, expected_conversation_id=current, follow_current_conversation=True)
    assert selected == [mode]
    await send(c)
    assert selected[-1] == "cli"
    assert c.session._execution_id is None


@pytest.mark.asyncio
async def test_bound_send_none_accepts_no_current_conversation(control, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield {"type": "done"}
    monkeypatch.setattr(api, "_stream_cli_chat", fake_stream)
    assert await send(control, expected_conversation_id=None) == [{"type": "done"}]


@pytest.mark.asyncio
async def test_snapshot_reads_explicit_conversation_without_history_repair(control, monkeypatch):
    c = control
    await create(c)
    history = api._get_chat_history_service(c.session)
    handle = history.start_turn(profile=c.profile, session=c.session, user_text="q", native_provider="codex")
    usage = {"used_tokens": 12, "context_window": 100}
    history.store.update_context_usage(handle.turn_id, usage)
    old_conversation = c.session.active_conversation_id
    before = history.store.db_path.read_bytes()
    monkeypatch.setattr(api, "_get_chat_history_service", Mock(side_effect=AssertionError("history repair")))
    monkeypatch.setattr(api, "_get_chat_store", Mock(side_effect=AssertionError("store migration")))
    result = await snapshot(c)
    assert result == {
        "conversation_id": old_conversation, "execution_mode": "cli", "phase": "idle",
        "execution_id": None, "turn_id": None, "cluster_run_id": None,
        "cluster_task_ids": [], "context_usage": usage,
    }
    assert history.store.db_path.read_bytes() == before
    with api._session_lifecycle_scope(c.session):
        preparing = await snapshot(c)
        assert preparing["phase"] == "preparing" and preparing["turn_id"] is None
    c.session.active_conversation_id = None
    result = await snapshot(c)
    assert result["conversation_id"] is None and result["context_usage"] is None
    assert history.store.db_path.read_bytes() == before
    json.dumps(result)


@pytest.mark.asyncio
async def test_snapshot_approval_requires_live_permission_signal(control, monkeypatch):
    c = control
    await create(c, execution_mode="native_agent")
    c.session.is_processing = True
    c.session._execution_id = "current-execution"
    c.session._execution_turn_id = "current-turn"
    c.session.native_agent_server_key = "runtime"
    runtime = SimpleNamespace(state=SimpleNamespace(pending_permission_ids=set()))
    monkeypatch.setattr(api, "get_native_agent_service", lambda: SimpleNamespace(get_control_runtime=lambda _: runtime))
    assert (await snapshot(c))["phase"] == "running"
    runtime.state.pending_permission_ids.add("approval")
    assert (await snapshot(c))["phase"] == "waiting_approval"
    runtime.state.pending_permission_ids.clear()
    assert (await snapshot(c))["phase"] == "running"
    c.session.is_processing = False


@pytest.mark.asyncio
async def test_preparation_has_unique_identity_and_old_stop_cannot_cancel_next_turn(control):
    c = control
    await create(c)
    with api._session_lifecycle_scope(c.session):
        first = await snapshot(c)
        assert first["phase"] == "preparing" and first["turn_id"] is None
        assert first["execution_id"]
    with api._session_lifecycle_scope(c.session):
        second = await snapshot(c)
        assert second["execution_id"] != first["execution_id"]
        with pytest.raises(WebApiError) as err:
            await stop(c, expected_control=first)
        assert err.value.code == "execution_changed"
        assert not c.session.stop_requested
        result = await stop(c, expected_control=second)
        assert result["stop_requested"] and c.session.stop_requested
    with pytest.raises(WebApiError) as err:
        await stop(c, expected_control=second)
    assert err.value.code == "execution_changed"


def add_cluster_task(c):
    runtime = api._CLUSTER_RUNTIME
    run_id = derive_cluster_run_id(c.session.active_conversation_id, 0)
    run = runtime.get_run(run_id) or runtime.ensure_run(ClusterRunRequest(
        bot_alias="main", user_id=c.session.user_id, profile=c.profile,
        main_conversation_id=c.session.active_conversation_id,
    ), run_id)
    task = runtime.create_agent_task(run_id, AskAgentRequest(
        agent_id="worker", message="work", model_tier="medium", timeout_seconds=60, allow_write=False,
    ))
    return run, task


@pytest.mark.asyncio
async def test_child_only_stop_rejects_task_set_changes_in_same_run(control):
    c = control
    await create(c)
    run, first = add_cluster_task(c)
    old = await snapshot(c)
    assert old["phase"] == "running" and old["execution_id"] is None
    assert old["cluster_task_ids"] == [first.task_id]
    _, second = add_cluster_task(c)
    with pytest.raises(WebApiError) as err:
        await stop(c, expected_control=old)
    assert err.value.code == "execution_changed"
    assert first.status == second.status == "queued"
    current = await snapshot(c)
    assert current["cluster_task_ids"] == sorted([first.task_id, second.task_id])
    result = await stop(c, expected_conversation_id=c.session.active_conversation_id, expected_control=current)
    assert result["cluster_run_cancelled"] == run.run_id
    assert first.status == second.status == "cancelled"
    assert (await snapshot(c))["phase"] == "idle"


@pytest.mark.asyncio
async def test_stop_hold_survives_completion_duplicate_requests_and_repeated_cancellation(control, monkeypatch):
    c = control
    await create(c)
    process = Mock()
    c.session.process = process
    c.session.is_processing = True
    c.session._execution_id = "execution"
    c.session._execution_turn_id = "turn"
    entered, release = asyncio.Event(), asyncio.Event()
    lifecycle = object()

    async def terminate(actual):
        assert actual is lifecycle
        entered.set()
        await release.wait()

    terminate_mock = AsyncMock(side_effect=terminate)
    monkeypatch.setattr(api, "_get_cli_process_lifecycle", lambda p: lifecycle if p is process else None)
    monkeypatch.setattr(api, "_terminate_cli_process_lifecycle", terminate_mock)
    expected = await snapshot(c)
    first = asyncio.create_task(stop(c, expected_control=expected))
    await entered.wait()
    second = asyncio.create_task(stop(c, expected_control=expected))
    await asyncio.sleep(0)
    c.session.is_processing = False
    c.session.process = None
    c.session._execution_id = None
    for _ in range(2):
        first.cancel()
        second.cancel()
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        assert (await snapshot(c))["phase"] == "stopping"
        assert (await send(c))[0]["code"] == "session_busy"
        with pytest.raises(WebApiError) as err:
            await create(c)
        assert err.value.code == "conversation_switch_blocked"
        with pytest.raises(WebApiError):
            await api.select_conversation(c.manager, "main", 42, c.session.active_conversation_id)
    await api.create_conversation(c.manager, "other", 42)
    release.set()
    await asyncio.gather(first, second, return_exceptions=True)
    terminate_mock.assert_awaited_once()
    assert c.session._control_stop_task is None
    await create(c)


@pytest.mark.asyncio
async def test_native_stop_uses_captured_runtime_and_rejects_replaced_execution(control, monkeypatch):
    c = control
    await create(c, execution_mode="native_agent")
    service = NativeAgentService()
    old = SimpleNamespace(abort=AsyncMock(return_value=True), state=SimpleNamespace(pending_permission_ids=set()))
    replacement = SimpleNamespace(abort=AsyncMock(return_value=True))
    service._runtime_registry = SimpleNamespace(get_by_runtime_id=Mock(return_value=old))
    monkeypatch.setattr(api, "get_native_agent_service", lambda: service)
    c.session.is_processing = True
    c.session._execution_id = "execution"
    c.session._execution_turn_id = "turn"
    c.session.native_agent_run_id = "native-run"
    c.session.native_agent_server_key = "native-runtime"
    expected = await snapshot(c)
    task = asyncio.create_task(stop(c, expected_control=expected))
    await asyncio.sleep(0)
    service._runtime_registry.get_by_runtime_id.return_value = replacement
    assert (await task)["native_agent_aborted"]
    old.abort.assert_awaited_once()
    replacement.abort.assert_not_awaited()
    c.session._execution_id = "next-execution"
    assert not await service.abort(c.session, expected_execution_id="execution", captured_runtime=old)
    old.abort.assert_awaited_once()
    c.session.is_processing = False


@pytest.mark.asyncio
async def test_stale_process_cleanup_never_clears_replacement_execution(control, monkeypatch):
    c = control
    await create(c)
    process = Mock(poll=Mock(return_value=0))
    c.session.process = process
    c.session.is_processing = True
    c.session._execution_id = "old"
    replacement = Mock()

    def close(actual):
        assert actual is process
        with c.session._lock:
            c.session.process = replacement
            c.session._execution_id = "replacement"

    monkeypatch.setattr(api, "close_process_streams", close)
    monkeypatch.setattr(api, "_get_cli_process_lifecycle", lambda _: None)
    await stop(c)
    assert c.session.is_processing and c.session.process is replacement
    assert c.session._execution_id == "replacement"
    c.session.process = None
    c.session.is_processing = False


@pytest.mark.asyncio
async def test_pi_execution_identity_survives_disconnect_and_resume_until_producer_finishes(control, monkeypatch):
    c = control
    await create(c, execution_mode="native_agent")
    service = NativeAgentService()
    release = asyncio.Event()
    executions = []

    async def produce(**kwargs):
        executions.append(c.session._execution_id)
        c.session.is_processing = True
        c.session._execution_turn_id = "turn"
        try:
            yield {"type": "status", "turn_id": "turn"}
            await release.wait()
            yield {"type": "done", "turn_id": "turn"}
        finally:
            c.session.is_processing = False

    monkeypatch.setattr(service, "stream_chat", produce)
    monkeypatch.setattr(api, "get_native_agent_service", lambda: service)
    events = api.stream_chat(c.manager, "main", 42, "hello", follow_current_conversation=True, enable_reconnect=True)
    first = await anext(events)
    before = await snapshot(c)
    await events.aclose()
    assert c.session._execution_id == before["execution_id"]
    assert c.session._lifecycle_operation == "chat"
    resumed = api.stream_chat(
        c.manager, "main", 42, "", follow_current_conversation=True,
        resume_stream_id=first["stream_id"], resume_turn_id="turn",
    )
    assert (await anext(resumed))["turn_id"] == "turn"
    assert (await snapshot(c))["execution_id"] == before["execution_id"]
    release.set()
    assert any([event["type"] == "done" async for event in resumed])
    assert executions == [before["execution_id"]]
    assert c.session._execution_id is None and c.session._lifecycle_operation == ""
    for channel in service._turn_channels.values():
        await channel.close()


@pytest.mark.asyncio
async def test_codex_server_stop_binds_runtime_and_active_turn(control, monkeypatch):
    from bot.codex_server import runtime as server_module

    c = control
    c.profile.cli_type = "codex_server"
    await create(c)
    c.session.is_processing = True
    runtime = SimpleNamespace(active_turn_id="voice-1", voice_task_active=True, interrupt=AsyncMock())
    replacement = SimpleNamespace(active_turn_id="voice-2", voice_task_active=True, interrupt=AsyncMock())
    owner = api._codex_server_owner(c.session)
    registry = SimpleNamespace(_runtimes={owner: runtime})
    monkeypatch.setattr(server_module, "get_codex_server_registry", lambda: registry)
    old = await snapshot(c)
    assert old["execution_id"] == "voice-1" and old["phase"] == "running"
    runtime.active_turn_id = "voice-2"
    with pytest.raises(WebApiError) as err:
        await stop(c, expected_control=old)
    assert err.value.code == "execution_changed"
    runtime.interrupt.assert_not_awaited()
    current = await snapshot(c)
    pending = asyncio.create_task(stop(c, expected_control=current))
    await asyncio.sleep(0)
    registry._runtimes[owner] = replacement
    assert (await pending)["stop_requested"]
    runtime.interrupt.assert_awaited_once()
    replacement.interrupt.assert_not_awaited()
    c.session.is_processing = False


@pytest.mark.asyncio
async def test_cluster_stop_waits_for_captured_child_cleanup(control):
    c = control
    await create(c)
    run, task = add_cluster_task(c)
    entered, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def child():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelling.set()
            await release.wait()
            raise

    background = asyncio.create_task(child())
    run_control = api._cluster_run_control(run.run_id, 1)
    run_control.tasks.add(background)
    await entered.wait()
    expected = await snapshot(c)
    pending = asyncio.create_task(stop(c, expected_control=expected))
    await cancelling.wait()
    api._cleanup_cluster_run_control_if_idle(run.run_id)
    with pytest.raises(api.ClusterToolError):
        api._require_cluster_run_control_ready(run.run_id)
    with pytest.raises(WebApiError):
        await create(c)
    assert not pending.done()
    assert c.session._control_stop_task is not None
    release.set()
    await pending
    assert task.status == "cancelled" and background.cancelled()
    assert c.session._control_stop_task is None
    assert run.run_id not in api._CLUSTER_RUN_CONTROLS
    assert "cluster_run_cancelled" not in await stop(c)


@pytest.mark.asyncio
async def test_stop_expected_conversation_none_rejects_existing_session(control):
    c = control
    assert not (await stop(c, expected_conversation_id=None))["killed"]
    await create(c)
    with pytest.raises(WebApiError) as err:
        await stop(c, expected_conversation_id=None)
    assert err.value.code == "conversation_changed"


@pytest.mark.asyncio
async def test_native_disconnect_abort_keeps_hold_through_duplicate_cancellation(control, monkeypatch):
    c = control
    await create(c, execution_mode="native_agent")
    service = NativeAgentService()
    entered, release = asyncio.Event(), asyncio.Event()

    async def abort_runtime():
        entered.set()
        await release.wait()
        return True

    runtime = SimpleNamespace(abort=AsyncMock(side_effect=abort_runtime))
    service._runtime_registry = SimpleNamespace(get_by_runtime_id=lambda _: runtime)
    c.session.is_processing = True
    c.session._execution_id = "execution"
    c.session.native_agent_server_key = "runtime"
    first = asyncio.create_task(service.abort(c.session, expected_execution_id="execution"))
    await entered.wait()
    second = asyncio.create_task(service.abort(c.session, expected_execution_id="execution"))
    await asyncio.sleep(0)
    c.session.is_processing = False
    c.session._execution_id = None
    c.session.native_agent_server_key = None
    for _ in range(2):
        first.cancel()
        second.cancel()
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        assert (await send(c))[0]["code"] == "session_busy"
        with pytest.raises(WebApiError):
            await create(c)
        assert (await snapshot(c))["phase"] == "stopping"
    release.set()
    await asyncio.gather(first, second, return_exceptions=True)
    runtime.abort.assert_awaited_once()
    assert c.session._native_abort_task is None
    await create(c)
