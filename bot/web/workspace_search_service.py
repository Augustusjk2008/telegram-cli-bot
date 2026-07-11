"""Workspace quick-open, text search and outline helpers."""

from __future__ import annotations

import ast
import heapq
import json
import os
import re
import shutil
import subprocess
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import workspace_index_service
from bot.platform.processes import terminate_process_tree_sync

DEFAULT_EXCLUDES = [".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"]
SEARCH_TIMEOUT_SECONDS = max(0.1, float(os.environ.get("TCB_SEARCH_TIMEOUT_SECONDS", "10")))
SEARCH_STDOUT_MAX_BYTES = max(1024, int(os.environ.get("TCB_SEARCH_STDOUT_MAX_BYTES", str(8 * 1024 * 1024))))
SEARCH_STDERR_MAX_BYTES = max(1024, int(os.environ.get("TCB_SEARCH_STDERR_MAX_BYTES", str(64 * 1024))))
SEARCH_MAX_LINE_BYTES = max(1024, int(os.environ.get("TCB_SEARCH_MAX_LINE_BYTES", str(1024 * 1024))))
SEARCH_PYTHON_MAX_SCAN_BYTES = max(1024, int(os.environ.get("TCB_SEARCH_PYTHON_MAX_SCAN_BYTES", str(64 * 1024 * 1024))))
_SEARCH_DIAGNOSTICS_LOCK = threading.Lock()
_SEARCH_DIAGNOSTICS = {
    "active_processes": 0,
    "search_count": 0,
    "timeout_count": 0,
    "truncated_count": 0,
    "stdout_bytes": 0,
    "stderr_bytes": 0,
}


@dataclass(slots=True)
class _SearchOutcome:
    items: list[dict[str, Any]]
    truncated: bool
    reason: str
    backend: str


def workspace_search_diagnostics() -> dict[str, int]:
    with _SEARCH_DIAGNOSTICS_LOCK:
        return dict(_SEARCH_DIAGNOSTICS)


def _diag_add(**values: int) -> None:
    with _SEARCH_DIAGNOSTICS_LOCK:
        for key, value in values.items():
            _SEARCH_DIAGNOSTICS[key] = int(_SEARCH_DIAGNOSTICS.get(key, 0)) + int(value)

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


def normalize_workspace_path_input(path: str) -> str:
    """Normalize Web workspace paths to slash-separated virtual paths."""
    text = str(path or "").strip()
    if "\x00" in text:
        raise ValueError("路径不合法")
    return text.replace("\\", "/")


def _resolve_workspace_file(root: Path, path: str) -> Path:
    raw = Path(normalize_workspace_path_input(path))
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


def _iter_quick_open_candidates(paths: Iterable[str], q: str) -> Iterable[tuple[int, int, str]]:
    lowered_query = q.lower()
    for index, path in enumerate(paths):
        normalized = path.replace("\\", "/")
        if lowered_query and lowered_query not in normalized.lower():
            continue
        score = _quick_open_score(normalized, q)
        if lowered_query and score <= 0:
            continue
        yield (score, index, normalized)


def quick_open_files(workspace: Path | str, query: str, *, limit: int = 50) -> dict[str, object]:
    root = _workspace_root(workspace)
    q = (query or "").strip()
    safe_limit = max(1, min(int(limit or 50), 200))
    items = heapq.nsmallest(
        safe_limit,
        _iter_quick_open_candidates(
            workspace_index_service.get_workspace_files(root, _list_workspace_files),
            q,
        ),
        key=lambda item: (-item[0], item[2], item[1]),
    )
    return {
        "items": [
            {"path": path, "score": score}
            for score, _index, path in items
        ]
    }


def _preview_line(text: str) -> str:
    return text.rstrip("\r\n")


