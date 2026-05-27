from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bot.assistant.home import AssistantHome

_PROPOSAL_INDEX_CACHE_TTL_SECONDS = 2.0
_PROPOSAL_INDEX_CACHE: dict[str, dict[str, object]] = {}
_PROPOSAL_FILE_CACHE: dict[str, tuple[int, dict]] = {}


def _proposal_path(home: AssistantHome, proposal_id: str) -> Path:
    return home.root / "proposals" / f"{proposal_id}.json"


def create_proposal(home: AssistantHome, *, kind: str, title: str, body: str) -> dict:
    proposal = {
        "id": f"pr_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "title": title,
        "body": body,
        "status": "proposed",
        "created_at": datetime.now(UTC).isoformat(),
    }
    _proposal_path(home, proposal["id"]).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _invalidate_proposal_cache(home.root / "proposals")
    return proposal


def list_proposals(home: AssistantHome, *, status: str | None = None) -> list[dict]:
    items = []
    for path in _list_cached_proposal_paths(home.root / "proposals"):
        data = _read_cached_proposal(path)
        if status and data.get("status") != status:
            continue
        items.append(data)
    return items


def get_proposal(home: AssistantHome, proposal_id: str) -> dict:
    path = _proposal_path(home, proposal_id)
    return _read_cached_proposal(path)


def set_proposal_status(home: AssistantHome, proposal_id: str, status: str, *, reviewer: str) -> dict:
    path = _proposal_path(home, proposal_id)
    data = _read_cached_proposal(path)
    data["status"] = status
    data["reviewed_by"] = reviewer
    data["reviewed_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_proposal_cache(home.root / "proposals", path=path)
    return data


def _dir_signature(root: Path) -> tuple[int, int]:
    try:
        stat = root.stat()
    except OSError:
        return (0, 0)
    try:
        file_count = sum(1 for entry in root.iterdir() if entry.is_file())
    except OSError:
        file_count = 0
    return (stat.st_mtime_ns, file_count)


def _list_cached_proposal_paths(root: Path) -> list[Path]:
    cache_key = str(root.resolve())
    now = time.monotonic()
    signature = _dir_signature(root)
    cached = _PROPOSAL_INDEX_CACHE.get(cache_key)
    if (
        cached is not None
        and cached.get("signature") == signature
        and now - float(cached.get("loaded_at") or 0.0) < _PROPOSAL_INDEX_CACHE_TTL_SECONDS
    ):
        return list(cached.get("paths") or [])
    paths = sorted(root.glob("*.json")) if root.exists() else []
    _PROPOSAL_INDEX_CACHE[cache_key] = {
        "signature": signature,
        "loaded_at": now,
        "paths": list(paths),
    }
    return paths


def _read_cached_proposal(path: Path) -> dict:
    resolved = path.resolve()
    stat = resolved.stat()
    cache_key = str(resolved)
    cached = _PROPOSAL_FILE_CACHE.get(cache_key)
    if cached is not None and cached[0] == stat.st_mtime_ns:
        return dict(cached[1])
    data = json.loads(resolved.read_text(encoding="utf-8"))
    _PROPOSAL_FILE_CACHE[cache_key] = (stat.st_mtime_ns, data)
    return dict(data)


def _invalidate_proposal_cache(root: Path, *, path: Path | None = None) -> None:
    _PROPOSAL_INDEX_CACHE.pop(str(root.resolve()), None)
    if path is not None:
        _PROPOSAL_FILE_CACHE.pop(str(path.resolve()), None)
