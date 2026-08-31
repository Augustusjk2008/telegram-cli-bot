from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from bot.cluster.config import BotClusterConfig
import pytest

from bot.cluster.runtime import (
    AskAgentRequest,
    ClusterRuntime,
    ClusterRunRequest,
    ClusterToolError,
    derive_cluster_run_id,
)
from bot.models import AgentProfile, BotProfile, UserSession
from bot.web.api_common import WebApiError


def test_enabled_cluster_starts_run_without_legacy_request_flag(monkeypatch) -> None:
    import bot.web.api_service as api_service

    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    profile = BotProfile(
        alias="main",
        working_dir=".",
        cluster=BotClusterConfig(enabled=True),
    )

    run = api_service._start_cluster_run_if_requested(
        profile=profile,
        alias="main",
        shared_user_id=1,
        cluster=False,
        execution_mode="cli",
        mentions=[],
        allow_unsafe_cli=False,
        main_conversation_id="conv_main",
        team_state={"cluster_team_revision": 0},
    )

    assert run is not None
    assert run.run_id == derive_cluster_run_id("conv_main", 0)
    assert run.tasks == {}


def test_stable_run_is_reused_across_turns_and_runtime_restart() -> None:
    profile = BotProfile(alias="main", working_dir=".", cluster=BotClusterConfig(enabled=True))
    request = ClusterRunRequest(
        bot_alias="main",
        user_id=1,
        profile=profile,
        main_conversation_id="conv_a",
        team_revision=3,
    )
    run_id = derive_cluster_run_id("conv_a", 3)
    runtime = ClusterRuntime()
    first = runtime.ensure_run(request, run_id)
    task = runtime.create_agent_task(
        run_id,
        AskAgentRequest(
            agent_id="worker",
            message="work",
            model_tier="medium",
            timeout_seconds=60,
            allow_write=False,
        ),
    )
    runtime.complete_agent_task(run_id, task.task_id, "done")

    second = runtime.ensure_run(request, run_id)
    restarted = ClusterRuntime().ensure_run(request, run_id)

    assert second is first
    assert second.run_id == restarted.run_id == run_id
    assert runtime.build_task_status(run_id, include_messages=True)["tasks"][0]["output"] == "done"
    assert derive_cluster_run_id("conv_b", 3) != run_id


def test_queued_task_keeps_execution_snapshot_when_run_is_refreshed() -> None:
    first_profile = BotProfile(
        alias="main",
        working_dir=".",
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    run_id = derive_cluster_run_id("conv_main", 0)
    runtime = ClusterRuntime()
    runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=first_profile,
            execution_mode="cli",
            allow_unsafe_cli=False,
            main_conversation_id="conv_main",
        ),
        run_id,
    )
    first_task = runtime.create_agent_task(
        run_id,
        AskAgentRequest(
            agent_id="worker",
            message="first",
            model_tier="low",
            timeout_seconds=60,
            allow_write=False,
        ),
    )
    refreshed_profile = BotProfile(
        alias="main",
        working_dir=".",
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=4),
    )
    runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=refreshed_profile,
            execution_mode="native_agent",
            allow_unsafe_cli=True,
            main_conversation_id="conv_main",
        ),
        run_id,
    )
    second_task = runtime.create_agent_task(
        run_id,
        AskAgentRequest(
            agent_id="worker",
            message="second",
            model_tier="high",
            timeout_seconds=60,
            allow_write=False,
        ),
    )

    assert first_task.execution_mode == "cli"
    assert first_task.allow_unsafe_cli is False
    assert first_task.profile.cluster.max_parallel_agents == 1
    assert second_task.execution_mode == "native_agent"
    assert second_task.allow_unsafe_cli is True
    assert second_task.profile.cluster.max_parallel_agents == 4


def test_cluster_run_is_not_created_for_child_or_internal_continuation(monkeypatch) -> None:
    import bot.web.api_service as api_service

    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    profile = BotProfile(
        alias="main",
        working_dir=".",
        cluster=BotClusterConfig(enabled=True),
    )
    common = {
        "profile": profile,
        "alias": "main",
        "shared_user_id": 1,
        "cluster": True,
        "execution_mode": "cli",
        "mentions": [],
        "allow_unsafe_cli": False,
    }

    assert api_service._start_cluster_run_if_requested(**common, agent_id="worker") is None
    assert api_service._start_cluster_run_if_requested(**common, solo_mode=True) is None
    assert api_service._start_cluster_run_if_requested(**common, internal_continuation=True) is None


def test_disabled_cluster_ignores_legacy_request_flag(monkeypatch) -> None:
    import bot.web.api_service as api_service

    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    profile = BotProfile(alias="main", working_dir=".", cluster=BotClusterConfig(enabled=False))

    run = api_service._start_cluster_run_if_requested(
        profile=profile,
        alias="main",
        shared_user_id=1,
        cluster=True,
        execution_mode="cli",
        mentions=[],
        allow_unsafe_cli=False,
    )

    assert run is None


def test_ask_agent_rejects_slot_occupied_by_another_run() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=BotClusterConfig(enabled=True),
    )
    runtime = ClusterRuntime()
    first = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1, profile=profile))
    second = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1, profile=profile))
    first_request = runtime.validate_ask_agent(first.run_id, {"agent_id": "worker", "message": "first"})
    runtime.create_agent_task(first.run_id, first_request)

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_ask_agent(second.run_id, {"agent_id": "worker", "message": "second"})

    assert exc_info.value.code == "cluster_agent_busy"


def test_agent_slot_remains_busy_between_main_conversations() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=BotClusterConfig(enabled=True),
    )
    team = {
        "version": 1,
        "assignments": [{
            "agent_id": "worker",
            "name": "分析",
            "responsibility": "检查实现",
            "assignment_revision": 1,
        }],
    }
    runtime = ClusterRuntime()
    runs = []
    for conversation_id in ("conv_a", "conv_b"):
        run_id = derive_cluster_run_id(conversation_id, 1)
        runs.append(runtime.ensure_run(
            ClusterRunRequest(
                bot_alias="main",
                user_id=1,
                profile=profile,
                main_conversation_id=conversation_id,
                team_revision=1,
                team=team,
            ),
            run_id,
        ))
    first_request = runtime.validate_ask_agent(
        runs[0].run_id,
        {"agent_id": "worker", "message": "first"},
    )
    runtime.create_agent_task(runs[0].run_id, first_request)

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_ask_agent(
            runs[1].run_id,
            {"agent_id": "worker", "message": "second"},
        )

    assert exc_info.value.code == "cluster_agent_busy"


