from __future__ import annotations

import re
from contextlib import closing
from dataclasses import dataclass

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput

_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_WORKING_KINDS = {
    "current_goal": "episodic",
    "open_loops": "episodic",
    "user_prefs": "semantic",
    "recent_summary": "episodic",
}


@dataclass(frozen=True)
class WorkingMemoryIndexResult:
    indexed_count: int
    memory_ids: list[str]


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


def index_working_memories(home: AssistantHome, *, user_id: int = 0) -> WorkingMemoryIndexResult:
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
    return WorkingMemoryIndexResult(indexed_count=len(memory_ids), memory_ids=memory_ids)
