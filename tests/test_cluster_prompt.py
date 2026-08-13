from bot.prompts import render_prompt


def test_cluster_prompt_requires_self_contained_delegation_context() -> None:
    prompt = render_prompt("cluster_mode", run_id="run-123", mentioned_agents="worker")

    assert "集群可用不代表必须委派" in prompt
    assert "简单、不可并行或委派成本更高" in prompt
    assert "configure_team" in prompt
    assert "extend" in prompt
    assert "replace" in prompt
    assert "只有用户明确要求" in prompt
    assert "满编" in prompt
    assert "子 agent 不继承主 agent 当前对话" in prompt
    assert "委派消息必须自包含" in prompt
    assert "文件路径" in prompt
    assert "重复工作" in prompt
    assert "同一文件" in prompt
    assert "当前 run_id: run-123" in prompt
    assert "显式提及" not in prompt
    assert "wait_agent_messages" in prompt
    assert "poll_agent_tasks" in prompt
