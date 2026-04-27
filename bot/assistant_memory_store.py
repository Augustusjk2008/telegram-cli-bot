from __future__ import annotations

import json
import re
from contextlib import closing
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bot.assistant_home import AssistantHome

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class MemoryRecordInput:
    user_id: int
    scope: str
    kind: str
    source_type: str
    source_ref: str
    title: str
    summary: str
    body: str
    tags: list[str] = field(default_factory=list)
    entity_keys: list[str] = field(default_factory=list)
    event_at: str | None = None
    importance: float = 0.5
    confidence: float = 0.5
    freshness: float = 0.5
    pinned: bool = False
    valid_until: str | None = None


@dataclass(frozen=True)
class MemorySearchRow:
    id: str
    kind: str
    scope: str
    title: str
    summary: str
    body: str
    event_at: str | None
    importance: float
    confidence: float
    freshness: float
    lexical_score: float


class AssistantMemoryStore:
    def __init__(self, home: AssistantHome) -> None:
        self.home = home
        self.db_path = home.root / "indexes" / "memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    entity_keys_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_at TEXT,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    freshness REAL NOT NULL DEFAULT 0.5,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    valid_until TEXT,
                    invalidated_at TEXT,
                    invalidation_reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_source
                ON memories(user_id, source_type, source_ref, kind, title);
                CREATE INDEX IF NOT EXISTS idx_memories_lookup
                ON memories(user_id, scope, kind, invalidated_at, updated_at);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    title,
                    summary,
                    body,
                    tags,
                    tokenize='unicode61'
                );
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _clip_score(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _cjk_ngrams(text: str, *, max_terms: int = 80) -> list[str]:
        chars = [char for char in str(text or "") if _CJK_CHAR_RE.fullmatch(char)]
        terms: list[str] = []
        for size in (2, 3):
            for index in range(0, max(0, len(chars) - size + 1)):
                term = "".join(chars[index : index + size])
                if term and term not in terms:
                    terms.append(term)
                if len(terms) >= max_terms:
                    return terms
        return terms

    def upsert(self, record: MemoryRecordInput) -> str:
        now = self._now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT id FROM memories
                WHERE user_id=? AND source_type=? AND source_ref=? AND kind=? AND title=?
                """,
                (record.user_id, record.source_type, record.source_ref, record.kind, record.title),
            ).fetchone()
            memory_id = str(row["id"]) if row else uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO memories (
                    id, user_id, scope, kind, source_type, source_ref, title, summary, body,
                    tags_json, entity_keys_json, created_at, event_at, updated_at,
                    importance, confidence, freshness, pinned, valid_until, invalidated_at, invalidation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    scope=excluded.scope, source_type=excluded.source_type, source_ref=excluded.source_ref,
                    summary=excluded.summary, body=excluded.body, tags_json=excluded.tags_json,
                    entity_keys_json=excluded.entity_keys_json, event_at=excluded.event_at,
                    updated_at=excluded.updated_at, importance=excluded.importance,
                    confidence=excluded.confidence, freshness=excluded.freshness, pinned=excluded.pinned,
                    valid_until=excluded.valid_until, invalidated_at=NULL, invalidation_reason=NULL
                """,
                (
                    memory_id, int(record.user_id), record.scope, record.kind, record.source_type,
                    record.source_ref, record.title, record.summary, record.body,
                    json.dumps(record.tags, ensure_ascii=False),
                    json.dumps(record.entity_keys, ensure_ascii=False), now, record.event_at, now,
                    self._clip_score(record.importance), self._clip_score(record.confidence),
                    self._clip_score(record.freshness), 1 if record.pinned else 0, record.valid_until,
                ),
            )
            conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            conn.execute(
                "INSERT INTO memory_fts(memory_id, title, summary, body, tags) VALUES (?, ?, ?, ?, ?)",
                (
                    memory_id,
                    record.title,
                    record.summary,
                    record.body,
                    " ".join(
                        record.tags
                        + record.entity_keys
                        + self._cjk_ngrams(f"{record.title} {record.summary} {record.body}")
                    ),
                ),
            )
            conn.commit()
        return memory_id

    def invalidate(self, memory_id: str, *, reason: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("UPDATE memories SET invalidated_at=?, invalidation_reason=? WHERE id=?", (self._now(), reason, memory_id))
            conn.commit()

    def mark_used(self, memory_ids: list[str]) -> None:
        ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as conn:
            conn.execute(f"UPDATE memories SET last_used_at=? WHERE id IN ({placeholders})", [self._now(), *ids])
            conn.commit()

    @staticmethod
    def _fts_query(query_text: str) -> str:
        text = str(query_text or "")
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text, flags=re.UNICODE)
        expanded: list[str] = []
        for token in tokens:
            if token not in expanded:
                expanded.append(token)
            for gram in AssistantMemoryStore._cjk_ngrams(token, max_terms=20):
                if gram not in expanded:
                    expanded.append(gram)
        return " OR ".join(expanded[:24])

    def search_lexical(self, *, user_id: int, query_text: str, kinds: list[str] | None = None, scopes: list[str] | None = None, limit: int = 5) -> list[MemorySearchRow]:
        query = self._fts_query(query_text)
        if not query:
            return []
        kind_values = kinds or ["semantic", "episodic", "procedural"]
        scope_values = scopes or ["user", "project", "global"]
        kind_placeholders = ",".join("?" for _ in kind_values)
        scope_placeholders = ",".join("?" for _ in scope_values)
        sql = f"""
            SELECT m.*, bm25(memory_fts) AS lexical_score
            FROM memory_fts JOIN memories m ON m.id = memory_fts.memory_id
            WHERE memory_fts MATCH ? AND m.user_id IN (?, 0)
              AND m.kind IN ({kind_placeholders}) AND m.scope IN ({scope_placeholders})
              AND m.invalidated_at IS NULL
              AND (m.valid_until IS NULL OR m.valid_until = '' OR m.valid_until > ?)
            ORDER BY lexical_score ASC, m.pinned DESC, m.importance DESC, m.updated_at DESC
            LIMIT ?
        """
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(sql, [query, int(user_id), *kind_values, *scope_values, self._now(), int(limit)]).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            MemorySearchRow(
                id=str(row["id"]), kind=str(row["kind"]), scope=str(row["scope"]),
                title=str(row["title"]), summary=str(row["summary"]), body=str(row["body"]),
                event_at=row["event_at"], importance=float(row["importance"]),
                confidence=float(row["confidence"]), freshness=float(row["freshness"]),
                lexical_score=float(row["lexical_score"]),
            )
            for row in rows
        ]