def _search_with_rg(root: Path, query: str, limit: int) -> _SearchOutcome | None:
    if not shutil.which("rg"):
        return None
    items: list[dict[str, Any]] = []
    process: subprocess.Popen[bytes] | None = None
    stdout_queue: queue.Queue[bytes | object] = queue.Queue(maxsize=64)
    reader_done = object()
    stop_reader = threading.Event()
    state_lock = threading.Lock()
    state = {"stdout_bytes": 0, "stderr_bytes": 0, "reason": ""}

    def set_reason(reason: str) -> None:
        with state_lock:
            if not state["reason"]:
                state["reason"] = reason

    def read_stdout(stream) -> None:
        try:
            while not stop_reader.is_set():
                line = stream.readline(SEARCH_MAX_LINE_BYTES + 1)
                if not line:
                    break
                with state_lock:
                    state["stdout_bytes"] += len(line)
                    total = state["stdout_bytes"]
                if len(line) > SEARCH_MAX_LINE_BYTES:
                    set_reason("line_bytes")
                    break
                if total > SEARCH_STDOUT_MAX_BYTES:
                    set_reason("stdout_bytes")
                    break
                while not stop_reader.is_set():
                    try:
                        stdout_queue.put(line, timeout=0.05)
                        break
                    except queue.Full:
                        continue
        finally:
            try:
                stdout_queue.put(reader_done, timeout=0.1)
            except queue.Full:
                pass

    def read_stderr(stream) -> None:
        while not stop_reader.is_set():
            chunk = stream.read(min(8192, SEARCH_STDERR_MAX_BYTES + 1))
            if not chunk:
                return
            with state_lock:
                state["stderr_bytes"] += len(chunk)
                total = state["stderr_bytes"]
            if total > SEARCH_STDERR_MAX_BYTES:
                set_reason("stderr_bytes")
                return

    truncated = False
    reason = ""
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    try:
        process = subprocess.Popen(
            ["rg", "--line-number", "--column", "--json", "--hidden", "--fixed-strings", query, *_exclude_args()],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _diag_add(active_processes=1, search_count=1)
        assert process.stdout is not None and process.stderr is not None
        stdout_thread = threading.Thread(target=read_stdout, args=(process.stdout,), daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, args=(process.stderr,), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
        while True:
            if time.monotonic() >= deadline:
                truncated = True
                reason = "timeout"
                break
            with state_lock:
                reader_reason = str(state["reason"])
            if reader_reason:
                truncated = True
                reason = reader_reason
                break
            try:
                queued = stdout_queue.get(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                if process.poll() is not None and stdout_thread is not None and not stdout_thread.is_alive():
                    break
                continue
            if queued is reader_done:
                with state_lock:
                    reader_reason = str(state["reason"])
                if reader_reason:
                    truncated = True
                    reason = reader_reason
                break
            assert isinstance(queued, bytes)
            try:
                event = json.loads(queued.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            path_data = data.get("path") if isinstance(data.get("path"), dict) else {}
            lines_data = data.get("lines") if isinstance(data.get("lines"), dict) else {}
            submatches = data.get("submatches") if isinstance(data.get("submatches"), list) else []
            first_match = submatches[0] if submatches and isinstance(submatches[0], dict) else {}
            path = str(path_data.get("text") or "").replace("\\", "/")
            if path:
                items.append({
                    "path": path,
                    "line": int(data.get("line_number") or 0),
                    "column": int(first_match.get("start") or 0) + 1,
                    "preview": _preview_line(str(lines_data.get("text") or "")),
                })
            if len(items) >= limit:
                truncated = True
                reason = "limit"
                break
    except OSError:
        return None
    finally:
        stop_reader.set()
        if process is not None:
            if process.poll() is None and (truncated or reason):
                terminate_process_tree_sync(process)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                terminate_process_tree_sync(process)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            _diag_add(active_processes=-1)
        for thread in (stdout_thread, stderr_thread):
            if thread is not None:
                thread.join(timeout=0.2)
        with state_lock:
            stdout_bytes = int(state["stdout_bytes"])
            stderr_bytes = int(state["stderr_bytes"])
        _diag_add(
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            timeout_count=int(reason == "timeout"),
            truncated_count=int(truncated),
        )
    if process is not None and process.returncode not in {0, 1} and not reason:
        items = []
        truncated = True
        reason = "rg_error"
        _diag_add(truncated_count=1)
    return _SearchOutcome(items=items, truncated=truncated, reason=reason, backend="rg")


def _search_with_python(root: Path, query: str, limit: int) -> _SearchOutcome:
    items: list[dict[str, Any]] = []
    needle = query.lower()
    deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
    scanned_bytes = 0
    truncated = False
    reason = ""
    for rel_path in _iter_files_with_os_walk(root):
        if len(items) >= limit:
            truncated = True
            reason = "limit"
            break
        if time.monotonic() >= deadline:
            truncated = True
            reason = "timeout"
            break
        path = root / rel_path
        try:
            file_size = int(path.stat().st_size)
            if scanned_bytes + file_size > SEARCH_PYTHON_MAX_SCAN_BYTES:
                truncated = True
                reason = "scan_bytes"
                break
            scanned_bytes += file_size
            if file_size > 2 * 1024 * 1024:
                continue
            stream = path.open("rb")
        except OSError:
            continue
        with stream:
            line_number = 0
            while True:
                raw_line = stream.readline(SEARCH_MAX_LINE_BYTES + 1)
                if not raw_line:
                    break
                line_number += 1
                if len(raw_line) > SEARCH_MAX_LINE_BYTES:
                    truncated = True
                    reason = "line_bytes"
                    break
                if time.monotonic() >= deadline:
                    truncated = True
                    reason = "timeout"
                    break
                text = raw_line.decode("utf-8", errors="ignore")
                column = text.lower().find(needle)
                if column < 0:
                    continue
                items.append({
                    "path": rel_path,
                    "line": line_number,
                    "column": column + 1,
                    "preview": _preview_line(text),
                })
                if len(items) >= limit:
                    truncated = True
                    reason = "limit"
                    break
        if truncated:
            break
    _diag_add(
        search_count=1,
        timeout_count=int(reason == "timeout"),
        truncated_count=int(truncated),
        stdout_bytes=scanned_bytes,
    )
    return _SearchOutcome(items=items, truncated=truncated, reason=reason, backend="python")


def search_workspace_text(workspace: Path | str, query: str, *, limit: int = 100) -> dict[str, object]:
    root = _workspace_root(workspace)
    q = (query or "").strip()
    safe_limit = max(1, min(int(limit or 100), 500))
    if not q:
        return {"items": [], "truncated": False, "reason": "", "backend": "none"}

    outcome = _search_with_rg(root, q, safe_limit)
    if outcome is None:
        outcome = _search_with_python(root, q, safe_limit)
    return {
        "items": outcome.items[:safe_limit],
        "truncated": outcome.truncated,
        "reason": outcome.reason,
        "backend": outcome.backend,
    }


def _outline_item(name: str, kind: str, line: int, *, level: int) -> dict[str, object]:
    return {
        "name": name,
        "kind": kind,
        "line": int(line),
        "level": int(level),
        "children": [],
    }


def _outline_children(item: dict[str, object]) -> list[dict[str, object]]:
    children = item.get("children")
    if isinstance(children, list):
        return children
    item["children"] = []
    return item["children"]  # type: ignore[return-value]


def _python_outline(content: str) -> list[dict[str, object]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    def convert(node: ast.stmt, *, level: int, parent_kind: str = "") -> dict[str, object] | None:
        if isinstance(node, ast.ClassDef):
            item = _outline_item(node.name, "class", node.lineno, level=level)
            child_parent_kind = "class"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if parent_kind == "class" else "function"
            item = _outline_item(node.name, kind, node.lineno, level=level)
            child_parent_kind = kind
        else:
            return None

        children = _outline_children(item)
        for child in getattr(node, "body", []):
            if not isinstance(child, ast.stmt):
                continue
            child_item = convert(child, level=level + 1, parent_kind=child_parent_kind)
            if child_item is not None:
                children.append(child_item)
        return item

    items: list[dict[str, object]] = []
    for node in tree.body:
        item = convert(node, level=1)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: int(item["line"]))
    return items


def _markdown_outline(content: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    stack: list[tuple[int, dict[str, object]]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        item = _outline_item(match.group(2).strip(), "heading", index, level=level)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            _outline_children(stack[-1][1]).append(item)
        else:
            items.append(item)
        stack.append((level, item))
    return items


def _generic_code_outline(content: str) -> list[dict[str, object]]:
    patterns = [
        ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")),
        ("method", re.compile(r"^\s*(?:public|private|protected|static|async|\s)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")),
    ]
    items: list[dict[str, object]] = []
    stack: list[tuple[int, dict[str, object]]] = []
    brace_depth = 0

    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        leading_closes = len(stripped) - len(stripped.lstrip("}"))
        effective_depth = max(0, brace_depth - leading_closes)
        while stack and effective_depth <= stack[-1][0]:
            stack.pop()

        matched_kind = ""
        matched_name = ""
        for kind, pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch"}:
                break
            matched_kind = kind
            matched_name = name
            break

        if matched_kind and matched_name:
            parent = stack[-1][1] if stack else None
            level = len(stack) + 1
            item = _outline_item(matched_name, matched_kind, index, level=level)
            if parent is not None and matched_kind in {"method", "function"}:
                _outline_children(parent).append(item)
            else:
                items.append(item)
            if "{" in line and matched_kind in {"class", "function", "method"}:
                stack.append((effective_depth, item))

        brace_depth = max(0, brace_depth + line.count("{") - line.count("}"))

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
