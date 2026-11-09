"""Pure helpers shared by local and remote Git services."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any
from urllib.parse import urlsplit


GIT_OVERVIEW_CHANGED_FILES_LIMIT = 2000
GIT_COMMIT_GRAPH_DEFAULT_LIMIT = 100
GIT_COMMIT_GRAPH_MAX_LIMIT = 300
GIT_REMOTE_NAME_MAX_LENGTH = 64
GIT_REMOTE_URL_MAX_LENGTH = 2048
GITHUB_HOST = "github.com"

_GIT_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GIT_REMOTE_URL_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_GIT_REMOTE_URL_SCHEMES = frozenset({"https", "http", "ssh", "git", "file"})
# scp-like syntax requires an explicit user so it cannot be confused with a
# Windows drive path such as ``C:\repo``.
_GIT_SCP_URL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._~-]*@[A-Za-z0-9][A-Za-z0-9.-]*:(?!//)\S+$")
_GITHUB_TOKEN_TEXT_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_GITHUB_OWNER_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_GITHUB_REPO_PATTERN = r"[A-Za-z0-9._-]+?"
_GITHUB_HTTPS_REMOTE_RE = re.compile(
    rf"^https?://(?:[^/@\s]+@)?(?:www\.)?github\.com(?::443)?/({_GITHUB_OWNER_PATTERN})/({_GITHUB_REPO_PATTERN})(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_REMOTE_RE = re.compile(
    rf"^ssh://git@(?:ssh\.)?github\.com(?::(?:22|443))?/({_GITHUB_OWNER_PATTERN})/({_GITHUB_REPO_PATTERN})(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SCP_REMOTE_RE = re.compile(
    rf"^git@github\.com:({_GITHUB_OWNER_PATTERN})/({_GITHUB_REPO_PATTERN})(?:\.git)?/?$",
    re.IGNORECASE,
)


class GitRemoteInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def redact_git_secret_text(value: object) -> str:
    """Remove credentials that Git or a remote may echo into diagnostics."""
    text = str(value or "")
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1", text)
    text = re.sub(
        r"(?i)(?<![\w])[^@\s/:]+@(?=[A-Za-z0-9._-]+(?::\d+)?[:/])",
        "",
        text,
    )
    text = re.sub(
        r"(?i)([?&](?:access[_-]?token|auth[_-]?token|password|passwd|secret|token)\s*=\s*)[^&\s]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)(\bauthorization\s*:\s*(?:basic|bearer|token)\s+)[^\s\r\n]+", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)(\b(?:authorization\s*:\s*bearer|(?:git|ssh)_askpass|askpass(?:_command)?|password|passwd|secret|token)\s*(?:[:=]|\s)\s*)[^\s\r\n]+",
        r"\1<redacted>",
        text,
    )
    return _GITHUB_TOKEN_TEXT_RE.sub("<redacted>", text)


def _looks_like_token(value: str) -> bool:
    return bool(_GITHUB_TOKEN_TEXT_RE.fullmatch(value or ""))


def normalize_git_remote_name(name: Any) -> str:
    """Validate a remote name chosen in Orbit.

    Git itself accepts names such as ``-origin``; Orbit restricts new names to
    a conservative set so they can never be parsed as command options.
    """
    value = str(name or "").strip()
    if not value:
        raise GitRemoteInputError("invalid_git_remote_name", "远端名称不能为空")
    if (
        len(value) > GIT_REMOTE_NAME_MAX_LENGTH
        or not _GIT_REMOTE_NAME_RE.fullmatch(value)
        or ".." in value
        or value.endswith((".", ".lock"))
    ):
        raise GitRemoteInputError(
            "invalid_git_remote_name",
            "远端名称只能包含字母、数字、点、下划线和连字符，并以字母或数字开头",
        )
    return value


def normalize_existing_git_remote_name(name: Any) -> str:
    """Validate the name of a remote that may have been created outside Orbit."""
    value = str(name or "").strip()
    if not value or len(value) > 255:
        raise GitRemoteInputError("invalid_git_remote_name", "远端名称不合法")
    if value.startswith("-") or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise GitRemoteInputError("invalid_git_remote_name", "远端名称不合法")
    return value


def normalize_git_remote_url(url: Any) -> str:
    value = str(url or "").strip()
    if not value:
        raise GitRemoteInputError("invalid_git_remote_url", "远端地址不能为空")
    if len(value) > GIT_REMOTE_URL_MAX_LENGTH:
        raise GitRemoteInputError("invalid_git_remote_url", "远端地址过长")
    if value.startswith("-") or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise GitRemoteInputError("invalid_git_remote_url", "远端地址不能以 - 开头，也不能包含空白或控制字符")

    scheme_match = _GIT_REMOTE_URL_SCHEME_RE.match(value)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in _GIT_REMOTE_URL_SCHEMES:
            raise GitRemoteInputError(
                "invalid_git_remote_url",
                "仅支持 https、http、ssh、git、file 地址或 user@host:path 形式",
            )
        try:
            parsed = urlsplit(value)
            parsed.port  # noqa: B018 - validates the port range
        except ValueError as exc:
            raise GitRemoteInputError("invalid_git_remote_url", "远端地址格式不正确") from exc
        if scheme != "file" and not parsed.hostname:
            raise GitRemoteInputError("invalid_git_remote_url", "远端地址缺少主机名")
        # A leading dash could be read as an ssh option by older transports.
        if (parsed.hostname or "").startswith("-") or (parsed.username or "").startswith("-"):
            raise GitRemoteInputError("invalid_git_remote_url", "远端地址的主机名或用户名不能以 - 开头")
        if parsed.password is not None or _looks_like_token(parsed.username or ""):
            raise GitRemoteInputError(
                "git_remote_url_has_credentials",
                "远端地址不能包含密码或令牌；请连接 GitHub 账号或使用系统 Git 凭据",
            )
        return value

    if _GIT_SCP_URL_RE.fullmatch(value):
        return value
    raise GitRemoteInputError(
        "invalid_git_remote_url",
        "仅支持 https、http、ssh、git、file 地址或 user@host:path 形式",
    )


def redact_git_url(url: str) -> tuple[str, bool]:
    """Return a URL safe for display and whether it carried credentials."""
    value = str(url or "")
    scheme_match = _GIT_REMOTE_URL_SCHEME_RE.match(value)
    if not scheme_match:
        return value, False
    prefix = scheme_match.group(0)
    rest = value[len(prefix):]
    authority, slash, path = rest.partition("/")
    userinfo, at, host = authority.rpartition("@")
    if not at:
        return value, False
    username, colon, _password = userinfo.partition(":")
    if not colon and not _looks_like_token(username):
        return value, False
    return f"{prefix}{host}{slash}{path}", True


def git_url_protocol(url: str) -> str:
    value = str(url or "")
    scheme_match = _GIT_REMOTE_URL_SCHEME_RE.match(value)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        return scheme if scheme in _GIT_REMOTE_URL_SCHEMES else "other"
    if _GIT_SCP_URL_RE.fullmatch(value):
        return "ssh"
    return "other"


def parse_github_remote(url: str) -> dict[str, str] | None:
    value = str(url or "").strip()
    for pattern, protocol in (
        (_GITHUB_HTTPS_REMOTE_RE, "https"),
        (_GITHUB_SSH_REMOTE_RE, "ssh"),
        (_GITHUB_SCP_REMOTE_RE, "ssh"),
    ):
        match = pattern.fullmatch(value)
        if match:
            owner, repo = match.group(1), match.group(2)
            return {
                "owner": owner,
                "repo": repo,
                "full_name": f"{owner}/{repo}",
                "html_url": f"https://{GITHUB_HOST}/{owner}/{repo}",
                "protocol": protocol,
            }
    return None


def parse_git_remote_verbose(text: str) -> list[dict[str, Any]]:
    """Parse ``git remote -v`` while keeping the configured order."""
    remotes: dict[str, dict[str, Any]] = {}
    for line in str(text or "").splitlines():
        name, tab, rest = line.partition("\t")
        if not tab or not name:
            continue
        if rest.endswith(" (fetch)"):
            kind, url = "fetch_urls", rest[: -len(" (fetch)")]
        elif rest.endswith(" (push)"):
            kind, url = "push_urls", rest[: -len(" (push)")]
        else:
            continue
        entry = remotes.setdefault(name, {"name": name, "fetch_urls": [], "push_urls": []})
        entry[kind].append(url)
    return list(remotes.values())


def build_git_remote_entry(name: str, fetch_urls: list[str], push_urls: list[str]) -> dict[str, Any]:
    fetch_url = fetch_urls[0] if fetch_urls else ""
    push_url = push_urls[0] if push_urls else fetch_url
    display_fetch, fetch_credentials = redact_git_url(fetch_url)
    display_push, push_credentials = redact_git_url(push_url)
    return {
        "name": name,
        "fetch_url": display_fetch,
        "push_url": display_push,
        "protocol": git_url_protocol(push_url or fetch_url),
        "has_embedded_credentials": fetch_credentials or push_credentials,
        "github": parse_github_remote(fetch_url) or parse_github_remote(push_url),
    }


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


def _porcelain_status_entry(status: str, path: str, original_path: str = "") -> dict[str, Any]:
    if status == "??":
        return {
            "path": path,
            "original_path": "",
            "status": "??",
            "staged": False,
            "unstaged": False,
            "untracked": True,
        }
    return {
        "path": path,
        "original_path": original_path,
        "status": status,
        "staged": status[0] not in (" ", "?"),
        "unstaged": status[1] != " ",
        "untracked": False,
    }


def _parse_porcelain_entry(raw_line: str) -> dict[str, Any] | None:
    """Parse an internal ``XY path`` line built from NUL-delimited Git output.

    The path after the status and separator is kept verbatim: it is never
    C-quoted, trimmed or split on `` -> ``, so spaces, non-ASCII characters and
    arrow-like names survive.
    """
    if not raw_line or raw_line.startswith("## ") or len(raw_line) < 4 or raw_line[2] != " ":
        return None
    return _porcelain_status_entry(raw_line[:2], raw_line[3:])


def _parse_porcelain_v1_z(status_text: str) -> list[dict[str, Any]]:
    """Parse ``git status --porcelain=1 -z`` records.

    Renames and copies are ``XY new<NUL>old<NUL>``: the destination comes first,
    followed by the original path, with no `` -> `` separator.
    """
    entries: list[dict[str, Any]] = []
    records = (status_text or "").split("\x00")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or record.startswith("## ") or len(record) < 4 or record[2] != " ":
            continue
        status = record[:2]
        original_path = ""
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            if index < len(records):
                original_path = records[index]
                index += 1
        entries.append(_porcelain_status_entry(status, record[3:], original_path))
    return entries


def _format_porcelain_entries(entries: list[dict[str, Any]]) -> str:
    """Render parsed status entries as readable, unquoted ``--short`` lines."""
    lines: list[str] = []
    for entry in entries:
        path = str(entry.get("path") or "")
        original_path = str(entry.get("original_path") or "")
        target = f"{original_path} -> {path}" if original_path else path
        lines.append(f"{entry.get('status') or '  '} {target}")
    return "\n".join(lines)


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


def _zero_changed_file_stats() -> dict[str, int]:
    return {
        "additions": 0,
        "deletions": 0,
        "staged_additions": 0,
        "staged_deletions": 0,
        "unstaged_additions": 0,
        "unstaged_deletions": 0,
    }


def _parse_porcelain_v2_z(status_text: str) -> tuple[str, list[str]]:
    branch_head = ""
    upstream = ""
    ahead = 0
    behind = 0
    tree_lines: list[str] = []
    records = (status_text or "").split("\x00")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("# branch.head "):
            branch_head = record.removeprefix("# branch.head ").strip()
            continue
        if record.startswith("# branch.upstream "):
            upstream = record.removeprefix("# branch.upstream ").strip()
            continue
        if record.startswith("# branch.ab "):
            match = re.search(r"\+(\d+)\s+-(\d+)", record)
            if match:
                ahead, behind = int(match.group(1)), int(match.group(2))
            continue
        if record.startswith("1 "):
            parts = record.split(" ", 8)
            if len(parts) >= 9:
                tree_lines.append(f"{parts[1].replace('.', ' ')} {parts[8]}")
            continue
        if record.startswith("2 "):
            parts = record.split(" ", 9)
            if len(parts) >= 10:
                tree_lines.append(f"{parts[1].replace('.', ' ')} {parts[9]}")
                if index < len(records):
                    index += 1
            continue
        if record.startswith("u "):
            parts = record.split(" ", 10)
            if len(parts) >= 11:
                tree_lines.append(f"{parts[1].replace('.', ' ')} {parts[10]}")

    display_branch = branch_head if branch_head and branch_head != "(detached)" else "HEAD (no branch)"
    header = f"## {display_branch}"
    if upstream:
        header += f"...{upstream}"
    tracking: list[str] = []
    if ahead:
        tracking.append(f"ahead {ahead}")
    if behind:
        tracking.append(f"behind {behind}")
    if tracking:
        header += f" [{', '.join(tracking)}]"
    return header, tree_lines


class GitGraphInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _parse_tree_status_kind(status: str) -> str | None:
    if status == "!!":
        return "ignored"
    if status == "??" or status.startswith("A"):
        return "added"
    if "D" in status:
        return None
    return "modified" if status.strip() else None


def _normalize_git_graph_scope(scope: str) -> str:
    value = str(scope or "all").strip().lower()
    if value not in {"current", "all"}:
        raise GitGraphInputError("invalid_git_graph_scope", "版本树范围不合法")
    return value


def _normalize_git_graph_limit(limit: Any) -> int:
    text = "" if limit is None else str(limit).strip()
    if not text:
        return GIT_COMMIT_GRAPH_DEFAULT_LIMIT
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise GitGraphInputError("invalid_limit", "limit 必须是 1-300 的整数")
    if value < 1 or value > GIT_COMMIT_GRAPH_MAX_LIMIT:
        raise GitGraphInputError("invalid_limit", "limit 必须是 1-300 的整数")
    return value


def _decode_git_graph_cursor(cursor: Any, *, scope: str) -> int:
    value = str(cursor or "").strip()
    if not value:
        return 0
    try:
        padded = value + ("=" * (-len(value) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise GitGraphInputError("invalid_cursor", "cursor 不合法")

    if not isinstance(payload, dict):
        raise GitGraphInputError("invalid_cursor", "cursor 不合法")
    if payload.get("scope") != scope:
        raise GitGraphInputError("invalid_cursor", "cursor 不合法")
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise GitGraphInputError("invalid_cursor", "cursor 不合法")
    return offset


def _encode_git_graph_cursor(*, offset: int, scope: str, head_token: str) -> str:
    payload = json.dumps(
        {"offset": offset, "scope": scope, "head": head_token},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _git_graph_ref_kind(refname: str) -> tuple[str, str] | None:
    if refname.startswith("refs/heads/"):
        return "local_branch", refname.removeprefix("refs/heads/")
    if refname.startswith("refs/remotes/"):
        return "remote_branch", refname.removeprefix("refs/remotes/")
    if refname.startswith("refs/tags/"):
        return "tag", refname.removeprefix("refs/tags/")
    return None


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
