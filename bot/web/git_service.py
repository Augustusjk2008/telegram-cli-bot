"""Web Git 工作台服务。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from bot.cli import (
    build_cli_command,
    parse_claude_stream_json_output,
    parse_codex_json_output,
    parse_kimi_stream_json_output,
    resolve_cli_executable,
)
from bot.cli_params import CliParamsConfig, coerce_param_value
from bot.app_settings import get_git_proxy_config_args
from bot.manager import MultiBotManager
from bot.platform.processes import build_hidden_process_kwargs, terminate_process_tree_sync
from .api_common import WebApiError, get_profile_or_raise
from .git_commit_message import (
    build_commit_message_prompt,
    build_git_commit_cli_config,
    extract_commit_message,
    truncate_diff_text,
)

GIT_COMMIT_MESSAGE_TIMEOUT_SECONDS = 30 * 60
GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT = 4096


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


def _normalize_branch_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        _raise(400, "invalid_git_branch", "分支名不能为空")
    if len(value) > 120 or value.startswith("-") or any(ch.isspace() for ch in value):
        _raise(400, "invalid_git_branch", "分支名不合法")
    if "\\" in value or value.endswith("/") or value.endswith("."):
        _raise(400, "invalid_git_branch", "分支名不合法")
    return value


def _assert_valid_branch_name(repo_root: str, name: str) -> str:
    branch_name = _normalize_branch_name(name)
    result = _run_git(repo_root, ["check-ref-format", "--branch", branch_name], check=False)
    if result.returncode != 0:
        _raise(400, "invalid_git_branch", "分支名不合法")
    return branch_name


_STASH_REF_RE = re.compile(r"^stash@\{\d+\}$")


def _normalize_stash_ref(ref: str) -> str:
    value = (ref or "").strip()
    if not _STASH_REF_RE.match(value):
        _raise(400, "invalid_git_stash_ref", "stash 引用不合法")
    return value


def _normalize_identity_scope(scope: str) -> str:
    value = (scope or "").strip().lower()
    if value not in {"global", "local"}:
        _raise(400, "invalid_git_identity_scope", "Git 用户配置范围不合法")
    return value


def _normalize_git_identity_value(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        _raise(400, f"empty_git_{field}", "Git 用户名和邮箱不能为空")
    if len(text) > 200 or "\x00" in text or "\n" in text or "\r" in text:
        _raise(400, f"invalid_git_{field}", "Git 用户名或邮箱不合法")
    if field == "email" and ("@" not in text or any(ch.isspace() for ch in text)):
        _raise(400, "invalid_git_email", "Git 邮箱不合法")
    return text


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


def _run_git_with_input(
    repo_root: str,
    args: list[str],
    *,
    input_text: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            _build_git_command(args),
            cwd=repo_root,
            input=input_text,
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


def _build_git_commit_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    return env


def _terminate_process_sync(process: subprocess.Popen) -> None:
    try:
        if process.poll() is None:
            terminate_process_tree_sync(process)
    except Exception:
        pass


async def _communicate_process(process: subprocess.Popen) -> tuple[str, int]:
    try:
        output, _ = await asyncio.to_thread(process.communicate)
    except Exception:
        _terminate_process_sync(process)
        raise
    return str(output or ""), int(process.returncode or 0)


def _start_cli_process(
    cmd: list[str],
    *,
    use_stdin: bool,
    cwd: str,
    env: dict[str, str],
) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if use_stdin else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=env,
        encoding="utf-8",
        errors="replace",
        **build_hidden_process_kwargs(),
    )


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
            "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%B%x1e",
        ],
        check=False,
    )
    if result.returncode != 0:
        return []

    items: list[dict[str, str]] = []
    for record in (result.stdout or "").split("\x1e"):
        record = record.rstrip("\r\n")
        if not record.strip():
            continue
        full_hash, short_hash, author_name, authored_at, subject, message = (
            record.split("\x1f") + ["", "", "", "", "", ""]
        )[:6]
        items.append(
            {
                "hash": full_hash,
                "short_hash": short_hash,
                "author_name": author_name,
                "authored_at": authored_at,
                "subject": subject,
                "message": message,
            }
        )
    return items


def _parse_branch_lines(lines: list[str]) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        name, head_marker, upstream, short_hash, subject = (line.split("\x00") + ["", "", "", "", ""])[:5]
        branches.append(
            {
                "name": name,
                "current": head_marker == "*",
                "upstream": upstream,
                "short_hash": short_hash,
                "subject": subject,
            }
        )
    return branches


def _list_git_branches_for_repo(repo_root: str) -> dict[str, Any]:
    result = _run_git(
        repo_root,
        [
            "branch",
            "--format=%(refname:short)%00%(HEAD)%00%(upstream:short)%00%(objectname:short)%00%(contents:subject)",
        ],
    )
    branches = _parse_branch_lines((result.stdout or "").splitlines())
    current = next((item["name"] for item in branches if item["current"]), "")
    return {
        "current_branch": current,
        "branches": branches,
    }


def _parse_stash_lines(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        ref, full_hash, created_at, message = (line.split("\x1f") + ["", "", "", ""])[:4]
        items.append(
            {
                "ref": ref,
                "hash": full_hash[:12],
                "created_at": created_at,
                "message": message,
            }
        )
    return items


def _format_git_author_time(value: str) -> str:
    try:
        return datetime.fromtimestamp(int(value)).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _parse_blame_porcelain(output: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        if re.match(r"^[0-9a-f]{40} ", raw_line):
            parts = raw_line.split()
            current = {
                "commit": parts[0],
                "short_commit": parts[0][:7],
                "line": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else len(lines) + 1,
                "author_name": "",
                "author_mail": "",
                "authored_at": "",
                "summary": "",
                "content": "",
            }
            continue
        if current is None:
            continue
        if raw_line.startswith("author "):
            current["author_name"] = raw_line.removeprefix("author ").strip()
        elif raw_line.startswith("author-mail "):
            current["author_mail"] = raw_line.removeprefix("author-mail ").strip().strip("<>")
        elif raw_line.startswith("author-time "):
            current["authored_at"] = _format_git_author_time(raw_line.removeprefix("author-time ").strip())
        elif raw_line.startswith("summary "):
            current["summary"] = raw_line.removeprefix("summary ").strip()
        elif raw_line.startswith("\t"):
            current["content"] = raw_line[1:]
            lines.append(current)
            current = None
    return lines


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


def _read_git_config_value(cwd: str, scope: str, key: str) -> str:
    result = _run_git(cwd, ["config", f"--{scope}", "--get", key], check=False)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _git_identity_for_scope(cwd: str, scope: str) -> dict[str, str]:
    return {
        "name": _read_git_config_value(cwd, scope, "user.name"),
        "email": _read_git_config_value(cwd, scope, "user.email"),
    }


def get_git_identity_config(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    return {
        "repo_found": bool(repo_root),
        "repo_path": repo_root or "",
        "global": _git_identity_for_scope(working_dir, "global"),
        "local": _git_identity_for_scope(repo_root, "local") if repo_root else {"name": "", "email": ""},
    }


def update_git_identity_config(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    scope: str,
    name: Any,
    email: Any,
) -> dict[str, Any]:
    working_dir = _get_git_working_dir(manager, alias)
    repo_root = _resolve_repo_root(working_dir)
    normalized_scope = _normalize_identity_scope(scope)
    if normalized_scope == "local" and not repo_root:
        _raise(409, "not_git_repo", "当前目录不在 Git 仓库中")

    normalized_name = _normalize_git_identity_value(name, field="name")
    normalized_email = _normalize_git_identity_value(email, field="email")
    cwd = repo_root if normalized_scope == "local" and repo_root else working_dir

    try:
        _run_git(cwd, ["config", f"--{normalized_scope}", "user.name", normalized_name])
        _run_git(cwd, ["config", f"--{normalized_scope}", "user.email", normalized_email])
    except GitCommandError as exc:
        _raise(400, "git_identity_update_failed", str(exc))

    return get_git_identity_config(manager, alias, user_id)


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


def _read_git_commit_message_context(repo_root: str) -> dict[str, Any]:
    staged_stat = _run_git(repo_root, ["diff", "--cached", "--stat"], check=False).stdout or ""
    staged_diff = _run_git(repo_root, ["diff", "--cached", "--find-renames"], check=False).stdout or ""
    unstaged_stat = _run_git(repo_root, ["diff", "--stat"], check=False).stdout or ""
    unstaged_diff = _run_git(repo_root, ["diff", "--find-renames"], check=False).stdout or ""
    status_text = _run_git(repo_root, ["status", "--short"], check=False).stdout or ""

    use_staged_diff = bool(staged_diff.strip())
    selected_diff = staged_diff if use_staged_diff else "\n".join(
        part for part in [unstaged_stat.strip(), unstaged_diff.strip()] if part
    )
    truncated_diff, diff_truncated = truncate_diff_text(selected_diff)

    return {
        "status_text": status_text,
        "diff_text": truncated_diff,
        "use_staged_diff": use_staged_diff,
        "diff_truncated": diff_truncated,
    }


def _extract_untracked_paths(status_text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in (status_text or "").splitlines():
        entry = _parse_porcelain_entry(raw_line)
        if entry is None or not entry["untracked"]:
            continue
        paths.append(str(entry["path"] or "").strip())
    return _unique_paths(paths)


def _read_untracked_file_preview(repo_root: str, relative_path: str) -> str:
    target_path = _resolve_repo_worktree_path(repo_root, relative_path)
    try:
        raw = Path(target_path).read_bytes()
    except OSError:
        return f"--- {relative_path} ---\n[unreadable]"
    if b"\x00" in raw:
        return f"--- {relative_path} ---\n[binary file]"

    preview = raw[:GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT].decode("utf-8", errors="replace").strip()
    if len(raw) > GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT:
        preview = f"{preview}\n...[truncated]".strip()
    return f"--- {relative_path} ---\n{preview or '[empty file]'}"


def _read_git_smart_commit_message_context(repo_root: str) -> dict[str, Any]:
    status_text = _run_git(repo_root, ["status", "--short", "--untracked-files=all"], check=False).stdout or ""
    staged_stat = _run_git(repo_root, ["diff", "--cached", "--stat"], check=False).stdout or ""
    staged_diff = _run_git(repo_root, ["diff", "--cached", "--find-renames"], check=False).stdout or ""
    unstaged_stat = _run_git(repo_root, ["diff", "--stat"], check=False).stdout or ""
    unstaged_diff = _run_git(repo_root, ["diff", "--find-renames"], check=False).stdout or ""

    sections: list[str] = []
    if staged_stat.strip() or staged_diff.strip():
        sections.append(
            "\n".join(
                part
                for part in [
                    "=== STAGED CHANGES ===",
                    staged_stat.strip(),
                    staged_diff.strip(),
                ]
                if part
            )
        )
    if unstaged_stat.strip() or unstaged_diff.strip():
        sections.append(
            "\n".join(
                part
                for part in [
                    "=== UNSTAGED CHANGES ===",
                    unstaged_stat.strip(),
                    unstaged_diff.strip(),
                ]
                if part
            )
        )

    untracked_paths = _extract_untracked_paths(status_text)
    if untracked_paths:
        previews = [_read_untracked_file_preview(repo_root, path) for path in untracked_paths]
        sections.append("=== UNTRACKED FILES ===\n" + "\n\n".join(previews))

    diff_text, diff_truncated = truncate_diff_text("\n\n".join(part for part in sections if part))
    return {
        "status_text": status_text,
        "diff_text": diff_text,
        "use_staged_diff": True,
        "diff_truncated": diff_truncated,
    }


def _build_git_worktree_snapshot(repo_root: str) -> str:
    status_text = _run_git(repo_root, ["status", "--porcelain=1", "--untracked-files=all"], check=False).stdout or ""
    staged_diff = _run_git(repo_root, ["diff", "--cached", "--find-renames"], check=False).stdout or ""
    unstaged_diff = _run_git(repo_root, ["diff", "--find-renames"], check=False).stdout or ""
    untracked_paths = _extract_untracked_paths(status_text)
    untracked_preview = "\n\n".join(_read_untracked_file_preview(repo_root, path) for path in untracked_paths)
    return "\n<<STATUS>>\n".join(
        [
            status_text,
            "<<STAGED>>\n" + staged_diff,
            "<<UNSTAGED>>\n" + unstaged_diff,
            "<<UNTRACKED>>\n" + untracked_preview,
        ]
    )


async def _generate_git_commit_message_from_context(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    repo_root: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    cli_config = manager.get_git_commit_cli_config(alias)
    cli_type = str(cli_config.cli_type or "").strip().lower()
    cli_path = str(cli_config.cli_path or "").strip()
    resolved_cli = resolve_cli_executable(cli_path, repo_root)
    if not resolved_cli:
        _raise(400, "cli_not_found", f"未找到 CLI 可执行文件: {cli_path}")

    prompt_text = build_commit_message_prompt(**context)
    env = _build_git_commit_cli_env()
    try:
        cmd, use_stdin = build_cli_command(
            cli_type=cli_type,
            resolved_cli=resolved_cli,
            user_text=prompt_text,
            env=env,
            params_config=cli_config.cli_params,
            session_id=None,
            resume_session=False,
            json_output=True,
            working_dir=repo_root,
        )
    except ValueError as exc:
        _raise(400, "invalid_git_commit_cli_command", str(exc))

    try:
        process = _start_cli_process(
            cmd,
            use_stdin=use_stdin,
            cwd=repo_root,
            env=env,
        )
    except FileNotFoundError:
        _raise(400, "cli_not_found", f"未找到 CLI 可执行文件: {cli_path}")

    if use_stdin:
        try:
            assert process.stdin is not None
            process.stdin.write(prompt_text + "\n")
            process.stdin.flush()
            process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            process.wait()
            _raise(500, "git_commit_message_failed", f"写入 CLI 失败: {exc}")

    try:
        raw_output, returncode = await asyncio.wait_for(
            _communicate_process(process),
            timeout=GIT_COMMIT_MESSAGE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        _terminate_process_sync(process)
        _raise(504, "git_commit_message_timeout", "生成 commit message 超时")

    if cli_type == "codex":
        response_text, _ = parse_codex_json_output(raw_output)
    elif cli_type == "claude":
        response_text, _ = parse_claude_stream_json_output(raw_output)
    elif cli_type == "kimi":
        response_text = parse_kimi_stream_json_output(raw_output)
    else:
        response_text = raw_output.strip()

    if returncode != 0:
        detail = response_text.strip() or raw_output.strip() or "CLI 执行失败"
        _raise(400, "git_commit_message_failed", detail)

    message = extract_commit_message(response_text)
    if not message:
        _raise(400, "git_commit_message_parse_failed", "未提取到 commit message")
    return {"message": message}


def get_git_commit_message_cli_config(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    config = manager.get_git_commit_cli_config(alias)
    return build_git_commit_cli_config(profile, config)


async def update_git_commit_message_cli_config(
    manager: MultiBotManager,
    alias: str,
    *,
    cli_type: Any = None,
    cli_path: Any = None,
    key: Any = None,
    value: Any = None,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    current = manager.get_git_commit_cli_config(alias)
    next_cli_type = str(cli_type or current.cli_type or profile.cli_type).strip().lower()
    next_cli_path = str(cli_path if cli_path is not None else current.cli_path).strip()
    next_params = CliParamsConfig.from_dict(current.cli_params.to_dict())

    key_text = str(key or "").strip()
    if key_text:
        try:
            coerced_value = coerce_param_value(next_cli_type, key_text, value)
        except ValueError as exc:
            _raise(400, "invalid_param_value", str(exc))
        next_params.set_param(next_cli_type, key_text, coerced_value)

    try:
        await manager.set_git_commit_cli_config(
            alias,
            cli_type=next_cli_type,
            cli_path=next_cli_path,
            cli_params=next_params,
        )
    except ValueError as exc:
        _raise(400, "invalid_git_commit_cli_config", str(exc))
    return get_git_commit_message_cli_config(manager, alias)


async def reset_git_commit_message_cli_config(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.reset_git_commit_cli_config(alias)
    return get_git_commit_message_cli_config(manager, alias)


async def generate_git_commit_message(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    _working_dir, repo_root = await asyncio.to_thread(_require_repo_root, manager, alias, user_id)
    context = await asyncio.to_thread(_read_git_commit_message_context, repo_root)
    return await _generate_git_commit_message_from_context(
        manager,
        alias,
        user_id,
        repo_root=repo_root,
        context=context,
    )


def get_git_status_porcelain_snapshot(repo_root: str) -> str:
    return _build_git_worktree_snapshot(repo_root)


def get_git_status_porcelain_text(repo_root: str) -> str:
    return _run_git(repo_root, ["status", "--porcelain=1", "--untracked-files=all"], check=False).stdout or ""


def get_git_smart_commit_repo_hint(manager: MultiBotManager, alias: str) -> tuple[str, str]:
    working_dir = _get_git_working_dir(manager, alias)
    return working_dir, _resolve_repo_root(working_dir) or ""


def preflight_git_smart_commit(manager: MultiBotManager, alias: str, user_id: int) -> tuple[str, str, str]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    status_text = get_git_status_porcelain_text(repo_root)
    if not status_text.strip():
        _raise(409, "git_no_changes", "当前没有可提交的改动")
    snapshot = get_git_status_porcelain_snapshot(repo_root)

    cli_config = manager.get_git_commit_cli_config(alias)
    cli_path = str(cli_config.cli_path or "").strip()
    resolved_cli = resolve_cli_executable(cli_path, repo_root)
    if not resolved_cli:
        _raise(400, "cli_not_found", f"未找到 CLI 可执行文件: {cli_path}")
    return working_dir, repo_root, snapshot


async def generate_git_smart_commit_message(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *,
    repo_root: str,
) -> dict[str, Any]:
    context = await asyncio.to_thread(_read_git_smart_commit_message_context, repo_root)
    return await _generate_git_commit_message_from_context(
        manager,
        alias,
        user_id,
        repo_root=repo_root,
        context=context,
    )


def ensure_git_status_snapshot_unchanged(repo_root: str, expected_snapshot: str) -> None:
    current_snapshot = get_git_status_porcelain_snapshot(repo_root)
    if current_snapshot != expected_snapshot:
        _raise(409, "git_worktree_changed", "生成期间工作区已变化，请重新生成提交说明")


def stage_all_git_changes(repo_root: str) -> None:
    try:
        _run_git(repo_root, ["add", "-A"])
    except GitCommandError as exc:
        _raise(400, "git_stage_failed", str(exc))


def commit_git_message(repo_root: str, message: str) -> None:
    commit_message = (message or "").strip()
    if not commit_message:
        _raise(400, "empty_commit_message", "提交说明不能为空")
    try:
        _run_git_with_input(repo_root, ["commit", "-F", "-"], input_text=commit_message)
    except GitCommandError as exc:
        _raise(400, "git_commit_failed", str(exc))


def list_git_branches(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    _, repo_root = _require_repo_root(manager, alias, user_id)
    try:
        return _list_git_branches_for_repo(repo_root)
    except GitCommandError as exc:
        _raise(400, "git_branch_list_failed", str(exc))


def create_git_branch(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    name: str,
    start_point: str = "",
) -> dict[str, Any]:
    _, repo_root = _require_repo_root(manager, alias, user_id)
    branch_name = _assert_valid_branch_name(repo_root, name)
    args = ["branch", branch_name]
    if (start_point or "").strip():
        args.append(_assert_valid_branch_name(repo_root, start_point))
    try:
        _run_git(repo_root, args)
        return _list_git_branches_for_repo(repo_root)
    except GitCommandError as exc:
        _raise(400, "git_branch_create_failed", str(exc))


def switch_git_branch(manager: MultiBotManager, alias: str, user_id: int, name: str) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    branch_name = _assert_valid_branch_name(repo_root, name)
    try:
        _run_git(repo_root, ["switch", branch_name])
        return {
            "branches": _list_git_branches_for_repo(repo_root)["branches"],
            "current_branch": _build_git_overview(working_dir, repo_root)["current_branch"],
        }
    except GitCommandError as exc:
        _raise(400, "git_branch_switch_failed", str(exc))


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


def list_git_stashes(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    _, repo_root = _require_repo_root(manager, alias, user_id)
    try:
        result = _run_git(
            repo_root,
            ["stash", "list", "--format=%gd%x1f%H%x1f%ci%x1f%gs"],
        )
    except GitCommandError as exc:
        _raise(400, "git_stash_list_failed", str(exc))
    return {"items": _parse_stash_lines((result.stdout or "").splitlines())}


def apply_git_stash(manager: MultiBotManager, alias: str, user_id: int, ref: str) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    stash_ref = _normalize_stash_ref(ref)
    try:
        _run_git(repo_root, ["stash", "apply", stash_ref])
    except GitCommandError as exc:
        _raise(400, "git_stash_apply_failed", str(exc))
    return _build_git_overview(working_dir, repo_root)


def drop_git_stash(manager: MultiBotManager, alias: str, user_id: int, ref: str) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    stash_ref = _normalize_stash_ref(ref)
    try:
        _run_git(repo_root, ["stash", "drop", stash_ref])
    except GitCommandError as exc:
        _raise(400, "git_stash_drop_failed", str(exc))
    return _build_git_overview(working_dir, repo_root)


def pop_git_stash(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["stash", "pop"],
        error_code="git_stash_pop_failed",
        error_message="恢复暂存失败",
    )


def get_git_blame(manager: MultiBotManager, alias: str, user_id: int, path: str) -> dict[str, Any]:
    _, repo_root = _require_repo_root(manager, alias, user_id)
    relative_path = _normalize_repo_relative_path(path)
    try:
        result = _run_git(repo_root, ["blame", "--line-porcelain", "--", relative_path])
    except GitCommandError as exc:
        _raise(400, "git_blame_failed", str(exc))
    return {
        "path": relative_path,
        "lines": _parse_blame_porcelain(result.stdout or ""),
    }
