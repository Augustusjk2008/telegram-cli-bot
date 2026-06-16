from __future__ import annotations

import random
from typing import Any

from .paths import PRESET_BENCHMARKS, WORKSPACE_BENCHMARK


def build_dataset(
    *,
    preset: str,
    samples: int,
    seed: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    if preset not in PRESET_BENCHMARKS:
        raise ValueError(f"unsupported preset: {preset}")
    benchmarks = PRESET_BENCHMARKS[preset]
    samples = max(samples, len(benchmarks))
    counts = _benchmark_counts(samples, benchmarks)
    rng = random.Random(seed)
    builders = _hard_builders() if preset == "win-native-hard" else _static_builders()

    visible: dict[str, list[dict[str, Any]]] = {}
    gold: dict[str, list[dict[str, Any]]] = {}
    for benchmark, count in counts.items():
        if benchmark == WORKSPACE_BENCHMARK:
            task_rows, gold_rows = _build_workspace_ops(count, rng)
        else:
            task_rows, gold_rows = builders[benchmark](count, rng)
        visible[benchmark] = task_rows
        gold[benchmark] = gold_rows
    return visible, gold


def _benchmark_counts(samples: int, benchmarks: tuple[str, ...]) -> dict[str, int]:
    base = samples // len(benchmarks)
    remainder = samples % len(benchmarks)
    counts = {
        benchmark: base + (1 if index < remainder else 0)
        for index, benchmark in enumerate(benchmarks)
    }
    if WORKSPACE_BENCHMARK in counts:
        counts[WORKSPACE_BENCHMARK] = max(3, counts[WORKSPACE_BENCHMARK])
    return counts


def _static_builders() -> dict[str, Any]:
    return {
        "ifeval": _build_ifeval,
        "simpleqa": _build_simpleqa,
        "evalplus": _build_evalplus,
        "gaia": _build_gaia,
    }


def _hard_builders() -> dict[str, Any]:
    return {
        "ifeval": _build_ifeval_hard,
        "simpleqa": _build_simpleqa_hard,
        "evalplus": _build_evalplus_hard,
        "gaia": _build_gaia_hard,
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


def _build_ifeval_hard(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task_id = f"ifeval_{i + 1:04d}"
        keyword = f"ORBIT{i}"
        prompt = (
            "Return only a JSON object. It must have keys status, tag, and note. "
            f"Use status=ready, tag={keyword}. The note must start with PASS, "
            "end with DONE, and contain no more than 6 words."
        )
        tasks.append({"id": task_id, "prompt": prompt, "difficulty": "hard"})
        gold.append(
            {
                "id": task_id,
                "instructions": [
                    {"type": "format_json"},
                    {"type": "json_field", "key": "status", "value": "ready"},
                    {"type": "json_field", "key": "tag", "value": keyword},
                    {"type": "keyword_include_all", "keywords": [keyword]},
                    {"type": "prefix", "text": "{"},
                    {"type": "suffix", "text": "}"},
                    {"type": "max_words", "count": 12},
                ],
            }
        )
    return tasks, gold


def _build_simpleqa_hard(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task_id = f"simpleqa_{i + 1:04d}"
        if i % 2 == 0:
            answer = f"CASE-{100 + i}"
            question = (
                f"Read cases/{task_id}/facts.json. What is the canonical incident code?"
            )
            source = "facts.json"
        else:
            answer = f"north-{i + 3}"
            question = f"Read cases/{task_id}/notes.md. What route is marked final?"
            source = "notes.md"
        tasks.append(
            {
                "id": task_id,
                "question": question,
                "topic": "workspace-reference",
                "source": f"cases/{task_id}/{source}",
                "difficulty": "hard",
            }
        )
        gold.append({"id": task_id, "answer": answer, "aliases": [answer], "source": source})
    rng.shuffle(tasks)
    return tasks, gold


def _build_evalplus_hard(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    templates = (
        _evalplus_parse_ints,
        _evalplus_safe_ratio,
        _evalplus_window_sum,
    )
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task, hidden = templates[i % len(templates)](i)
        tasks.append(task)
        gold.append(hidden)
    return tasks, gold


def _evalplus_parse_ints(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"parse_ints_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(text: str) -> list[int]`.\n"
        "Split on commas, trim whitespace, ignore empty fields, and parse signed integers."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry, "difficulty": "hard"},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}('1, 2, -3') == [1, 2, -3]",
            "plus_tests": f"assert {entry}(' 4,, -5 ,0 ') == [4, -5, 0]",
        },
    )


def _evalplus_safe_ratio(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"safe_ratio_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(num: float, den: float) -> float | None`.\n"
        "Return None when den is zero; otherwise return num / den."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry, "difficulty": "hard"},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}(6, 3) == 2\nassert {entry}(1, 0) is None",
            "plus_tests": f"assert {entry}(-9, 3) == -3\nassert {entry}(0, 5) == 0",
        },
    )


