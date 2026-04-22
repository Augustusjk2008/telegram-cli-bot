"""Workspace definition resolver helpers."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .workspace_search_service import (
    _relative_path,
    _resolve_workspace_file,
    _workspace_root,
    search_workspace_text,
)

_DEFINITION_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\b"),
    re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b"),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
]


def resolve_workspace_definition(
    workspace: Path | str,
    path: str,
    *,
    line: int,
    column: int,
    symbol: str = "",
) -> dict[str, object]:
    root = _workspace_root(workspace)
    for strategy in (
        _resolve_import_or_include_target,
        _resolve_same_file_symbol,
        _resolve_workspace_symbol_search,
    ):
        items = strategy(root, path, line=line, column=column, symbol=symbol)
        if items:
            return {"items": items}
    return {"items": []}


def _resolve_import_or_include_target(
    root: Path,
    path: str,
    *,
    line: int,
    column: int,
    symbol: str,
) -> list[dict[str, object]]:
    target = _resolve_workspace_file(root, path)
    if target.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(target.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    relative_path = _relative_path(root, target)
    cursor_symbol = str(symbol or "").strip()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        node_line = int(getattr(node, "lineno", 0) or 0)
        node_end_line = int(getattr(node, "end_lineno", node_line) or node_line)
        if line < node_line or line > node_end_line:
            continue

        if isinstance(node, ast.ImportFrom):
            resolved_module = _resolve_relative_module_name(relative_path, node.module or "", int(node.level or 0))
            if not resolved_module:
                continue
            for alias in node.names:
                imported_name = alias.asname or alias.name.split(".")[-1]
                if cursor_symbol and cursor_symbol not in {imported_name, alias.name.split(".")[-1]}:
                    continue
                resolved = _resolve_python_module_target(root, resolved_module)
                if resolved is None:
                    continue
                resolved_line, resolved_column = _find_symbol_definition_in_file(resolved, alias.name.split(".")[-1] or cursor_symbol)
                return [
                    _build_result_item(
                        root,
                        resolved,
                        line=resolved_line or 1,
                        column=resolved_column,
                        match_kind="import",
                        confidence=0.97 if resolved_line else 0.9,
                    )
                ]

        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = alias.asname or alias.name.split(".")[-1]
                if cursor_symbol and cursor_symbol not in {imported_name, alias.name.split(".")[-1]}:
                    continue
                resolved = _resolve_python_module_target(root, alias.name)
                if resolved is None:
                    continue
                return [
                    _build_result_item(
                        root,
                        resolved,
                        line=1,
                        column=1,
                        match_kind="import",
                        confidence=0.92,
                    )
                ]
    return []


def _resolve_same_file_symbol(
    root: Path,
    path: str,
    *,
    line: int,
    column: int,
    symbol: str,
) -> list[dict[str, object]]:
    del line, column
    target = _resolve_workspace_file(root, path)
    resolved_symbol = str(symbol or "").strip()
    if not resolved_symbol:
        return []
    resolved_line, resolved_column = _find_symbol_definition_in_file(target, resolved_symbol)
    if not resolved_line:
        return []
    return [
        _build_result_item(
            root,
            target,
            line=resolved_line,
            column=resolved_column,
            match_kind="same_file",
            confidence=0.95,
        )
    ]


def _resolve_workspace_symbol_search(
    root: Path,
    path: str,
    *,
    line: int,
    column: int,
    symbol: str,
) -> list[dict[str, object]]:
    del path, line, column
    resolved_symbol = str(symbol or "").strip()
    if not resolved_symbol:
        return []
    result = search_workspace_text(root, resolved_symbol, limit=50)
    items = result.get("items")
    if not isinstance(items, list):
        return []

    ranked: list[tuple[float, dict[str, object]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path") or "").strip()
        if not item_path:
            continue
        preview = str(item.get("preview") or "")
        match = _is_definition_preview(preview, resolved_symbol)
        confidence = 0.78 if match else 0.42
        ranked.append(
            (
                confidence,
                {
                    "path": item_path.replace("\\", "/"),
                    "line": int(item.get("line") or 1),
                    "column": int(item.get("column") or 1),
                    "match_kind": "workspace_search",
                    "confidence": confidence,
                },
            )
        )

    ranked.sort(key=lambda item: (-item[0], str(item[1]["path"]), int(item[1]["line"])))
    return [item for _score, item in ranked[:8]]


def _resolve_relative_module_name(current_relative_path: str, module: str, level: int) -> str:
    package_parts = Path(current_relative_path).with_suffix("").parts[:-1]
    if level > 0:
        parent_parts = package_parts[: max(0, len(package_parts) - level + 1)]
    else:
        parent_parts = package_parts
    module_parts = [part for part in module.split(".") if part]
    return ".".join([*parent_parts, *module_parts]).strip(".")


def _resolve_python_module_target(root: Path, module_name: str) -> Path | None:
    if not module_name:
        return None
    module_path = Path(*module_name.split("."))
    candidates = [
        root / module_path.with_suffix(".py"),
        root / module_path / "__init__.py",
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return resolved
    return None


def _find_symbol_definition_in_file(path: Path, symbol: str) -> tuple[int, int | None]:
    resolved_symbol = str(symbol or "").strip()
    if not resolved_symbol:
        return 0, None
    content = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == resolved_symbol:
                    return int(node.lineno), int(getattr(node, "col_offset", 0)) + 1
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = list(getattr(node, "targets", []))
                    if isinstance(node, ast.AnnAssign):
                        targets = [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id == resolved_symbol:
                            return int(target.lineno), int(getattr(target, "col_offset", 0)) + 1

    needle = re.compile(rf"\b{re.escape(resolved_symbol)}\b")
    for index, text in enumerate(content.splitlines(), start=1):
        if not _is_definition_preview(text, resolved_symbol):
            continue
        matched = needle.search(text)
        return index, (matched.start() + 1) if matched else 1
    return 0, None


def _is_definition_preview(preview: str, symbol: str) -> bool:
    for pattern in _DEFINITION_PATTERNS:
        match = pattern.match(preview)
        if match and match.group(1) == symbol:
            return True
    return False


def _build_result_item(
    root: Path,
    target: Path,
    *,
    line: int,
    column: int | None,
    match_kind: str,
    confidence: float,
) -> dict[str, object]:
    item = {
        "path": _relative_path(root, target),
        "line": max(1, int(line or 1)),
        "match_kind": match_kind,
        "confidence": float(confidence),
    }
    if column and int(column) > 0:
        item["column"] = int(column)
    return item
