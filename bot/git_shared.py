"""Pure helpers shared by local and remote Git services."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any


GIT_OVERVIEW_CHANGED_FILES_LIMIT = 2000
GIT_COMMIT_GRAPH_DEFAULT_LIMIT = 100
GIT_COMMIT_GRAPH_MAX_LIMIT = 300


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
