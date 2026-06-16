from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graders.evalplus import score_evalplus
from .graders.gaia import score_gaia
from .graders.ifeval import score_ifeval
from .graders.simpleqa import score_simpleqa
from .graders.workspace import score_workspace_ops
from .jsonl import read_jsonl
from .paths import BENCHMARKS, SuitePaths
from .validation import validate_answer_rows


def score_run(
    *,
    suite_root: Path,
    run_id: str,
    simpleqa_grader: str = "deterministic",
    simpleqa_grader_model: str | None = None,
    evalplus_timeout: float = 3.0,
    model: str = "unknown",
) -> dict[str, Any]:
    paths = SuitePaths(suite_root=suite_root.resolve(), run_id=run_id)
    metadata = _load_metadata(paths)
    metadata["scored_at"] = datetime.now(timezone.utc).isoformat()
    metadata["model"] = model
    metadata["simpleqa_grader"] = simpleqa_grader
    metadata["simpleqa_grader_model"] = simpleqa_grader_model or ""
    metadata["evalplus_timeout"] = evalplus_timeout
    metadata["evalplus_adapter"] = "win-adapter-subprocess"
    benchmarks: dict[str, Any] = {}
    validation: dict[str, list[dict[str, Any]]] = {}

    for benchmark in _enabled_benchmarks(metadata):
        tasks = read_jsonl(paths.tasks_dir / f"{benchmark}.jsonl")
        gold = read_jsonl(paths.gold_dir / f"{benchmark}.jsonl")
        answers = read_jsonl(paths.answers_dir / f"{benchmark}.jsonl")
        validation[benchmark] = validate_answer_rows(
            benchmark=benchmark,
            task_rows=tasks,
            answer_rows=answers,
        )
        if benchmark == "ifeval":
            result = score_ifeval(gold_rows=gold, answer_rows=answers)
        elif benchmark == "simpleqa":
            result = score_simpleqa(
                gold_rows=gold,
                answer_rows=answers,
                grader=simpleqa_grader,
                grader_model=simpleqa_grader_model,
            )
        elif benchmark == "evalplus":
            result = score_evalplus(
                gold_rows=gold,
                answer_rows=answers,
                timeout_seconds=evalplus_timeout,
            )
        elif benchmark == "gaia":
            result = score_gaia(gold_rows=gold, answer_rows=answers)
        elif benchmark == "workspace_ops":
            result = score_workspace_ops(
                gold_rows=gold,
                answer_rows=answers,
                workspace_root=paths.workspace,
            )
        else:
            raise ValueError(f"unsupported benchmark: {benchmark}")
        result["answer_file"] = str(paths.answers_dir / f"{benchmark}.jsonl")
        result["schema_errors"] = validation[benchmark]
        benchmarks[benchmark] = result

    results = {
        "metadata": metadata,
        "benchmarks": benchmarks,
        "schema_validation": validation,
        "workspace_integrity": _workspace_integrity(paths),
    }
    paths.report_dir.mkdir(parents=True, exist_ok=True)
    (paths.report_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    _write_summary_csv(paths.report_dir / "summary.csv", results)
    return results


def _load_metadata(paths: SuitePaths) -> dict[str, Any]:
    metadata_path = paths.manifest_path if paths.manifest_path.exists() else paths.metadata_path
    if not metadata_path.exists():
        raise FileNotFoundError(f"missing run metadata: {paths.metadata_path}")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _enabled_benchmarks(metadata: dict[str, Any]) -> list[str]:
    value = metadata.get("enabled_benchmarks")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return list(BENCHMARKS)


def _write_summary_csv(path: Path, results: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["benchmark", "metric", "value", "passed", "total"],
        )
        writer.writeheader()
        for benchmark, result in results["benchmarks"].items():
            for metric, value in result.get("metrics", {}).items():
                writer.writerow(
                    {
                        "benchmark": benchmark,
                        "metric": metric,
                        "value": value.get("value", 0),
                        "passed": value.get("passed", 0),
                        "total": value.get("total", 0),
                    }
                )
            errors = result.get("schema_errors", [])
            writer.writerow(
                {
                    "benchmark": benchmark,
                    "metric": "schema_errors",
                    "value": len(errors),
                    "passed": 0 if errors else 1,
                    "total": 1,
                }
            )
        integrity = results["workspace_integrity"]
        writer.writerow(
            {
                "benchmark": "workspace",
                "metric": "no_gold_or_hidden_tests",
                "value": 1 if integrity["passed"] else 0,
                "passed": 1 if integrity["passed"] else 0,
                "total": 1,
            }
        )


def _workspace_integrity(paths: SuitePaths) -> dict[str, Any]:
    forbidden_names = {
        "private_gold",
        "gold",
        "hidden_tests",
        "reference_answer",
        "oracle",
        "gold_backup",
    }
    violations: list[str] = []
    if paths.workspace.exists():
        for item in paths.workspace.rglob("*"):
            lowered = item.name.casefold()
            if lowered in forbidden_names or lowered.endswith(".gold"):
                violations.append(str(item.relative_to(paths.workspace)))
    return {"passed": not violations, "violations": violations}
