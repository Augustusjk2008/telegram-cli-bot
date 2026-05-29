from __future__ import annotations

import pytest

from bot.prompts import PromptRenderError, load_prompt_template, render_prompt


def test_load_prompt_template_reads_markdown_body():
    text = load_prompt_template("plan_mode")

    assert "Plan Mode" in text
    assert "{user_text}" in text
    assert "不要切换、请求或使用 Claude Code 自带 Plan Mode" in text
    assert "优先于 Claude Code 自带 Plan Mode" in text


def test_render_prompt_substitutes_variables_without_stripping_newlines():
    text = render_prompt(
        "plan_execution",
        relative_plan_path="docs/plan/demo.md",
    )

    assert text.startswith("请按方案执行。方案文件：docs/plan/demo.md")
    assert "\n\n要求：\n" in text
    assert "不要使用 Claude Code 自带 Plan Mode" in text


def test_render_prompt_raises_clear_error_for_missing_variable():
    with pytest.raises(PromptRenderError, match="prompt 缺少变量: user_text"):
        render_prompt(
            "plan_mode",
            plan_draft_open="<PLAN_DRAFT>",
            plan_draft_close="</PLAN_DRAFT>",
            cluster_rule="",
        )
