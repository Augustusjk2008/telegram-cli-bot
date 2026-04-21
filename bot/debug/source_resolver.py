from __future__ import annotations

import json
import ntpath
from pathlib import Path, PurePosixPath
from typing import Any

from .models import DebugProfile, DebugSourceMap


def _line_from_payload(payload: dict[str, object] | None) -> int:
    try:
        return int((payload or {}).get("line") or 0)
    except (TypeError, ValueError):
        return 0


def _is_unknown_source(source: str, line: int) -> bool:
    candidate = source.strip()
    return not candidate or candidate == "??" or (candidate.startswith("??") and line <= 0) or line <= 0


def _normalize_prefix(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def _workspace_path(workspace: str | Path) -> Path:
    return Path(workspace).resolve()


def _local_candidate(path: str) -> Path:
    return Path(path).expanduser()


def _is_absolute_path(path: str) -> bool:
    return ntpath.isabs(path) or Path(path).is_absolute() or PurePosixPath(path).is_absolute()


def _resolve_local_absolute(source: str) -> str | None:
    if not _is_absolute_path(source):
        return None
    candidate = _local_candidate(source)
    if candidate.exists():
        return str(candidate.resolve())
    return None


def _map_source(source: str, source_maps: list[DebugSourceMap]) -> str | None:
    normalized_source = _normalize_prefix(source)
    for item in source_maps:
        remote = _normalize_prefix(item.remote)
        if not remote:
            continue
        if normalized_source != remote and not normalized_source.startswith(f"{remote}/"):
            continue
        relative = normalized_source[len(remote):].lstrip("/")
        return str((_local_candidate(item.local) / Path(relative)).resolve())
    return None


def _compile_commands_candidates(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    compile_path = Path(path)
    if not compile_path.is_file():
        return []
    try:
        data = json.loads(compile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _resolve_from_compile_commands(profile: DebugProfile, source: str) -> str | None:
    basename = ntpath.basename(source.replace("\\", "/"))
    if not basename:
        return None
    for item in _compile_commands_candidates(profile.compile_commands):
        if not isinstance(item, dict):
            continue
        raw_file = str(item.get("file") or "").strip()
        if not raw_file:
            continue
        directory = str(item.get("directory") or "").strip()
        file_path = Path(raw_file)
        if not file_path.is_absolute() and directory:
            file_path = Path(directory) / raw_file
        normalized_file = _normalize_prefix(str(file_path))
        normalized_source = _normalize_prefix(source)
        if ntpath.basename(normalized_file) != basename:
            continue
        if normalized_source.endswith(_normalize_prefix(raw_file)) or Path(file_path).exists():
            return str(Path(file_path).resolve())
    return None


def _resolve_by_filename(workspace: Path, source: str) -> str | None:
    basename = ntpath.basename(source.replace("\\", "/"))
    if not basename:
        return None
    try:
        matches = [item for item in workspace.rglob(basename) if item.is_file()]
    except OSError:
        return None
    if not matches:
        return None
    normalized_source = _normalize_prefix(source)
    matches.sort(key=lambda item: (not normalized_source.endswith(_normalize_prefix(str(item.relative_to(workspace)))), len(str(item))))
    return str(matches[0].resolve())


def resolve_source(
    workspace: str | Path,
    profile: DebugProfile,
    source: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    line = _line_from_payload(payload)
    candidate = str(source or "").strip()
    if _is_unknown_source(candidate, line):
        return {"path": "", "line": line, "resolved": False, "reason": "unknown_source"}

    local = _resolve_local_absolute(candidate)
    if local:
        return {"path": local, "line": line, "resolved": True, "reason": "absolute"}

    source_maps = list(profile.source_maps)
    if not source_maps and profile.remote_dir:
        source_maps = [DebugSourceMap(remote=profile.remote_dir, local=str(_workspace_path(workspace)))]

    mapped = _map_source(candidate, source_maps)
    if mapped:
        return {"path": mapped, "line": line, "resolved": True, "reason": "source_map"}

    root = _workspace_path(workspace)
    if not _is_absolute_path(candidate):
        relative = str((root / candidate).resolve())
        if Path(relative).exists():
            return {"path": relative, "line": line, "resolved": True, "reason": "workspace_relative"}

    compiled = _resolve_from_compile_commands(profile, candidate)
    if compiled:
        return {"path": compiled, "line": line, "resolved": True, "reason": "compile_commands"}

    found = _resolve_by_filename(root, candidate)
    if found:
        return {"path": found, "line": line, "resolved": True, "reason": "workspace_search"}

    fallback = str((root / candidate).resolve()) if not _is_absolute_path(candidate) else candidate
    return {"path": fallback, "line": line, "resolved": False, "reason": "not_found"}
