from __future__ import annotations

import asyncio

import pytest

from bot.cluster.config import BotClusterConfig
from bot.cluster.runtime import AskAgentRequest, ClusterRuntime, ClusterRunRequest
from bot.models import BotProfile


def _profile() -> BotProfile:
    return BotProfile(
        alias="main",
        working_dir=".",
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )


def _run_with_task(runtime: ClusterRuntime):
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=_profile(),
            execution_mode="cli",
        )
    )
    task = runtime.create_agent_task(
        run.run_id,
        AskAgentRequest(
            agent_id="worker",
            message="do work",
            model_tier="medium",
            timeout_seconds=60,
            allow_write=False,
        ),
    )
    return run, task


def test_complete_and_fail_keep_cancelled_task_status() -> None:
    runtime = ClusterRuntime()
    run, task = _run_with_task(runtime)

    runtime.mark_agent_task_running(run.run_id, task.task_id)
    runtime.cancel_run_tasks(run.run_id, "stop")
    runtime.complete_agent_task(run.run_id, task.task_id, "late output")
    runtime.fail_agent_task(run.run_id, task.task_id, "late failure")

    saved = runtime.get_run(run.run_id).tasks[task.task_id]  # type: ignore[union-attr]
    assert saved.status == "cancelled"
    assert saved.error == "stop"
    assert saved.output == ""
    assert [message.kind for message in saved.messages].count("final") == 1


def test_finish_run_keeps_cancelled_run_status() -> None:
    runtime = ClusterRuntime()
    run, _task = _run_with_task(runtime)

    runtime.finish_run(run.run_id, "cancelled")
    runtime.finish_run(run.run_id, "completed")

    assert runtime.get_run(run.run_id).status == "cancelled"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_cancel_cluster_run_cancels_running_background_tasks(monkeypatch) -> None:
    import bot.web.api_service as api_service

    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    api_service._CLUSTER_RUN_CONTROLS.clear()
    run, task = _run_with_task(runtime)
    runtime.mark_agent_task_running(run.run_id, task.task_id)
    control = api_service._cluster_run_control(run.run_id, 1)
    background_task = asyncio.create_task(asyncio.sleep(60))
    control.tasks.add(background_task)
    background_task.add_done_callback(control.tasks.discard)

    try:
        await api_service._cancel_cluster_run(run.run_id, "stop")
        await asyncio.sleep(0)
        assert background_task.cancelled()
        assert api_service._CLUSTER_RUN_CONTROLS.get(run.run_id) is control
    finally:
        background_task.cancel()
        await asyncio.gather(background_task, return_exceptions=True)
        api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_cluster_agent_task_does_not_complete_after_stream_cancel(monkeypatch) -> None:
    import bot.web.api_service as api_service

    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    api_service._CLUSTER_RUN_CONTROLS.clear()
    run, task = _run_with_task(runtime)

    async def fake_stream_cli_chat(*_args, **_kwargs):
        yield {"type": "status", "preview_text": "started"}
        runtime.cancel_run_tasks(run.run_id, "stop")
        yield {"type": "done", "output": "late output", "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream_cli_chat)

    await api_service._run_cluster_agent_task(object(), run.run_id, task.task_id)

    saved = runtime.get_run(run.run_id).tasks[task.task_id]  # type: ignore[union-attr]
    assert saved.status == "cancelled"
    assert saved.output == ""
    assert saved.error == "stop"
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_cluster_runtime_wait_for_task_change_is_not_polling() -> None:
    runtime = ClusterRuntime()
    run, task = _run_with_task(runtime)
    runtime.mark_agent_task_running(run.run_id, task.task_id)

    waiter = asyncio.create_task(runtime.wait_for_task_change(run.run_id, [task.task_id], 1))
    await asyncio.sleep(0)
    runtime.complete_agent_task(run.run_id, task.task_id, "done")
    await runtime.notify_agent_task_message(run.run_id)
    await asyncio.wait_for(waiter, timeout=0.5)
