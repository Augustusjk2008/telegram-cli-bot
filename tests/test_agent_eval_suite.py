from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

SUITE_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "agent_eval_suite"
sys.path.insert(0, str(SUITE_PACKAGE_ROOT))

from suite.jsonl import read_jsonl, write_jsonl  # noqa: E402
from suite.paths import BENCHMARKS  # noqa: E402
from suite.prepare import prepare_run  # noqa: E402
from suite.report import render_report  # noqa: E402
from suite.scoring import score_run  # noqa: E402


def test_prepare_smoke_creates_workspace_without_gold(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="r001",
        preset="smoke",
        samples=4,
        seed=123,
    )

    assert paths.prompt_path.exists()
    assert paths.manifest_path.exists()
    assert paths.answers_dir.exists()
    assert (paths.tasks_dir / "ifeval.jsonl").exists()
    assert (paths.gold_dir / "ifeval.jsonl").exists()
    assert not (paths.workspace / "private_gold").exists()

    workspace_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in paths.tasks_dir.glob("*.jsonl")
    )
    assert "base_tests" not in workspace_text
    assert "plus_tests" not in workspace_text
    assert "final_answer" not in workspace_text
    assert "answer" not in workspace_text

    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "r001"
    assert manifest["seed"] == 123
    assert manifest["task_hash"]
    assert manifest["dataset_source"] == "local-built-in-v1"


def test_prepare_hard_creates_workspace_ops_without_hidden_oracle(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="hard001",
        preset="win-native-hard",
        samples=10,
        seed=123,
    )

    task_path = paths.tasks_dir / "workspace_ops.jsonl"
    gold_path = paths.gold_dir / "workspace_ops.jsonl"
    assert task_path.exists()
    assert gold_path.exists()
    assert paths.cases_dir.exists()

    workspace_tasks = read_jsonl(task_path)
    workspace_gold = read_jsonl(gold_path)
    assert workspace_tasks
    assert workspace_gold
    assert {row["case_type"] for row in workspace_gold} >= {"add_tags", "path_report", "manifest_fix"}
    assert workspace_tasks[0]["workdir"].startswith("cases/workspace_")
    assert (paths.workspace / workspace_tasks[0]["workdir"]).exists()

    workspace_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in paths.workspace.rglob("*")
        if path.is_file()
    )
    assert "checks" not in workspace_text
    assert "return [f\"#{item}\" for item in tags]" not in workspace_text
    assert "oracle" not in workspace_text.casefold()
    assert "hidden_tests" not in workspace_text

    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["enabled_benchmarks"] == [*BENCHMARKS, "workspace_ops"]
    assert manifest["benchmarks"]["workspace_ops"] == len(workspace_tasks)

    prompt = paths.prompt_path.read_text(encoding="utf-8")
    assert "answers/workspace_ops.jsonl" in prompt
    assert "Work inside each listed cases/<id> directory." in prompt


def test_prepare_smoke_still_uses_static_benchmarks_only(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="smoke001",
        preset="smoke",
        samples=4,
        seed=123,
    )

    assert sorted(path.stem for path in paths.tasks_dir.glob("*.jsonl")) == sorted(BENCHMARKS)
    assert not (paths.tasks_dir / "workspace_ops.jsonl").exists()
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["enabled_benchmarks"] == list(BENCHMARKS)


def test_workspace_ops_score_passes_known_correct_case_and_report(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="hard002",
        preset="win-native-hard",
        samples=10,
        seed=123,
    )
    task = read_jsonl(paths.tasks_dir / "workspace_ops.jsonl")[0]
    case_dir = paths.workspace / task["workdir"]
    formatter = case_dir / "src" / "formatter.py"
    if formatter.exists():
        formatter.write_text(
            "def add_tags(tags):\n    return [f\"#{item}\" for item in tags]\n",
            encoding="utf-8",
        )
    write_jsonl(
        paths.answers_dir / "workspace_ops.jsonl",
        [{"id": task["id"], "status": "done", "summary": "fixed"}],
    )

    results = score_run(suite_root=tmp_path, run_id="hard002", evalplus_timeout=1.0)
    report_path = render_report(suite_root=tmp_path, run_id="hard002")
    summary_rows = list(csv.DictReader((paths.report_dir / "summary.csv").open(encoding="utf-8")))

    assert "workspace_ops" in results["benchmarks"]
    assert results["benchmarks"]["workspace_ops"]["metrics"]["pass@1"]["passed"] >= 1
    assert any(row["benchmark"] == "workspace_ops" for row in summary_rows)
    assert "workspace_ops" in report_path.read_text(encoding="utf-8")


def test_report_includes_workspace_failed_checks(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="hard003",
        preset="win-native-hard",
        samples=10,
        seed=123,
    )
    task = read_jsonl(paths.tasks_dir / "workspace_ops.jsonl")[0]
    write_jsonl(
        paths.answers_dir / "workspace_ops.jsonl",
        [{"id": task["id"], "status": "done", "summary": "not fixed"}],
    )

    score_run(suite_root=tmp_path, run_id="hard003", evalplus_timeout=1.0)
    report_path = render_report(suite_root=tmp_path, run_id="hard003")
    html = report_path.read_text(encoding="utf-8")

    assert "failed_checks:" in html
    assert "text_contains" in html


