from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class LocatedTranscript:
    provider: Literal["codex", "claude"]
    session_id: str
    path: Path
    cwd_hint: str | None = None


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
    for db_path in _iter_codex_state_databases(home):
        try:
            with sqlite3.connect(db_path) as conn:
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
            return LocatedTranscript("codex", session_id, transcript, cwd_hint)

    for candidate in home.glob("sessions/**/*.jsonl"):
        if candidate.is_file() and session_id in candidate.name:
            return LocatedTranscript("codex", session_id, candidate)
    return None


def locate_claude_transcript(
    session_id: str,
    *,
    cwd_hint: str | None,
    claude_home: Path | None = None,
) -> LocatedTranscript | None:
    home = claude_home or (Path.home() / ".claude")
    projects_dir = home / "projects"
    for bucket in build_claude_bucket_candidates(cwd_hint):
        candidate = projects_dir / bucket / f"{session_id}.jsonl"
        if candidate.is_file():
            return LocatedTranscript("claude", session_id, candidate, cwd_hint)

    matches = sorted(projects_dir.glob(f"**/{session_id}.jsonl"))
    if matches:
        return LocatedTranscript("claude", session_id, matches[0], cwd_hint)
    return None
