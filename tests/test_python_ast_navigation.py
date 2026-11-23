"""Python AST fallback navigation: import statements lead to the modules they name."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.language_server.python_ast_navigation import resolve_code_navigation

SOURCE_PATH = "pkg/other/caller.py"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    files = {
        "pkg/__init__.py": "",
        "pkg/sub/__init__.py": "VALUE = 1\n",
        "pkg/sub/mod.py": '"""Worker."""\n\ndef run():\n    pass\n',
        SOURCE_PATH: "",
        # A directory without ``__init__.py`` has no file to open.
        "space/mod.py": "",
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _definition(workspace: Path, marked_source: str) -> dict[str, object]:
    """Resolve the definition at the ``|`` cursor marker in ``marked_source``."""
    before, after = marked_source.split("|")
    return resolve_code_navigation(
        workspace,
        {
            "kind": "definition",
            "requestId": "request-1",
            "document": {"path": SOURCE_PATH, "languageId": "python", "content": before + after},
            "position": {"line": before.count("\n") + 1, "column": len(before.rsplit("\n", 1)[-1]) + 1},
        },
    )


@pytest.mark.parametrize(
    ("marked_source", "path", "line"),
    [
        # Each segment of a dotted module path names the package or module up to it.
        ("from p|kg.sub.mod import run", "pkg/__init__.py", 1),
        ("from pkg.s|ub.mod import run", "pkg/sub/__init__.py", 1),
        ("from pkg.sub.m|od import run", "pkg/sub/mod.py", 1),
        ("import os, pkg.s|ub.mod as worker", "pkg/sub/__init__.py", 1),
        ("import pkg.sub.mod as w|orker", "pkg/sub/mod.py", 1),
        ("from ..s|ub import mod", "pkg/sub/__init__.py", 1),
        # The same word after ``import`` is the imported name, not a path segment.
        ("from pkg.sub.mod import run as s|ub", "pkg/sub/mod.py", 3),
        ("from pkg.sub import V|ALUE", "pkg/sub/__init__.py", 1),
        # An imported name that is a module of the package opens that module.
        ("from ..sub import m|od", "pkg/sub/mod.py", 1),
        ("from pkg.sub import (\n    VALUE,\n    m|od,\n)", "pkg/sub/mod.py", 1),
    ],
)
def test_import_statements_resolve_to_modules(workspace: Path, marked_source: str, path: str, line: int) -> None:
    result = _definition(workspace, marked_source)

    assert result["message"] == ""
    [item] = result["items"]
    assert (item["path"], item["selection_range"]["start"]["line"]) == (path, line)
    assert item["provider"] == "python-ast"


@pytest.mark.parametrize("marked_source", ["from missing.s|ub import run", "from s|pace.mod import run"])
def test_module_path_without_a_file_is_not_found(workspace: Path, marked_source: str) -> None:
    result = _definition(workspace, marked_source)

    assert result == {"request_id": "request-1", "items": [], "message": "未找到语义定义"}
