from __future__ import annotations

from pathlib import Path

import pytest

from bot.assistant.runtime import AssistantRunRequest
from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_service import build_assistant_run_request, execute_plan, run_chat, run_cli_chat, stream_chat
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
    assert "优先于 Claude Code 自带 Plan Mode" in prompt
    assert "写的 plan 应详细、可执行" in prompt
    assert "docs/plan" not in prompt


def test_extract_plan_draft_returns_first_complete_block():
    text = "先问个问题\n<PLAN_DRAFT>\n# 方案\n- 改 A\n</PLAN_DRAFT>\n后续"

    assert extract_plan_draft(text) == "# 方案\n- 改 A"


def test_save_execution_plan_writes_docs_plan(tmp_path: Path):
    saved = save_execution_plan(tmp_path, "# 执行方案\n\n- step", title="Plan Mode v2")

    assert saved.relative_path.startswith("docs/plan/")
    assert saved.relative_path.endswith("-plan-mode-v2.md")
    assert (tmp_path / saved.relative_path).read_text(encoding="utf-8") == "# 执行方案\n\n- step\n"


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
    assert captured["user_id"] == chat_session_user_id(None)
    assert captured["text"] == "先出方案"
    request = captured["request"]
    assert isinstance(request, AssistantRunRequest)
    assert request.task_mode == "plan"
    assert request.text == "先出方案"


@pytest.mark.asyncio
async def test_run_chat_passes_plan_prompt_to_native_agent(monkeypatch: pytest.MonkeyPatch, web_manager):
    web_manager.main_profile.supported_execution_modes = ["cli", "native_agent"]
    captured: dict[str, object] = {}

    class FakeNativeService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "ok", "message": {"id": "m1", "content": "ok"}}

    monkeypatch.setattr("bot.web.api_service.get_native_agent_service", lambda: FakeNativeService())

    await run_chat(web_manager, "main", 1001, "先出原生方案", task_mode="plan", execution_mode="native_agent")

    assert captured["user_text"] == "先出原生方案"
    prompt_text = str(captured["prompt_text"])
    assert "<PLAN_DRAFT>" in prompt_text
    assert "</PLAN_DRAFT>" in prompt_text
    assert "先出原生方案" in prompt_text


@pytest.mark.asyncio
async def test_stream_chat_passes_plan_prompt_to_native_agent(monkeypatch: pytest.MonkeyPatch, web_manager):
    web_manager.main_profile.supported_execution_modes = ["cli", "native_agent"]
    captured: dict[str, object] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {
                "type": "done",
                "output": "ok",
                "message": {"id": "m1", "role": "assistant", "content": "ok", "meta": {}},
                "elapsed_seconds": 0,
                "returncode": 0,
            }

    monkeypatch.setattr("bot.web.api_service.get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in stream_chat(
            web_manager,
            "main",
            1001,
            "先流式原生方案",
            task_mode="plan",
            execution_mode="native_agent",
        )
    ]

    assert events[-1]["type"] == "done"
    prompt_text = str(captured["prompt_text"])
    assert "<PLAN_DRAFT>" in prompt_text
    assert "</PLAN_DRAFT>" in prompt_text
    assert "先流式原生方案" in prompt_text


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


def test_execute_plan_can_create_native_agent_conversation(web_manager):
    web_manager.main_profile.supported_execution_modes = ["cli", "native_agent"]
    web_manager.main_profile.default_execution_mode = "cli"

    data = execute_plan(
        web_manager,
        "main",
        1001,
        "# 原生方案\n\n- 改代码",
        title="Native Plan",
        execution_mode="native_agent",
    )

    assert data["conversation"]["execution_mode"] == "native_agent"
