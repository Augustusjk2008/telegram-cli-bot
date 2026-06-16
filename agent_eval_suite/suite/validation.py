from __future__ import annotations

from collections import Counter
from typing import Any


ANSWER_KEYS = {
    "ifeval": ("id", "response"),
    "simpleqa": ("id", "answer"),
    "evalplus": ("task_id", "solution"),
    "gaia": ("id", "final_answer"),
    "workspace_ops": ("id", "status", "summary"),
}

ID_KEYS = {
    "ifeval": "id",
    "simpleqa": "id",
    "evalplus": "task_id",
    "gaia": "id",
    "workspace_ops": "id",
}


def validate_answer_rows(
    *,
    benchmark: str,
    task_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if benchmark not in ANSWER_KEYS:
        raise ValueError(f"unsupported benchmark: {benchmark}")
    id_key = ID_KEYS[benchmark]
    allowed_ids = {str(row.get(id_key)) for row in task_rows if row.get(id_key) is not None}
    row_ids = [str(row.get(id_key)) for row in answer_rows if row.get(id_key) is not None]
    counts = Counter(row_ids)
    problems: list[dict[str, Any]] = []

    for index, row in enumerate(answer_rows, start=1):
        row_id = row.get(id_key)
        if row_id is None:
            problems.append({"line": index, "reason": "missing_id", "id": ""})
            continue
        text_id = str(row_id)
        if text_id not in allowed_ids:
            problems.append({"line": index, "reason": "unknown_id", "id": text_id})
        if counts[text_id] > 1:
            problems.append({"line": index, "reason": "duplicate_id", "id": text_id})
        for key in ANSWER_KEYS[benchmark]:
            if key not in row:
                problems.append({"line": index, "reason": f"missing_{key}", "id": text_id})
            elif not isinstance(row[key], str):
                problems.append({"line": index, "reason": f"{key}_must_be_string", "id": text_id})
    for missing_id in sorted(allowed_ids - set(row_ids)):
        problems.append({"line": "", "reason": "missing_answer", "id": missing_id})
    return problems
