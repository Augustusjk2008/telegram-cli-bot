from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class LocatedTranscript:
    provider: Literal["codex", "claude", "kimi"]
    session_id: str
    path: Path
    cwd_hint: str | None = None


_LOCATOR_CACHE_LOCK = threading.Lock()
_LOCATOR_CACHE: dict[tuple[str, str, str, str], LocatedTranscript] = {}


def clear_history_locator_cache() -> None:
    with _LOCATOR_CACHE_LOCK:
        _LOCATOR_CACHE.clear()


def _locator_cache_key(provider: str, session_id: str, cwd_hint: str | None, home: Path) -> tuple[str, str, str, str]:
    normalized_cwd = re.sub(r"[\\/]+", "/", str(cwd_hint or "").strip()).rstrip("/").lower()
    return (provider, str(session_id or "").strip(), normalized_cwd, str(home))


def _get_cached_transcript(
    provider: str,
    session_id: str,
    cwd_hint: str | None,
    home: Path,
) -> LocatedTranscript | None:
    key = _locator_cache_key(provider, session_id, cwd_hint, home)
    with _LOCATOR_CACHE_LOCK:
        cached = _LOCATOR_CACHE.get(key)
    if cached is None or not cached.path.is_file():
        if cached is not None:
            with _LOCATOR_CACHE_LOCK:
                _LOCATOR_CACHE.pop(key, None)
        return None
    return cached


def _set_cached_transcript(
    provider: str,
    session_id: str,
    cwd_hint: str | None,
    home: Path,
    ref: LocatedTranscript,
) -> LocatedTranscript:
    key = _locator_cache_key(provider, session_id, cwd_hint, home)
    with _LOCATOR_CACHE_LOCK:
        _LOCATOR_CACHE[key] = ref
    return ref


def build_claude_bucket_candidates(cwd_hint: str | None) -> list[str]:
    raw = str(cwd_hint or "").strip()
    if not raw:
        return []

    parts = [part for part in re.split(r"[\\/]+", raw) if part]
    candidates: list[str] = []
    if re.match(r"^[A-Za-z]:", raw):
        drive = raw[0].upper()
        tail = "-".join(parts[1:])
        if tail:
            candidates.append(f"{drive}--{tail}")
    if parts:
        candidates.append("-" + "-".join(parts))

    return list(dict.fromkeys(candidate.replace(":", "-") for candidate in candidates if candidate))


def _iter_codex_state_databases(home: Path):
    return sorted(home.glob("state_*.sqlite"), reverse=True)


def locate_codex_transcript(
    session_id: str,
    *,
    codex_home: Path | None = None,
) -> LocatedTranscript | None:
    home = codex_home or (Path.home() / ".codex")
    cached = _get_cached_transcript("codex", session_id, None, home)
    if cached is not None:
        return cached
    for db_path in _iter_codex_state_databases(home):
        try:
            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT rollout_path, cwd FROM threads WHERE id = ?",
                    (session_id,),
                ).fetchone()
        except sqlite3.Error:
            continue
        if not row:
            continue
        transcript = Path(str(row[0] or ""))
        if transcript.is_file():
            cwd_hint = str(row[1] or "").strip() or None
            return _set_cached_transcript(
                "codex",
                session_id,
                None,
                home,
                LocatedTranscript("codex", session_id, transcript, cwd_hint),
            )

    for candidate in home.glob("sessions/**/*.jsonl"):
        if candidate.is_file() and session_id in candidate.name:
            return _set_cached_transcript(
                "codex",
                session_id,
                None,
                home,
                LocatedTranscript("codex", session_id, candidate),
            )
    return None


def locate_claude_transcript(
    session_id: str,
    *,
    cwd_hint: str | None,
    claude_home: Path | None = None,
) -> LocatedTranscript | None:
    home = claude_home or (Path.home() / ".claude")
    cached = _get_cached_transcript("claude", session_id, cwd_hint, home)
    if cached is not None:
        return cached
    projects_dir = home / "projects"
    for bucket in build_claude_bucket_candidates(cwd_hint):
        candidate = projects_dir / bucket / f"{session_id}.jsonl"
        if candidate.is_file():
            return _set_cached_transcript(
                "claude",
                session_id,
                cwd_hint,
                home,
                LocatedTranscript("claude", session_id, candidate, cwd_hint),
            )

    matches = sorted(projects_dir.glob(f"**/{session_id}.jsonl"))
    if matches:
        return _set_cached_transcript(
            "claude",
            session_id,
            cwd_hint,
            home,
            LocatedTranscript("claude", session_id, matches[0], cwd_hint),
        )
    return None


def locate_kimi_transcript(
    session_id: str,
    *,
    kimi_home: Path | None = None,
) -> LocatedTranscript | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None

    home = kimi_home or (Path.home() / ".kimi")
    for candidate in sorted(home.glob(f"sessions/*/{normalized_session_id}/wire.jsonl")):
        if candidate.is_file():
            return LocatedTranscript("kimi", normalized_session_id, candidate)

    imported = home / "imported_sessions" / normalized_session_id / "wire.jsonl"
    if imported.is_file():
        return LocatedTranscript("kimi", normalized_session_id, imported)
    return None


def _normalize_kimi_workdir_path(value: str | None) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    if re.match(r"^[A-Za-z]:", normalized):
        normalized = normalized[0].lower() + normalized[1:]
    return normalized.lower()


def locate_kimi_last_session_id_for_workdir(
    working_dir: str,
    *,
    kimi_home: Path | None = None,
) -> str | None:
    target_dir = _normalize_kimi_workdir_path(working_dir)
    if not target_dir:
        return None

    home = kimi_home or (Path.home() / ".kimi")
    metadata_path = home / "kimi.json"
    if not metadata_path.is_file():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    work_dirs = payload.get("work_dirs")
    if not isinstance(work_dirs, list):
        return None

    for item in work_dirs:
        if not isinstance(item, dict):
            continue
        path_value = _normalize_kimi_workdir_path(item.get("path"))
        if path_value != target_dir:
            continue
        session_id = str(item.get("last_session_id") or "").strip()
        if session_id:
            return session_id
    return None
