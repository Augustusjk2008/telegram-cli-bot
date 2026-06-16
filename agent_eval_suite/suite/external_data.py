from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any


def load_ifeval_official(path: Path, *, samples: int, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _read_jsonl(path)
    selected = _sample(rows, samples, seed)
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        source_key = row.get("key", index)
        task_id = f"ifeval_{source_key}"
        prompt = str(row["prompt"])
        tasks.append({"id": task_id, "prompt": prompt})
        gold.append(
            {
                "id": task_id,
                "key": source_key,
                "prompt": prompt,
                "official_instruction_id_list": row["instruction_id_list"],
                "official_kwargs": row["kwargs"],
            }
        )
    return tasks, gold


def load_simpleqa_csv(path: Path, *, samples: int, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = _sample(rows, samples, seed)
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        task_id = str(row.get("id") or f"simpleqa_{index:04d}")
        question = str(row.get("problem") or row.get("question") or "")
        answer = str(row.get("answer") or row.get("target") or "")
        tasks.append({"id": task_id, "question": question})
        gold.append({"id": task_id, "answer": answer, "aliases": []})
    return tasks, gold


def load_gaia_jsonl(path: Path, *, samples: int, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _read_jsonl(path)
    selected = _sample(rows, samples, seed)
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        task_id = str(row.get("id") or row.get("task_id") or f"gaia_{index:04d}")
        question = str(row.get("question") or row.get("Question") or "")
        level = row.get("level") or row.get("Level") or "unknown"
        visible = {"id": task_id, "question": question, "level": level}
        if row.get("file_name"):
            visible["file_name"] = row["file_name"]
        tasks.append(visible)
        gold.append(
            {
                "id": task_id,
                "final_answer": str(row.get("final_answer") or row.get("Final answer") or row.get("answer") or ""),
                "level": level,
            }
        )
    return tasks, gold


def load_evalplus_humaneval(*, samples: int, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    try:
        from evalplus.data import get_human_eval_plus, get_human_eval_plus_hash  # type: ignore
    except ImportError as exc:
        raise RuntimeError("install evalplus to use --evalplus-source humaneval-plus") from exc

    problems = get_human_eval_plus()
    dataset_hash = get_human_eval_plus_hash()
    selected = _sample(list(problems.items()), samples, seed)
    tasks: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for task_id, problem in selected:
        tasks.append(
            {
                "task_id": task_id,
                "prompt": problem["prompt"],
                "entry_point": problem["entry_point"],
                "source": "HumanEval+",
            }
        )
        gold.append(
            {
                "task_id": task_id,
                "prompt": problem["prompt"],
                "entry_point": problem["entry_point"],
                "canonical_solution": problem["canonical_solution"],
                "base_input": problem["base_input"],
                "plus_input": problem["plus_input"],
                "atol": problem.get("atol", 0),
                "source": "HumanEval+",
            }
        )
    return tasks, gold, dataset_hash


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: JSONL row must be an object")
            rows.append(value)
    return rows


def _sample(rows: list[Any], samples: int, seed: int) -> list[Any]:
    if samples <= 0 or samples >= len(rows):
        return list(rows)
    rng = random.Random(seed)
    return rng.sample(rows, samples)

