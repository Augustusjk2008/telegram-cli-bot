"""Workspace quick-open, text search and outline helpers."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

DEFAULT_EXCLUDES = [".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"]

_SOURCE_ROOTS = {"src", "bot", "front", "tests", "scripts"}
_SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".css",
    ".html",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".sh",
    ".ps1",
    ".yml",
    ".yaml",
    ".toml",
}


def _workspace_root(workspace: Path | str) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("工作目录不存在")
    return root


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _resolve_workspace_file(root: Path, path: str) -> Path:
    raw = Path(path)
    target = raw if raw.is_absolute() else root / raw
    resolved = target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("路径不在工作目录内") from exc
    if not resolved.exists() or not resolved.is_file():
        raise ValueError("文件不存在")
    return resolved


def _exclude_args() -> list[str]:
    args: list[str] = []
    for name in DEFAULT_EXCLUDES:
        args.extend(["--glob", f"!{name}/**", "--glob", f"!**/{name}/**"])
    return args


def _run_rg(root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    if not shutil.which("rg"):
        return None
    try:
        return subprocess.run(
            ["rg", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _iter_files_with_os_walk(root: Path) -> Iterable[str]:
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if item not in DEFAULT_EXCLUDES]
        base = Path(current_root)
        for filename in files:
            try:
                yield _relative_path(root, base / filename)
            except ValueError:
                continue


def _list_workspace_files(root: Path) -> list[str]:
    result = _run_rg(root, ["--files", "--hidden", *_exclude_args()])
    if result is not None and result.returncode in {0, 1}:
        return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    return list(_iter_files_with_os_walk(root))


def _quick_open_score(path: str, query: str) -> int:
    if not query:
        return 1

    normalized_path = path.lower()
    q = query.lower()
    basename = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    parts = [part.lower() for part in path.split("/")]
    score = 0

    if basename == q:
        score += 5000
    elif basename.startswith(q):
        score += 3000
    elif q in basename:
        score += 2000

    if normalized_path == q:
        score += 1200
    elif normalized_path.startswith(q):
        score += 800
    elif q in normalized_path:
        score += 300

    if parts and parts[0] in _SOURCE_ROOTS:
        score += 200
    if suffix in _SOURCE_SUFFIXES:
        score += 40
    score -= min(len(path), 240)
    return score


def quick_open_files(workspace: Path | str, query: str, *, limit: int = 50) -> dict[str, object]:
    root = _workspace_root(workspace)
    q = (query or "").strip()
    safe_limit = max(1, min(int(limit or 50), 200))
    items: list[tuple[int, int, str]] = []

    for index, path in enumerate(_list_workspace_files(root)):
        normalized = path.replace("\\", "/")
        if q and q.lower() not in normalized.lower():
            continue
        score = _quick_open_score(normalized, q)
        if q and score <= 0:
            continue
        items.append((score, index, normalized))

    items.sort(key=lambda item: (-item[0], item[1], item[2]))
    return {
        "items": [
            {"path": path, "score": score}
            for score, _index, path in items[:safe_limit]
        ]
    }


def _preview_line(text: str) -> str:
    return text.rstrip("\r\n")


def _search_with_rg(root: Path, query: str, limit: int) -> list[dict[str, Any]] | None:
    result = _run_rg(
        root,
        [
            "--line-number",
            "--column",
            "--json",
            "--hidden",
            "--fixed-strings",
            query,
            *_exclude_args(),
        ],
    )
    if result is None:
        return None
    if result.returncode not in {0, 1}:
        return []

    items: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if len(items) >= limit:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        path_data = data.get("path") if isinstance(data.get("path"), dict) else {}
        lines_data = data.get("lines") if isinstance(data.get("lines"), dict) else {}
        submatches = data.get("submatches") if isinstance(data.get("submatches"), list) else []
        first_match = submatches[0] if submatches and isinstance(submatches[0], dict) else {}
        path = str(path_data.get("text") or "").replace("\\", "/")
        if not path:
            continue
        column = int(first_match.get("start") or 0) + 1
        items.append({
            "path": path,
            "line": int(data.get("line_number") or 0),
            "column": column,
            "preview": _preview_line(str(lines_data.get("text") or "")),
        })
    return items


def _search_with_python(root: Path, query: str, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    needle = query.lower()
    for rel_path in _iter_files_with_os_walk(root):
        if len(items) >= limit:
            break
        path = root / rel_path
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, text in enumerate(lines, start=1):
            column = text.lower().find(needle)
            if column < 0:
                continue
            items.append({
                "path": rel_path,
                "line": line_number,
                "column": column + 1,
                "preview": text,
            })
            if len(items) >= limit:
                break
    return items


def search_workspace_text(workspace: Path | str, query: str, *, limit: int = 100) -> dict[str, object]:
    root = _workspace_root(workspace)
    q = (query or "").strip()
    safe_limit = max(1, min(int(limit or 100), 500))
    if not q:
        return {"items": []}

    items = _search_with_rg(root, q, safe_limit)
    if items is None:
        items = _search_with_python(root, q, safe_limit)
    return {"items": items[:safe_limit]}


def _python_outline(content: str) -> list[dict[str, object]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    items: list[dict[str, object]] = []

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                items.append({"name": node.name, "kind": "class", "line": node.lineno})
                visit(list(node.body))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                items.append({"name": node.name, "kind": "function", "line": node.lineno})
                visit(list(node.body))

    visit(list(tree.body))
    items.sort(key=lambda item: int(item["line"]))
    return items


def _markdown_outline(content: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            items.append({"name": match.group(2).strip(), "kind": "heading", "line": index})
    return items


def _generic_code_outline(content: str) -> list[dict[str, object]]:
    patterns = [
        ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")),
        ("method", re.compile(r"^\s*(?:public|private|protected|static|async|\s)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")),
    ]
    items: list[dict[str, object]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        for kind, pattern in patterns:
            match = pattern.match(line)
            if match:
                name = match.group(1)
                if name not in {"if", "for", "while", "switch", "catch"}:
                    items.append({"name": name, "kind": kind, "line": index})
                break
    return items


def build_file_outline(workspace: Path | str, path: str) -> dict[str, object]:
    root = _workspace_root(workspace)
    target = _resolve_workspace_file(root, path)
    content = target.read_text(encoding="utf-8", errors="ignore")
    suffix = target.suffix.lower()

    if suffix == ".py":
        items = _python_outline(content)
    elif suffix in {".md", ".markdown"}:
        items = _markdown_outline(content)
    else:
        items = _generic_code_outline(content)

    return {"items": items}
