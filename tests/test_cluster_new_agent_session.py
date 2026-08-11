from __future__ import annotations

import pytest

from bot.cluster.config import BotClusterConfig
from bot.cluster.mcp_stdio import _tools_for_environment
from bot.cluster.runtime import AskAgentRequest, ClusterRuntime, ClusterRunRequest, ClusterToolError
from bot.models import AgentProfile, BotProfile
from bot.web.api_common import WebApiError


def _profile() -> BotProfile:
    return BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=BotClusterConfig(enabled=True),
    )


def _runtime_with_run() -> tuple[ClusterRuntime, str]:
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=_profile(),
            execution_mode="cli",
        )
    )
    return runtime, run.run_id


def _create_worker_task(runtime: ClusterRuntime, run_id: str) -> str:
    task = runtime.create_agent_task(
        run_id,
        AskAgentRequest(
            agent_id="worker",
            message="do work",
            model_tier="medium",
            timeout_seconds=60,
            allow_write=False,
        ),
    )
    return task.task_id


def test_mcp_exposes_new_agent_session_tool() -> None:
    tools = {item["name"]: item for item in _tools_for_environment()}

    tool = tools["new_agent_session"]

    assert tool["inputSchema"]["required"] == ["agent_id"]
    assert "message" not in tool["inputSchema"]["properties"]


def test_validate_new_agent_session_accepts_idle_child() -> None:
    runtime, run_id = _runtime_with_run()

    agent_id = runtime.validate_new_agent_session(run_id, {"agent_id": "WORKER"})

    assert agent_id == "worker"


@pytest.mark.parametrize("task_status", ["queued", "running"])
def test_validate_new_agent_session_rejects_child_with_pending_task(task_status: str) -> None:
    runtime, run_id = _runtime_with_run()
    task_id = _create_worker_task(runtime, run_id)
    if task_status == "running":
        runtime.mark_agent_task_running(run_id, task_id)

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_new_agent_session(run_id, {"agent_id": "worker"})

    assert exc_info.value.code == "cluster_agent_busy"


def test_validate_new_agent_session_rejects_pending_task_from_another_run() -> None:
    runtime, run_id = _runtime_with_run()
    other_run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=_profile(),
            execution_mode="cli",
        )
    )
    _create_worker_task(runtime, other_run.run_id)

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_new_agent_session(run_id, {"agent_id": "worker"})

    assert exc_info.value.code == "cluster_agent_busy"


@pytest.mark.asyncio
async def test_new_agent_session_tool_creates_fresh_child_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.web.api_service as api_service

    runtime, run_id = _runtime_with_run()
    profile = runtime.get_run(run_id).profile  # type: ignore[union-attr]
    calls: list[dict[str, object]] = []

    def fake_create_conversation(manager, alias, user_id, *, agent_id, execution_mode):
        calls.append(
            {
                "manager": manager,
                "alias": alias,
                "user_id": user_id,
                "agent_id": agent_id,
                "execution_mode": execution_mode,
            }
        )
        return {"conversation": {"id": "conv_new"}, "messages": []}

    manager = object()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "create_conversation", fake_create_conversation)

    result = await api_service.handle_cluster_mcp_tool(
        manager,
        run_id,
        "new_agent_session",
        {"agent_id": "worker"},
    )

    assert result == {
        "ok": True,
        "data": {
            "agent_id": "worker",
            "conversation_id": "conv_new",
            "execution_mode": "cli",
        },
    }
    assert calls == [
        {
            "manager": manager,
            "alias": "main",
            "user_id": 1,
            "agent_id": "worker",
            "execution_mode": "cli",
        }
    ]


@pytest.mark.asyncio
async def test_new_agent_session_tool_reports_busy_child_as_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.web.api_service as api_service

    runtime, run_id = _runtime_with_run()
    profile = runtime.get_run(run_id).profile  # type: ignore[union-attr]
    _create_worker_task(runtime, run_id)

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run_id,
            "new_agent_session",
            {"agent_id": "worker"},
        )

    assert (exc_info.value.status, exc_info.value.code) == (409, "cluster_agent_busy")


@pytest.mark.asyncio
async def test_new_agent_session_tool_maps_processing_session_to_busy_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.web.api_service as api_service

    runtime, run_id = _runtime_with_run()
    profile = runtime.get_run(run_id).profile  # type: ignore[union-attr]

    def reject_processing_session(*_args, **_kwargs):
        raise WebApiError(409, "conversation_switch_blocked", "当前任务运行中")

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "create_conversation", reject_processing_session)

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run_id,
            "new_agent_session",
            {"agent_id": "worker"},
        )

    assert (exc_info.value.status, exc_info.value.code) == (409, "cluster_agent_busy")
