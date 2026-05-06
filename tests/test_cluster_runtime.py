import pytest

from bot.cluster_config import AgentClusterConfig
from bot.cluster_runtime import ClusterRuntime, ClusterRunRequest, ClusterToolError
from bot.models import AgentProfile, BotProfile


def test_cluster_runtime_starts_run():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="reviewer", name="代码审查")])
    runtime = ClusterRuntime()

    run = runtime.start_run(
        ClusterRunRequest(
            bot_alias="main",
            user_id=1001,
            profile=profile,
            mentions=[{"agent_id": "reviewer"}],
        )
    )

    assert run.run_id.startswith("clr_")
    assert run.status == "running"
    assert run.bot_alias == "main"
    assert run.mentions == [{"agent_id": "reviewer"}]
    assert runtime.get_run(run.run_id) is run


def test_cluster_runtime_status_lists_enabled_child_agents():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="reviewer", name="代码审查")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    status = runtime.build_status(run.run_id)

    assert status["run_id"] == run.run_id
    assert status["agents"][0]["id"] == "reviewer"
    assert status["agents"][0]["allow_write"] is False


def test_cluster_runtime_finish_removes_run():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="reviewer", name="代码审查")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    runtime.finish_run(run.run_id)

    assert runtime.get_run(run.run_id) is None


def test_cluster_runtime_rejects_main_agent_target():
    profile = BotProfile(alias="main")
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    with pytest.raises(ClusterToolError) as exc:
        runtime.validate_ask_agent(run.run_id, {"agent_id": "main", "message": "hi"})

    assert exc.value.code == "cluster_tool_forbidden"


def test_cluster_runtime_rejects_write_when_agent_disallows():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="reviewer", name="代码审查")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    with pytest.raises(ClusterToolError) as exc:
        runtime.validate_ask_agent(run.run_id, {"agent_id": "reviewer", "message": "hi", "allow_write": True})

    assert exc.value.code == "cluster_tool_forbidden"


def test_cluster_runtime_accepts_write_enabled_agent():
    profile = BotProfile(
        alias="main",
        agents=[
            AgentProfile(
                id="impl",
                name="实现",
                cluster=AgentClusterConfig(allow_cluster=True, allow_write=True),
            )
        ],
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    request = runtime.validate_ask_agent(
        run.run_id,
        {"agent_id": "impl", "message": "改 README", "allow_write": True, "model_tier": "high"},
    )

    assert request.agent_id == "impl"
    assert request.allow_write is True
    assert request.model_tier == "high"


def test_cluster_runtime_defaults_invalid_model_tier_to_medium():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="reviewer", name="代码审查")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    request = runtime.validate_ask_agent(
        run.run_id,
        {"agent_id": "reviewer", "message": "看一下", "model_tier": "invalid"},
    )

    assert request.model_tier == "medium"
