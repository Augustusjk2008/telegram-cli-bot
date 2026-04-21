from __future__ import annotations


def test_discover_tasks_from_package_json_and_pytest(tmp_path):
    from bot.web.task_service import discover_tasks

    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest","build":"tsc"}}', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    result = discover_tasks(tmp_path)

    ids = [item["id"] for item in result["items"]]
    assert "npm:test" in ids
    assert "npm:build" in ids
    assert "python:pytest" in ids


def test_parse_typescript_problem_line():
    from bot.web.task_service import parse_problem_lines

    output = "src/app.ts(12,8): error TS2322: Type 'string' is not assignable to type 'number'.\n"

    result = parse_problem_lines(output)

    assert result == [{
        "path": "src/app.ts",
        "line": 12,
        "column": 8,
        "severity": "error",
        "message": "TS2322: Type 'string' is not assignable to type 'number'.",
        "source": "tsc",
    }]
