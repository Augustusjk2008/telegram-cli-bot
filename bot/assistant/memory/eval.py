from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from bot.assistant_home import AssistantHome
from bot.assistant_memory_recall import recall_assistant_memories


@dataclass(frozen=True)
class MemoryEvalCase:
    query: str
    expected_memory_kind: str
    expected_hit_terms: list[str]
    must_not_hit_terms: list[str]


@dataclass(frozen=True)
class MemoryEvalRun:
    metrics: dict[str, float]
    report_path: str


def run_memory_eval(home: AssistantHome, *, user_id: int, cases: list[MemoryEvalCase]) -> MemoryEvalRun:
    hit_count = 0
    stale_hits = 0
    rows = []
    for case in cases:
        recall = recall_assistant_memories(home, user_id=user_id, user_text=case.query)
        text = recall.prompt_block
        hit = all(term in text for term in case.expected_hit_terms) and case.expected_memory_kind in text
        stale = any(term in text for term in case.must_not_hit_terms)
        hit_count += 1 if hit else 0
        stale_hits += 1 if stale else 0
        rows.append({"query": case.query, "prompt_block": text, "hit": hit, "stale": stale, "audit_path": recall.audit_path})
    metrics = {
        "hit_at_5": hit_count / len(cases) if cases else 0.0,
        "stale_recall_rate": stale_hits / len(cases) if cases else 0.0,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = home.root / "evals" / "memory" / f"{timestamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return MemoryEvalRun(metrics=metrics, report_path=str(path))
