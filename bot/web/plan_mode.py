from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    return (
        "你处于本程序 Plan Mode。\n"
        "不要修改文件，不要创建文件，不要执行会改变项目状态的命令。\n"
        "可以阅读代码、分析问题、提出澄清问题。\n"
        f"只有当你给出可执行最终方案时，才使用 {PLAN_DRAFT_OPEN} 和 {PLAN_DRAFT_CLOSE} 包裹完整方案。\n"
        "普通交流、问题、阶段性分析不要使用该标签。\n"
        "最终方案应包含目标、改动范围、实施步骤和验证步骤。"
        f"{cluster_rule}\n\n"
        f"用户请求：\n{user_text}"
    )


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
    return (
        "请按方案执行。方案文件："
        f"{relative_plan_path}\n\n"
        "要求：\n"
        "- 先阅读方案和相关代码\n"
        "- 按方案实施\n"
        "- 不要回到 Plan Mode\n"
        "- 完成后运行必要验证"
    )


def _derive_title(content: str) -> str:
    for line in str(content or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "plan"
