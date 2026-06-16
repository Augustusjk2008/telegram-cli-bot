from __future__ import annotations

import json
import sys
from pathlib import Path

SUITE_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE_PACKAGE_ROOT))

from suite.graders.workspace import score_workspace_ops  # noqa: E402


def test_workspace_grader_passes_file_and_command_checks(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    (case_dir / "src").mkdir(parents=True)
    (case_dir / "tests").mkdir()
    (case_dir / "src" / "formatter.py").write_text(
        "def add_tags(tags):\n    return [f\"#{item}\" for item in tags]\n",
        encoding="utf-8",
    )
    (case_dir / "tests" / "test_formatter.py").write_text(
        "from src.formatter import add_tags\n\n"
        "def test_add_tags():\n"
        "    assert add_tags(['a', 'b']) == ['#a', '#b']\n",
        encoding="utf-8",
    )

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [
                    {
                        "type": "text_contains",
                        "path": "src/formatter.py",
                        "text": "return [f\"#{item}\" for item in tags]",
                    },
                    {
                        "type": "command_exit_zero",
                        "argv": [sys.executable, "-m", "pytest", "tests/test_formatter.py", "-q"],
                        "timeout_seconds": 5,
                    },
                ],
            }
        ],
        answer_rows=[{"id": "workspace_0001", "status": "done", "summary": "fixed"}],
        workspace_root=tmp_path,
    )

    assert result["metrics"]["pass@1"]["passed"] == 1
    assert result["metrics"]["check_pass_rate"]["passed"] == 2
    assert result["details"][0]["passed"] is True
    assert result["details"][0]["answer_present"] is True


def test_workspace_grader_reports_missing_answer(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    case_dir.mkdir(parents=True)
    (case_dir / "done.txt").write_text("ok", encoding="utf-8")

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [{"type": "file_exists", "path": "done.txt"}],
            }
        ],
        answer_rows=[],
        workspace_root=tmp_path,
    )

    detail = result["details"][0]
    assert detail["passed"] is False
    assert detail["answer_present"] is False
    assert detail["reason"] == "missing_answer"
    assert result["metrics"]["check_pass_rate"]["passed"] == 1


def test_workspace_grader_lists_failed_text_checks(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    case_dir.mkdir(parents=True)
    (case_dir / "notes.md").write_text("actual", encoding="utf-8")

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [{"type": "text_contains", "path": "notes.md", "text": "expected"}],
            }
        ],
        answer_rows=[{"id": "workspace_0001", "status": "done", "summary": "checked"}],
        workspace_root=tmp_path,
    )

    detail = result["details"][0]
    assert detail["passed"] is False
    assert detail["reason"] == "check_failed"
    assert detail["failed_checks"][0]["type"] == "text_contains"


def test_workspace_grader_counts_command_timeout(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    case_dir.mkdir(parents=True)

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [
                    {
                        "type": "command_exit_zero",
                        "argv": [sys.executable, "-c", "import time; time.sleep(2)"],
                        "timeout_seconds": 0.1,
                    }
                ],
            }
        ],
        answer_rows=[{"id": "workspace_0001", "status": "done", "summary": "ran"}],
        workspace_root=tmp_path,
    )

    assert result["metrics"]["timeout"]["passed"] == 1
    assert result["details"][0]["failed_checks"][0]["reason"] == "timeout"


def test_workspace_grader_rejects_shell_string_command(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    case_dir.mkdir(parents=True)

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [
                    {
                        "type": "command_exit_zero",
                        "argv": "python -c \"print(1)\"",
                    }
                ],
            }
        ],
        answer_rows=[{"id": "workspace_0001", "status": "done", "summary": "ran"}],
        workspace_root=tmp_path,
    )

    assert result["metrics"]["runtime_error"]["passed"] == 1
    assert result["details"][0]["failed_checks"][0]["reason"] == "invalid_argv"


def test_workspace_grader_supports_json_field_and_glob_checks(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases" / "workspace_0001"
    case_dir.mkdir(parents=True)
    (case_dir / "plugin.json").write_text(
        json.dumps({"permissions": {"filesystem": "readonly"}}),
        encoding="utf-8",
    )
    (case_dir / "a.txt").write_text("a", encoding="utf-8")
    (case_dir / "b.txt").write_text("b", encoding="utf-8")

    result = score_workspace_ops(
        gold_rows=[
            {
                "id": "workspace_0001",
                "workdir": "cases/workspace_0001",
                "checks": [
                    {
                        "type": "json_field_equals",
                        "path": "plugin.json",
                        "field": "permissions.filesystem",
                        "value": "readonly",
                    },
                    {"type": "glob_count", "pattern": "*.txt", "count": 2},
                ],
            }
        ],
        answer_rows=[{"id": "workspace_0001", "status": "done", "summary": "checked"}],
        workspace_root=tmp_path,
    )

    assert result["metrics"]["pass@1"]["passed"] == 1
