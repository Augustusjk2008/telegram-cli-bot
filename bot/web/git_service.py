"""Web Git 工作台服务。"""

from __future__ import annotations

import os
import re
import shutil
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


def _build_git_command(args: list[str]) -> list[str]:
    # H:/ 等非系统盘上的 fsmonitor 可能让 status/diff 长时间卡住，Web Git 统一禁用。
    return ["git", "-c", "core.fsmonitor=false", *get_git_proxy_config_args(), *args]


def _run_git(repo_root: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            _build_git_command(args),
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
            _build_git_command(["rev-parse", "--show-toplevel"]),
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
        entry = _parse_porcelain_entry(raw_line)
        if entry is None:
            continue

        items.append(
            {
                "path": entry["path"],
                "status": entry["status"],
                "staged": entry["staged"],
                "unstaged": entry["unstaged"],
                "untracked": entry["untracked"],
            }
        )
    return items


def _parse_porcelain_entry(raw_line: str) -> dict[str, Any] | None:
    if not raw_line or raw_line.startswith("## "):
        return None

    if raw_line.startswith("?? "):
        return {
            "path": raw_line[3:].strip(),
            "original_path": "",
            "status": "??",
            "staged": False,
            "unstaged": False,
            "untracked": True,
        }

    status = raw_line[:2]
    path_text = raw_line[3:].strip()
    original_path = ""
    if " -> " in path_text:
        original_path, path_text = [part.strip() for part in path_text.split(" -> ", 1)]

    return {
        "path": path_text,
        "original_path": original_path,
        "status": status,
        "staged": status[0] not in (" ", "?"),
        "unstaged": status[1] != " ",
        "untracked": False,
    }


def _parse_tree_status_kind(status: str) -> Optional[str]:
    if status == "!!":
        return "ignored"
    if status == "??" or status.startswith("A"):
        return "added"
    if "D" in status:
        return None
    return "modified" if status.strip() else None


def _relative_to_working_dir(repo_relative_path: str, working_dir: str, repo_root: str) -> Optional[str]:
    normalized_path = repo_relative_path.replace("\\", "/").rstrip("/")
    if not normalized_path:
        return None

    working_prefix = os.path.relpath(working_dir, repo_root).replace("\\", "/")
    if working_prefix == ".":
        return normalized_path

    prefix = f"{working_prefix.rstrip('/')}/"
    if normalized_path == working_prefix.rstrip("/"):
        return normalized_path.split("/")[-1]
    if not normalized_path.startswith(prefix):
        return None
    return normalized_path[len(prefix) :]


def _parse_tree_status_items(lines: list[str], *, working_dir: str, repo_root: str) -> dict[str, str]:
    items: dict[str, str] = {}
    for raw_line in lines:
        if not raw_line or raw_line.startswith("## "):
            continue

        status = raw_line[:2]
        path_text = raw_line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()

        kind = _parse_tree_status_kind(status)
        if not kind:
            continue

        relative_path = _relative_to_working_dir(path_text, working_dir, repo_root)
        if not relative_path:
            continue

        items[relative_path] = kind
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


def get_git_tree_status(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    if not repo_root:
        return {
            "repo_found": False,
            "working_dir": working_dir,
            "repo_path": "",
            "items": {},
        }

    try:
        result = _run_git(
            repo_root,
            [
                "status",
                "--porcelain=1",
                "--ignored=matching",
                "--untracked-files=all",
            ],
        )
    except GitCommandError as exc:
        _raise(400, "git_tree_status_failed", str(exc))

    return {
        "repo_found": True,
        "working_dir": working_dir,
        "repo_path": repo_root,
        "items": _parse_tree_status_items(
            (result.stdout or "").splitlines(),
            working_dir=working_dir,
            repo_root=repo_root,
        ),
    }


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


def _get_status_entries(repo_root: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
    args = ["status", "--porcelain=1", "--untracked-files=all"]
    if paths:
        args.extend(["--", *paths])
    result = _run_git(repo_root, args)
    entries: list[dict[str, Any]] = []
    for raw_line in (result.stdout or "").splitlines():
        entry = _parse_porcelain_entry(raw_line)
        if entry is not None:
            entries.append(entry)
    return entries


def _unique_paths(paths: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _repo_has_head_commit(repo_root: str) -> bool:
    return _run_git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False).returncode == 0


def _resolve_repo_worktree_path(repo_root: str, relative_path: str) -> str:
    repo_root_abs = os.path.abspath(repo_root)
    target_path = os.path.abspath(os.path.join(repo_root_abs, relative_path))
    if os.path.commonpath([repo_root_abs, target_path]) != repo_root_abs:
        _raise(400, "unsafe_git_path", "Git 文件路径不安全")
    return target_path


def _delete_worktree_path(repo_root: str, relative_path: str) -> None:
    target_path = _resolve_repo_worktree_path(repo_root, relative_path)
    if os.path.isdir(target_path) and not os.path.islink(target_path):
        shutil.rmtree(target_path, ignore_errors=True)
    elif os.path.lexists(target_path):
        os.remove(target_path)

    repo_root_abs = os.path.abspath(repo_root)
    parent = os.path.dirname(target_path)
    while parent and parent != repo_root_abs:
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def _restore_git_paths(repo_root: str, paths: list[str], *, error_code: str) -> None:
    if not paths:
        return
    if not _repo_has_head_commit(repo_root):
        _raise(400, error_code, "当前仓库还没有可恢复的提交")

    try:
        _run_git(repo_root, ["restore", "--source=HEAD", "--staged", "--worktree", "--", *paths])
        return
    except GitCommandError:
        try:
            _run_git(repo_root, ["reset", "HEAD", "--", *paths])
            _run_git(repo_root, ["checkout", "--", *paths])
            return
        except GitCommandError as exc:
            _raise(400, error_code, str(exc))


def _unstage_added_git_paths(repo_root: str, paths: list[str], *, error_code: str) -> None:
    if not paths:
        return
    try:
        _run_git(repo_root, ["rm", "--cached", "-f", "--", *paths])
    except GitCommandError as exc:
        _raise(400, error_code, str(exc))


def _discard_status_entries(repo_root: str, entries: list[dict[str, Any]], *, error_code: str) -> None:
    restore_paths: list[str] = []
    unstage_and_remove_paths: list[str] = []
    remove_paths: list[str] = []

    for entry in entries:
        path = entry["path"]
        status = entry["status"]
        original_path = entry.get("original_path") or ""

        if entry["untracked"]:
            remove_paths.append(path)
            continue

        if "R" in status and original_path:
            restore_paths.append(original_path)
            if path != original_path:
                remove_paths.append(path)
            continue

        if "C" in status and original_path:
            remove_paths.append(path)
            continue

        if status.startswith("A"):
            unstage_and_remove_paths.append(path)
            remove_paths.append(path)
            continue

        restore_paths.append(path)

    _restore_git_paths(repo_root, _unique_paths(restore_paths), error_code=error_code)
    _unstage_added_git_paths(repo_root, _unique_paths(unstage_and_remove_paths), error_code=error_code)

    for path in _unique_paths(remove_paths):
        _delete_worktree_path(repo_root, path)


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


def discard_git_paths(manager: MultiBotManager, alias: str, user_id: int, paths: list[str]) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    normalized = _unique_paths([_normalize_repo_relative_path(path) for path in paths if str(path).strip()])
    if not normalized:
        _raise(400, "missing_git_paths", "至少选择一个文件")

    entries = _get_status_entries(repo_root, normalized)
    _discard_status_entries(repo_root, entries, error_code="git_discard_failed")
    return _build_git_overview(working_dir, repo_root)


def discard_all_git_changes(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    entries = _get_status_entries(repo_root)
    _discard_status_entries(repo_root, entries, error_code="git_discard_all_failed")
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
