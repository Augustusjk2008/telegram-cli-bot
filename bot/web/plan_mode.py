from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bot.prompts import render_prompt

PLAN_MODE_TASK_MODE = "plan"
PLAN_DRAFT_OPEN = "<PLAN_DRAFT>"
PLAN_DRAFT_CLOSE = "</PLAN_DRAFT>"


@dataclass(frozen=True)
class SavedPlan:
    path: Path
    relative_path: str


def build_plan_mode_prompt(user_text: str, *, cluster_active: bool = False) -> str:
    cluster_rule = (
        "\n如果你使用集群能力，必须等待所有子任务完成或明确超时，再输出最终方案。"
        if cluster_active
        else ""
    )
    return render_prompt(
        "plan_mode",
        plan_draft_open=PLAN_DRAFT_OPEN,
        plan_draft_close=PLAN_DRAFT_CLOSE,
        cluster_rule=cluster_rule,
        user_text=user_text,
    ).removesuffix("\n")


def extract_plan_draft(text: str) -> str:
    match = re.search(
        rf"{re.escape(PLAN_DRAFT_OPEN)}\s*(.*?)\s*{re.escape(PLAN_DRAFT_CLOSE)}",
        str(text or ""),
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def slugify_plan_title(title: str, *, fallback: str = "plan") -> str:
    value = str(title or "").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return (value or fallback)[:48].strip("-") or fallback


def save_execution_plan(working_dir: str | Path, content: str, *, title: str = "") -> SavedPlan:
    root = Path(working_dir).resolve()
    plan_dir = root / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    slug = slugify_plan_title(title or _derive_title(content))
    filename = f"{stamp}-{slug}.md"
    path = plan_dir / filename
    suffix = 2
    while path.exists():
        path = plan_dir / f"{stamp}-{slug}-{suffix}.md"
        suffix += 1
    normalized = str(content or "").strip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    return SavedPlan(path=path, relative_path=path.relative_to(root).as_posix())


def build_plan_execution_prompt(relative_plan_path: str) -> str:
    return render_prompt(
        "plan_execution",
        relative_plan_path=relative_plan_path,
    ).removesuffix("\n")


def _derive_title(content: str) -> str:
    for line in str(content or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "plan"
