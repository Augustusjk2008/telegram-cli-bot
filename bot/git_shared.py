"""Pure helpers shared by local and remote Git services."""

from __future__ import annotations

import re
from typing import Any


GIT_OVERVIEW_CHANGED_FILES_LIMIT = 2000


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
