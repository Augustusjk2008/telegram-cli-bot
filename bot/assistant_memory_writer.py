from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


@dataclass(frozen=True)
class DreamMemoryInput:
    title: str
    summary: str
    body: str
    kind: str = "episodic"
    scope: str = "project"
    tags: list[str] = field(default_factory=list)
    entity_keys: list[str] = field(default_factory=list)
    importance: float = 0.7
    confidence: float = 0.8
    freshness: float = 0.8


def extract_hot_path_memories(*, user_id: int, user_text: str, assistant_text: str, source_ref: str) -> list[MemoryRecordInput]:
    text = str(user_text or "").strip()
    response = str(assistant_text or "").strip()
    combined = f"{text}\n{response}"
    patterns = [
        (r"(?:以后|今后|默认|请记住|记住)[:： ]*(.+)", "用户偏好"),
        (r"(?:我的|我叫|用户名是)[:： ]*([\w\u4e00-\u9fff-]{1,40})", "用户身份"),
    ]
    records: list[MemoryRecordInput] = []
    for pattern, title in patterns:
        match = re.search(pattern, combined)
        if not match:
            continue
        summary = match.group(1).strip(" 。.\n\r\t")[:120]
        if not summary:
            continue
        records.append(
            MemoryRecordInput(
                user_id=user_id,
                scope="user",
                kind="semantic",
                source_type="chat",
                source_ref=source_ref,
                title=title,
                summary=summary,
                body=f"- {summary}",
                tags=["preference"],
                entity_keys=[f"user:{user_id}"],
                importance=0.85,
                confidence=0.75,
                freshness=0.9,
            )
        )
    return records[:3]


def write_hot_path_memories(home: AssistantHome, *, user_id: int, user_text: str, assistant_text: str, source_ref: str) -> list[str]:
    store = AssistantMemoryStore(home)
    return [store.upsert(record) for record in extract_hot_path_memories(user_id=user_id, user_text=user_text, assistant_text=assistant_text, source_ref=source_ref)]


def write_dream_memories(home: AssistantHome, *, user_id: int, source_ref: str, memories: list[DreamMemoryInput]) -> list[str]:
    store = AssistantMemoryStore(home)
    ids: list[str] = []
    for memory in memories:
        ids.append(
            store.upsert(
                MemoryRecordInput(
                    user_id=user_id,
                    scope=memory.scope,
                    kind=memory.kind,
                    source_type="dream",
                    source_ref=source_ref,
                    title=memory.title,
                    summary=memory.summary,
                    body=memory.body,
                    tags=memory.tags,
                    entity_keys=memory.entity_keys,
                    event_at=datetime.now(UTC).isoformat(),
                    importance=memory.importance,
                    confidence=memory.confidence,
                    freshness=memory.freshness,
                )
            )
        )
    return ids
