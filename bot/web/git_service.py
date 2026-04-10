"""Web Git 工作台服务。"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from bot.app_settings import get_git_proxy_config_args
from bot.manager import MultiBotManager
from .api_service import WebApiError, get_profile_or_raise


class GitCommandError(RuntimeError):
    """Git 命令执行失败。"""


def _raise(status: int, code: str, message: str):
    raise WebApiError(status=status, code=code, message=message)


def _normalize_repo_relative_path(path: str) -> str:
    value = (path or "").strip().replace("\\", "/")
    if not value:
        _raise(400, "missing_git_path", "缺少 Git 文件路径")

    path_obj = Path(value)
    if path_obj.is_absolute() or ".." in path_obj.parts:
        _raise(400, "unsafe_git_path", "Git 文件路径不安全")

    return value


def _run_git(repo_root: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *get_git_proxy_config_args(), *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        _raise(500, "git_not_found", "未找到 git 可执行文件")
        raise exc  # pragma: no cover

    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip() or "Git 命令执行失败"
        raise GitCommandError(output)
    return result


def _resolve_repo_root(working_dir: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *get_git_proxy_config_args(), "rev-parse", "--show-toplevel"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        _raise(500, "git_not_found", "未找到 git 可执行文件")

    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    if not output:
        return None
    return os.path.normpath(output)


def _get_git_working_dir(manager: MultiBotManager, alias: str) -> str:
    profile = get_profile_or_raise(manager, alias)
    return profile.working_dir


def _parse_status_header(header: str) -> tuple[str, int, int]:
    current_branch = ""
    ahead_count = 0
    behind_count = 0

    if not header.startswith("## "):
        return current_branch, ahead_count, behind_count

    content = header[3:].strip()
    if content.startswith("No commits yet on "):
        current_branch = content.removeprefix("No commits yet on ").strip()
    else:
        branch_part = content.split("...")[0].strip()
        current_branch = branch_part or ""

    bracket_match = re.search(r"\[(.+?)\]", content)
    if bracket_match:
        pieces = [piece.strip() for piece in bracket_match.group(1).split(",")]
        for piece in pieces:
            if piece.startswith("ahead "):
                try:
                    ahead_count = int(piece.removeprefix("ahead ").strip())
                except ValueError:
                    ahead_count = 0
            elif piece.startswith("behind "):
                try:
                    behind_count = int(piece.removeprefix("behind ").strip())
                except ValueError:
                    behind_count = 0

    return current_branch, ahead_count, behind_count


def _parse_changed_files(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in lines:
        if not raw_line:
            continue
        if raw_line.startswith("## "):
            continue

        if raw_line.startswith("?? "):
            path = raw_line[3:].strip()
            items.append(
                {
                    "path": path,
                    "status": "??",
                    "staged": False,
                    "unstaged": False,
                    "untracked": True,
                }
            )
            continue

        status = raw_line[:2]
        path_text = raw_line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()

        staged = status[0] not in (" ", "?")
        unstaged = status[1] != " "
        items.append(
            {
                "path": path_text,
                "status": status,
                "staged": staged,
                "unstaged": unstaged,
                "untracked": False,
            }
        )
    return items


def _list_recent_commits(repo_root: str, limit: int = 8) -> list[dict[str, str]]:
    result = _run_git(
        repo_root,
        [
            "log",
            f"-n{max(1, limit)}",
            "--date=iso",
            "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s",
        ],
        check=False,
    )
    if result.returncode != 0:
        return []

    items: list[dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        if not line.strip():
            continue
        full_hash, short_hash, author_name, authored_at, subject = (line.split("\x1f") + ["", "", "", "", ""])[:5]
        items.append(
            {
                "hash": full_hash,
                "short_hash": short_hash,
                "author_name": author_name,
                "authored_at": authored_at,
                "subject": subject,
            }
        )
    return items


def _build_git_overview(working_dir: str, repo_root: Optional[str]) -> dict[str, Any]:
    if not repo_root:
        return {
            "repo_found": False,
            "can_init": True,
            "working_dir": working_dir,
            "repo_path": "",
            "repo_name": "",
            "current_branch": "",
            "is_clean": True,
            "ahead_count": 0,
            "behind_count": 0,
            "changed_files": [],
            "recent_commits": [],
        }

    status_result = _run_git(repo_root, ["status", "--porcelain=1", "--branch"])
    status_lines = (status_result.stdout or "").splitlines()
    header = status_lines[0] if status_lines else ""
    current_branch, ahead_count, behind_count = _parse_status_header(header)
    changed_files = _parse_changed_files(status_lines[1:] if status_lines else [])

    return {
        "repo_found": True,
        "can_init": False,
        "working_dir": working_dir,
        "repo_path": repo_root,
        "repo_name": Path(repo_root).name,
        "current_branch": current_branch,
        "is_clean": len(changed_files) == 0,
        "ahead_count": ahead_count,
        "behind_count": behind_count,
        "changed_files": changed_files,
        "recent_commits": _list_recent_commits(repo_root),
    }


def get_git_overview(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    return _build_git_overview(working_dir, repo_root)


def init_git_repository(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    if repo_root:
        return _build_git_overview(working_dir, repo_root)

    try:
        _run_git(working_dir, ["init"])
    except GitCommandError as exc:
        _raise(400, "git_init_failed", str(exc))

    repo_root = _resolve_repo_root(working_dir)
    return _build_git_overview(working_dir, repo_root)


def _require_repo_root(manager: MultiBotManager, alias: str, user_id: int) -> tuple[str, str]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    if not repo_root:
        _raise(409, "not_git_repo", "当前目录不在 Git 仓库中")
    return working_dir, repo_root


def get_git_diff(manager: MultiBotManager, alias: str, user_id: int, path: str, staged: bool = False) -> dict[str, Any]:
    _, repo_root = _require_repo_root(manager, alias, user_id)
    relative_path = _normalize_repo_relative_path(path)
    args = ["diff"]
    if staged:
        args.append("--cached")
    args.extend(["--", relative_path])

    try:
        result = _run_git(repo_root, args)
    except GitCommandError as exc:
        _raise(400, "git_diff_failed", str(exc))

    return {
        "path": relative_path,
        "staged": staged,
        "diff": result.stdout or "",
    }


def stage_git_paths(manager: MultiBotManager, alias: str, user_id: int, paths: list[str]) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    normalized = [_normalize_repo_relative_path(path) for path in paths if str(path).strip()]
    if not normalized:
        _raise(400, "missing_git_paths", "至少选择一个文件")

    try:
        _run_git(repo_root, ["add", "--", *normalized])
    except GitCommandError as exc:
        _raise(400, "git_stage_failed", str(exc))

    return _build_git_overview(working_dir, repo_root)


def unstage_git_paths(manager: MultiBotManager, alias: str, user_id: int, paths: list[str]) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    normalized = [_normalize_repo_relative_path(path) for path in paths if str(path).strip()]
    if not normalized:
        _raise(400, "missing_git_paths", "至少选择一个文件")

    try:
        _run_git(repo_root, ["restore", "--staged", "--", *normalized])
    except GitCommandError:
        try:
            _run_git(repo_root, ["reset", "HEAD", "--", *normalized])
        except GitCommandError as exc:
            _raise(400, "git_unstage_failed", str(exc))

    return _build_git_overview(working_dir, repo_root)


def commit_git_changes(manager: MultiBotManager, alias: str, user_id: int, message: str) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    commit_message = (message or "").strip()
    if not commit_message:
        _raise(400, "empty_commit_message", "提交说明不能为空")

    try:
        _run_git(repo_root, ["commit", "-m", commit_message])
    except GitCommandError as exc:
        _raise(400, "git_commit_failed", str(exc))

    return _build_git_overview(working_dir, repo_root)


def _run_git_action(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    args: list[str],
    *,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    try:
        _run_git(repo_root, args)
    except GitCommandError as exc:
        _raise(400, error_code, str(exc))
    return _build_git_overview(working_dir, repo_root)


def fetch_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["fetch", "--all", "--prune"],
        error_code="git_fetch_failed",
        error_message="抓取远端失败",
    )


def pull_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["pull", "--ff-only"],
        error_code="git_pull_failed",
        error_message="拉取远端失败",
    )


def push_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["push"],
        error_code="git_push_failed",
        error_message="推送远端失败",
    )


def stash_git_changes(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        [
            "stash",
            "push",
            "-u",
            "-m",
            f"Web Bot stash {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ],
        error_code="git_stash_failed",
        error_message="暂存工作区失败",
    )


def pop_git_stash(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["stash", "pop"],
        error_code="git_stash_pop_failed",
        error_message="恢复暂存失败",
    )
