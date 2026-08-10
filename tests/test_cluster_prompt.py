from bot.prompts import render_prompt


def test_cluster_prompt_requires_self_contained_delegation_context() -> None:
    prompt = render_prompt("cluster_mode", run_id="run-123", mentioned_agents="worker")

    assert "子 agent 不继承主 agent 当前对话" in prompt
    assert "委派消息必须自包含" in prompt
    assert "文件路径" in prompt
