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
from .paths import BENCHMARKS, PRESET_BENCHMARKS, SuitePaths, WORKSPACE_BENCHMARK


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
    enabled_benchmarks = list(PRESET_BENCHMARKS[preset])
    per_benchmark_samples = max(1, samples // len(enabled_benchmarks))
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
    if preset == "win-native-hard":
        paths.cases_dir.mkdir(parents=True, exist_ok=True)
        paths.gold_cases_dir.mkdir(parents=True, exist_ok=True)

    for benchmark in enabled_benchmarks:
        write_jsonl(paths.tasks_dir / f"{benchmark}.jsonl", visible[benchmark])
        write_jsonl(paths.gold_dir / f"{benchmark}.jsonl", gold[benchmark])
    if preset == "win-native-hard":
        _write_reference_cases(paths, visible, gold)
        _write_workspace_cases(paths, visible["workspace_ops"], gold["workspace_ops"])

    paths.prompt_path.write_text(_build_prompt(enabled_benchmarks), encoding="utf-8", newline="\n")
    metadata = {
        "run_id": run_id,
        "preset": preset,
        "samples": samples,
        "seed": seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmarks": {name: len(visible[name]) for name in enabled_benchmarks},
        "enabled_benchmarks": enabled_benchmarks,
        "dataset_source": "local-built-in-v1",
        "task_hash": _hash_dataset(visible),
        "gold_hash": _hash_dataset(gold),
        "adapters": {
            "ifeval": "local-verifiable-instructions",
            "simpleqa": "deterministic-or-openai-grader",
            "evalplus": "win-adapter-subprocess",
            "gaia": "local-final-answer-lite",
            "workspace_ops": "workspace-file-state-grader",
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


def _build_prompt(enabled_benchmarks: list[str]) -> str:
    prompt = """# Agent Evaluation Task

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
    if WORKSPACE_BENCHMARK not in enabled_benchmarks:
        return prompt
    return (
        prompt
        + """

For workspace_ops:
- Work inside each listed cases/<id> directory.
- Do not modify tasks/.
- Write answers/workspace_ops.jsonl with {"id":"workspace_0001","status":"done","summary":"..."}.
"""
    )


def _write_workspace_cases(paths: SuitePaths, task_rows: list[dict[str, Any]], gold_rows: list[dict[str, Any]]) -> None:
    gold_by_id = {str(row["id"]): row for row in gold_rows}
    for task in task_rows:
        task_id = str(task["id"])
        case_rel = Path(str(task["workdir"]))
        case_dir = paths.workspace / case_rel
        case_dir.mkdir(parents=True, exist_ok=True)
        _seed_workspace_case(case_dir, task_id, gold_by_id[task_id])


def _seed_workspace_case(case_dir: Path, task_id: str, gold_row: dict[str, Any]) -> None:
    del task_id
    case_type = str(gold_row.get("case_type", ""))
    if case_type == "add_tags":
        (case_dir / "src").mkdir(parents=True, exist_ok=True)
        (case_dir / "tests").mkdir(parents=True, exist_ok=True)
        (case_dir / "src" / "formatter.py").write_text(
            "def add_tags(tags):\n    return [item for item in tags]\n",
            encoding="utf-8",
            newline="\n",
        )
        (case_dir / "tests" / "test_formatter.py").write_text(
            "from src.formatter import add_tags\n\n"
            "def test_add_tags():\n"
            "    assert add_tags(['a', 'b']) == ['#a', '#b']\n",
            encoding="utf-8",
            newline="\n",
        )
        return
    if case_type == "path_report":
        (case_dir / "notes.md").write_text(
            "output path: reports/final.txt\nline: 42\nconclusion: ready\n",
            encoding="utf-8",
            newline="\n",
        )
        (case_dir / "reports").mkdir(parents=True, exist_ok=True)
        return
    if case_type == "manifest_fix":
        (case_dir / "plugin.json").write_text(
            json.dumps({"permissions": {"filesystem": "read"}}),
            encoding="utf-8",
            newline="\n",
        )
        return
    (case_dir / "README.md").write_text("workspace case\n", encoding="utf-8", newline="\n")


def _write_reference_cases(
    paths: SuitePaths,
    visible: dict[str, list[dict[str, Any]]],
    gold: dict[str, list[dict[str, Any]]],
) -> None:
    _write_simpleqa_reference_cases(paths, visible.get("simpleqa", []), gold.get("simpleqa", []))
    _write_gaia_reference_cases(paths, visible.get("gaia", []), gold.get("gaia", []))


def _write_simpleqa_reference_cases(
    paths: SuitePaths,
    task_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
) -> None:
    gold_by_id = {str(row["id"]): row for row in gold_rows}
    for task in task_rows:
        task_id = str(task["id"])
        if str(task.get("topic", "")) != "workspace-reference":
            continue
        case_dir = paths.cases_dir / task_id
        case_dir.mkdir(parents=True, exist_ok=True)
        answer = str(gold_by_id.get(task_id, {}).get("answer", ""))
        if str(task.get("source", "")).endswith("facts.json"):
            (case_dir / "facts.json").write_text(
                json.dumps({"canonical_incident_code": answer, "distractor_code": "CASE-000"}),
                encoding="utf-8",
                newline="\n",
            )
        else:
            (case_dir / "notes.md").write_text(
                f"draft route: east-0\nfinal route: {answer}\n",
                encoding="utf-8",
                newline="\n",
            )


def _write_gaia_reference_cases(
    paths: SuitePaths,
    task_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
) -> None:
    gold_by_id = {str(row["id"]): row for row in gold_rows}
    for task in task_rows:
        task_id = str(task["id"])
        if str(task.get("difficulty", "")) != "hard":
            continue
        case_dir = paths.cases_dir / task_id
        case_dir.mkdir(parents=True, exist_ok=True)
        answer = str(gold_by_id.get(task_id, {}).get("final_answer", ""))
        (case_dir / "ledger.md").write_text(
            "candidate launch code: delta-000\n"
            f"confirmed launch code: {answer}\n",
            encoding="utf-8",
            newline="\n",
        )
        (case_dir / "archive.json").write_text(
            json.dumps({"ignore": ["delta-111", "delta-999"], "status": "confirmed"}),
            encoding="utf-8",
            newline="\n",
        )


def _hash_dataset(dataset: dict[str, list[dict[str, Any]]]) -> str:
    payload = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