def test_cluster_run_keeps_immutable_profile_snapshot() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Before")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()

    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1, profile=profile))
    profile.agents[0].name = "After"
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=8)

    assert run.profile.get_agent("worker").name == "Before"
    assert run.profile.cluster.max_parallel_agents == 1


def test_unassigned_slot_cannot_be_called() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Legacy")],
        cluster=BotClusterConfig(enabled=True),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1, profile=profile))
    run.main_conversation_id = "conv_main"  # type: ignore[attr-defined]
    run.team = {"version": 1, "assignments": []}  # type: ignore[attr-defined]

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_ask_agent(run.run_id, {"agent_id": "worker", "message": "work"})

    assert exc_info.value.code == "cluster_agent_not_assigned"


def test_cluster_task_keeps_dynamic_role_snapshot() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="worker", name="Legacy", system_prompt="legacy prompt")],
        cluster=BotClusterConfig(enabled=True),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=4,
            team={
                "version": 1,
                "assignments": [
                    {
                        "agent_id": "worker",
                        "name": "后端分析",
                        "responsibility": "检查并发边界",
                        "assignment_revision": 3,
                    }
                ],
            },
        )
    )

    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "worker", "message": "work"})
    task = runtime.create_agent_task(run.run_id, request)
    serialized = runtime.build_task_status(run.run_id)["tasks"][0]

    assert task.role_name == "后端分析"
    assert task.responsibility == "检查并发边界"
    assert task.team_revision == 4
    assert task.assignment_revision == 3
    assert serialized["role_name"] == "后端分析"
    assert serialized["responsibility"] == "检查并发边界"


def test_cluster_status_reports_team_capacity_and_free_slots() -> None:
    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One"), AgentProfile(id="two", name="Two")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=2),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=2,
            team={
                "version": 1,
                "assignments": [
                    {
                        "agent_id": "one",
                        "name": "分析",
                        "responsibility": "分析问题",
                        "assignment_revision": 1,
                    }
                ],
            },
        )
    )

    status = runtime.build_status(run.run_id)

    assert status["capacity"] == 2
    assert status["free_slots"] == 1
    assert status["team_revision"] == 2
    assert status["slots"] == [
        {
            "agent_id": "one",
            "assigned": True,
            "role_name": "分析",
            "responsibility": "分析问题",
            "assignment_revision": 1,
            "status": "idle",
        },
        {
            "agent_id": "two",
            "assigned": False,
            "role_name": "",
            "responsibility": "",
            "assignment_revision": 0,
            "status": "idle",
        },
    ]


@pytest.mark.asyncio
async def test_configure_team_extend_assigns_first_free_slot_and_updates_run(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One"), AgentProfile(id="two", name="Two")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=2),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=0,
            team={"version": 1, "assignments": []},
        )
    )

    class FakeStore:
        state = {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 0}

        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_main"
            return self.state

        def update_conversation_team(self, conversation_id, team, *, expected_revision):
            assert conversation_id == "conv_main"
            assert expected_revision == self.state["cluster_team_revision"]
            self.state = {
                "cluster_team": team,
                "cluster_team_revision": expected_revision + 1,
            }
            return self.state

    store = FakeStore()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: store, raising=False)
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    result = await api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "configure_team",
        {
            "mode": "extend",
            "roles": [{"name": "分析", "responsibility": "检查后端"}],
        },
    )

    assert result["data"]["team_revision"] == 1
    assert result["data"]["changed"] is True
    assert result["data"]["run_id"] == derive_cluster_run_id("conv_main", 1)
    assert result["data"]["capacity"] == 2
    assert result["data"]["free_slots"] == 1
    assert result["data"]["assignments"] == [
        {
            "agent_id": "one",
            "name": "分析",
            "responsibility": "检查后端",
            "assignment_revision": 1,
        }
    ]
    assert runtime.get_run(run.run_id).status == "completed"  # type: ignore[union-attr]
    next_run = runtime.get_run(result["data"]["run_id"])
    assert next_run is not None
    assert next_run.team_revision == 1

    async def finish_agent_task(_manager, current_run_id, task_id):
        runtime.mark_agent_task_running(current_run_id, task_id)
        runtime.complete_agent_task(current_run_id, task_id, "done")

    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")
    monkeypatch.setattr(api_service, "_run_cluster_agent_task", finish_agent_task)
    api_service._CLUSTER_RUN_CONTROLS.clear()
    delegated = await api_service.handle_cluster_mcp_tool(
        object(),
        result["data"]["run_id"],
        "ask_agent",
        {"agent_id": "one", "message": "continue"},
    )
    await asyncio.sleep(0)

    assert delegated["data"]["agent_id"] == "one"
    assert runtime.build_task_status(result["data"]["run_id"])["completed_count"] == 1
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_configure_team_replace_compacts_roles_and_preserves_unchanged_revision(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One"), AgentProfile(id="two", name="Two")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=2),
    )
    runtime = ClusterRuntime()
    initial_team = {
        "version": 1,
        "assignments": [
            {
                "agent_id": "one",
                "name": "分析",
                "responsibility": "检查后端",
                "assignment_revision": 3,
            },
            {
                "agent_id": "two",
                "name": "前端",
                "responsibility": "检查界面",
                "assignment_revision": 2,
            },
        ],
    }
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=5,
            team=initial_team,
        )
    )

    class FakeStore:
        state = {"cluster_team": initial_team, "cluster_team_revision": 5}

        def get_conversation_team(self, _conversation_id):
            return self.state

        def update_conversation_team(self, _conversation_id, team, *, expected_revision):
            self.state = {"cluster_team": team, "cluster_team_revision": expected_revision + 1}
            return self.state

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: FakeStore())
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    result = await api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "configure_team",
        {
            "mode": "replace",
            "roles": [
                {"name": "分析", "responsibility": "检查后端"},
                {"name": "质量", "responsibility": "复核结果"},
            ],
        },
    )

    assignments = result["data"]["assignments"]
    assert result["data"]["changed"] is True
    assert result["data"]["run_id"] == derive_cluster_run_id("conv_main", 6)
    assert [item["agent_id"] for item in assignments] == ["one", "two"]
    assert assignments[0]["assignment_revision"] == 3
    assert assignments[1]["assignment_revision"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "extend", "roles": []},
        {"mode": "replace", "roles": [{"name": "分析", "responsibility": "检查后端"}]},
    ],
)
async def test_configure_team_no_change_keeps_revision_and_run_id(monkeypatch, payload) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    team = {
        "version": 1,
        "assignments": [{
            "agent_id": "one",
            "name": "分析",
            "responsibility": "检查后端",
            "assignment_revision": 2,
        }],
    }
    runtime = ClusterRuntime()
    run_id = derive_cluster_run_id("conv_main", 5)
    runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=5,
            team=team,
        ),
        run_id,
    )

    class FakeStore:
        update_calls = 0

        def get_conversation_team(self, _conversation_id):
            return {"cluster_team": team, "cluster_team_revision": 5}

        def update_conversation_team(self, *_args, **_kwargs):
            self.update_calls += 1
            raise AssertionError("无变化配置不应写入")

    store = FakeStore()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: store)
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    result = await api_service.handle_cluster_mcp_tool(
        object(),
        run_id,
        "configure_team",
        payload,
    )

    assert result["data"]["changed"] is False
    assert result["data"]["run_id"] == run_id
    assert result["data"]["team_revision"] == 5
    assert store.update_calls == 0
    assert runtime.get_run(run_id).status == "running"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_configure_team_stale_run_returns_current_run_id(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    stale_run_id = derive_cluster_run_id("conv_main", 1)
    runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
        ),
        stale_run_id,
    )

    class Store:
        def get_conversation_team(self, _conversation_id):
            return {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 2}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: Store())
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            stale_run_id,
            "configure_team",
            {"mode": "extend", "roles": []},
        )

    assert exc_info.value.code == "cluster_team_changed"
    assert exc_info.value.data == {"run_id": derive_cluster_run_id("conv_main", 2)}


