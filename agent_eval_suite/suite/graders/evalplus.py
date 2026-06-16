from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..jsonl import index_by


def score_evalplus(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    answers = index_by(answer_rows, "task_id")
    details: list[dict[str, Any]] = []
    base_passed = 0
    plus_passed = 0
    timeouts = 0
    runtime_errors = 0

    for gold in gold_rows:
        task_id = str(gold["task_id"])
        row = answers.get(task_id)
        solution = str(row.get("solution", "")) if row else ""
        if not solution.strip():
            details.append(
                {
                    "task_id": task_id,
                    "passed": False,
                    "base_passed": False,
                    "plus_passed": False,
                    "reason": "missing_answer",
                    "answer_present": row is not None,
                }
            )
            runtime_errors += 1
            continue

        base = _run_evalplus_case(
            solution=solution,
            gold=gold,
            split="base",
            timeout_seconds=timeout_seconds,
        )
        plus = {"ok": False, "reason": "base_failed"}
        if base["ok"]:
            plus = _run_evalplus_case(
                solution=solution,
                gold=gold,
                split="plus",
                timeout_seconds=timeout_seconds,
            )
        base_ok = bool(base["ok"])
        plus_ok = bool(base_ok and plus["ok"])
        base_passed += int(base_ok)
        plus_passed += int(plus_ok)
        timed_out = base.get("reason") == "timeout" or plus.get("reason") == "timeout"
        runtime_error = not timed_out and not plus_ok
        timeouts += int(timed_out)
        runtime_errors += int(runtime_error)
        if plus_ok:
            reason = "pass"
        elif base.get("reason") == "timeout" or plus.get("reason") == "timeout":
            reason = "timeout"
        elif not base_ok:
            reason = str(base.get("reason"))
        else:
            reason = str(plus.get("reason"))
        details.append(
            {
                "task_id": task_id,
                "passed": plus_ok,
                "base_passed": base_ok,
                "plus_passed": plus_ok,
                "reason": reason,
                "base_result": base,
                "plus_result": plus,
                "answer_present": row is not None,
            }
        )

    total = len(gold_rows)
    return {
        "metrics": {
            "base_pass@1": _metric(base_passed, total),
            "plus_pass@1": _metric(plus_passed, total),
            "timeout": _count_metric(timeouts, total),
            "runtime_error": _count_metric(runtime_errors, total),
        },
        "details": details,
    }


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {"value": (passed / total) if total else 0.0, "passed": passed, "total": total}


def _count_metric(count: int, total: int) -> dict[str, Any]:
    return {"value": count, "passed": count, "total": total}


def _run_tests(*, solution: str, test_code: str, timeout_seconds: float) -> dict[str, Any]:
    runner = Path(__file__).with_name("evalplus_runner.py")
    payload = {"solution": solution, "test_code": test_code}
    return _run_payload(runner=runner, payload=payload, timeout_seconds=timeout_seconds)


def _run_payload(
    *,
    runner: Path,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-evalplus-") as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                [sys.executable, str(runner), str(payload_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=tmp_dir,
                env=_runner_env(),
                **popen_kwargs,
            )
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            return {"ok": False, "reason": "timeout"}
    stdout = _truncate(stdout.strip())
    stderr = _truncate(stderr.strip())
    try:
        parsed = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except json.JSONDecodeError:
        parsed = {"ok": False, "error": "invalid_runner_output", "stdout": stdout, "stderr": stderr}
    if process.returncode == 0 and parsed.get("ok") is True:
        return {"ok": True, "reason": "pass"}
    return {
        "ok": False,
        "reason": parsed.get("error") or "runtime_error",
        "message": _truncate(str(parsed.get("message", ""))),
        "stderr": stderr,
    }


def _run_evalplus_case(
    *,
    solution: str,
    gold: dict[str, Any],
    split: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    input_key = f"{split}_input"
    test_key = f"{split}_tests"
    if input_key in gold:
        return _run_call_tests(
            solution=solution,
            prompt=str(gold.get("prompt", "")),
            canonical_solution=str(gold["canonical_solution"]),
            entry_point=str(gold["entry_point"]),
            inputs=list(gold.get(input_key, [])),
            atol=float(gold.get("atol", 0) or 0),
            timeout_seconds=timeout_seconds,
        )
    return _run_tests(
        solution=solution,
        test_code=str(gold.get(test_key, "")),
        timeout_seconds=timeout_seconds,
    )


def _run_call_tests(
    *,
    solution: str,
    prompt: str,
    canonical_solution: str,
    entry_point: str,
    inputs: list[Any],
    atol: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    runner = Path(__file__).with_name("evalplus_runner.py")
    payload = {
        "mode": "call_tests",
        "solution": solution,
        "prompt": prompt,
        "canonical_solution": canonical_solution,
        "entry_point": entry_point,
        "inputs": inputs,
        "atol": atol,
    }
    return _run_payload(runner=runner, payload=payload, timeout_seconds=timeout_seconds)


def _runner_env() -> dict[str, str]:
    return {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        import psutil  # type: ignore
    except ImportError:
        process.kill()
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=1)
    except psutil.Error:
        process.kill()
