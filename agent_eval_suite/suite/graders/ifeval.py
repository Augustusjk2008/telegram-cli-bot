from __future__ import annotations

import json
import re
from typing import Any

from ..jsonl import index_by


def score_ifeval(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if any("official_instruction_id_list" in row for row in gold_rows):
        return _score_ifeval_official(gold_rows=gold_rows, answer_rows=answer_rows)
    answers = index_by(answer_rows, "id")
    details: list[dict[str, Any]] = []
    prompt_strict = 0
    prompt_loose = 0
    instruction_strict = 0
    instruction_loose = 0
    instruction_total = 0

    for gold in gold_rows:
        task_id = str(gold["id"])
        answer = answers.get(task_id)
        response = str(answer.get("response", "")) if answer else ""
        strict_results = [
            _check_instruction(response, instruction, loose=False)
            for instruction in gold.get("instructions", [])
        ]
        loose_results = [
            _check_instruction(response, instruction, loose=True)
            for instruction in gold.get("instructions", [])
        ]
        strict_pass = bool(strict_results) and all(strict_results)
        loose_pass = bool(loose_results) and all(loose_results)
        prompt_strict += int(strict_pass)
        prompt_loose += int(loose_pass)
        instruction_strict += sum(1 for passed in strict_results if passed)
        instruction_loose += sum(1 for passed in loose_results if passed)
        instruction_total += len(strict_results)
        details.append(
            {
                "id": task_id,
                "passed": strict_pass,
                "prompt_strict": strict_pass,
                "prompt_loose": loose_pass,
                "instruction_strict": sum(1 for passed in strict_results if passed),
                "instruction_loose": sum(1 for passed in loose_results if passed),
                "instruction_total": len(strict_results),
                "reason": "pass" if strict_pass else "instruction_failed",
                "answer_present": answer is not None,
            }
        )

    total = len(gold_rows)
    return {
        "metrics": {
            "prompt_strict_accuracy": _metric(prompt_strict, total),
            "prompt_loose_accuracy": _metric(prompt_loose, total),
            "instruction_strict_accuracy": _metric(instruction_strict, instruction_total),
            "instruction_loose_accuracy": _metric(instruction_loose, instruction_total),
        },
        "details": details,
    }


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {
        "value": (passed / total) if total else 0.0,
        "passed": passed,
        "total": total,
    }


def _check_instruction(response: str, instruction: dict[str, Any], *, loose: bool) -> bool:
    text = _loose_text(response) if loose else response
    kind = instruction.get("type")
    if kind == "keyword_include_all":
        keywords = [str(keyword) for keyword in instruction.get("keywords", [])]
        haystack = text.casefold() if loose else text
        return all((keyword.casefold() if loose else keyword) in haystack for keyword in keywords)
    if kind == "bullet_count":
        return _bullet_count(text) == int(instruction.get("count", 0))
    if kind == "format_json":
        return _parse_json(text) is not None
    if kind == "json_field":
        value = _parse_json(text)
        if not isinstance(value, dict):
            return False
        actual = value.get(str(instruction.get("key", "")))
        expected = instruction.get("value")
        if loose and isinstance(actual, str) and isinstance(expected, str):
            return actual.casefold() == expected.casefold()
        return actual == expected
    if kind == "max_words":
        return len(_words(text)) <= int(instruction.get("count", 0))
    if kind == "min_words":
        return len(_words(text)) >= int(instruction.get("count", 0))
    if kind == "prefix":
        expected = str(instruction.get("text", ""))
        return text.casefold().startswith(expected.casefold()) if loose else text.startswith(expected)
    if kind == "suffix":
        expected = str(instruction.get("text", ""))
        return text.casefold().endswith(expected.casefold()) if loose else text.endswith(expected)
    return False


def _loose_text(response: str) -> str:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _bullet_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith(("-", "*")))


def _parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _words(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text)


def _score_ifeval_official(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    answers = index_by(answer_rows, "id")
    try:
        from instruction_following_eval import evaluation_lib  # type: ignore
    except ImportError:
        details = [
            {
                "id": str(row["id"]),
                "passed": False,
                "prompt_strict": False,
                "prompt_loose": False,
                "instruction_strict": 0,
                "instruction_loose": 0,
                "instruction_total": len(row.get("official_instruction_id_list", [])),
                "reason": "official_ifeval_grader_unavailable",
                "answer_present": str(row["id"]) in answers,
            }
            for row in gold_rows
        ]
        instruction_total = sum(row["instruction_total"] for row in details)
        return {
            "metrics": {
                "prompt_strict_accuracy": _metric(0, len(gold_rows)),
                "prompt_loose_accuracy": _metric(0, len(gold_rows)),
                "instruction_strict_accuracy": _metric(0, instruction_total),
                "instruction_loose_accuracy": _metric(0, instruction_total),
            },
            "details": details,
        }

    prompt_to_response = {
        str(row["prompt"]): str(answers.get(str(row["id"]), {}).get("response", ""))
        for row in gold_rows
    }
    inputs = [
        evaluation_lib.InputExample(
            key=int(row.get("key", index)),
            instruction_id_list=list(row["official_instruction_id_list"]),
            prompt=str(row["prompt"]),
            kwargs=list(row["official_kwargs"]),
        )
        for index, row in enumerate(gold_rows)
    ]
    strict_outputs = [
        evaluation_lib.test_instruction_following_strict(inp, prompt_to_response)
        for inp in inputs
    ]
    loose_outputs = [
        evaluation_lib.test_instruction_following_loose(inp, prompt_to_response)
        for inp in inputs
    ]
    details: list[dict[str, Any]] = []
    prompt_strict = 0
    prompt_loose = 0
    instruction_strict = 0
    instruction_loose = 0
    instruction_total = 0
    for row, strict, loose in zip(gold_rows, strict_outputs, loose_outputs):
        strict_pass = bool(strict.follow_all_instructions)
        loose_pass = bool(loose.follow_all_instructions)
        strict_count = sum(1 for passed in strict.follow_instruction_list if passed)
        loose_count = sum(1 for passed in loose.follow_instruction_list if passed)
        total = len(strict.follow_instruction_list)
        prompt_strict += int(strict_pass)
        prompt_loose += int(loose_pass)
        instruction_strict += strict_count
        instruction_loose += loose_count
        instruction_total += total
        details.append(
            {
                "id": str(row["id"]),
                "passed": strict_pass,
                "prompt_strict": strict_pass,
                "prompt_loose": loose_pass,
                "instruction_strict": strict_count,
                "instruction_loose": loose_count,
                "instruction_total": total,
                "reason": "pass" if strict_pass else "instruction_failed",
                "answer_present": str(row["id"]) in answers,
            }
        )
    return {
        "metrics": {
            "prompt_strict_accuracy": _metric(prompt_strict, len(gold_rows)),
            "prompt_loose_accuracy": _metric(prompt_loose, len(gold_rows)),
            "instruction_strict_accuracy": _metric(instruction_strict, instruction_total),
            "instruction_loose_accuracy": _metric(instruction_loose, instruction_total),
        },
        "details": details,
    }