@pytest.mark.asyncio
async def test_configure_team_rejects_run_after_main_conversation_switch(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    run_id = derive_cluster_run_id("conv_old", 0)
    runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_old",
        ),
        run_id,
    )

    class Store:
        def get_conversation_team(self, _conversation_id):
            raise AssertionError("切换会话后不应读取或更新旧编组")

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: Store())
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_new")

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run_id,
            "configure_team",
            {"mode": "extend", "roles": []},
        )

    assert exc_info.value.code == "cluster_team_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "roles"),
    [
        ("replace", []),
        ("extend", [{"name": "补充", "responsibility": "补充检查"}]),
    ],
)
async def test_configure_team_changes_are_blocked_by_pending_task(monkeypatch, mode, roles) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    team = {
        "version": 1,
        "assignments": [
            {
                "agent_id": "one",
                "name": "分析",
                "responsibility": "检查后端",
                "assignment_revision": 1,
            }
        ],
    }
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team=team,
        )
    )
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "one", "message": "work"})
    runtime.create_agent_task(run.run_id, request)

    class FakeStore:
        def get_conversation_team(self, _conversation_id):
            return {"cluster_team": team, "cluster_team_revision": 1}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: FakeStore())
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run.run_id,
            "configure_team",
            {"mode": mode, "roles": roles},
        )

    assert exc_info.value.status == 409
    assert exc_info.value.code == "cluster_team_busy"


@pytest.mark.asyncio
async def test_configure_team_uses_current_capacity_after_run_started(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id=f"slot-{index}", name=f"Slot {index}") for index in range(1, 5)],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=4),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=0,
            team={"version": 1, "assignments": []},
        )
    )
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=2)

    class FakeStore:
        def get_conversation_team(self, _conversation_id):
            return {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 0}

        def update_conversation_team(self, *_args, **_kwargs):
            raise AssertionError("超过当前容量时不应写入")

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: FakeStore())
    monkeypatch.setattr(api_service, "_active_main_conversation_for_cluster_run", lambda *_args: "conv_main")

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run.run_id,
            "configure_team",
            {
                "mode": "extend",
                "roles": [
                    {"name": "一", "responsibility": "职责一"},
                    {"name": "二", "responsibility": "职责二"},
                    {"name": "三", "responsibility": "职责三"},
                ],
            },
        )

    assert exc_info.value.code == "cluster_team_full"


@pytest.mark.asyncio
async def test_main_chat_run_loads_persisted_conversation_team_before_start(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    team_state = {
        "cluster_team": {
            "version": 1,
            "assignments": [
                {
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 2,
                }
            ],
        },
        "cluster_team_revision": 7,
    }

    call_count = 0

    async def fake_run_cli_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("boom")
        return {"output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(api_service, "run_cli_chat", fake_run_cli_chat)
    async def fake_ensure_cluster_main_conversation(*_args, **_kwargs):
        return "conv_main", team_state

    monkeypatch.setattr(
        api_service,
        "_ensure_cluster_main_conversation",
        fake_ensure_cluster_main_conversation,
        raising=False,
    )

    await api_service.run_chat(object(), "main", 1, "hello")
    with pytest.raises(RuntimeError, match="boom"):
        await api_service.run_chat(object(), "main", 1, "again")

    [saved_run] = list(runtime._runs.values())
    assert saved_run.run_id == derive_cluster_run_id("conv_main", 7)
    assert saved_run.status == "running"
    assert saved_run.main_conversation_id == "conv_main"
    assert saved_run.team_revision == 7
    assert saved_run.team == team_state["cluster_team"]


@pytest.mark.asyncio
async def test_implicit_execution_mode_switch_retires_previous_children(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(alias="main", working_dir=str(tmp_path), cluster=BotClusterConfig(enabled=True))
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_cli",
        _persist_enabled=False,
    )

    class Store:
        def get_conversation(self, conversation_id):
            assert conversation_id == "conv_cli"
            return {"id": conversation_id, "native_provider": "codex"}

        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_native"
            return {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 0}

    store = Store()
    retired: list[str] = []
    cleared: list[str] = []

    def fake_create(_profile, current_session, **_kwargs):
        current_session.active_conversation_id = "conv_native"
        return store, "conv_native"

    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session))
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_create_agent_conversation", fake_create)
    monkeypatch.setattr(api_service, "_retire_cluster_child_conversations", lambda *_args: retired.append(_args[-1]))
    monkeypatch.setattr(
        api_service,
        "_clear_cluster_child_session_bindings",
        lambda *_args: cleared.append(_args[-1]),
    )

    conversation_id, _team = await api_service._ensure_cluster_main_conversation(
        object(),
        profile,
        "main",
        1,
        "native_agent",
    )

    assert conversation_id == "conv_native"
    assert retired == ["conv_cli"]
    assert cleared == ["conv_cli"]


