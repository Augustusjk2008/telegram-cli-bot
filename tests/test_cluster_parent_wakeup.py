from __future__ import annotations

import asyncio

import pytest

from bot.cluster.config import BotClusterConfig
from bot.cluster.runtime import AskAgentRequest, ClusterRunRequest, ClusterRuntime, derive_cluster_run_id
from bot.models import AgentProfile, BotProfile, UserSession


def _cluster_fixture():
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
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


def _complete_task(runtime: ClusterRuntime, run_id: str, *, output: str = "child secret"):
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
    runtime.complete_agent_task(run_id, task.task_id, output)
    return task


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

    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    wakeup = run.parent_wakeup_task
    assert wakeup is not None
    await wakeup
    await asyncio.sleep(0)

    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert task.task_id in prompt
    assert "child secret" not in prompt
    assert "poll_agent_tasks" in prompt
    assert kwargs["internal_continuation"] is True
    assert kwargs["expected_conversation_id"] == "conv_main"
    assert kwargs["cluster_run_id"] == run.run_id
    assert task.wakeup_sent is True
    assert run.pending_parent_wakeup_task_ids == set()
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_parent_wakeup_waits_for_busy_parent_and_merges_tasks(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    calls: list[str] = []

    async def fake_run_chat(*args, **_kwargs):
        calls.append(args[3])
        return {"output": "ok", "returncode": 0}

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

    session.is_processing = True
    first = _complete_task(runtime, run.run_id, output="first secret")
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, first.task_id)
    first_wakeup = run.parent_wakeup_task
    assert first_wakeup is not None
    await first_wakeup
    await asyncio.sleep(0)

    second = _complete_task(runtime, run.run_id, output="second secret")
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, second.task_id)
    session.is_processing = False
    second_wakeup = run.parent_wakeup_task
    assert second_wakeup is not None
    await second_wakeup
    await asyncio.sleep(0)

    assert len(calls) == 1
    assert first.task_id in calls[0]
    assert second.task_id in calls[0]
    assert "first secret" not in calls[0]
    assert "second secret" not in calls[0]
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_cancel_clears_pending_parent_wakeup(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile, runtime, run, session = _cluster_fixture()
    session.is_processing = True
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_require_current_cluster_team", lambda *_args: None)
    task = _complete_task(runtime, run.run_id)
    api_service._schedule_cluster_parent_wakeup(object(), run.run_id, task.task_id)
    wakeup = run.parent_wakeup_task
    assert wakeup is not None
    await wakeup
    await asyncio.sleep(0)
    assert run.pending_parent_wakeup_task_ids == {task.task_id}

    await api_service._cancel_cluster_run(run.run_id, "stop")

    assert run.pending_parent_wakeup_task_ids == set()
    assert task.wakeup_pending is False
    api_service._CLUSTER_RUN_CONTROLS.clear()
