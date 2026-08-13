from types import SimpleNamespace

from bot.prompts import render_prompt
from bot.web.api_service import _apply_cluster_prompt


def test_cluster_prompt_requires_self_contained_delegation_context() -> None:
    prompt = render_prompt(
        "cluster_mode",
        run_id="run-123",
        mentioned_agents="worker",
        write_guidance="本轮仅主 agent 可写。",
    )

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


def test_cluster_prompt_encourages_write_for_implementation_tasks_when_allowed() -> None:
    profile = SimpleNamespace(cluster=SimpleNamespace(enabled=True, write_policy="all_agents"))

    prompt = _apply_cluster_prompt(profile, "完成这个实现", cluster_run_id="run-123")

    assert "本轮允许子 agent 写入" in prompt
    assert "实现、修复等需要修改文件的任务" in prompt
    assert "allow_write=true" in prompt
    assert "分析、调研、审查任务保持只读" in prompt


def test_cluster_prompt_keeps_child_tasks_read_only_when_write_is_disallowed() -> None:
    profile = SimpleNamespace(cluster=SimpleNamespace(enabled=True, write_policy="main_only"))

    prompt = _apply_cluster_prompt(profile, "完成这个实现", cluster_run_id="run-123")

    assert "本轮仅主 agent 可写" in prompt
    assert "不要设置 allow_write=true" in prompt