@pytest.mark.asyncio
async def test_new_main_conversation_does_not_precreate_child_conversations(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One"), AgentProfile(id="two", name="Two")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=2),
    )
    sessions = {
        agent_id: SimpleNamespace(
            agent_id=agent_id,
            is_processing=False,
            active_conversation_id=None,
            codex_session_id=None,
            claude_session_id=None,
            claude_session_initialized=False,
            native_agent_session_id=None,
            native_agent_server_key=None,
            native_agent_run_id=None,
            _lock=threading.RLock(),
            persist=lambda: None,
        )
        for agent_id in ("main", "one", "two")
    }
    created_for: list[str] = []

    class FakeStore:
        def get_conversation(self, conversation_id):
            return {"id": conversation_id}

    def fake_get_session(_manager, _alias, _user_id, agent_id="main"):
        return profile, profile.get_agent(agent_id), sessions[agent_id]

    def fake_create(_profile, session, **_kwargs):
        created_for.append(session.agent_id)
        return FakeStore(), f"conv_{session.agent_id}"

    monkeypatch.setattr(api_service, "get_chat_session_for_alias", fake_get_session)
    monkeypatch.setattr(api_service, "_create_agent_conversation", fake_create)

    await api_service.create_conversation(object(), "main", 1)

    assert created_for == ["main"]


@pytest.mark.asyncio
async def test_cluster_task_lazily_prepares_child_and_injects_dynamic_role(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="Legacy", system_prompt="legacy prompt")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [
                    {
                        "agent_id": "one",
                        "name": "后端分析",
                        "responsibility": "检查并发边界",
                        "assignment_revision": 1,
                    }
                ],
            },
        )
    )
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "one", "message": "检查 runtime.py"})
    task = runtime.create_agent_task(run.run_id, request)
    prepared: list[tuple[str, int]] = []
    captured: dict[str, object] = {}

    def fake_prepare(_manager, live_run, live_task, *, force_new=False):
        prepared.append((live_run.main_conversation_id, live_task.assignment_revision))
        return "conv_child"

    async def fake_stream(*args, **kwargs):
        captured["message"] = args[3]
        captured["kwargs"] = kwargs
        yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_ensure_cluster_child_conversation", fake_prepare, raising=False)
    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream)
    api_service._CLUSTER_RUN_CONTROLS.clear()

    await api_service._run_cluster_agent_task(object(), run.run_id, task.task_id)

    assert prepared == [("conv_main", 1)]
    assert captured["message"] == (
        "<tcb_team_role>\n"
        "名称：后端分析\n"
        "职责：检查并发边界\n"
        "边界：只完成委派任务，不扩展职责，不自行创建子代理。\n"
        "</tcb_team_role>\n\n"
        "<tcb_delegated_task>\n"
        "检查 runtime.py\n"
        "</tcb_delegated_task>"
    )
    assert captured["kwargs"]["suppress_agent_prompt"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_ask_agent_rejects_stale_persisted_team_revision(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=".",
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [
                    {
                        "agent_id": "one",
                        "name": "分析",
                        "responsibility": "检查实现",
                        "assignment_revision": 1,
                    }
                ],
            },
        )
    )

    class StaleStore:
        def get_conversation_team(self, _conversation_id):
            return {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 2}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "_active_main_conversation_for_cluster_run",
        lambda *_args: "conv_main",
    )
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: StaleStore())

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            object(),
            run.run_id,
            "ask_agent",
            {"agent_id": "one", "message": "work"},
        )

    assert exc_info.value.status == 409
    assert exc_info.value.code == "cluster_run_changed"
    assert exc_info.value.data == {"run_id": derive_cluster_run_id("conv_main", 2)}
    assert runtime.build_task_status(run.run_id)["tasks"] == []


@pytest.mark.asyncio
async def test_cluster_resize_reports_blocking_conversations(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[
            AgentProfile(id="one", name="One"),
            AgentProfile(id="two", name="Two"),
            AgentProfile(id="three", name="Three"),
            AgentProfile(id="four", name="Four"),
        ],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=4),
    )

    class Manager:
        main_profile = profile
        managed_profiles = {}
        updated = False

        async def update_bot_cluster(self, _alias, _data):
            self.updated = True
            return _data

    class FakeStore:
        def list_cluster_resize_blockers(self, **_kwargs):
            return [
                {
                    "conversation_id": "conv_old",
                    "title": "旧会话",
                    "execution_mode": "cli",
                    "role_count": 1,
                    "outside_agent_ids": ["four"],
                    "minimum_size": 4,
                }
            ]

    manager = Manager()
    monkeypatch.setattr(api_service, "ChatStore", lambda _path: FakeStore())
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", ClusterRuntime())

    with pytest.raises(WebApiError) as exc_info:
        await api_service.update_cluster_config(
            manager,
            "main",
            {**profile.cluster.to_dict(), "max_parallel_agents": 2},
        )

    assert exc_info.value.status == 409
    assert exc_info.value.code == "cluster_resize_blocked"
    assert exc_info.value.data == {
        "code": "cluster_resize_blocked",
        "target_size": 2,
        "minimum_size": 4,
        "blockers": [
            {
                "conversation_id": "conv_old",
                "title": "旧会话",
                "execution_mode": "cli",
                "role_count": 1,
                "outside_agent_ids": ["four"],
                "minimum_size": 4,
            }
        ],
    }
    assert manager.updated is False


