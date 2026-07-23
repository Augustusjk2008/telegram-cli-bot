"""Semantic workspace code-navigation helpers and legacy adapters."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Mapping

from .workspace_search_service import _relative_path, _resolve_workspace_file, _workspace_root

_PYTHON_LANGUAGE_IDS = {"python", "py"}
_NAVIGATION_KINDS = {"definition", "implementation"}


def resolve_code_navigation(
    workspace: Path | str,
    request: Mapping[str, Any],
    *,
    cursor_symbol: str = "",
) -> dict[str, object]:
    """Resolve one semantic navigation request using the temporary Python AST provider."""

    root = _workspace_root(workspace)
    kind = str(request.get("kind") or "").strip().lower()
    if kind not in _NAVIGATION_KINDS:
        raise ValueError("代码导航类型无效")

    request_id = str(request.get("requestId") or request.get("request_id") or "").strip()
    if not request_id:
        raise ValueError("缺少代码导航请求 ID")

    document = request.get("document")
    position = request.get("position")
    if not isinstance(document, Mapping) or not isinstance(position, Mapping):
        raise ValueError("代码导航请求格式无效")

    path = str(document.get("path") or "").strip()
    language_id = str(document.get("languageId") or document.get("language_id") or "").strip().lower()
    content = str(document.get("content") or "")
    line = _positive_int(position.get("line"), default=1)
    column = _positive_int(position.get("column"), default=1)

    empty_message = "未找到语义实现" if kind == "implementation" else "未找到语义定义"
    if kind == "implementation" or not path:
        return {"request_id": request_id, "items": [], "message": empty_message}

    target = _resolve_workspace_file(root, path)
    if language_id not in _PYTHON_LANGUAGE_IDS and target.suffix.lower() not in {".py", ".pyi"}:
        return {"request_id": request_id, "items": [], "message": empty_message}

    resolved_symbol = str(cursor_symbol or "").strip() or _symbol_at_position(content, line, column)
    if not resolved_symbol:
        return {"request_id": request_id, "items": [], "message": empty_message}

    locations = _resolve_python_import_target(
        root,
        target,
        content,
        line=line,
        symbol=resolved_symbol,
    )
    if not locations:
        location = _find_python_symbol_location(content, resolved_symbol)
        if location is not None:
            locations = [_build_code_location(root, target, location)]

    return {
        "request_id": request_id,
        "items": locations,
        "message": "" if locations else empty_message,
    }


def resolve_workspace_definition(
    workspace: Path | str,
    path: str,
    *,
    line: int,
    column: int,
    symbol: str = "",
) -> dict[str, object]:
    """Adapt the deprecated definition contract to semantic code navigation."""

    navigation_request = build_legacy_code_navigation_request(
        workspace,
        path,
        line=line,
        column=column,
    )
    result = resolve_code_navigation(
        workspace,
        navigation_request,
        cursor_symbol=symbol,
    )
    document = navigation_request["document"]
    source_path = str(document["path"]) if isinstance(document, Mapping) else path
    return adapt_code_navigation_to_legacy(result, source_path=source_path)


def build_legacy_code_navigation_request(
    workspace: Path | str,
    path: str,
    *,
    line: int,
    column: int,
) -> dict[str, object]:
    """Read the legacy target safely and produce the unified navigation request."""

    root = _workspace_root(workspace)
    target = _resolve_workspace_file(root, path)
    content = target.read_text(encoding="utf-8", errors="ignore")
    return {
        "kind": "definition",
        "requestId": "legacy-definition",
        "document": {
            "path": _relative_path(root, target),
            "languageId": "python" if target.suffix.lower() in {".py", ".pyi"} else "",
            "version": 0,
            "content": content,
        },
        "position": {"line": line, "column": column},
    }


def adapt_code_navigation_to_legacy(
    result: Mapping[str, object],
    *,
    source_path: str,
) -> dict[str, object]:
    """Convert normalized CodeLocation items to the deprecated response shape."""

    legacy_items: list[dict[str, object]] = []
    for item in result.get("items", []):
        if not isinstance(item, Mapping):
            continue
        selection = item.get("selection_range")
        start = selection.get("start") if isinstance(selection, Mapping) else None
        if not isinstance(start, Mapping):
            continue
        item_path = str(item.get("path") or "")
        legacy_items.append(
            {
                "path": item_path,
                "line": _positive_int(start.get("line"), default=1),
                "column": _positive_int(start.get("column"), default=1),
                "match_kind": "same_file" if item_path == source_path else "import",
                "confidence": 1.0,
            }
        )
    return {"items": legacy_items}


def _resolve_python_import_target(
    root: Path,
    source_path: Path,
    content: str,
    *,
    line: int,
    symbol: str,
) -> list[dict[str, object]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    relative_path = _relative_path(root, source_path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        node_line = int(getattr(node, "lineno", 0) or 0)
        node_end_line = int(getattr(node, "end_lineno", node_line) or node_line)
        if line < node_line or line > node_end_line:
            continue

        if isinstance(node, ast.ImportFrom):
            module_name = _resolve_relative_module_name(relative_path, node.module or "", int(node.level or 0))
            if not module_name:
                continue
            for alias in node.names:
                imported_name = alias.asname or alias.name.split(".")[-1]
                if symbol not in {imported_name, alias.name.split(".")[-1]}:
                    continue
                target = _resolve_python_module_target(root, module_name)
                if target is None:
                    continue
                target_content = target.read_text(encoding="utf-8", errors="ignore")
                location = _find_python_symbol_location(target_content, alias.name.split(".")[-1])
                if location is None:
                    location = _module_start_location(target_content)
                return [_build_code_location(root, target, location)]

        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = alias.asname or alias.name.split(".")[-1]
                if symbol not in {imported_name, alias.name.split(".")[-1]}:
                    continue
                target = _resolve_python_module_target(root, alias.name)
                if target is None:
                    continue
                target_content = target.read_text(encoding="utf-8", errors="ignore")
                return [_build_code_location(root, target, _module_start_location(target_content))]
    return []


def _find_python_symbol_location(content: str, symbol: str) -> dict[str, object] | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            selection = _definition_name_range(content, node, symbol)
            if selection is None:
                continue
            return {
                "range": _ast_node_range(node),
                "selection_range": selection,
            }

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = list(getattr(node, "targets", []))
            if isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == symbol:
                    selection = _ast_node_range(target)
                    return {
                        "range": _ast_node_range(node),
                        "selection_range": selection,
                    }
    return None


def _definition_name_range(
    content: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    symbol: str,
) -> dict[str, dict[str, int]] | None:
    lines = content.splitlines()
    line_number = int(getattr(node, "lineno", 0) or 0)
    if line_number <= 0 or line_number > len(lines):
        return None
    line_text = lines[line_number - 1]
    keyword = "class" if isinstance(node, ast.ClassDef) else "def"
    match = re.search(rf"\b{keyword}\s+({re.escape(symbol)})\b", line_text)
    if match is None:
        return None
    return {
        "start": {"line": line_number, "column": match.start(1) + 1},
        "end": {"line": line_number, "column": match.end(1) + 1},
    }


def _ast_node_range(node: ast.AST) -> dict[str, dict[str, int]]:
    start_line = _positive_int(getattr(node, "lineno", 1), default=1)
    start_column = max(1, int(getattr(node, "col_offset", 0) or 0) + 1)
    end_line = _positive_int(getattr(node, "end_lineno", start_line), default=start_line)
    end_column = max(1, int(getattr(node, "end_col_offset", start_column - 1) or 0) + 1)
    return {
        "start": {"line": start_line, "column": start_column},
        "end": {"line": end_line, "column": end_column},
    }


def _module_start_location(content: str) -> dict[str, object]:
    first_line = content.splitlines()[0] if content.splitlines() else ""
    position = {"line": 1, "column": 1}
    return {
        "range": {
            "start": position,
            "end": {"line": 1, "column": max(1, len(first_line) + 1)},
        },
        "selection_range": {"start": position, "end": position},
    }


def _build_code_location(
    root: Path,
    target: Path,
    location: Mapping[str, object],
) -> dict[str, object]:
    return {
        "target_type": "workspace",
        "path": _relative_path(root, target),
        "provider": "python-ast",
        "range": location["range"],
        "selection_range": location["selection_range"],
    }


def _symbol_at_position(content: str, line: int, column: int) -> str:
    lines = content.splitlines()
    if line <= 0 or line > len(lines):
        return ""
    text = lines[line - 1]
    if not text:
        return ""
    index = min(max(column - 1, 0), len(text) - 1)
    if not _is_symbol_character(text[index]):
        return ""
    start = index
    end = index + 1
    while start > 0 and _is_symbol_character(text[start - 1]):
        start -= 1
    while end < len(text) and _is_symbol_character(text[end]):
        end += 1
    return text[start:end]


def _is_symbol_character(value: str) -> bool:
    return value == "_" or value == "$" or value.isalnum()


def _resolve_relative_module_name(current_relative_path: str, module: str, level: int) -> str:
    package_parts = Path(current_relative_path).with_suffix("").parts[:-1]
    if level > 0:
        prefix = package_parts[: max(0, len(package_parts) - level + 1)]
    else:
        prefix = ()
    module_parts = [part for part in module.split(".") if part]
    return ".".join([*prefix, *module_parts]).strip(".")


def _resolve_python_module_target(root: Path, module_name: str) -> Path | None:
    if not module_name:
        return None
    module_path = Path(*module_name.split("."))
    for candidate in (root / module_path.with_suffix(".py"), root / module_path / "__init__.py"):
        resolved = candidate.resolve()
        if not resolved.exists() or not resolved.is_file():
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    return None


def _positive_int(value: object, *, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default
