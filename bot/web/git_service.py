"""Web Git 工作台服务。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
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
from bot import config
from bot.cli_params import CliParamsConfig, coerce_param_value, with_global_extra_args
from bot.app_settings import get_git_proxy_config_args
from bot.manager import MultiBotManager
from bot.platform.processes import build_hidden_process_kwargs, terminate_process_tree_sync
from bot.platform.subprocess_streams import close_process_streams
from .api_common import WebApiError, get_profile_or_raise
from .git_commit_message import (
    build_commit_message_prompt,
    build_git_commit_cli_config,
    extract_commit_message,
    truncate_diff_text,
)

GIT_COMMIT_MESSAGE_TIMEOUT_SECONDS = 30 * 60
GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT = 4096
GIT_DIFF_OUTPUT_CHAR_LIMIT = 128 * 1024
GIT_COMMIT_GRAPH_DEFAULT_LIMIT = 100
GIT_COMMIT_GRAPH_MAX_LIMIT = 300
_GIT_STATUS_CACHE_TTL_SECONDS = 0.75
_GIT_STATUS_CACHE_LOCK = threading.Lock()
_GIT_STATUS_CACHE: dict[str, dict[str, Any]] = {}
_SSH_STRICT_HOST_KEY_OPTION_RE = re.compile(
    r"(?:^|\s)-o\s*['\"]?stricthostkeychecking(?:\s*=|\s|=|$)",
    re.IGNORECASE,
)


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
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _resolve_commit_ref(repo_root: str, ref: str) -> str:
    value = (ref or "").strip()
    if not _COMMIT_SHA_RE.match(value):
        _raise(400, "invalid_git_commit", "提交引用不合法")

    result = _run_git(repo_root, ["rev-parse", "--verify", f"{value}^{{commit}}"], check=False)
    if result.returncode != 0:
        _raise(400, "invalid_git_commit", "提交不存在")

    full_sha = (result.stdout or "").strip()
    if not full_sha:
        _raise(400, "invalid_git_commit", "提交不存在")
    return full_sha


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


def _run_git(
    repo_root: str,
    args: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            _build_git_command(args),
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError as exc:
        _raise(500, "git_not_found", "未找到 git 可执行文件")
        raise exc  # pragma: no cover

    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip() or "Git 命令执行失败"
        raise GitCommandError(output)
    return result


def _get_configured_git_ssh_command(repo_root: str) -> str:
    try:
        result = subprocess.run(
            _build_git_command(["config", "--get", "core.sshCommand"]),
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ""

    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _ssh_command_sets_strict_host_key_checking(ssh_command: str) -> bool:
    return bool(_SSH_STRICT_HOST_KEY_OPTION_RE.search(ssh_command))


def _build_git_remote_env(repo_root: str) -> dict[str, str]:
    env = os.environ.copy()
    ssh_command = str(env.get("GIT_SSH_COMMAND") or "").strip()
    if not ssh_command:
        ssh_command = _get_configured_git_ssh_command(repo_root)
    if ssh_command:
        if not _ssh_command_sets_strict_host_key_checking(ssh_command):
            env["GIT_SSH_COMMAND"] = f"{ssh_command} -o StrictHostKeyChecking=accept-new"
        else:
            env["GIT_SSH_COMMAND"] = ssh_command
        return env

    if "GIT_SSH" not in env:
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new"
    return env


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


async def _communicate_process(process: subprocess.Popen, *, input_text: str | None = None) -> tuple[str, int]:
    try:
        if input_text is None:
            output, _ = await asyncio.to_thread(process.communicate)
        else:
            output, _ = await asyncio.to_thread(process.communicate, input=input_text)
    except Exception:
        _terminate_process_sync(process)
        raise
    finally:
        close_process_streams(process)
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


def _read_git_head_token(repo_root: str) -> str:
    git_dir = Path(repo_root) / ".git"
    head_path = git_dir / "HEAD"
    try:
        head_value = head_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if head_value.startswith("ref: "):
        ref_path = git_dir / head_value.removeprefix("ref: ").strip()
        try:
            return ref_path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return head_value
    return head_value


def _status_path_token(repo_root: str, lines: list[str]) -> tuple[tuple[str, int, int], ...]:
    tokens: list[tuple[str, int, int]] = []
    for raw_line in lines:
        entry = _parse_porcelain_entry(raw_line)
        if entry is None:
            continue
        path_text = str(entry.get("path") or "").replace("\\", "/").strip()
        if not path_text:
            continue
        path = Path(repo_root) / path_text
        try:
            stat_result = path.stat()
            token = (path_text, int(stat_result.st_mtime_ns), int(stat_result.st_size))
        except OSError:
            token = (path_text, 0, 0)
        tokens.append(token)
    return tuple(sorted(tokens))


def _git_status_cache_key(repo_root: str) -> str:
    return os.path.normcase(os.path.abspath(repo_root))


def _read_git_status_cache(repo_root: str) -> dict[str, Any] | None:
    cache_key = _git_status_cache_key(repo_root)
    now = time.monotonic()
    with _GIT_STATUS_CACHE_LOCK:
        entry = dict(_GIT_STATUS_CACHE.get(cache_key) or {})
    if not entry:
        return None
    if now - float(entry.get("created_at") or 0.0) > _GIT_STATUS_CACHE_TTL_SECONDS:
        return None
    return entry


def _write_git_status_cache(repo_root: str, entry: dict[str, Any]) -> None:
    cache_key = _git_status_cache_key(repo_root)
    with _GIT_STATUS_CACHE_LOCK:
        _GIT_STATUS_CACHE[cache_key] = dict(entry)


def _invalidate_git_status_cache(repo_root: str) -> None:
    cache_key = _git_status_cache_key(repo_root)
    with _GIT_STATUS_CACHE_LOCK:
        _GIT_STATUS_CACHE.pop(cache_key, None)


def _build_repo_status_snapshot(repo_root: str) -> dict[str, Any]:
    cached = _read_git_status_cache(repo_root)
    head_token = _read_git_head_token(repo_root)
    index_path = Path(repo_root) / ".git" / "index"
    try:
        index_stat = index_path.stat()
        index_token = (int(index_stat.st_mtime_ns), int(index_stat.st_size))
    except OSError:
        index_token = (0, 0)
    if (
        cached
        and cached.get("head_token") == head_token
        and cached.get("index_token") == index_token
        and cached.get("status_path_token") == _status_path_token(repo_root, cached.get("tree_lines") or [])
    ):
        return cached

    branch_result = _run_git(repo_root, ["status", "--porcelain=1", "--branch"])
    tree_result = _run_git(
        repo_root,
        [
            "status",
            "--porcelain=1",
            "--ignored=matching",
            "--untracked-files=all",
        ],
    )
    tree_lines = (tree_result.stdout or "").splitlines()
    entry = {
        "created_at": time.monotonic(),
        "head_token": head_token,
        "index_token": index_token,
        "branch_lines": (branch_result.stdout or "").splitlines(),
        "tree_lines": tree_lines,
        "status_path_token": _status_path_token(repo_root, tree_lines),
    }
    if tree_lines:
        _write_git_status_cache(repo_root, entry)
    return entry


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
        full_hash = full_hash.strip()
        short_hash = short_hash.strip()
        author_name = author_name.strip()
        authored_at = authored_at.strip()
        subject = subject.strip()
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


def _normalize_git_graph_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in {"current", "all"}:
        _raise(400, "invalid_git_graph_scope", "版本树范围不合法")
    return value


def _normalize_git_graph_limit(limit: Any) -> int:
    text = "" if limit is None else str(limit).strip()
    if not text:
        return GIT_COMMIT_GRAPH_DEFAULT_LIMIT
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        _raise(400, "invalid_limit", "limit 必须是 1-300 的整数")
        raise exc  # pragma: no cover
    if value < 1 or value > GIT_COMMIT_GRAPH_MAX_LIMIT:
        _raise(400, "invalid_limit", "limit 必须是 1-300 的整数")
    return value


def _decode_git_graph_cursor(cursor: Any, *, scope: str) -> int:
    value = str(cursor or "").strip()
    if not value:
        return 0
    try:
        padded = value + ("=" * (-len(value) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _raise(400, "invalid_cursor", "cursor 不合法")
        raise exc  # pragma: no cover

    if not isinstance(payload, dict):
        _raise(400, "invalid_cursor", "cursor 不合法")
    if payload.get("scope") != scope:
        _raise(400, "invalid_cursor", "cursor 不合法")
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        _raise(400, "invalid_cursor", "cursor 不合法")
    return offset


def _encode_git_graph_cursor(*, offset: int, scope: str, head_token: str) -> str:
    payload = json.dumps(
        {"offset": offset, "scope": scope, "head": head_token},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _parse_git_graph_records(output: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    for record in (output or "").split("\x1e"):
        record = record.rstrip("\r\n")
        if not record.strip():
            continue
        full_hash, parents_text, short_hash, author_name, authored_at, subject = (
            record.split("\x1f") + ["", "", "", "", "", ""]
        )[:6]
        full_hash = full_hash.strip()
        if not full_hash:
            continue
        commits.append(
            {
                "hash": full_hash,
                "parents": [item.strip() for item in parents_text.split() if item.strip()],
                "short_hash": short_hash.strip(),
                "author_name": author_name.strip(),
                "authored_at": authored_at.strip(),
                "subject": subject.strip(),
            }
        )
    return commits


def _list_git_graph_commits(repo_root: str, *, scope: str, limit: int) -> list[dict[str, Any]]:
    args = [
        "log",
        "--topo-order",
        f"-n{limit}",
        "--date=iso-strict",
        "--format=%H%x1f%P%x1f%h%x1f%an%x1f%aI%x1f%s%x1e",
    ]
    args.append("--all" if scope == "all" else "HEAD")
    result = _run_git(repo_root, args, check=False)
    if result.returncode != 0:
        return []
    return _parse_git_graph_records(result.stdout or "")


def _git_graph_ref_kind(refname: str) -> tuple[str, str] | None:
    if refname.startswith("refs/heads/"):
        return "local_branch", refname.removeprefix("refs/heads/")
    if refname.startswith("refs/remotes/"):
        return "remote_branch", refname.removeprefix("refs/remotes/")
    if refname.startswith("refs/tags/"):
        return "tag", refname.removeprefix("refs/tags/")
    return None


def _list_git_graph_refs(repo_root: str) -> dict[str, list[dict[str, Any]]]:
    refs_by_commit: dict[str, list[dict[str, Any]]] = {}
    result = _run_git(
        repo_root,
        [
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(*objectname)%00%(objecttype)%00%(*objecttype)%00%(HEAD)",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        ],
        check=False,
    )
    if result.returncode == 0:
        for raw_line in (result.stdout or "").splitlines():
            if not raw_line:
                continue
            refname, object_hash, peeled_hash, object_type, peeled_type, head_marker = (
                raw_line.split("\x00") + ["", "", "", "", "", ""]
            )[:6]
            kind_name = _git_graph_ref_kind(refname)
            if kind_name is None:
                continue
            kind, name = kind_name
            commit_hash = ""
            if peeled_hash and peeled_type == "commit":
                commit_hash = peeled_hash
            elif object_type == "commit":
                commit_hash = object_hash
            if not commit_hash:
                continue
            refs_by_commit.setdefault(commit_hash, []).append(
                {
                    "name": name,
                    "kind": kind,
                    "current": kind == "local_branch" and head_marker == "*",
                }
            )

    head_result = _run_git(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"], check=False)
    head_hash = (head_result.stdout or "").strip() if head_result.returncode == 0 else ""
    if head_hash:
        refs_by_commit.setdefault(head_hash, []).append({"name": "HEAD", "kind": "head", "current": True})

    order = {"head": 0, "local_branch": 1, "remote_branch": 2, "tag": 3}
    for refs in refs_by_commit.values():
        refs.sort(key=lambda item: (order.get(str(item.get("kind")), 99), str(item.get("name") or "")))
    return refs_by_commit


def _find_lane(lanes: list[str], commit_hash: str, *, exclude_index: int | None = None) -> int | None:
    for index, value in enumerate(lanes):
        if index == exclude_index:
            continue
        if value == commit_hash:
            return index
    return None


def _layout_git_graph_nodes(
    commits: list[dict[str, Any]],
    refs_by_commit: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    lanes: list[str] = []
    nodes: list[dict[str, Any]] = []
    for commit in commits:
        commit_hash = str(commit.get("hash") or "")
        column = _find_lane(lanes, commit_hash)
        if column is None:
            lanes.append(commit_hash)
            column = len(lanes) - 1

        parents = list(commit.get("parents") or [])
        before_width = len(lanes)
        next_lanes = list(lanes)
        edges: list[dict[str, Any]] = []
        if parents:
            first_parent = str(parents[0])
            existing = _find_lane(next_lanes, first_parent, exclude_index=column)
            if existing is None:
                next_lanes[column] = first_parent
                parent_column = column
            else:
                next_lanes.pop(column)
                parent_column = existing if existing < column else existing - 1
            edges.append({"from": column, "to": parent_column, "commit": first_parent})

            for parent in parents[1:]:
                parent_hash = str(parent)
                existing = _find_lane(next_lanes, parent_hash)
                if existing is None:
                    insert_at = min(column + len(edges), len(next_lanes))
                    next_lanes.insert(insert_at, parent_hash)
                    parent_column = insert_at
                else:
                    parent_column = existing
                edges.append({"from": column, "to": parent_column, "commit": parent_hash})
        else:
            next_lanes.pop(column)

        edge_width = max([column + 1, *(max(edge["from"], edge["to"]) + 1 for edge in edges)], default=1)
        node = {
            **commit,
            "refs": list(refs_by_commit.get(commit_hash) or []),
            "graph": {
                "column": column,
                "width": max(before_width, len(next_lanes), edge_width, 1),
                "edges": edges,
            },
        }
        nodes.append(node)
        lanes = next_lanes
    return nodes


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

    status_lines = _build_repo_status_snapshot(repo_root)["branch_lines"]
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


def get_git_commit_graph(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    scope: str = "all",
    limit: Any = GIT_COMMIT_GRAPH_DEFAULT_LIMIT,
    cursor: Any = "",
) -> dict[str, Any]:
    normalized_scope = _normalize_git_graph_scope(scope)
    normalized_limit = _normalize_git_graph_limit(limit)
    offset = _decode_git_graph_cursor(cursor, scope=normalized_scope)
    _working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    fetch_count = offset + normalized_limit + 1

    commits = _list_git_graph_commits(repo_root, scope=normalized_scope, limit=fetch_count)
    refs_by_commit = _list_git_graph_refs(repo_root)
    nodes = _layout_git_graph_nodes(commits, refs_by_commit)
    page_nodes = nodes[offset : offset + normalized_limit]
    has_more = len(nodes) > offset + normalized_limit
    return {
        "repo_found": True,
        "scope": normalized_scope,
        "nodes": page_nodes,
        "has_more": has_more,
        "next_cursor": _encode_git_graph_cursor(
            offset=offset + normalized_limit,
            scope=normalized_scope,
            head_token=_read_git_head_token(repo_root),
        )
        if has_more
        else "",
    }


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

    return {
        "repo_found": True,
        "working_dir": working_dir,
        "repo_path": repo_root,
        "items": _parse_tree_status_items(
            _build_repo_status_snapshot(repo_root)["tree_lines"],
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
    if repo_root:
        _invalidate_git_status_cache(repo_root)
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
        target = Path(target_path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            raw = handle.read(GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT + 1)
    except OSError:
        return f"--- {relative_path} ---\n[unreadable]"
    if b"\x00" in raw:
        return f"--- {relative_path} ---\n[binary file]"

    preview = raw[:GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT].decode("utf-8", errors="replace").strip()
    if size > GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT or len(raw) > GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT:
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
    params_config = with_global_extra_args(cli_config.cli_params, config.CLI_GLOBAL_EXTRA_ARGS)
    try:
        cmd, use_stdin = build_cli_command(
            cli_type=cli_type,
            resolved_cli=resolved_cli,
            user_text=prompt_text,
            env=env,
            params_config=params_config,
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

    try:
        raw_output, returncode = await asyncio.wait_for(
            _communicate_process(process, input_text=prompt_text + "\n" if use_stdin else None),
            timeout=GIT_COMMIT_MESSAGE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        _terminate_process_sync(process)
        close_process_streams(process)
        _raise(504, "git_commit_message_timeout", "生成 commit message 超时")
    except (BrokenPipeError, OSError) as exc:
        close_process_streams(process)
        _raise(500, "git_commit_message_failed", f"写入 CLI 失败: {exc}")
    finally:
        close_process_streams(process)

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
        args.append(_resolve_commit_ref(repo_root, start_point))
    try:
        _run_git(repo_root, args)
        return _list_git_branches_for_repo(repo_root)
    except GitCommandError as exc:
        _raise(400, "git_branch_create_failed", str(exc))


def reset_git_branch_to_commit(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    commit: str,
    mode: str = "mixed",
) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    reset_mode = (mode or "mixed").strip().lower()
    if reset_mode not in {"soft", "mixed", "hard"}:
        _raise(400, "invalid_git_reset_mode", "reset 模式不合法")

    full_sha = _resolve_commit_ref(repo_root, commit)
    head_result = _run_git(repo_root, ["symbolic-ref", "--short", "HEAD"], check=False)
    if head_result.returncode != 0 or not (head_result.stdout or "").strip():
        _raise(409, "git_detached_head", "当前处于 detached HEAD，无法重置分支")

    status_result = _run_git(repo_root, ["status", "--porcelain"], check=False)
    if (status_result.stdout or "").strip():
        _raise(409, "git_dirty_worktree", "工作区有未提交改动，无法重置分支")

    ancestor_result = _run_git(repo_root, ["merge-base", "--is-ancestor", full_sha, "HEAD"], check=False)
    if ancestor_result.returncode != 0:
        _raise(409, "git_commit_not_ancestor", "目标提交不是当前 HEAD 的祖先")

    try:
        _run_git(repo_root, ["reset", f"--{reset_mode}", full_sha])
    except GitCommandError as exc:
        _raise(400, "git_branch_reset_failed", str(exc))

    _invalidate_git_status_cache(repo_root)
    overview = _build_git_overview(working_dir, repo_root)
    branches = _list_git_branches_for_repo(repo_root)
    return {
        "message": "分支已重置",
        "overview": overview,
        "branches": branches["branches"],
        "current_branch": branches["current_branch"],
        "head_commit": full_sha,
    }


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

    diff_text, truncated = truncate_diff_text(result.stdout or "", limit=GIT_DIFF_OUTPUT_CHAR_LIMIT)

    return {
        "path": relative_path,
        "staged": staged,
        "diff": diff_text,
        "truncated": truncated,
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

    _invalidate_git_status_cache(repo_root)
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

    _invalidate_git_status_cache(repo_root)
    return _build_git_overview(working_dir, repo_root)


def discard_git_paths(manager: MultiBotManager, alias: str, user_id: int, paths: list[str]) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    normalized = _unique_paths([_normalize_repo_relative_path(path) for path in paths if str(path).strip()])
    if not normalized:
        _raise(400, "missing_git_paths", "至少选择一个文件")

    entries = _get_status_entries(repo_root, normalized)
    _discard_status_entries(repo_root, entries, error_code="git_discard_failed")
    _invalidate_git_status_cache(repo_root)
    return _build_git_overview(working_dir, repo_root)


def discard_all_git_changes(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    entries = _get_status_entries(repo_root)
    _discard_status_entries(repo_root, entries, error_code="git_discard_all_failed")
    _invalidate_git_status_cache(repo_root)
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

    _invalidate_git_status_cache(repo_root)
    return _build_git_overview(working_dir, repo_root)


def _run_git_action(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    args: list[str],
    *,
    error_code: str,
    error_message: str,
    remote: bool = False,
) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    try:
        _run_git(repo_root, args, env=_build_git_remote_env(repo_root) if remote else None)
    except GitCommandError as exc:
        _raise(400, error_code, str(exc))
    _invalidate_git_status_cache(repo_root)
    return _build_git_overview(working_dir, repo_root)


def fetch_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["fetch", "--all", "--prune"],
        error_code="git_fetch_failed",
        error_message="抓取远端失败",
        remote=True,
    )


def pull_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["pull", "--ff-only"],
        error_code="git_pull_failed",
        error_message="拉取远端失败",
        remote=True,
    )


def push_git_remote(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    return _run_git_action(
        manager,
        alias,
        user_id,
        ["push"],
        error_code="git_push_failed",
        error_message="推送远端失败",
        remote=True,
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
    _invalidate_git_status_cache(repo_root)
    return _build_git_overview(working_dir, repo_root)


def drop_git_stash(manager: MultiBotManager, alias: str, user_id: int, ref: str) -> dict[str, Any]:
    working_dir, repo_root = _require_repo_root(manager, alias, user_id)
    stash_ref = _normalize_stash_ref(ref)
    try:
        _run_git(repo_root, ["stash", "drop", stash_ref])
    except GitCommandError as exc:
        _raise(400, "git_stash_drop_failed", str(exc))
    _invalidate_git_status_cache(repo_root)
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
