from __future__ import annotations

import os
import re
from typing import Any

from ..jsonl import index_by


NOT_ATTEMPTED = {
    "",
    "n/a",
    "na",
    "unknown",
    "i don't know",
    "i do not know",
    "not attempted",
}


def score_simpleqa(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
    grader: str = "deterministic",
    grader_model: str | None = None,
) -> dict[str, Any]:
    answers = index_by(answer_rows, "id")
    details: list[dict[str, Any]] = []
    correct = 0
    incorrect = 0
    not_attempted = 0
    f1_total = 0.0
    attempted = 0

    for gold in gold_rows:
        task_id = str(gold["id"])
        row = answers.get(task_id)
        answer = str(row.get("answer", "")) if row else ""
        if _is_not_attempted(answer):
            status = "not_attempted"
            not_attempted += 1
            f1 = 0.0
        else:
            attempted += 1
            if grader == "openai":
                passed = _grade_with_openai(answer=answer, gold=gold, model=grader_model)
            else:
                passed = _deterministic_correct(answer, gold)
            status = "correct" if passed else "incorrect"
            correct += int(passed)
            incorrect += int(not passed)
            f1 = _best_f1(answer, [str(gold.get("answer", "")), *gold.get("aliases", [])])
        f1_total += f1
        details.append(
            {
                "id": task_id,
                "passed": status == "correct",
                "status": status,
                "f1": f1,
                "reason": status,
                "answer_present": row is not None,
            }
        )

    total = len(gold_rows)
    return {
        "metrics": {
            "accuracy": _metric(correct, total),
            "correct": _count_metric(correct, total),
            "incorrect": _count_metric(incorrect, total),
            "not_attempted": _count_metric(not_attempted, total),
            "correct_given_attempted": {
                "value": (correct / attempted) if attempted else 0.0,
                "passed": correct,
                "total": attempted,
            },
            "f1": {"value": (f1_total / total) if total else 0.0, "passed": correct, "total": total},
        },
        "details": details,
    }


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {"value": (passed / total) if total else 0.0, "passed": passed, "total": total}


def _count_metric(count: int, total: int) -> dict[str, Any]:
    return {"value": count, "passed": count, "total": total}


def _is_not_attempted(answer: str) -> bool:
    return _normalize(answer) in NOT_ATTEMPTED


def _deterministic_correct(answer: str, gold: dict[str, Any]) -> bool:
    accepted = [str(gold.get("answer", "")), *[str(alias) for alias in gold.get("aliases", [])]]
    normalized_answer = _normalize(answer)
    return any(normalized_answer == _normalize(candidate) for candidate in accepted)


def _grade_with_openai(*, answer: str, gold: dict[str, Any], model: str | None) -> bool:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for SimpleQA OpenAI grader")
    if not model:
        model = os.environ.get("SIMPLEQA_GRADER_MODEL")
    if not model:
        raise RuntimeError("SIMPLEQA_GRADER_MODEL is required for SimpleQA OpenAI grader")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("install openai to use SimpleQA OpenAI grader") from exc

    client = OpenAI(api_key=api_key)
    prompt = (
        "Grade whether the answer matches the reference. "
        "Respond with only CORRECT or INCORRECT.\n"
        f"Reference: {gold.get('answer', '')}\n"
        f"Aliases: {gold.get('aliases', [])}\n"
        f"Answer: {answer}"
    )
    response = client.responses.create(model=model, input=prompt)
    text = getattr(response, "output_text", "")
    return str(text).strip().upper().startswith("CORRECT")


def _best_f1(answer: str, candidates: list[str]) -> float:
    answer_tokens = _tokens(answer)
    if not answer_tokens:
        return 0.0
    return max((_f1(answer_tokens, _tokens(candidate)) for candidate in candidates), default=0.0)


def _f1(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    remaining = right.copy()
    overlap = 0
    for token in left:
        if token in remaining:
            overlap += 1
            remaining.remove(token)
    if overlap == 0:
        return 0.0
    precision = overlap / len(left)
    recall = overlap / len(right)
    return 2 * precision * recall / (precision + recall)


def _normalize(text: str) -> str:
    return " ".join(_tokens(text))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())

