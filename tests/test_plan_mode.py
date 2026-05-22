from __future__ import annotations

from pathlib import Path

import pytest

from bot.assistant.runtime import AssistantRunRequest
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_service import build_assistant_run_request, execute_plan, run_chat
from bot.web.plan_mode import (
    PLAN_MODE_TASK_MODE,
    build_plan_execution_prompt,
    build_plan_mode_prompt,
    extract_plan_draft,
    save_execution_plan,
    slugify_plan_title,
)


@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text('{"bots": []}', encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(temp_dir),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


def test_build_plan_mode_prompt_uses_plan_draft_protocol_without_file_instruction():
    prompt = build_plan_mode_prompt("分析一下怎么改")

    assert PLAN_MODE_TASK_MODE == "plan"
    assert "分析一下怎么改" in prompt
    assert "<PLAN_DRAFT>" in prompt
    assert "</PLAN_DRAFT>" in prompt
    assert "不要修改文件" in prompt
    assert "不要创建文件" in prompt
    assert "会改变项目状态的命令" in prompt
    assert "写的 plan 应详细、可执行" in prompt
    assert "docs/plan" not in prompt


def test_plan_mode_cluster_prompt_requires_waiting_for_children():
    prompt = build_plan_mode_prompt("拆任务分析", cluster_active=True)

    assert "必须等待所有子任务完成或明确超时" in prompt
    assert "PLAN_DRAFT" in prompt


def test_extract_plan_draft_returns_first_complete_block():
    text = "先问个问题\n<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>\n后续"

    assert extract_plan_draft(text) == "# 方案\n- 改 A"


def test_extract_plan_draft_ignores_incomplete_block():
    assert extract_plan_draft("<PLAN_DRAFT>\n# 未完成") == ""


def test_slugify_plan_title_keeps_ascii_and_limits_length():
    assert slugify_plan_title("修复 Chat 自动滚动!!") == "chat"
    assert slugify_plan_title("Plan Mode v2") == "plan-mode-v2"


def test_save_execution_plan_writes_docs_plan(tmp_path: Path):
    saved = save_execution_plan(tmp_path, "# 执行方案\n\n- step", title="Plan Mode v2")

    assert saved.relative_path.startswith("docs/plan/")
    assert saved.relative_path.endswith("-plan-mode-v2.md")
    assert (tmp_path / saved.relative_path).read_text(encoding="utf-8") == "# 执行方案\n\n- step\n"


def test_build_plan_execution_prompt_references_saved_plan():
    prompt = build_plan_execution_prompt("docs/plan/2026-05-21-1010-plan-mode.md")

    assert "请按方案执行" in prompt
    assert "docs/plan/2026-05-21-1010-plan-mode.md" in prompt
    assert "先阅读方案和相关代码" in prompt
    assert "不要回到 Plan Mode" in prompt


def test_build_assistant_run_request_preserves_plan_mode():
    request = build_assistant_run_request("main", 1001, "先出方案", task_mode="plan")

    assert isinstance(request, AssistantRunRequest)
    assert request.task_mode == "plan"
    assert request.text == "先出方案"


def test_plan_prompt_wrapper_is_used_for_cli_request():
    wrapped = build_plan_mode_prompt("先出方案", cluster_active=True)

    assert "先出方案" in wrapped
    assert "PLAN_DRAFT" in wrapped
    assert "必须等待所有子任务完成或明确超时" in wrapped


@pytest.mark.asyncio
async def test_run_chat_passes_plan_request_to_cli(monkeypatch: pytest.MonkeyPatch, web_manager):
    captured: dict[str, object] = {}

    async def fake_run_cli_chat(_manager, alias, user_id, text, **kwargs):
        captured["alias"] = alias
        captured["user_id"] = user_id
        captured["text"] = text
        captured["request"] = kwargs.get("request")
        return {"output": "ok", "message": {"id": "m1", "content": "ok"}}

    monkeypatch.setattr("bot.web.api_service.run_cli_chat", fake_run_cli_chat)

    await run_chat(web_manager, "main", 1001, "先出方案", task_mode="plan")

    assert captured["alias"] == "main"
    assert captured["user_id"] == 1001
    assert captured["text"] == "先出方案"
    request = captured["request"]
    assert isinstance(request, AssistantRunRequest)
    assert request.task_mode == "plan"
    assert request.text == "先出方案"


def test_execute_plan_saves_plan_and_creates_fresh_conversation(web_manager):
    data = execute_plan(
        web_manager,
        "main",
        1001,
        "# 方案\n\n- 改代码",
        title="Plan Mode",
    )

    assert data["plan_path"].startswith("docs/plan/")
    assert data["conversation"]["active"] is True
    assert data["execution_message"].startswith("请按方案执行")
    assert data["plan_path"] in data["execution_message"]