@pytest.mark.asyncio
async def test_configure_team_and_resize_share_bot_lock(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id=name, name=name.title()) for name in ("one", "two", "three", "four")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=4),
    )

    class Manager:
        main_profile = profile
        managed_profiles = {}

        async def update_bot_cluster(self, _alias, data):
            profile.cluster = BotClusterConfig(
                enabled=bool(data.get("enabled")),
                max_parallel_agents=int(data.get("max_parallel_agents") or 1),
            )
            return profile.cluster.to_dict()

    manager = Manager()
    store = api_service.ChatStore(tmp_path)
    conversation_id = store.create_conversation(
        bot_id=api_service.resolve_session_bot_id(manager, "main"),
        bot_alias="main",
        user_id=1,
        agent_id="main",
        cli_type="codex",
        working_dir=str(tmp_path),
        session_epoch=0,
        native_provider="codex",
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id=conversation_id,
            team_revision=0,
            team={"version": 1, "assignments": []},
        )
    )
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: store)
    monkeypatch.setattr(
        api_service,
        "_active_main_conversation_for_cluster_run",
        lambda *_args: conversation_id,
    )

    lock = api_service._CLUSTER_TEAM_SERVICE.bot_lock("main")
    await lock.acquire()
    configure_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        manager,
        run.run_id,
        "configure_team",
        {
            "mode": "extend",
            "roles": [
                {"name": "一", "responsibility": "职责一"},
                {"name": "二", "responsibility": "职责二"},
                {"name": "三", "responsibility": "职责三"},
            ],
        },
    ))
    await asyncio.sleep(0)
    resize_task = asyncio.create_task(api_service.update_cluster_config(
        manager,
        "main",
        {**profile.cluster.to_dict(), "max_parallel_agents": 2},
    ))
    await asyncio.sleep(0)
    lock.release()

    configured = await configure_task
    with pytest.raises(WebApiError) as exc_info:
        await resize_task

    assert configured["data"]["assignments"][-1]["agent_id"] == "three"
    assert exc_info.value.code == "cluster_resize_blocked"
    assert profile.cluster.max_parallel_agents == 4


@pytest.mark.asyncio
async def test_switching_main_conversation_is_blocked_while_child_task_is_pending(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_a",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_a",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [
                    {
                        "agent_id": "one",
                        "name": "分析",
                        "responsibility": "检查实现",
                        "assignment_revision": 1,
                    }
                ],
            },
        )
    )
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "one", "message": "work"})
    runtime.create_agent_task(run.run_id, request)

    class Store:
        def get_conversation(self, _conversation_id):
            return {
                "id": "conv_b",
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
            }

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session))
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: Store())
    monkeypatch.setattr(
        api_service,
        "_history_service_for_execution_mode",
        lambda *_args: SimpleNamespace(list_history=lambda *_args, **_kwargs: []),
    )

    with pytest.raises(WebApiError) as exc_info:
        await api_service.select_conversation(object(), "main", 1, "conv_b")

    assert exc_info.value.status == 409
    assert exc_info.value.code == "cluster_team_busy"


@pytest.mark.asyncio
async def test_deleting_main_conversation_is_blocked_while_child_task_is_pending(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_main",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "one", "message": "work"})
    runtime.create_agent_task(run.run_id, request)

    class Store:
        deleted = False

        def get_conversation(self, _conversation_id):
            return {
                "id": "conv_main",
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
            }

        def delete_conversation_by_id(self, _conversation_id):
            self.deleted = True

    store = Store()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session))
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "list_conversations", lambda *_args, **_kwargs: {"items": []})
    monkeypatch.setattr(
        api_service,
        "ChatFavoriteStore",
        lambda *_args: SimpleNamespace(delete_favorites_for_conversations=lambda *_args: 0),
    )

    with pytest.raises(WebApiError) as exc_info:
        await api_service.delete_conversation(object(), "main", 1, "conv_main")

    assert exc_info.value.code == "cluster_team_busy"
    assert store.deleted is False


