from __future__ import annotations

import asyncio
import re

import pytest

from bot.cluster.config import BotClusterConfig
from bot.cluster.runtime import (
    CLUSTER_PARENT_WAKEUP_GRACE_SECONDS,
    AskAgentRequest,
    ClusterRunRequest,
    ClusterRuntime,
    derive_cluster_run_id,
)
from bot.models import AgentProfile, BotProfile, UserSession


def _cluster_fixture(clock=None):
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime(clock=clock) if clock is not None else ClusterRuntime()
    run_id = derive_cluster_run_id("conv_main", 1)
    run = runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "worker",
                    "name": "后端分析",
                    "responsibility": "检查后端",
                    "assignment_revision": 1,
                }],
            },
        ),
        run_id,
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=".",
        active_conversation_id="conv_main",
        _persist_enabled=False,
    )
    return profile, runtime, run, session


def _patch_parent(monkeypatch, api_service, profile, runtime, session) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def fake_run_chat(*args, **kwargs):
        calls.append((args[3], kwargs))
        return {"output": "parent response", "returncode": 0}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_require_current_cluster_team", lambda *_args: None)
    monkeypatch.setattr(api_service, "run_chat", fake_run_chat)
    api_service._CLUSTER_RUN_CONTROLS.clear()
    return calls


def _start_task(runtime: ClusterRuntime, run_id: str):
    task = runtime.create_agent_task(
        run_id,
        AskAgentRequest(
            agent_id="worker",
            message="work",
            model_tier="medium",
            timeout_seconds=60,
            allow_write=False,
            role_name="后端分析",
            responsibility="检查后端",
            team_revision=1,
            assignment_revision=1,
        ),
        parent_conversation_id="conv_main",
        parent_turn_id="turn_parent",
    )
    runtime.mark_agent_task_running(run_id, task.task_id)
    return task


def _complete_task(runtime: ClusterRuntime, run_id: str, *, output: str = "child secret"):
    task = _start_task(runtime, run_id)
    runtime.complete_agent_task(run_id, task.task_id, output)
    return task


async def _drain_wakeup(run) -> None:
    if run.parent_wakeup_task is not None:
        await run.parent_wakeup_task
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_ask_agent_snapshots_parent_conversation_and_turn(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    session._execution_turn_id = "turn_parent"
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_require_current_cluster_team", lambda *_args: None)

    async def no_op_child(*_args):
        return None

    monkeypatch.setattr(api_service, "_run_cluster_agent_task", no_op_child)
    api_service._CLUSTER_RUN_CONTROLS.clear()

    await api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "ask_agent",
        {"agent_id": "worker", "message": "work"},
    )
    task = next(iter(run.tasks.values()))

    assert task.parent_conversation_id == "conv_main"
    assert task.parent_turn_id == "turn_parent"
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_completed_child_wakes_idle_parent_without_child_output(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    calls = _patch_parent(monkeypatch, api_service, profile, runtime, session)

    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    assert run.parent_wakeup_task is not None
    await _drain_wakeup(run)

    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert f'task_ids=["{task.task_id}"]' in prompt
    assert "child secret" not in prompt
    assert "poll_agent_tasks" in prompt
    assert not re.search(r"[　-〿一-鿿＀-￯]", prompt.replace("后端分析", ""))
    assert kwargs["internal_continuation"] is True
    assert kwargs["expected_conversation_id"] == "conv_main"
    assert kwargs["cluster_run_id"] == run.run_id
    assert task.wakeup_sent is True
    assert run.pending_parent_wakeup_task_ids == set()
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_child_finishing_before_parent_turn_ends_never_wakes_parent(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    calls = _patch_parent(monkeypatch, api_service, profile, runtime, session)

    session.is_processing = True
    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    session.is_processing = False
    api_service._finish_cluster_parent_turn(object(), run.run_id)
    await _drain_wakeup(run)

    assert calls == []
    assert run.pending_parent_wakeup_task_ids == set()
    assert task.wakeup_sent is False
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_child_finishing_within_grace_window_does_not_wake_parent(monkeypatch) -> None:
    import bot.web.api_service as api_service

    now = [1000.0]
    profile, runtime, run, session = _cluster_fixture(clock=lambda: now[0])
    calls = _patch_parent(monkeypatch, api_service, profile, runtime, session)
    api_service._finish_cluster_parent_turn(object(), run.run_id)

    now[0] += CLUSTER_PARENT_WAKEUP_GRACE_SECONDS
    close_finish = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, close_finish.task_id)
    assert run.parent_wakeup_task is None

    now[0] += 1
    late_finish = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, late_finish.task_id)
    await _drain_wakeup(run)

    assert len(calls) == 1
    assert late_finish.task_id in calls[0][0]
    assert close_finish.task_id not in calls[0][0]
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_only_children_of_latest_request_wake_parent(monkeypatch) -> None:
    import bot.web.api_service as api_service

    now = [1000.0]
    profile, runtime, run, session = _cluster_fixture(clock=lambda: now[0])
    calls = _patch_parent(monkeypatch, api_service, profile, runtime, session)

    runtime.begin_parent_request("conv_main", "exec_first")
    previous = _start_task(runtime, run.run_id)
    checked_again = _start_task(runtime, run.run_id)
    api_service._finish_cluster_parent_turn(object(), run.run_id)

    latest = runtime.begin_parent_request("conv_main", "exec_latest")
    # Endless-mode attempts reuse the request id and stay in the same request.
    assert runtime.begin_parent_request("conv_main", "exec_latest") == latest
    await api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [checked_again.task_id]},
    )
    api_service._finish_cluster_parent_turn(object(), run.run_id)

    now[0] += CLUSTER_PARENT_WAKEUP_GRACE_SECONDS + 30
    for task in (previous, checked_again):
        runtime.complete_agent_task(run.run_id, task.task_id, "done")
        api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    await _drain_wakeup(run)

    assert len(calls) == 1
    assert checked_again.task_id in calls[0][0]
    assert previous.task_id not in calls[0][0]
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_new_request_drops_undelivered_parent_wakeup(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    calls = _patch_parent(monkeypatch, api_service, profile, runtime, session)

    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    session.is_processing = True  # The user's next message starts before the notice is delivered.
    await _drain_wakeup(run)
    assert run.pending_parent_wakeup_task_ids == {task.task_id}

    runtime.begin_parent_request("conv_main", "exec_next")
    session.is_processing = False
    api_service._finish_cluster_parent_turn(object(), run.run_id)
    await _drain_wakeup(run)

    assert calls == []
    assert run.pending_parent_wakeup_task_ids == set()
    assert task.wakeup_pending is False
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_cancel_clears_pending_parent_wakeup(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    _patch_parent(monkeypatch, api_service, profile, runtime, session)

    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    session.is_processing = True
    await _drain_wakeup(run)
    assert run.pending_parent_wakeup_task_ids == {task.task_id}

    await api_service._cancel_cluster_run(run.run_id, "stop")

    assert run.pending_parent_wakeup_task_ids == set()
    assert task.wakeup_pending is False
    api_service._CLUSTER_RUN_CONTROLS.clear()
