from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..jsonl import index_by


def score_workspace_ops(
    *,
    gold_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
    workspace_root: Path,
) -> dict[str, Any]:
    answers = index_by(answer_rows, "id")
    details: list[dict[str, Any]] = []
    passed = 0
    check_passed = 0
    check_total = 0
    timeouts = 0
    runtime_errors = 0

    for gold in gold_rows:
        task_id = str(gold["id"])
        answer = answers.get(task_id)
        case_dir = _case_dir(workspace_root, str(gold.get("workdir", "")))
        failed_checks: list[dict[str, Any]] = []
        case_check_total = 0
        case_check_passed = 0
        case_timeouts = False
        case_runtime_errors = False

        for check in gold.get("checks", []):
            case_check_total += 1
            result = _run_check(case_dir=case_dir, check=check)
            if result["passed"]:
                case_check_passed += 1
            else:
                failed_checks.append(result)
                if result.get("reason") == "timeout":
                    case_timeouts = True
                elif result.get("runtime_error", False):
                    case_runtime_errors = True

        check_total += case_check_total
        check_passed += case_check_passed
        timeouts += int(case_timeouts)
        runtime_errors += int(case_runtime_errors)
        case_passed = answer is not None and case_check_total > 0 and not failed_checks
        passed += int(case_passed)
        if answer is None:
            reason = "missing_answer"
        elif case_passed:
            reason = "pass"
        else:
            reason = "check_failed"
        details.append(
            {
                "id": task_id,
                "passed": case_passed,
                "reason": reason,
                "answer_present": answer is not None,
                "checks_passed": case_check_passed,
                "checks_total": case_check_total,
                "failed_checks": failed_checks,
            }
        )

    total = len(gold_rows)
    return {
        "metrics": {
            "pass@1": _metric(passed, total),
            "check_pass_rate": _metric(check_passed, check_total),
            "timeout": _count_metric(timeouts, total),
            "runtime_error": _count_metric(runtime_errors, total),
        },
        "details": details,
    }


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {"value": (passed / total) if total else 0.0, "passed": passed, "total": total}


def _count_metric(count: int, total: int) -> dict[str, Any]:
    return {"value": count, "passed": count, "total": total}


def _case_dir(workspace_root: Path, workdir: str) -> Path:
    candidate = (workspace_root / workdir).resolve()
    root = workspace_root.resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    raise ValueError(f"workspace_ops workdir escapes workspace: {workdir}")


def _run_check(*, case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    check_type = str(check.get("type", ""))
    try:
        if check_type == "file_exists":
            return _file_exists(case_dir, check)
        if check_type == "text_contains":
            return _text_contains(case_dir, check)
        if check_type == "text_equals":
            return _text_equals(case_dir, check)
        if check_type == "json_field_equals":
            return _json_field_equals(case_dir, check)
        if check_type == "glob_count":
            return _glob_count(case_dir, check)
        if check_type == "command_exit_zero":
            return _command_exit_zero(case_dir, check)
        return _fail(check, "unsupported_check", runtime_error=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _fail(check, type(exc).__name__, message=str(exc), runtime_error=True)


def _file_exists(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    path = _safe_child(case_dir, str(check.get("path", "")))
    return _pass(check) if path.exists() else _fail(check, "file_missing")


def _text_contains(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    path = _safe_child(case_dir, str(check.get("path", "")))
    text = path.read_text(encoding="utf-8")
    expected = str(check.get("text", ""))
    return _pass(check) if expected in text else _fail(check, "text_not_found")


def _text_equals(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    path = _safe_child(case_dir, str(check.get("path", "")))
    text = path.read_text(encoding="utf-8")
    expected = str(check.get("text", ""))
    return _pass(check) if text == expected else _fail(check, "text_mismatch")


def _json_field_equals(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    path = _safe_child(case_dir, str(check.get("path", "")))
    data = json.loads(path.read_text(encoding="utf-8"))
    actual = _json_path(data, str(check.get("field", "")))
    expected = check.get("value")
    return _pass(check) if actual == expected else _fail(check, "json_field_mismatch")


def _glob_count(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    pattern = str(check.get("pattern", ""))
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        return _fail(check, "invalid_glob", runtime_error=True)
    count = len(list(case_dir.glob(pattern)))
    expected = int(check.get("count", 0))
    return _pass(check) if count == expected else _fail(check, "glob_count_mismatch")


def _command_exit_zero(case_dir: Path, check: dict[str, Any]) -> dict[str, Any]:
    argv = check.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return _fail(check, "invalid_argv", runtime_error=True)
    timeout = float(check.get("timeout_seconds", 5))
    try:
        completed = subprocess.run(
            argv,
            cwd=case_dir,
            timeout=timeout,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.TimeoutExpired:
        return _fail(check, "timeout")
    if completed.returncode == 0:
        return _pass(check)
    return _fail(
        check,
        "nonzero_exit",
        message=_truncate((completed.stderr or completed.stdout or "").strip()),
        runtime_error=True,
    )


def _safe_child(case_dir: Path, raw_path: str) -> Path:
    candidate = (case_dir / raw_path).resolve()
    root = case_dir.resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    raise ValueError(f"check path escapes case dir: {raw_path}")


def _json_path(data: Any, field: str) -> Any:
    current = data
    for part in field.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _pass(check: dict[str, Any]) -> dict[str, Any]:
    return {"type": str(check.get("type", "")), "passed": True, "reason": "pass"}


def _fail(
    check: dict[str, Any],
    reason: str,
    *,
    message: str = "",
    runtime_error: bool = False,
) -> dict[str, Any]:
    result = {
        "type": str(check.get("type", "")),
        "passed": False,
        "reason": reason,
        "runtime_error": runtime_error,
    }
    if message:
        result["message"] = message
    path = check.get("path")
    if path:
        result["path"] = str(path)
    return result


def _truncate(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"