@pytest.mark.parametrize("operation", ["delete", "archive"])
def test_deleted_or_archived_main_conversation_retires_stable_run(monkeypatch, tmp_path, operation) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(alias="main", working_dir=str(tmp_path), cluster=BotClusterConfig(enabled=True))
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_main",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run_id = derive_cluster_run_id("conv_main", 2)
    run = runtime.ensure_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=2,
        ),
        run_id,
    )

    class Store:
        changed = ""

        def get_conversation(self, _conversation_id):
            return {
                "id": "conv_main",
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
            }

        def get_conversation_team(self, _conversation_id):
            return {"cluster_team_revision": 2}

        def delete_conversation_by_id(self, _conversation_id):
            self.changed = "delete"

        def archive_conversation_by_id(self, _conversation_id):
            self.changed = "archive"

    store = Store()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_retire_cluster_child_conversations", lambda *_args: 0)
    monkeypatch.setattr(api_service, "_clear_cluster_child_session_bindings", lambda *_args: None)
    monkeypatch.setattr(api_service, "list_conversations", lambda *_args, **_kwargs: {"items": []})
    monkeypatch.setattr(
        api_service,
        "ChatFavoriteStore",
        lambda *_args: SimpleNamespace(delete_favorites_for_conversations=lambda *_args: 0),
    )

    if operation == "delete":
        api_service._delete_conversation_locked(object(), "main", 1, "conv_main")
    else:
        api_service._archive_conversation_locked(object(), "main", 1, "conv_main")

    assert store.changed == operation
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_parent_lock_prevents_implicit_switch_from_overtaking_ask_enqueue(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_cli",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_cli",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )

    class Store:
        def get_conversation(self, conversation_id):
            assert conversation_id == "conv_cli"
            return {"id": conversation_id, "native_provider": "codex"}

        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_cli"
            return {"cluster_team": run.team, "cluster_team_revision": 1}

    created: list[str] = []
    worker_release = asyncio.Event()

    def fake_create(_profile, _session, **_kwargs):
        created.append("conv_native")
        return Store(), "conv_native"

    async def fake_run_cluster_agent_task(*_args):
        await worker_release.wait()

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: Store())
    monkeypatch.setattr(api_service, "_create_agent_conversation", fake_create)
    monkeypatch.setattr(api_service, "_run_cluster_agent_task", fake_run_cluster_agent_task)
    api_service._CLUSTER_RUN_CONTROLS.clear()

    lock = api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_cli")
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_parent_lock() -> None:
        async with lock:
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_parent_lock())
    await holder_entered.wait()
    ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "ask_agent",
        {"agent_id": "one", "message": "work"},
    ))
    await asyncio.sleep(0)
    switch_task = asyncio.create_task(api_service._ensure_cluster_main_conversation(
        object(),
        profile,
        "main",
        1,
        "native_agent",
    ))
    await asyncio.sleep(0)

    assert ask_task.done() is False
    assert switch_task.done() is False

    release_holder.set()
    await holder
    await ask_task
    with pytest.raises(WebApiError) as exc_info:
        await switch_task

    assert exc_info.value.code == "cluster_team_busy"
    assert created == []
    worker_release.set()
    await asyncio.sleep(0)
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
async def test_ask_does_not_enqueue_after_implicit_switch_wins_parent_lock(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_cli",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_cli",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )

    class Store:
        def get_conversation(self, conversation_id):
            assert conversation_id == "conv_cli"
            return {"id": conversation_id, "native_provider": "codex"}

        def get_conversation_team(self, conversation_id):
            if conversation_id == "conv_native":
                return {"cluster_team": {"version": 1, "assignments": []}, "cluster_team_revision": 0}
            assert conversation_id == "conv_cli"
            return {"cluster_team": run.team, "cluster_team_revision": 1}

    store = Store()

    def fake_create(_profile, current_session, **_kwargs):
        current_session.active_conversation_id = "conv_native"
        return store, "conv_native"

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_create_agent_conversation", fake_create)
    monkeypatch.setattr(api_service, "_retire_cluster_child_conversations", lambda *_args: 0)
    monkeypatch.setattr(api_service, "_clear_cluster_child_session_bindings", lambda *_args: None)
    api_service._CLUSTER_RUN_CONTROLS.clear()

    lock = api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_cli")
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_parent_lock() -> None:
        async with lock:
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_parent_lock())
    await holder_entered.wait()
    switch_task = asyncio.create_task(api_service._ensure_cluster_main_conversation(
        object(),
        profile,
        "main",
        1,
        "native_agent",
    ))
    await asyncio.sleep(0)
    ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "ask_agent",
        {"agent_id": "one", "message": "work"},
    ))
    await asyncio.sleep(0)
    release_holder.set()
    await holder

    conversation_id, _team = await switch_task
    with pytest.raises(WebApiError) as exc_info:
        await ask_task

    assert conversation_id == "conv_native"
    assert exc_info.value.code == "cluster_team_changed"
    assert runtime.build_task_status(run.run_id)["tasks"] == []


@pytest.mark.asyncio
async def test_parent_lock_prevents_delete_from_overtaking_ask_enqueue(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_main",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_main",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )

    class Store:
        deleted = False

        def get_conversation(self, _conversation_id):
            return {
                "id": "conv_main",
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
            }

        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_main"
            return {"cluster_team": run.team, "cluster_team_revision": 1}

        def delete_conversation_by_id(self, _conversation_id):
            self.deleted = True

    store = Store()
    worker_release = asyncio.Event()

    async def fake_run_cluster_agent_task(*_args):
        await worker_release.wait()

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_run_cluster_agent_task", fake_run_cluster_agent_task)
    monkeypatch.setattr(api_service, "list_conversations", lambda *_args, **_kwargs: {"items": []})
    monkeypatch.setattr(
        api_service,
        "ChatFavoriteStore",
        lambda *_args: SimpleNamespace(delete_favorites_for_conversations=lambda *_args: 0),
    )
    api_service._CLUSTER_RUN_CONTROLS.clear()

    lock = api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_main")
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_parent_lock() -> None:
        async with lock:
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_parent_lock())
    await holder_entered.wait()
    ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        object(),
        run.run_id,
        "ask_agent",
        {"agent_id": "one", "message": "work"},
    ))
    await asyncio.sleep(0)
    delete_task = asyncio.create_task(api_service.delete_conversation(
        object(),
        "main",
        1,
        "conv_main",
    ))
    await asyncio.sleep(0)

    assert ask_task.done() is False
    assert delete_task.done() is False

    release_holder.set()
    await holder
    await ask_task
    with pytest.raises(WebApiError) as exc_info:
        await delete_task

    assert exc_info.value.code == "cluster_team_busy"
    assert store.deleted is False
    worker_release.set()
    await asyncio.sleep(0)
    api_service._CLUSTER_RUN_CONTROLS.clear()


