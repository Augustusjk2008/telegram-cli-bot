from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .data import build_dataset
from .external_data import (
    load_evalplus_humaneval,
    load_gaia_jsonl,
    load_ifeval_official,
    load_simpleqa_csv,
)
from .jsonl import write_jsonl
from .paths import BENCHMARKS, SuitePaths


def prepare_run(
    *,
    suite_root: Path,
    run_id: str,
    preset: str,
    samples: int,
    seed: int,
    overwrite: bool = False,
    ifeval_input: Path | None = None,
    simpleqa_csv: Path | None = None,
    evalplus_source: str = "local",
    gaia_jsonl: Path | None = None,
) -> SuitePaths:
    paths = SuitePaths(suite_root=suite_root.resolve(), run_id=run_id)
    _validate_run_id(run_id)
    if overwrite:
        _safe_rmtree(paths.run_root, paths.suite_root)
        _safe_rmtree(paths.gold_dir, paths.suite_root)
    elif paths.run_root.exists() or paths.gold_dir.exists():
        raise FileExistsError(f"run already exists: {run_id}")

    visible, gold = build_dataset(preset=preset, samples=samples, seed=seed)
    external_metadata: dict[str, Any] = {}
    per_benchmark_samples = max(1, samples // len(BENCHMARKS))
    if ifeval_input:
        visible["ifeval"], gold["ifeval"] = load_ifeval_official(
            ifeval_input,
            samples=per_benchmark_samples,
            seed=seed,
        )
        external_metadata["ifeval_source"] = str(ifeval_input)
    if simpleqa_csv:
        visible["simpleqa"], gold["simpleqa"] = load_simpleqa_csv(
            simpleqa_csv,
            samples=per_benchmark_samples,
            seed=seed,
        )
        external_metadata["simpleqa_source"] = str(simpleqa_csv)
    if evalplus_source == "humaneval-plus":
        visible["evalplus"], gold["evalplus"], dataset_hash = load_evalplus_humaneval(
            samples=per_benchmark_samples,
            seed=seed,
        )
        external_metadata["evalplus_source"] = "humaneval-plus"
        external_metadata["evalplus_dataset_hash"] = dataset_hash
    elif evalplus_source != "local":
        raise ValueError(f"unsupported evalplus source: {evalplus_source}")
    if gaia_jsonl:
        visible["gaia"], gold["gaia"] = load_gaia_jsonl(
            gaia_jsonl,
            samples=per_benchmark_samples,
            seed=seed,
        )
        external_metadata["gaia_source"] = str(gaia_jsonl)
    paths.tasks_dir.mkdir(parents=True, exist_ok=True)
    paths.answers_dir.mkdir(parents=True, exist_ok=True)
    paths.report_dir.mkdir(parents=True, exist_ok=True)
    paths.gold_dir.mkdir(parents=True, exist_ok=True)

    for benchmark in BENCHMARKS:
        write_jsonl(paths.tasks_dir / f"{benchmark}.jsonl", visible[benchmark])
        write_jsonl(paths.gold_dir / f"{benchmark}.jsonl", gold[benchmark])

    paths.prompt_path.write_text(_build_prompt(), encoding="utf-8", newline="\n")
    metadata = {
        "run_id": run_id,
        "preset": preset,
        "samples": samples,
        "seed": seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmarks": {name: len(visible[name]) for name in BENCHMARKS},
        "dataset_source": "local-built-in-v1",
        "task_hash": _hash_dataset(visible),
        "gold_hash": _hash_dataset(gold),
        "adapters": {
            "ifeval": "local-verifiable-instructions",
            "simpleqa": "deterministic-or-openai-grader",
            "evalplus": "win-adapter-subprocess",
            "gaia": "local-final-answer-lite",
        },
        "external_sources": external_metadata,
    }
    metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
    paths.metadata_path.write_text(metadata_text, encoding="utf-8", newline="\n")
    paths.manifest_path.write_text(metadata_text, encoding="utf-8", newline="\n")
    return paths


def _validate_run_id(run_id: str) -> None:
    if not run_id:
        raise ValueError("run_id is required")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(char not in allowed for char in run_id):
        raise ValueError("run_id may only contain letters, digits, '_' and '-'")


def _safe_rmtree(path: Path, suite_root: Path) -> None:
    if not path.exists():
        return
    resolved_path = path.resolve()
    resolved_root = suite_root.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise ValueError(f"refusing to remove path outside suite root: {path}")
    shutil.rmtree(resolved_path)


def _build_prompt() -> str:
    return """# Agent Evaluation Task

Read every JSONL file in `tasks/` and write answers to `answers/`.

Rules:
- Do not read parent directories.
- Do not modify `tasks/`.
- Write valid JSONL, one object per line.
- Preserve each task id.
- If you cannot answer, still write a row with an empty string.

Output files and schemas:

`answers/ifeval.jsonl`
```jsonl
{"id":"ifeval_0001","response":"your response"}
```

`answers/simpleqa.jsonl`
```jsonl
{"id":"simpleqa_0001","answer":"your short answer"}
```

`answers/evalplus.jsonl`
```jsonl
{"task_id":"HumanEval/0","solution":"def function_name(...):\\n    ..."}
```

`answers/gaia.jsonl`
```jsonl
{"id":"gaia_0001","final_answer":"your final answer"}
```
"""


def _hash_dataset(dataset: dict[str, list[dict[str, Any]]]) -> str:
    payload = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
