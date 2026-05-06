from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


@dataclass(frozen=True)
class KnowledgeIndexResult:
    indexed_count: int
    memory_ids: list[str]


def _relative_ref(home: AssistantHome, path: Path) -> str:
    return path.relative_to(home.root).as_posix()


def _read_title_and_body(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return path.stem, ""
    title = path.stem
    body_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and title == path.stem:
            title = stripped[2:].strip() or path.stem
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip() or text
    return title[:120], body


def _bucket_for(home: AssistantHome, path: Path) -> str:
    relative = path.relative_to(home.root / "memory" / "knowledge")
    return relative.parts[0] if len(relative.parts) > 1 else "knowledge"


def index_knowledge_memories(home: AssistantHome, *, user_id: int = 0) -> KnowledgeIndexResult:
    knowledge_root = home.root / "memory" / "knowledge"
    store = AssistantMemoryStore(home)
    memory_ids: list[str] = []
    for path in sorted(knowledge_root.rglob("*.md")):
        title, body = _read_title_and_body(path)
        if not body:
            continue
        bucket = _bucket_for(home, path)
        summary = " ".join(body.split())[:180]
        memory_ids.append(
            store.upsert(
                MemoryRecordInput(
                    user_id=user_id,
                    scope="global",
                    kind="procedural",
                    source_type="knowledge",
                    source_ref=_relative_ref(home, path),
                    title=title,
                    summary=summary,
                    body=body,
                    tags=["knowledge", bucket],
                    entity_keys=[f"knowledge:{bucket}", f"knowledge_file:{path.stem}"],
                    importance=0.65,
                    confidence=0.8,
                    freshness=0.7,
                )
            )
        )
    return KnowledgeIndexResult(indexed_count=len(memory_ids), memory_ids=memory_ids)
