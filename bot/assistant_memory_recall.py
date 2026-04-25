from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from bot.assistant_home import AssistantHome
from bot.assistant_memory_store import AssistantMemoryStore, MemorySearchRow


@dataclass(frozen=True)
class MemoryRecallPlan:
    query_text: str
    kinds: list[str]
    scopes: list[str]
    limit: int = 5


@dataclass(frozen=True)
class MemoryRecallItem:
    id: str
    kind: str
    scope: str
    title: str
    summary: str
    body: str
    score: float


@dataclass(frozen=True)
class MemoryRecallResult:
    plan: MemoryRecallPlan
    items: list[MemoryRecallItem]
    prompt_block: str
    audit_path: str | None = None


def plan_memory_recall(user_text: str) -> MemoryRecallPlan:
    text = str(user_text or "").strip()
    lower = text.lower()
    semantic_hints = ("偏好", "习惯", "默认", "规则", "身份", "喜欢", "不喜欢", "preference")
    procedural_hints = ("怎么", "流程", "步骤", "规范", "协议", "how", "workflow")
    episodic_hints = ("之前", "上次", "最近", "进展", "结论", "原因", "根因", "历史", "remember")
    kinds: list[str] = []
    if any(hint in lower or hint in text for hint in semantic_hints):
        kinds.append("semantic")
    if any(hint in lower or hint in text for hint in procedural_hints):
        kinds.append("procedural")
    if any(hint in lower or hint in text for hint in episodic_hints):
        kinds.append("episodic")
    if not kinds:
        kinds = ["semantic", "episodic", "procedural"]
    return MemoryRecallPlan(query_text=text, kinds=kinds, scopes=["user", "project", "global"], limit=5)


def _rerank_rows(rows: list[MemorySearchRow]) -> list[MemoryRecallItem]:
    items: list[MemoryRecallItem] = []
    for row in rows:
        lexical_component = 1.0 / (1.0 + max(0.0, abs(row.lexical_score)))
        score = (lexical_component * 0.35) + (row.importance * 0.25) + (row.confidence * 0.25) + (row.freshness * 0.15)
        if row.scope == "user":
            score += 0.04
        if row.kind == "semantic":
            score += 0.02
        items.append(
            MemoryRecallItem(
                id=row.id,
                kind=row.kind,
                scope=row.scope,
                title=row.title,
                summary=row.summary,
                body=row.body,
                score=round(min(score, 1.0), 4),
            )
        )
    return sorted(items, key=lambda item: item.score, reverse=True)


def render_recall_block(items: list[MemoryRecallItem]) -> str:
    if not items:
        return ""
    lines = ["<ASSISTANT_MEMORY_RECALL>", "使用下列召回记忆作参考；若与用户新消息冲突，以新消息为准。"]
    for index, item in enumerate(items, start=1):
        body_lines = [line.strip() for line in item.body.splitlines() if line.strip()][:4]
        body = "\n  ".join(body_lines) if body_lines else item.summary
        lines.append(f"{index}. [{item.kind}/{item.scope}] {item.title}: {item.summary}")
        if body:
            lines.append(f"  {body}")
    lines.append("</ASSISTANT_MEMORY_RECALL>")
    return "\n".join(lines)


def _write_recall_audit(home: AssistantHome, *, user_id: int, plan: MemoryRecallPlan, items: list[MemoryRecallItem]) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = home.root / "audit" / "memory" / f"{timestamp}-{user_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "plan": {"query_text": plan.query_text, "kinds": plan.kinds, "scopes": plan.scopes, "limit": plan.limit},
        "items": [item.__dict__ for item in items],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def recall_assistant_memories(home: AssistantHome, *, user_id: int, user_text: str, write_audit: bool = True) -> MemoryRecallResult:
    plan = plan_memory_recall(user_text)
    store = AssistantMemoryStore(home)
    rows = store.search_lexical(user_id=user_id, query_text=plan.query_text, kinds=plan.kinds, scopes=plan.scopes, limit=plan.limit * 2)
    items = _rerank_rows(rows)[: plan.limit]
    if items:
        store.mark_used([item.id for item in items])
    prompt_block = render_recall_block(items)
    audit_path = _write_recall_audit(home, user_id=user_id, plan=plan, items=items) if write_audit and items else None
    return MemoryRecallResult(plan=plan, items=items, prompt_block=prompt_block, audit_path=audit_path)