def test_empty_answers_fail_all(tmp_path: Path) -> None:
    prepare_run(
        suite_root=tmp_path,
        run_id="r002",
        preset="smoke",
        samples=4,
        seed=123,
    )

    results = score_run(suite_root=tmp_path, run_id="r002", evalplus_timeout=1.0)

    assert results["benchmarks"]["ifeval"]["metrics"]["prompt_strict_accuracy"]["passed"] == 0
    assert results["benchmarks"]["simpleqa"]["metrics"]["correct"]["passed"] == 0
    assert results["benchmarks"]["evalplus"]["metrics"]["plus_pass@1"]["passed"] == 0
    assert results["benchmarks"]["gaia"]["metrics"]["accuracy"]["passed"] == 0
    assert results["workspace_integrity"]["passed"] is True
    assert all(results["schema_validation"][name] for name in ("ifeval", "simpleqa", "evalplus", "gaia"))


def test_known_correct_answers_pass_and_report(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="r003",
        preset="smoke",
        samples=4,
        seed=123,
    )
    write_jsonl(
        paths.answers_dir / "ifeval.jsonl",
        [{"id": "ifeval_0001", "response": "- orbit0\n- orbit0\n- orbit0"}],
    )
    write_jsonl(
        paths.answers_dir / "simpleqa.jsonl",
        [{"id": "simpleqa_0001", "answer": "7"}],
    )
    write_jsonl(
        paths.answers_dir / "evalplus.jsonl",
        [
            {
                "task_id": "HumanEval/0",
                "solution": "def add_numbers_0(a, b):\n    return a + b\n",
            }
        ],
    )
    write_jsonl(
        paths.answers_dir / "gaia.jsonl",
        [{"id": "gaia_0001", "final_answer": "7"}],
    )

    results = score_run(suite_root=tmp_path, run_id="r003", evalplus_timeout=1.0)
    report_path = render_report(suite_root=tmp_path, run_id="r003")

    assert results["benchmarks"]["ifeval"]["metrics"]["prompt_strict_accuracy"]["passed"] == 1
    assert results["benchmarks"]["simpleqa"]["metrics"]["correct"]["passed"] == 1
    assert results["benchmarks"]["evalplus"]["metrics"]["plus_pass@1"]["passed"] == 1
    assert results["benchmarks"]["gaia"]["metrics"]["accuracy"]["passed"] == 1
    assert report_path.exists()
    assert "Agent Eval Report" in report_path.read_text(encoding="utf-8")

    summary_rows = list(csv.DictReader((paths.report_dir / "summary.csv").open(encoding="utf-8")))
    assert any(row["benchmark"] == "workspace" for row in summary_rows)


def test_evalplus_timeout_is_reported(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="r004",
        preset="smoke",
        samples=4,
        seed=123,
    )
    write_jsonl(
        paths.answers_dir / "evalplus.jsonl",
        [
            {
                "task_id": "HumanEval/0",
                "solution": "def add_numbers_0(a, b):\n    while True:\n        pass\n",
            }
        ],
    )

    results = score_run(suite_root=tmp_path, run_id="r004", evalplus_timeout=0.4)

    assert results["benchmarks"]["evalplus"]["metrics"]["timeout"]["passed"] == 1
    detail = results["benchmarks"]["evalplus"]["details"][0]
    assert detail["reason"] == "timeout"


def test_jsonl_rejects_non_object_rows(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_jsonl(path)


def test_answer_schema_errors_are_reported(tmp_path: Path) -> None:
    paths = prepare_run(
        suite_root=tmp_path,
        run_id="r005",
        preset="smoke",
        samples=4,
        seed=123,
    )
    write_jsonl(
        paths.answers_dir / "simpleqa.jsonl",
        [
            {"id": "simpleqa_0001", "answer": "7"},
            {"id": "simpleqa_0001", "answer": "7"},
            {"id": "unknown", "answer": "7"},
            {"answer": "7"},
            {"id": "simpleqa_0001", "answer": 7},
        ],
    )

    results = score_run(suite_root=tmp_path, run_id="r005", evalplus_timeout=1.0)
    reasons = {
        error["reason"]
        for error in results["schema_validation"]["simpleqa"]
    }

    assert "duplicate_id" in reasons
    assert "unknown_id" in reasons
    assert "missing_id" in reasons
    assert "answer_must_be_string" in reasons


def test_prepare_accepts_external_simpleqa_and_gaia_sources(tmp_path: Path) -> None:
    simpleqa = tmp_path / "simpleqa.csv"
    simpleqa.write_text("id,question,answer\ns1,What is 2+2?,4\n", encoding="utf-8")
    gaia = tmp_path / "gaia.jsonl"
    gaia.write_text(
        json.dumps(
            {
                "id": "g1",
                "question": "What color is the sky on a clear day?",
                "final_answer": "blue",
                "level": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    paths = prepare_run(
        suite_root=tmp_path,
        run_id="r006",
        preset="smoke",
        samples=4,
        seed=123,
        simpleqa_csv=simpleqa,
        gaia_jsonl=gaia,
    )

    assert read_jsonl(paths.tasks_dir / "simpleqa.jsonl")[0]["id"] == "s1"
    assert read_jsonl(paths.gold_dir / "gaia.jsonl")[0]["final_answer"] == "blue"
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["external_sources"]["simpleqa_source"] == str(simpleqa)
    assert manifest["external_sources"]["gaia_source"] == str(gaia)
