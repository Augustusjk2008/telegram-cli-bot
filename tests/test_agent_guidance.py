from __future__ import annotations

from pathlib import Path

from bot.native_agent.service import SOLO_NATIVE_AGENT_SYSTEM_PROMPT
from bot.prompts import render_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_root_agent_guidance_stays_lean_and_durable() -> None:
    guidance = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert len(guidance) <= 5000
    assert "当前仓库版本" not in guidance
    assert "文档最后更新" not in guidance
    assert "当前 agent 工作目录固定" not in guidance
    assert "不得主动关闭、重启、kill 当前 agent 自身" in guidance
    assert "python -m pytest tests -q" in guidance


def test_orbit_maintenance_skill_routes_details_to_references() -> None:
    skill_root = ROOT / ".agents" / "skills" / "orbit-maintenance"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")

    assert "TODO" not in skill
    assert len(skill) <= 4000
    for name in (
        "native-agent.md",
        "transfer-gateway.md",
        "plugin-system.md",
        "release-runtime.md",
    ):
        assert (skill_root / "references" / name).is_file()
        assert name in skill


def test_solo_native_agent_prompt_keeps_only_execution_contract() -> None:
    prompt = SOLO_NATIVE_AGENT_SYSTEM_PROMPT

    assert len(prompt.splitlines()) <= 4
    assert "Plan Mode" in prompt
    assert "verification" in prompt
    assert "blocked" in prompt
    assert "Be concise" not in prompt
    assert "Keep final replies concise" not in prompt


def test_cluster_prompts_are_routing_rules_not_tool_manuals() -> None:
    enabled = render_prompt("cluster_mode", run_id="run-123", mentioned_agents="reviewer")
    disabled = render_prompt("cluster_disabled")

    assert len(enabled) <= 1200
    assert "run-123" in enabled
    assert "reviewer" in enabled
    assert "tcb-cluster" in enabled
    assert "wait_agent_messages" in enabled or "poll_agent_tasks" in enabled
    assert "timeout_seconds" not in enabled
    assert "after_sequence" not in enabled
    assert "子 agent" in disabled
    assert "其它并行" not in disabled
