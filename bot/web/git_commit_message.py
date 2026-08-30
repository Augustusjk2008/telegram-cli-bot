"""Git commit message 生成 helper。"""

from __future__ import annotations

import copy
import re
from typing import Any

from bot.cli_params import get_default_params, get_params_schema, normalize_cli_model_options
from bot.config import CLI_MODEL_OPTIONS
from bot.models import BotProfile, GitCommitMessageCliConfig
from bot.prompts import render_prompt

DIFF_CHAR_LIMIT = 40 * 1024
COMMIT_MESSAGE_RE = re.compile(r"<COMMIT_MESSAGE>\s*(.*?)\s*</COMMIT_MESSAGE>", re.S)
DIFF_SECTION_RE = re.compile(r"(?m)^diff --git ")
DIFF_SECTION_MIN_CHARS = 160


def build_git_commit_cli_config(profile: BotProfile, config: GitCommitMessageCliConfig) -> dict[str, Any]:
    resolved_cli_type = str(config.cli_type or profile.cli_type or "").strip().lower()
    schema = _apply_cli_model_options(get_params_schema(resolved_cli_type))
    return {
        "cli_type": resolved_cli_type,
        "cli_path": str(config.cli_path or "").strip(),
        "params": copy.deepcopy(config.cli_params.get_params(resolved_cli_type)),
        "defaults": get_default_params(resolved_cli_type),
        "schema": schema,
    }


def build_commit_message_prompt(
    *,
    status_text: str,
    diff_text: str,
    use_staged_diff: bool,
    diff_truncated: bool,
) -> str:
    draft_notice = "" if use_staged_diff else "注意：当前无 staged 改动，本次仅基于未暂存/未跟踪内容生成草稿。\n"
    truncate_notice = "注意：Git diff 已截断。\n" if diff_truncated else ""
    return render_prompt(
        "git_commit_message",
        draft_notice=draft_notice,
        truncate_notice=truncate_notice,
        status_text=status_text.strip() or "(empty)",
        diff_text=diff_text.strip() or "(empty)",
    )


def truncate_diff_text(text: str, *, limit: int = DIFF_CHAR_LIMIT) -> tuple[str, bool]:
    cleaned = str(text or "")
    if len(cleaned) <= limit:
        return cleaned, False

    matches = list(DIFF_SECTION_RE.finditer(cleaned))
    if len(matches) < 2:
        return cleaned[:limit].rstrip() + "\n\n...[truncated]", True

    preamble = cleaned[: matches[0].start()]
    sections = [
        cleaned[match.start() : matches[index + 1].start() if index + 1 < len(matches) else None]
        for index, match in enumerate(matches)
    ]
    max_sections = max(1, limit // DIFF_SECTION_MIN_CHARS)
    if len(sections) > max_sections:
        last_index = len(sections) - 1
        if max_sections == 1:
            sections = [sections[0]]
        else:
            sections = [
                sections[round(index * last_index / (max_sections - 1))]
                for index in range(max_sections)
            ]

    separator_chars = len(sections)
    preamble_budget = max(
        0,
        limit - len(sections) * DIFF_SECTION_MIN_CHARS - separator_chars,
    )
    preamble_part = preamble[:preamble_budget].rstrip()
    remaining = max(0, limit - len(preamble_part) - separator_chars)
    section_budgets = [0] * len(sections)
    active = list(range(len(sections)))
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        next_active: list[int] = []
        for position, index in enumerate(active):
            available = len(sections[index]) - section_budgets[index]
            take = min(available, share, remaining)
            section_budgets[index] += take
            remaining -= take
            if section_budgets[index] < len(sections[index]):
                next_active.append(index)
            if remaining == 0:
                next_active.extend(active[position + 1 :])
                break
        active = next_active
    section_parts = [
        section[:section_budgets[index]].rstrip()
        for index, section in enumerate(sections)
    ]
    result = "\n".join(part for part in [preamble_part, *section_parts] if part)
    return result[:limit].rstrip() + "\n\n...[truncated]", True


def extract_commit_message(text: str) -> str:
    match = COMMIT_MESSAGE_RE.search(str(text or ""))
    if not match:
        return ""
    value = match.group(1)
    value = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return value.strip()


def _apply_cli_model_options(schema: dict[str, Any]) -> dict[str, Any]:
    next_schema = copy.deepcopy(schema)
    model_field = next_schema.get("model")
    model_options = normalize_cli_model_options(CLI_MODEL_OPTIONS)
    if isinstance(model_field, dict) and model_options:
        model_field["enum"] = model_options
    return next_schema