def _evalplus_window_sum(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = f"window_sum_{i}"
    task_id = f"HumanEval/{i}"
    prompt = (
        f"Implement `{entry}(values: list[int], size: int) -> list[int]`.\n"
        "Return sums for each contiguous window. Return [] when size <= 0 or size is too large."
    )
    return (
        {"task_id": task_id, "prompt": prompt, "entry_point": entry, "difficulty": "hard"},
        {
            "task_id": task_id,
            "entry_point": entry,
            "base_tests": f"assert {entry}([1, 2, 3], 2) == [3, 5]",
            "plus_tests": (
                f"assert {entry}([5], 2) == []\n"
                f"assert {entry}([1, -1, 4, 0], 3) == [4, 3]\n"
                f"assert {entry}([1, 2], 0) == []"
            ),
        },
    )


def _build_gaia_hard(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for i in range(count):
        task_id = f"gaia_{i + 1:04d}"
        answer = f"delta-{200 + i}"
        tasks.append(
            {
                "id": task_id,
                "question": (
                    f"Use cases/{task_id}/ledger.md and cases/{task_id}/archive.json. "
                    "Ignore distractors. What is the confirmed launch code?"
                ),
                "level": 2,
                "difficulty": "hard",
            }
        )
        gold.append({"id": task_id, "final_answer": answer, "level": 2})
    return tasks, gold


def _build_workspace_ops(
    count: int, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del rng
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    templates = (_workspace_add_tags, _workspace_path_report, _workspace_manifest_fix)
    for i in range(count):
        task, hidden = templates[i % len(templates)](i)
        tasks.append(task)
        gold.append(hidden)
    return tasks, gold


def _workspace_add_tags(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    task_id = f"workspace_{i + 1:04d}"
    workdir = f"cases/{task_id}"
    return (
        {
            "id": task_id,
            "instruction": (
                f"Fix the failing add_tags behavior in {workdir}. "
                "Only edit src/formatter.py. Then write an answer row."
            ),
            "workdir": workdir,
            "difficulty": "hard",
        },
        {
            "id": task_id,
            "workdir": workdir,
            "case_type": "add_tags",
            "checks": [
                {
                    "type": "text_contains",
                    "path": "src/formatter.py",
                    "text": "return [f\"#{item}\" for item in tags]",
                },
                {
                    "type": "command_exit_zero",
                    "argv": ["python", "-m", "pytest", "tests/test_formatter.py", "-q"],
                    "timeout_seconds": 5,
                },
            ],
        },
    )


def _workspace_path_report(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    task_id = f"workspace_{i + 1:04d}"
    workdir = f"cases/{task_id}"
    return (
        {
            "id": task_id,
            "instruction": (
                f"Inspect {workdir}. Create reports/final.txt containing output path, "
                "line number, and conclusion from notes.md."
            ),
            "workdir": workdir,
            "difficulty": "hard",
        },
        {
            "id": task_id,
            "workdir": workdir,
            "case_type": "path_report",
            "checks": [
                {"type": "file_exists", "path": "reports/final.txt"},
                {"type": "text_contains", "path": "reports/final.txt", "text": "reports/final.txt"},
                {"type": "text_contains", "path": "reports/final.txt", "text": "42"},
                {"type": "text_contains", "path": "reports/final.txt", "text": "ready"},
            ],
        },
    )


def _workspace_manifest_fix(i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    task_id = f"workspace_{i + 1:04d}"
    workdir = f"cases/{task_id}"
    return (
        {
            "id": task_id,
            "instruction": (
                f"Fix the plugin manifest in {workdir}. The filesystem permission "
                "must be readonly. Then write an answer row."
            ),
            "workdir": workdir,
            "difficulty": "hard",
        },
        {
            "id": task_id,
            "workdir": workdir,
            "case_type": "manifest_fix",
            "checks": [
                {
                    "type": "json_field_equals",
                    "path": "plugin.json",
                    "field": "permissions.filesystem",
                    "value": "readonly",
                }
            ],
        },
    )
