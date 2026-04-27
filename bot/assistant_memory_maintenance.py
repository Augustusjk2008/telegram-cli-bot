from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore


@dataclass(frozen=True)
class DuplicateMemoryGroup:
    user_id: int
    scope: str
    kind: str
    title: str
    summary: str
    memory_ids: list[str]


@dataclass(frozen=True)
class DuplicateCleanupResult:
    invalidated_count: int
    kept_ids: list[str]
    invalidated_ids: list[str]


def find_duplicate_memories(home: AssistantHome) -> list[DuplicateMemoryGroup]:
    store = AssistantMemoryStore(home)
    with closing(store._connect()) as conn:
        rows = conn.execute(
            """
            SELECT user_id, scope, kind, title, summary, GROUP_CONCAT(id) AS ids, COUNT(*) AS count
            FROM memories
            WHERE invalidated_at IS NULL
            GROUP BY user_id, scope, kind, title, summary
            HAVING COUNT(*) > 1
            ORDER BY count DESC
            """
        ).fetchall()
    return [
        DuplicateMemoryGroup(
            user_id=int(row["user_id"]),
            scope=str(row["scope"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            memory_ids=[item for item in str(row["ids"]).split(",") if item],
        )
        for row in rows
    ]


def invalidate_duplicate_memories(home: AssistantHome, *, reason: str) -> DuplicateCleanupResult:
    store = AssistantMemoryStore(home)
    kept_ids: list[str] = []
    invalidated_ids: list[str] = []
    with closing(store._connect()) as conn:
        for group in find_duplicate_memories(home):
            placeholders = ",".join("?" for _ in group.memory_ids)
            rows = conn.execute(
                f"SELECT id FROM memories WHERE id IN ({placeholders}) ORDER BY updated_at DESC, id DESC",
                group.memory_ids,
            ).fetchall()
            ordered_ids = [str(row["id"]) for row in rows]
            if not ordered_ids:
                continue
            kept_ids.append(ordered_ids[0])
            invalidated_ids.extend(ordered_ids[1:])
    for memory_id in invalidated_ids:
        store.invalidate(memory_id, reason=reason)
    return DuplicateCleanupResult(
        invalidated_count=len(invalidated_ids),
        kept_ids=kept_ids,
        invalidated_ids=invalidated_ids,
    )
