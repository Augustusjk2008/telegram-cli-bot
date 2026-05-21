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
    return cleaned[:limit].rstrip() + "\n\n...[truncated]", True


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
