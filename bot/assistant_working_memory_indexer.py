from __future__ import annotations

import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput

_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_WORKING_KINDS = {
    "current_goal": "episodic",
    "open_loops": "episodic",
    "user_prefs": "semantic",
    "recent_summary": "episodic",
}
_INDEX_CACHE_LOCK = RLock()
_INDEX_CACHE: dict[tuple[str, int], tuple[tuple[tuple[str, int, int], ...], WorkingMemoryIndexResult]] = {}


@dataclass(frozen=True)
class WorkingMemoryIndexResult:
    indexed_count: int
    memory_ids: list[str]


def _fingerprint_path(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, -1)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _working_memory_fingerprint(home: AssistantHome) -> tuple[tuple[str, int, int], ...]:
    working_root = home.root / "memory" / "working"
    rows: list[tuple[str, int, int]] = []
    for name in _WORKING_KINDS:
        mtime_ns, size = _fingerprint_path(working_root / f"{name}.md")
        rows.append((name, mtime_ns, size))
    return tuple(rows)


def clear_working_memory_index_cache() -> None:
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def _list_items(text: str) -> list[str]:
    items: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = _LIST_MARKER_RE.sub("", line).strip()
        if line:
            items.append(line)
    return items


def _invalidate_stale_refs(store: AssistantMemoryStore, *, name: str, active_refs: set[str]) -> None:
    source_prefix = f"memory/working/{name}.md:"
    with closing(store._connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, source_ref
            FROM memories
            WHERE source_type='working' AND invalidated_at IS NULL AND source_ref LIKE ?
            """,
            (f"{source_prefix}%",),
        ).fetchall()
    for row in rows:
        source_ref = str(row["source_ref"])
        if source_ref not in active_refs:
            store.invalidate(str(row["id"]), reason="working_memory_reindexed")


def index_working_memories(
    home: AssistantHome,
    *,
    user_id: int = 0,
    force: bool = False,
) -> WorkingMemoryIndexResult:
    cache_key = (str(home.root.resolve()), int(user_id))
    fingerprint = _working_memory_fingerprint(home)
    if not force:
        with _INDEX_CACHE_LOCK:
            cached = _INDEX_CACHE.get(cache_key)
            if cached and cached[0] == fingerprint:
                return WorkingMemoryIndexResult(indexed_count=0, memory_ids=list(cached[1].memory_ids))

    store = AssistantMemoryStore(home)
    memory_ids: list[str] = []
    working_root = home.root / "memory" / "working"
    for name, kind in _WORKING_KINDS.items():
        path = working_root / f"{name}.md"
        items = _list_items(path.read_text(encoding="utf-8")) if path.exists() else []
        active_refs = {f"memory/working/{name}.md:{index}" for index in range(1, len(items) + 1)}
        _invalidate_stale_refs(store, name=name, active_refs=active_refs)
        for index, item in enumerate(items, start=1):
            memory_ids.append(
                store.upsert(
                    MemoryRecordInput(
                        user_id=user_id,
                        scope="global",
                        kind=kind,
                        source_type="working",
                        source_ref=f"memory/working/{name}.md:{index}",
                        title=f"working/{name}",
                        summary=item[:180],
                        body=f"- {item}",
                        tags=["working", name],
                        entity_keys=[f"working:{name}"],
                        importance=0.75 if name in {"current_goal", "user_prefs"} else 0.65,
                        confidence=0.85,
                        freshness=0.85,
                    )
                )
            )
    result = WorkingMemoryIndexResult(indexed_count=len(memory_ids), memory_ids=memory_ids)
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[cache_key] = (fingerprint, result)
    return result
