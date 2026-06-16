from __future__ import annotations

import random
from typing import Any

from .paths import BENCHMARKS


def build_dataset(
    *,
    preset: str,
    samples: int,
    seed: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    if preset not in {"smoke", "win-native"}:
        raise ValueError(f"unsupported preset: {preset}")
    samples = max(samples, len(BENCHMARKS))
    counts = _benchmark_counts(samples)
    rng = random.Random(seed)

    visible: dict[str, list[dict[str, Any]]] = {}
    gold: dict[str, list[dict[str, Any]]] = {}
    for benchmark, count in counts.items():
        builders = {
            "ifeval": _build_ifeval,
            "simpleqa": _build_simpleqa,
            "evalplus": _build_evalplus,
            "gaia": _build_gaia,
        }[benchmark]
        task_rows, gold_rows = builders(count, rng)
        visible[benchmark] = task_rows
        gold[benchmark] = gold_rows
    return visible, gold


def _benchmark_counts(samples: int) -> dict[str, int]:
    base = samples // len(BENCHMARKS)
    remainder = samples % len(BENCHMARKS)
    return {
        benchmark: base + (1 if index < remainder else 0)
        for index, benchmark in enumerate(BENCHMARKS)
    }


def _build_ifeval(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task_id = f"ifeval_{i + 1:04d}"
        mode = i % 4
        if mode == 0:
            keyword = f"orbit{i}"
            prompt = (
                f"Write exactly 3 bullet points. Include the word {keyword} "
                "somewhere in the response."
            )
            instructions = [
                {"type": "bullet_count", "count": 3},
                {"type": "keyword_include_all", "keywords": [keyword]},
            ]
        elif mode == 1:
            prompt = (
                "Return only a JSON object with keys city and status. "
                "Use city=Paris and status=ready."
            )
            instructions = [
                {"type": "format_json"},
                {"type": "json_field", "key": "city", "value": "Paris"},
                {"type": "json_field", "key": "status", "value": "ready"},
            ]
        elif mode == 2:
            keyword = f"alpha{i}"
            prompt = f"Answer in at most 5 words and include {keyword}."
            instructions = [
                {"type": "max_words", "count": 5},
                {"type": "keyword_include_all", "keywords": [keyword]},
            ]
        else:
            keyword = f"beta{i}"
            prompt = f"Start with PASS, end with DONE, and mention {keyword}."
            instructions = [
                {"type": "prefix", "text": "PASS"},
                {"type": "suffix", "text": "DONE"},
                {"type": "keyword_include_all", "keywords": [keyword]},
            ]
        tasks.append({"id": task_id, "prompt": prompt})
        gold.append({"id": task_id, "instructions": instructions})
    return tasks, gold


def _build_simpleqa(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        left = 2 + i
        right = 5 + (i * 3) % 17
        answer = str(left + right)
        task_id = f"simpleqa_{i + 1:04d}"
        tasks.append(
            {
                "id": task_id,
                "question": f"What is {left} + {right}?",
                "topic": "deterministic-arithmetic",
            }
        )
        gold.append({"id": task_id, "answer": answer, "aliases": [answer]})
    rng.shuffle(tasks)
    return tasks, gold


def _build_evalplus(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    templates = (
        _evalplus_add,
        _evalplus_is_even,
        _evalplus_reverse,
        _evalplus_clamp,
    )
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task, hidden = templates[i % len(templates)](i)
        tasks.append(task)
        gold.append(hidden)
    return tasks, gold


def _evalplus_add(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"add_numbers_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(a: int, b: int) -> int`.\n"
        "Return the sum of a and b."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}(1, 2) == 3\nassert {entry}(-1, 1) == 0",
            "plus_tests": f"assert {entry}(123, 456) == 579",
        },
    )


def _evalplus_is_even(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"is_even_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(n: int) -> bool`.\n"
        "Return True when n is even, otherwise False."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}(2) is True\nassert {entry}(3) is False",
            "plus_tests": f"assert {entry}(0) is True\nassert {entry}(-4) is True",
        },
    )


def _evalplus_reverse(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"reverse_text_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(text: str) -> str`.\n"
        "Return the reversed string."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}('abc') == 'cba'",
            "plus_tests": f"assert {entry}('orbit') == 'tibro'",
        },
    )


def _evalplus_clamp(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"clamp_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(x: int, low: int, high: int) -> int`.\n"
        "Return x limited to the inclusive [low, high] range."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}(5, 1, 9) == 5\nassert {entry}(0, 1, 9) == 1",
            "plus_tests": f"assert {entry}(10, 1, 9) == 9",
        },
    )


def _build_gaia(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task_id = f"gaia_{i + 1:04d}"
        if i % 3 == 0:
            red = 3 + i
            blue = 4 + i
            answer = str(red + blue)
            question = f"A box has {red} red chips and {blue} blue chips. How many chips total?"
            level = 1
        elif i % 3 == 1:
            answer = "Wednesday"
            question = "If a meeting is two days after Monday, what weekday is it?"
            level = 1
        else:
            answer = "12"
            question = "A train leaves at 08:15 and arrives at 20:15. How many hours pass?"
            level = 2
        tasks.append({"id": task_id, "question": question, "level": level})
        gold.append({"id": task_id, "final_answer": answer, "level": level})
    return tasks, gold

