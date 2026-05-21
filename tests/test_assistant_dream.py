from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.assistant.dream.service import (
    AssistantDreamConfig,
    apply_dream_result,
    prepare_dream_prompt,
)
from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.memory.recall import recall_assistant_memories


class _FakeHistoryService:
    def __init__(self, items):
        self.items = items

    def list_history(self, profile, session, limit=50):
        return list(self.items)[:limit]


def test_prepare_dream_prompt_uses_recent_history_and_captures(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    (workdir / "AGENTS.md").write_text("agent rules\n", encoding="utf-8")
    (workdir / "CLAUDE.md").write_text("claude rules\n", encoding="utf-8")
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text("- 当前目标\n", encoding="utf-8")

    recent_time = datetime.now(UTC).isoformat()
    old_time = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    history_service = _FakeHistoryService(
        [
            {"role": "user", "content": "最近要把 dream 跑起来", "created_at": recent_time},
            {"role": "assistant", "content": "这条太旧，不该进入上下文", "created_at": old_time},
        ]
    )
    capture_payload = {
        "id": "cap_1",
        "created_at": recent_time,
        "user_text": "用户提醒要后台静默执行",
        "assistant_text": "收到，准备设计 dream。",
    }
    (home.root / "inbox" / "captures" / "cap_1.json").write_text(
        json.dumps(capture_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    prepared = prepare_dream_prompt(
        home,
        profile=SimpleNamespace(alias="assistant1"),
        session=SimpleNamespace(),
        history_service=history_service,
        config=AssistantDreamConfig(prompt="根据近期工作做自我完善", lookback_hours=24, history_limit=10, capture_limit=5),
        visible_text="每天早上做一次 dream",
    )

    assert "根据近期工作做自我完善" in prepared.prompt_text
    assert "最近要把 dream 跑起来" in prepared.prompt_text
    assert "这条太旧，不该进入上下文" not in prepared.prompt_text
    assert "用户提醒要后台静默执行" in prepared.prompt_text
    assert "不要输出 JSON" in prepared.prompt_text
    assert "<DREAM_SUMMARY>" in prepared.prompt_text
    assert "程序会把这些块组装回原协议对象" in prepared.prompt_text
    assert "working_memory 只接受 current_goal/open_loops/user_prefs/recent_summary 四类内容" in prepared.prompt_text
    assert prepared.context_stats["history_count"] == 1
    assert prepared.context_stats["capture_count"] == 1


def test_prepare_dream_prompt_deduplicates_matching_protocol_files(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    shared_protocol = "# Runtime\n- 使用中文\n"
    (workdir / "AGENTS.md").write_text(shared_protocol, encoding="utf-8")
    (workdir / "CLAUDE.md").write_text(shared_protocol, encoding="utf-8")
    home = bootstrap_assistant_home(workdir)

    prepared = prepare_dream_prompt(
        home,
        profile=SimpleNamespace(alias="assistant1"),
        session=SimpleNamespace(),
        history_service=_FakeHistoryService([]),
        config=AssistantDreamConfig(prompt="根据近期工作做自我完善", lookback_hours=24, history_limit=10, capture_limit=5),
        visible_text="daily dream",
    )

    assert "内容相同，仅展开 AGENTS.md" in prepared.prompt_text
    assert "AGENTS.md sha256:" in prepared.prompt_text
    assert "CLAUDE.md sha256:" in prepared.prompt_text
    assert "### AGENTS.md\n# Runtime\n- 使用中文" in prepared.prompt_text
    assert "### CLAUDE.md\n# Runtime\n- 使用中文" not in prepared.prompt_text


def test_prepare_dream_prompt_includes_protocol_diff_when_files_differ(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    (workdir / "AGENTS.md").write_text("- 使用中文\n- 少废话\n", encoding="utf-8")
    (workdir / "CLAUDE.md").write_text("- 使用中文\n- 可详细解释\n", encoding="utf-8")
    home = bootstrap_assistant_home(workdir)

    prepared = prepare_dream_prompt(
        home,
        profile=SimpleNamespace(alias="assistant1"),
        session=SimpleNamespace(),
        history_service=_FakeHistoryService([]),
        config=AssistantDreamConfig(prompt="根据近期工作做自我完善", lookback_hours=24, history_limit=10, capture_limit=5),
        visible_text="daily dream",
    )

    assert "### AGENTS.md\n- 使用中文\n- 少废话" in prepared.prompt_text
    assert "### CLAUDE.md 相对 AGENTS.md 的差异" in prepared.prompt_text
    assert "--- AGENTS.md" in prepared.prompt_text
    assert "+++ CLAUDE.md" in prepared.prompt_text
    assert "-- 少废话" in prepared.prompt_text
    assert "+- 可详细解释" in prepared.prompt_text


def test_prepare_dream_prompt_includes_managed_bot_context(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    prepared = prepare_dream_prompt(
        home,
        profile=SimpleNamespace(alias="assistant1"),
        session=SimpleNamespace(),
        history_service=_FakeHistoryService([]),
        config=AssistantDreamConfig(prompt="根据所有 bot 做自我整理", lookback_hours=24, history_limit=10, capture_limit=5),
        visible_text="daily dream",
        managed_context_text="### team2\n- history_count: 1\n#### 最近聊天\n- team2 最近修了 UI",
        managed_context_stats={
            "managed_bot_count": 1,
            "managed_history_count": 1,
            "managed_capture_count": 0,
            "managed_error_count": 0,
        },
    )

    assert "## 其它 managed bots 快照" in prepared.prompt_text
    assert "### team2" in prepared.prompt_text
    assert "team2 最近修了 UI" in prepared.prompt_text
    assert prepared.context_stats["managed_bot_count"] == 1
    assert prepared.context_stats["managed_history_count"] == 1
    assert prepared.context_stats["managed_capture_count"] == 0
    assert prepared.context_stats["managed_error_count"] == 0


def test_prepare_dream_prompt_includes_incident_cooldown_rule(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    prepared = prepare_dream_prompt(
        home,
        profile=SimpleNamespace(alias="assistant1"),
        session=SimpleNamespace(),
        history_service=_FakeHistoryService([]),
        config=AssistantDreamConfig(prompt="根据近期工作做自我完善", lookback_hours=24, history_limit=10, capture_limit=5),
        visible_text="daily dream",
    )

    assert "故障降温" in prepared.prompt_text
    assert "把对应排查项从 open_loops 删除" in prepared.prompt_text
    assert "recent_summary 留简短事实：时间、状态、直接错误、用户归因" in prepared.prompt_text


def test_apply_dream_result_writes_working_memory_knowledge_proposal_and_audit(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    raw_output = """
<DREAM_SUMMARY>
完成 dream 整理
</DREAM_SUMMARY>

<DREAM_CURRENT_GOAL>
- 补齐 dream 后台执行闭环
</DREAM_CURRENT_GOAL>

<DREAM_OPEN_LOOPS>
- 确认 cron 配置时间
</DREAM_OPEN_LOOPS>

<DREAM_RECENT_SUMMARY>
- 已实现 dream 方案并补测试
</DREAM_RECENT_SUMMARY>

<DREAM_KNOWLEDGE>
bucket: self-improving-agent
title: dream-rtk-lesson
- PowerShell cmdlet 需要用 rtk pwsh -Command 包装
</DREAM_KNOWLEDGE>

<DREAM_PROPOSAL>
kind: rule
title: 后续评审 dream 默认配置
- 保持 silent 为默认投递方式
</DREAM_PROPOSAL>
""".strip()

    result = apply_dream_result(
        home,
        raw_output=raw_output,
        visible_text="执行 dream",
        prompt_excerpt="dream prompt excerpt",
        context_stats={"history_count": 2, "capture_count": 1},
        run_id="run_123",
        job_id="daily_dream",
        scheduled_at="2026-04-20T09:00:00+08:00",
        context_user_id=1001,
        synthetic_user_id=-42,
    )

    assert result.summary == "完成 dream 整理"
    assert (home.root / "memory" / "working" / "current_goal.md").read_text(encoding="utf-8").strip() == "- 补齐 dream 后台执行闭环"
    assert (home.root / "memory" / "working" / "open_loops.md").read_text(encoding="utf-8").strip() == "- 确认 cron 配置时间"
    knowledge_files = list((home.root / "memory" / "knowledge" / "self-improving-agent").glob("*.md"))
    assert len(knowledge_files) == 1
    assert "rtk pwsh -Command" in knowledge_files[0].read_text(encoding="utf-8")
    proposal_files = list((home.root / "proposals").glob("*.json"))
    assert len(proposal_files) == 1
    proposal = json.loads(proposal_files[0].read_text(encoding="utf-8"))
    assert proposal["kind"] == "rule"
    assert result.proposal_id == proposal["id"]
    assert Path(result.audit_path).is_file()


def test_apply_dream_result_accepts_legacy_schema_and_normalizes_it(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    raw_output = """
这轮 dream 完成了整理。

<DREAM_RESULT>{
  "summary": "完成 dream 整理",
  "working_memory": {
    "current_goal": ["补齐 dream 后台执行闭环"]
  },
  "knowledge_entries": [
    {
      "title": "长书播客稿先卡片化压缩，不整本直写",
      "type": "workflow",
      "content": ["长书先做切块，再汇总成章卡和全书卡。"],
      "evidence": ["用户确认主体只抓 1-3 个命题。"]
    }
  ],
  "proposal": {
    "title": "长书转播客文案 skill v1",
    "type": "skill_proposal",
    "reason": "需把范文证据转成可执行 skill。",
    "scope": ["输入：书全文或章节、目标时长、可选命题、范文样本。"],
    "blocked_by": ["待用户提供满意范文样本。"]
  }
}</DREAM_RESULT>
""".strip()

    result = apply_dream_result(
        home,
        raw_output=raw_output,
        visible_text="执行 dream",
        prompt_excerpt="dream prompt excerpt",
        context_stats={"history_count": 2, "capture_count": 1},
        run_id="run_legacy",
        job_id="daily_dream",
        scheduled_at="2026-04-20T09:00:00+08:00",
        context_user_id=1001,
        synthetic_user_id=-42,
    )

    assert result.summary == "完成 dream 整理"
    knowledge_files = list((home.root / "memory" / "knowledge" / "self-improving-agent").glob("*.md"))
    assert len(knowledge_files) == 1
    knowledge_text = knowledge_files[0].read_text(encoding="utf-8")
    assert "长书先做切块" in knowledge_text
    assert "证据：" in knowledge_text
    proposal_files = list((home.root / "proposals").glob("*.json"))
    assert len(proposal_files) == 1
    proposal = json.loads(proposal_files[0].read_text(encoding="utf-8"))
    assert proposal["kind"] == "skill_proposal"
    assert "Reason" in proposal["body"]
    assert "Blocked By" in proposal["body"]


def test_apply_dream_result_rejects_invalid_working_memory_key_and_still_writes_audit(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    raw_output = """
<DREAM_RESULT>{
  "summary": "失败样例",
  "working_memory": {
    "bad_key": ["不允许写这里"]
  },
  "knowledge_entries": [],
  "proposal": null
}</DREAM_RESULT>
""".strip()

    with pytest.raises(RuntimeError):
        apply_dream_result(
            home,
            raw_output=raw_output,
            visible_text="执行 dream",
            prompt_excerpt="dream prompt excerpt",
            context_stats={"history_count": 0, "capture_count": 0},
            run_id="run_456",
            job_id="daily_dream",
            scheduled_at="2026-04-20T09:00:00+08:00",
            context_user_id=1001,
            synthetic_user_id=-42,
        )

    audit_files = list((home.root / "audit" / "dream").glob("*.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert "bad_key" in audit_payload["error"]
    assert not (home.root / "memory" / "working" / "current_goal.md").exists()


def test_apply_dream_result_rejects_malformed_dream_blocks_and_still_writes_audit(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    raw_output = """
<DREAM_CURRENT_GOAL>
- 补齐 dream 后台执行闭环
</DREAM_CURRENT_GOAL>
""".strip()

    with pytest.raises(RuntimeError):
        apply_dream_result(
            home,
            raw_output=raw_output,
            visible_text="执行 dream",
            prompt_excerpt="dream prompt excerpt",
            context_stats={"history_count": 0, "capture_count": 0},
            run_id="run_bad_blocks",
            job_id="daily_dream",
            scheduled_at="2026-04-20T09:00:00+08:00",
            context_user_id=1001,
            synthetic_user_id=-42,
        )

    audit_files = list((home.root / "audit" / "dream").glob("*.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert "<DREAM_SUMMARY>" in audit_payload["error"]


def test_apply_dream_result_indexes_knowledge_entries(temp_dir: Path):
    workdir = temp_dir / "assistant-repo"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    raw_output = """
<DREAM_SUMMARY>
沉淀 Vivado 知识
</DREAM_SUMMARY>

<DREAM_KNOWLEDGE>
bucket: vivado
title: Vivado generated clock
- generated_clock 需要检查主时钟、派生源和约束覆盖。
</DREAM_KNOWLEDGE>
""".strip()

    apply_dream_result(
        home,
        raw_output=raw_output,
        visible_text="",
        prompt_excerpt="",
        context_stats={},
        run_id="dream_knowledge_index",
        job_id="daily_dream",
        scheduled_at="2026-04-27T02:00:00+00:00",
        context_user_id=1001,
        synthetic_user_id=0,
    )

    recall = recall_assistant_memories(home, user_id=1001, user_text="generated_clock 约束")

    assert "Vivado generated clock" in recall.prompt_block
    assert "generated_clock" in recall.prompt_block
