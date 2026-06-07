import asyncio

import pytest

from bot.cluster.config import AgentClusterConfig, BotClusterConfig
from bot.cluster.runtime import ClusterRuntime, ClusterRunRequest, ClusterToolError
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
            allow_unsafe_cli=True,
        )
    )

    assert run.run_id.startswith("clr_")
    assert run.status == "running"
    assert run.bot_alias == "main"
    assert run.mentions == [{"agent_id": "reviewer"}]
    assert run.allow_unsafe_cli is True
    assert runtime.get_run(run.run_id) is run


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


def test_cluster_runtime_ask_agent_uses_agent_timeout_by_default():
    profile = BotProfile(
        alias="main",
        cluster=BotClusterConfig(default_timeout_seconds=900),
        agents=[
            AgentProfile(
                id="tester",
                name="测试专家",
                cluster=AgentClusterConfig(timeout_seconds=180),
            )
        ],
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    default_request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    explicit_request = runtime.validate_ask_agent(
        run.run_id,
        {"agent_id": "tester", "message": "跑测试", "timeout_seconds": 240},
    )

    assert default_request.timeout_seconds == 180
    assert explicit_request.timeout_seconds == 240


def test_cluster_runtime_ask_agent_rejects_empty_agent_id():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))

    with pytest.raises(ClusterToolError) as exc_info:
        runtime.validate_ask_agent(run.run_id, {"message": "跑测试"})

    assert exc_info.value.code == "cluster_agent_not_found"


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


def test_cluster_runtime_appends_progress_and_final_messages():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    task = runtime.create_agent_task(run.run_id, request)

    runtime.append_agent_task_message(run.run_id, task.task_id, kind="progress", content="我先检查测试。")
    runtime.append_agent_task_message(run.run_id, task.task_id, kind="progress", content="我先检查测试。")
    runtime.complete_agent_task(run.run_id, task.task_id, "全部通过。")

    status = runtime.build_task_status(
        run.run_id,
        [task.task_id],
        include_output=True,
        include_messages=True,
        message_limit=10,
    )
    item = status["tasks"][0]
    assert item["message_count"] == 2
    assert item["latest_message_sequence"] == 2
    assert item["messages"] == [
        {
            "sequence": 1,
            "task_id": task.task_id,
            "agent_id": "tester",
            "kind": "progress",
            "content": "我先检查测试。",
            "created_at": item["messages"][0]["created_at"],
        },
        {
            "sequence": 2,
            "task_id": task.task_id,
            "agent_id": "tester",
            "kind": "final",
            "content": "全部通过。",
            "created_at": item["messages"][1]["created_at"],
        },
    ]


@pytest.mark.asyncio
async def test_cluster_runtime_wait_agent_messages_returns_next_message():
    profile = BotProfile(alias="main", agents=[AgentProfile(id="tester", name="测试专家")])
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile))
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "tester", "message": "跑测试"})
    task = runtime.create_agent_task(run.run_id, request)

    async def append_later():
        await asyncio.sleep(0.01)
        runtime.append_agent_task_message(run.run_id, task.task_id, kind="progress", content="开始处理。")
        await runtime.notify_agent_task_message(run.run_id)

    background = asyncio.create_task(append_later())
    result = await runtime.wait_agent_messages(run.run_id, after_sequence=0, wait_seconds=1)
    await background

    assert result["timed_out"] is False
    assert result["messages"][0]["agent_id"] == "tester"
    assert result["messages"][0]["task_id"] == task.task_id
    assert result["messages"][0]["kind"] == "progress"
    assert result["messages"][0]["content"] == "开始处理。"


