"""Context selection for inline completion requests."""

from __future__ import annotations

import ast
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from .inline_completion_config import InlineCompletionConfig


TS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]+\s+from\s+)?|export\s+[^'"]+\s+from\s+|require\()\s*['"](?P<path>\.{1,2}/[^'"]+)['"]"""
)
TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")


@dataclass(frozen=True)
class InlineRelatedFile:
    path: str
    content: str


@dataclass(frozen=True)
class InlineCompletionContext:
    path: str
    prefix: str
    suffix: str
    related_files: list[InlineRelatedFile] = field(default_factory=list)
    truncated: bool = False
    denied: bool = False


def build_inline_completion_context(
    *,
    workspace_root: Path | str,
    relative_path: str,
    prefix: str,
    suffix: str,
    language_id: str,
    config: InlineCompletionConfig,
) -> InlineCompletionContext:
    root = Path(workspace_root).expanduser().resolve()
    normalized_path = str(relative_path or "").replace("\\", "/").lstrip("/")
    target = (root / normalized_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return InlineCompletionContext(path=normalized_path, prefix="", suffix="", denied=True)
    if _is_denied(normalized_path, config.deny_globs):
        return InlineCompletionContext(path=normalized_path, prefix="", suffix="", denied=True)

    trimmed_prefix = str(prefix or "")[-config.max_prefix_chars :]
    trimmed_suffix = str(suffix or "")[: config.max_suffix_chars]
    truncated = len(str(prefix or "")) > len(trimmed_prefix) or len(str(suffix or "")) > len(trimmed_suffix)
    related = _collect_related_files(
        root=root,
        current_file=target,
        current_relative=normalized_path,
        source=f"{trimmed_prefix}\n{trimmed_suffix}",
        language_id=language_id,
        config=config,
    )
    return InlineCompletionContext(
        path=normalized_path,
        prefix=trimmed_prefix,
        suffix=trimmed_suffix,
        related_files=related,
        truncated=truncated,
    )


def _is_denied(relative_path: str, deny_globs: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    for pattern in deny_globs:
        candidate = str(pattern or "").replace("\\", "/").lstrip("/")
        if not candidate:
            continue
        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(Path(normalized).name, candidate):
            return True
    return False


def _collect_related_files(
    *,
    root: Path,
    current_file: Path,
    current_relative: str,
    source: str,
    language_id: str,
    config: InlineCompletionConfig,
) -> list[InlineRelatedFile]:
    if config.max_related_files <= 0:
        return []
    language = (language_id or current_file.suffix.lstrip(".")).lower()
    candidates: list[Path] = []
    if language in {"python", "py"} or current_file.suffix == ".py":
        candidates = _python_import_candidates(root, current_file, source)
    elif language in {"typescript", "typescriptreact", "javascript", "javascriptreact", "ts", "tsx", "js", "jsx"}:
        candidates = _typescript_import_candidates(current_file, source)

    related: list[InlineRelatedFile] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative == current_relative or relative in seen or _is_denied(relative, config.deny_globs):
            continue
        content = _read_related_file(resolved, config.max_related_file_bytes)
        if content is None:
            continue
        seen.add(relative)
        related.append(InlineRelatedFile(path=relative, content=content))
        if len(related) >= config.max_related_files:
            break
    return related


def _python_import_candidates(root: Path, current_file: Path, source: str) -> list[Path]:
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return []
    candidates: list[Path] = []
    current_package_dir = current_file.parent
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                candidates.extend(_resolve_python_module(root, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base_dir = root
            module = node.module or ""
            if node.level:
                base_dir = current_package_dir
                for _ in range(max(0, node.level - 1)):
                    base_dir = base_dir.parent
            has_named_child = False
            for alias in node.names:
                if alias.name == "*":
                    continue
                has_named_child = True
                child_base = base_dir.joinpath(*([*module.split("."), alias.name] if module else [alias.name]))
                candidates.extend(_python_module_path_candidates(child_base))
            if module and not has_named_child:
                module_base = base_dir.joinpath(*module.split("."))
                candidates.extend(_python_module_path_candidates(module_base))
    return _existing_files(candidates)


def _resolve_python_module(root: Path, module: str) -> list[Path]:
    if not module:
        return []
    parts = module.split(".")
    candidates: list[Path] = []
    for index in range(len(parts), 0, -1):
        candidates.extend(_python_module_path_candidates(root.joinpath(*parts[:index])))
    return candidates


def _python_module_path_candidates(base: Path) -> list[Path]:
    return [base.with_suffix(".py"), base / "__init__.py"]


def _typescript_import_candidates(current_file: Path, source: str) -> list[Path]:
    candidates: list[Path] = []
    for match in TS_IMPORT_RE.finditer(source or ""):
        raw_path = match.group("path")
        base = (current_file.parent / raw_path).resolve()
        if base.suffix:
            candidates.append(base)
        else:
            candidates.extend(base.with_suffix(ext) for ext in TS_EXTENSIONS)
            candidates.extend(base / f"index{ext}" for ext in TS_EXTENSIONS)
    return _existing_files(candidates)


def _existing_files(candidates: list[Path]) -> list[Path]:
    existing: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        existing.append(candidate)
    return existing


def _read_related_file(path: Path, limit_bytes: int) -> str | None:
    try:
        data = path.read_bytes()[:limit_bytes]
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")
