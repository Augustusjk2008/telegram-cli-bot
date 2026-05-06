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

    assert runtime.get_run(run.run_id) is run
    assert runtime.get_run(run.run_id).status == "completed"


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


def test_cluster_runtime_creates_agent_task():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(
        run.run_id,
        {"agent_id": "tester", "message": "跑测试", "model_tier": "low"},
    )

    task = runtime.create_agent_task(run.run_id, request)

    assert task.task_id.startswith("clt_")
    assert task.agent_id == "tester"
    assert task.status == "queued"
    status = runtime.build_task_status(run.run_id, [task.task_id], include_output=True)
    assert status["queued_count"] == 1
    assert status["tasks"][0]["task_id"] == task.task_id


def test_cluster_runtime_completes_agent_task():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    task = runtime.create_agent_task(run.run_id, request)

    runtime.mark_agent_task_running(run.run_id, task.task_id)
    runtime.complete_agent_task(run.run_id, task.task_id, "843 passed")

    status = runtime.build_task_status(run.run_id, [task.task_id], include_output=True)
    assert status["completed_count"] == 1
    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0]["output"] == "843 passed"


def test_cluster_runtime_fails_agent_task():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    task = runtime.create_agent_task(run.run_id, request)

    runtime.fail_agent_task(run.run_id, task.task_id, "boom")

    status = runtime.build_task_status(run.run_id, [task.task_id], include_output=True)
    assert status["failed_count"] == 1
    assert status["tasks"][0]["status"] == "failed"
    assert status["tasks"][0]["error"] == "boom"


def test_cluster_runtime_keeps_finished_run_with_tasks_for_polling():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    task = runtime.create_agent_task(run.run_id, request)

    runtime.finish_run(run.run_id, "completed")

    assert runtime.get_run(run.run_id) is not None
    status = runtime.build_task_status(run.run_id, [task.task_id], include_output=False)
    assert status["queued_count"] == 1