def _explicit_lifecycle_race_setup(api_service, monkeypatch, tmp_path):
    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_old",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_old",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )

    class Store:
        archived = False
        deleted = False

        def get_conversation(self, conversation_id):
            return {
                "id": str(conversation_id),
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
                "cluster_parent_conversation_id": "",
            }

        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_old"
            return {"cluster_team": run.team, "cluster_team_revision": 1}

        def archive_conversation_by_id(self, conversation_id):
            assert conversation_id == "conv_old"
            self.archived = True
            return True

        def delete_conversation_by_id(self, conversation_id):
            assert conversation_id == "conv_old"
            self.deleted = True

    store = Store()
    created: list[str] = []
    retired: list[str] = []
    cleared: list[str] = []
    worker_release = asyncio.Event()

    def fake_create(_profile, current_session, **_kwargs):
        current_session.active_conversation_id = "conv_new"
        created.append("conv_new")
        return store, "conv_new"

    async def fake_run_cluster_agent_task(*_args):
        await worker_release.wait()

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_create_agent_conversation", fake_create)
    monkeypatch.setattr(api_service, "_run_cluster_agent_task", fake_run_cluster_agent_task)
    monkeypatch.setattr(api_service, "list_conversations", lambda *_args, **_kwargs: {"items": []})
    monkeypatch.setattr(
        api_service,
        "ChatFavoriteStore",
        lambda *_args: SimpleNamespace(delete_favorites_for_conversations=lambda *_args: 0),
    )
    monkeypatch.setattr(
        api_service,
        "_history_service_for_execution_mode",
        lambda *_args: SimpleNamespace(list_history=lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(
        api_service,
        "_retire_cluster_child_conversations",
        lambda *_args: retired.append(_args[-1]),
    )
    monkeypatch.setattr(
        api_service,
        "_clear_cluster_child_session_bindings",
        lambda *_args: cleared.append(_args[-1]),
    )
    api_service._CLUSTER_RUN_CONTROLS.clear()
    return SimpleNamespace(
        profile=profile,
        session=session,
        runtime=runtime,
        run=run,
        store=store,
        created=created,
        retired=retired,
        cleared=cleared,
        worker_release=worker_release,
    )


async def _run_explicit_lifecycle_operation(api_service, operation: str):
    if operation == "create":
        return await api_service.create_conversation(object(), "main", 1)
    if operation == "select":
        return await api_service.select_conversation(object(), "main", 1, "conv_target")
    if operation == "archive":
        return await api_service.archive_conversation(object(), "main", 1, "conv_old")
    if operation == "delete":
        return await api_service.delete_conversation(object(), "main", 1, "conv_old")
    raise AssertionError(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "select", "delete", "archive"])
async def test_cancelled_lifecycle_keeps_parent_lock_until_executor_worker_finishes(
    monkeypatch,
    tmp_path,
    operation,
) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_old",
        _persist_enabled=False,
    )
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def blocking_worker(*_args, **_kwargs):
        worker_started.set()
        assert release_worker.wait(timeout=2)
        worker_finished.set()
        return {"ok": True}

    worker_name = {
        "create": "_create_conversation_locked",
        "select": "_select_conversation_locked",
        "delete": "_delete_conversation_locked",
        "archive": "_archive_conversation_locked",
    }[operation]
    monkeypatch.setenv("TCB_ASYNC_CHAT_STORE", "true")
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, worker_name, blocking_worker)

    lifecycle_task = asyncio.create_task(_run_explicit_lifecycle_operation(api_service, operation))
    probe_acquired = asyncio.Event()
    probe_task = None
    try:
        assert await asyncio.wait_for(asyncio.to_thread(worker_started.wait, 2), timeout=2)
        lifecycle_task.cancel()
        await asyncio.sleep(0)
        lifecycle_task.cancel()

        async def acquire_parent_lock() -> None:
            async with api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_old"):
                probe_acquired.set()

        probe_task = asyncio.create_task(acquire_parent_lock())
        await asyncio.sleep(0.05)

        assert probe_acquired.is_set() is False
        assert lifecycle_task.done() is False
    finally:
        release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(lifecycle_task, timeout=2)
    assert worker_finished.is_set() is True
    assert probe_task is not None
    await asyncio.wait_for(probe_task, timeout=2)
    assert probe_acquired.is_set() is True


@pytest.mark.asyncio
async def test_cancelled_select_keeps_old_run_ask_blocked_until_worker_switch_finishes(
    monkeypatch,
    tmp_path,
) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_old",
        _persist_enabled=False,
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1,
            profile=profile,
            main_conversation_id="conv_old",
            team_revision=1,
            team={
                "version": 1,
                "assignments": [{
                    "agent_id": "one",
                    "name": "分析",
                    "responsibility": "检查实现",
                    "assignment_revision": 1,
                }],
            },
        )
    )
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    task_enqueued = asyncio.Event()
    agent_worker_release = asyncio.Event()

    def blocking_select(*_args, **_kwargs):
        worker_started.set()
        assert release_worker.wait(timeout=2)
        session.active_conversation_id = "conv_target"
        worker_finished.set()
        return {"conversation": {"id": "conv_target"}, "messages": []}

    class TeamStore:
        def get_conversation_team(self, conversation_id):
            assert conversation_id == "conv_old"
            return {"cluster_team": run.team, "cluster_team_revision": 1}

    original_create_agent_task = runtime.create_agent_task

    def create_agent_task(*args, **kwargs):
        task_enqueued.set()
        return original_create_agent_task(*args, **kwargs)

    async def fake_run_cluster_agent_task(*_args):
        await agent_worker_release.wait()

    monkeypatch.setenv("TCB_ASYNC_CHAT_STORE", "true")
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "get_profile_or_raise", lambda *_args: profile)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session),
    )
    monkeypatch.setattr(api_service, "_chat_store_for_cluster_run", lambda *_args: TeamStore())
    monkeypatch.setattr(api_service, "_select_conversation_locked", blocking_select)
    monkeypatch.setattr(api_service, "_run_cluster_agent_task", fake_run_cluster_agent_task)
    monkeypatch.setattr(runtime, "create_agent_task", create_agent_task)
    api_service._CLUSTER_RUN_CONTROLS.clear()

    select_task = asyncio.create_task(api_service.select_conversation(
        object(),
        "main",
        1,
        "conv_target",
    ))
    ask_task = None
    try:
        assert await asyncio.wait_for(asyncio.to_thread(worker_started.wait, 2), timeout=2)
        select_task.cancel()
        ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
            object(),
            run.run_id,
            "ask_agent",
            {"agent_id": "one", "message": "work"},
        ))
        await asyncio.sleep(0.05)

        assert task_enqueued.is_set() is False
        assert ask_task.done() is False
        assert select_task.done() is False
    finally:
        release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(select_task, timeout=2)
    assert worker_finished.is_set() is True
    assert ask_task is not None
    with pytest.raises(WebApiError) as exc_info:
        await asyncio.wait_for(ask_task, timeout=2)
    assert exc_info.value.code == "cluster_team_changed"
    assert task_enqueued.is_set() is False
    agent_worker_release.set()
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "select", "archive"])
async def test_ask_enqueue_wins_parent_lock_before_explicit_lifecycle_operation(
    monkeypatch,
    tmp_path,
    operation,
) -> None:
    import bot.web.api_service as api_service

    state = _explicit_lifecycle_race_setup(api_service, monkeypatch, tmp_path)
    lock = api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_old")
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_parent_lock() -> None:
        async with lock:
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_parent_lock())
    await holder_entered.wait()
    ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        object(),
        state.run.run_id,
        "ask_agent",
        {"agent_id": "one", "message": "work"},
    ))
    await asyncio.sleep(0)
    operation_task = asyncio.create_task(_run_explicit_lifecycle_operation(api_service, operation))
    await asyncio.sleep(0)

    assert ask_task.done() is False
    assert operation_task.done() is False

    release_holder.set()
    await holder
    await ask_task
    with pytest.raises(WebApiError) as exc_info:
        await operation_task

    assert exc_info.value.code == "cluster_team_busy"
    assert state.session.active_conversation_id == "conv_old"
    assert state.created == []
    assert state.store.archived is False
    state.worker_release.set()
    control = api_service._CLUSTER_RUN_CONTROLS.get(state.run.run_id)
    if control is not None:
        await asyncio.gather(*list(control.tasks), return_exceptions=True)
    api_service._CLUSTER_RUN_CONTROLS.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "select", "archive", "delete"])
