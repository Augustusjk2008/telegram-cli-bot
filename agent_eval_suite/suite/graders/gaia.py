from __future__ import annotations

import re
import string
from collections import defaultdict
from typing import Any

from ..jsonl import index_by


def score_gaia(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    answers = index_by(answer_rows, "id")
    details: list[dict[str, Any]] = []
    passed = 0
    by_level: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})

    for gold in gold_rows:
        task_id = str(gold["id"])
        row = answers.get(task_id)
        answer = str(row.get("final_answer", "")) if row else ""
        expected = str(gold.get("final_answer", ""))
        ok = _normalize(answer) == _normalize(expected)
        level = str(gold.get("level", "unknown"))
        passed += int(ok)
        by_level[level]["passed"] += int(ok)
        by_level[level]["total"] += 1
        details.append(
            {
                "id": task_id,
                "passed": ok,
                "level": gold.get("level", "unknown"),
                "reason": "pass" if ok else "exact_match_failed",
                "answer_present": row is not None,
            }
        )

    total = len(gold_rows)
    metrics: dict[str, Any] = {"accuracy": _metric(passed, total)}
    for level, counts in sorted(by_level.items()):
        metrics[f"level_{level}_accuracy"] = _metric(counts["passed"], counts["total"])
    return {"metrics": metrics, "details": details}


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {"value": (passed / total) if total else 0.0, "passed": passed, "total": total}


def _normalize(text: str) -> str:
    cleaned = text.strip().casefold()
    cleaned = cleaned.translate(str.maketrans("", "", string.punctuation.replace(".", "")))
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

