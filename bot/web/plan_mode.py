from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath

from bot.prompts import render_prompt
from bot.remote_workspace.transport import RemoteConnection, RemoteWorkspaceError

PLAN_MODE_TASK_MODE = "plan"
PLAN_DRAFT_OPEN = "<PLAN_DRAFT>"
PLAN_DRAFT_CLOSE = "</PLAN_DRAFT>"
PLAN_EXECUTION_PROMPT_PREFIX = "Please execute the plan. Plan file:"
_LEGACY_PLAN_EXECUTION_PROMPT_PREFIX = "请按方案执行。方案文件："


@dataclass(frozen=True)
class SavedPlan:
    path: PurePath
    relative_path: str


def build_plan_mode_prompt(user_text: str, *, cluster_active: bool = False) -> str:
    cluster_rule = (
        "\nIf you use cluster capabilities, you must wait until all subtasks have completed or explicitly timed out before presenting the final plan."
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
    basename = _plan_basename(content, title)
    path = plan_dir / f"{basename}.md"
    suffix = 2
    while path.exists():
        path = plan_dir / f"{basename}-{suffix}.md"
        suffix += 1
    normalized = str(content or "").strip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    return SavedPlan(path=path, relative_path=path.relative_to(root).as_posix())


def save_remote_execution_plan(connection: RemoteConnection, root: str, content: str, *, title: str = "") -> SavedPlan:
    for directory in ("docs", "docs/plan"):
        try:
            connection.mkdir(directory, root=root)
        except RemoteWorkspaceError as exc:
            if exc.code != "path_exists":
                raise
    basename = _plan_basename(content, title)
    normalized = str(content or "").strip() + "\n"
    suffix = 1
    while True:
        name = f"{basename}{f'-{suffix}' if suffix > 1 else ''}.md"
        relative_path = f"docs/plan/{name}"
        try:
            connection.create_file(relative_path, normalized, root=root)
        except RemoteWorkspaceError as exc:
            if exc.code != "path_exists":
                raise
            suffix += 1
            continue
        return SavedPlan(path=PurePosixPath(root) / relative_path, relative_path=relative_path)


def _plan_basename(content: str, title: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    slug = slugify_plan_title(title or _derive_title(content))
    return f"{stamp}-{slug}"


def build_plan_execution_prompt(relative_plan_path: str) -> str:
    return render_prompt(
        "plan_execution",
        relative_plan_path=relative_plan_path,
    ).removesuffix("\n")


def is_plan_execution_prompt(text: str) -> bool:
    return str(text or "").lstrip().startswith(
        (PLAN_EXECUTION_PROMPT_PREFIX, _LEGACY_PLAN_EXECUTION_PROMPT_PREFIX)
    )


def _derive_title(content: str) -> str:
    for line in str(content or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "plan"