async def test_explicit_lifecycle_operation_wins_parent_lock_before_old_run_ask(
    monkeypatch,
    tmp_path,
    operation,
) -> None:
    import bot.web.api_service as api_service

    state = _explicit_lifecycle_race_setup(api_service, monkeypatch, tmp_path)
    lock = api_service._CLUSTER_TEAM_SERVICE.conversation_lock("main", 1, "conv_old")
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_parent_lock() -> None:
        async with lock:
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_parent_lock())
    await holder_entered.wait()
    operation_task = asyncio.create_task(_run_explicit_lifecycle_operation(api_service, operation))
    await asyncio.sleep(0)
    ask_task = asyncio.create_task(api_service.handle_cluster_mcp_tool(
        object(),
        state.run.run_id,
        "ask_agent",
        {"agent_id": "one", "message": "work"},
    ))
    await asyncio.sleep(0)

    assert operation_task.done() is False
    assert ask_task.done() is False

    release_holder.set()
    await holder
    await operation_task
    with pytest.raises(WebApiError) as exc_info:
        await ask_task

    assert exc_info.value.code == "cluster_team_changed"
    assert state.runtime.build_task_status(state.run.run_id)["tasks"] == []
    assert state.cleared == ["conv_old"]


def test_cluster_child_cleanup_only_clears_matching_idle_child_after_cluster_is_disabled(monkeypatch) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        agents=[
            AgentProfile(id="related", name="Related"),
            AgentProfile(id="manual", name="Manual"),
            AgentProfile(id="busy", name="Busy"),
        ],
        cluster=BotClusterConfig(enabled=False, max_parallel_agents=1),
    )
    sessions = {}
    for agent_id in ("related", "manual", "busy"):
        session = SimpleNamespace(
            agent_id=agent_id,
            active_conversation_id=f"conv_{agent_id}",
            is_processing=agent_id == "busy",
            codex_session_id=f"codex-{agent_id}",
            claude_session_id=f"claude-{agent_id}",
            claude_session_initialized=True,
            native_agent_session_id=f"native-{agent_id}",
            native_agent_server_key=f"server-{agent_id}",
            native_agent_run_id=f"run-{agent_id}",
            _lock=threading.RLock(),
            persist_calls=0,
        )

        def persist(current=session) -> None:
            current.persist_calls += 1

        session.persist = persist
        sessions[agent_id] = session

    class Store:
        def __init__(self, agent_id):
            self.agent_id = agent_id

        def get_conversation(self, conversation_id):
            assert conversation_id == f"conv_{self.agent_id}"
            parent_id = "conv_parent" if self.agent_id in {"related", "busy"} else ""
            return {"id": conversation_id, "cluster_parent_conversation_id": parent_id}

    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda _manager, _alias, _user_id, agent_id="main": (
            profile,
            profile.get_agent(agent_id),
            sessions[agent_id],
        ),
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda session: Store(session.agent_id))

    api_service._clear_cluster_child_session_bindings(
        object(),
        "main",
        1,
        profile,
        "conv_parent",
    )

    related = sessions["related"]
    assert related.active_conversation_id is None
    assert related.codex_session_id is None
    assert related.claude_session_id is None
    assert related.claude_session_initialized is False
    assert related.native_agent_session_id is None
    assert related.native_agent_server_key is None
    assert related.native_agent_run_id is None
    assert related.persist_calls == 1

    for agent_id in ("manual", "busy"):
        preserved = sessions[agent_id]
        assert preserved.active_conversation_id == f"conv_{agent_id}"
        assert preserved.codex_session_id == f"codex-{agent_id}"
        assert preserved.native_agent_session_id == f"native-{agent_id}"
        assert preserved.persist_calls == 0


@pytest.mark.asyncio
async def test_switching_main_conversation_retires_previous_child_conversations(monkeypatch, tmp_path) -> None:
    import bot.web.api_service as api_service

    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="one", name="One")],
        cluster=BotClusterConfig(enabled=True, max_parallel_agents=1),
    )
    session = UserSession(
        bot_id=-1,
        bot_alias="main",
        user_id=1,
        working_dir=str(tmp_path),
        active_conversation_id="conv_a",
        _persist_enabled=False,
    )

    class Store:
        def get_conversation(self, _conversation_id):
            return {
                "id": "conv_b",
                "bot_id": -1,
                "user_id": 1,
                "agent_id": "main",
                "working_dir": str(tmp_path),
                "archived_at": "",
                "native_provider": "codex",
                "native_session_id": "",
            }

    retired: list[str] = []
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", ClusterRuntime())
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args, **_kwargs: (profile, profile.get_agent("main"), session))
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: Store())
    monkeypatch.setattr(api_service, "_clear_cluster_child_session_bindings", lambda *_args: None)
    monkeypatch.setattr(api_service, "_retire_cluster_child_conversations", lambda *_args: retired.append(_args[-1]), raising=False)
    monkeypatch.setattr(
        api_service,
        "_history_service_for_execution_mode",
        lambda *_args: SimpleNamespace(list_history=lambda *_args, **_kwargs: []),
    )

    await api_service.select_conversation(object(), "main", 1, "conv_b")

    assert retired == ["conv_a"]
