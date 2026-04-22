from __future__ import annotations

from pathlib import Path

from bot.web.workspace_definition_service import resolve_workspace_definition


def test_resolve_relative_python_import(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "api.py").write_text("from .service import run\n", encoding="utf-8")
    (tmp_path / "pkg" / "service.py").write_text("def run():\n    pass\n", encoding="utf-8")

    result = resolve_workspace_definition(tmp_path, "pkg/api.py", line=1, column=20, symbol="run")

    assert result["items"][0]["path"] == "pkg/service.py"
    assert result["items"][0]["line"] == 1


def test_resolve_same_file_symbol_definition(tmp_path: Path):
    target = tmp_path / "main.py"
    target.write_text("def greet():\n    return 'hi'\n\nvalue = greet()\n", encoding="utf-8")

    result = resolve_workspace_definition(tmp_path, "main.py", line=4, column=9, symbol="greet")

    assert result["items"][0]["path"] == "main.py"
    assert result["items"][0]["line"] == 1


def test_resolve_workspace_search_fallback_returns_multiple_candidates(tmp_path: Path):
    (tmp_path / "a.py").write_text("def run_task():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("run_task()\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def run_task():\n    pass\n", encoding="utf-8")

    result = resolve_workspace_definition(tmp_path, "b.py", line=1, column=5, symbol="run_task")

    assert len(result["items"]) >= 2
