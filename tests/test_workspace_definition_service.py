from __future__ import annotations

from pathlib import Path

from bot.web.workspace_definition_service import (
    resolve_code_navigation,
    resolve_workspace_definition,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "code_navigation"


def _request(
    *,
    path: str,
    content: str,
    line: int,
    column: int,
    kind: str = "definition",
    language_id: str = "python",
) -> dict[str, object]:
    return {
        "kind": kind,
        "requestId": "nav-test-1",
        "document": {
            "path": path,
            "languageId": language_id,
            "version": 7,
            "content": content,
        },
        "position": {"line": line, "column": column},
    }


def test_same_file_python_definition_uses_document_snapshot_and_exact_name_range(tmp_path: Path) -> None:
    disk_content = "def old_name():\n    return None\n"
    active_content = "def greet(name):\n    return name\n\ngreet(\"Orbit\")\n"
    (tmp_path / "main.py").write_text(disk_content, encoding="utf-8")

    result = resolve_code_navigation(
        tmp_path,
        _request(path="main.py", content=active_content, line=4, column=2),
    )

    assert result["request_id"] == "nav-test-1"
    assert result["message"] == ""
    assert result["items"] == [
        {
            "target_type": "workspace",
            "path": "main.py",
            "provider": "python-ast",
            "range": {
                "start": {"line": 1, "column": 1},
                "end": {"line": 2, "column": 16},
            },
            "selection_range": {
                "start": {"line": 1, "column": 5},
                "end": {"line": 1, "column": 10},
            },
        }
    ]


def test_python_import_resolves_to_semantic_definition() -> None:
    workspace = FIXTURE_ROOT / "python"
    content = (workspace / "main.py").read_text(encoding="utf-8")

    result = resolve_code_navigation(
        workspace,
        _request(path="main.py", content=content, line=1, column=21),
    )

    assert result["items"][0]["path"] == "helper.py"
    assert result["items"][0]["provider"] == "python-ast"
    assert result["items"][0]["selection_range"]["start"] == {"line": 1, "column": 5}


def test_definition_does_not_fall_back_to_workspace_text_search(tmp_path: Path) -> None:
    caller = "missing_symbol()\n"
    (tmp_path / "caller.py").write_text(caller, encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("def missing_symbol():\n    pass\n", encoding="utf-8")

    result = resolve_code_navigation(
        tmp_path,
        _request(path="caller.py", content=caller, line=1, column=3),
    )

    assert result["items"] == []
    assert result["message"] == "未找到语义定义"


def test_temporary_provider_returns_no_fake_implementation(tmp_path: Path) -> None:
    content = "def greet():\n    return None\n\ngreet()\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")

    result = resolve_code_navigation(
        tmp_path,
        _request(path="main.py", content=content, line=4, column=2, kind="implementation"),
    )

    assert result["items"] == []
    assert result["message"] == "未找到语义实现"


def test_non_python_fixture_does_not_produce_regex_definition_candidates() -> None:
    workspace = FIXTURE_ROOT / "typescript"
    content = (workspace / "main.ts").read_text(encoding="utf-8")

    result = resolve_code_navigation(
        workspace,
        _request(
            path="main.ts",
            content=content,
            line=1,
            column=10,
            language_id="typescript",
        ),
    )

    assert result["items"] == []
    assert result["message"] == "未找到语义定义"


def test_legacy_definition_adapter_keeps_semantic_result_shape(tmp_path: Path) -> None:
    content = "def greet():\n    return None\n\ngreet()\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")

    result = resolve_workspace_definition(
        tmp_path,
        "main.py",
        line=4,
        column=2,
        symbol="greet",
    )

    assert result == {
        "items": [
            {
                "path": "main.py",
                "line": 1,
                "column": 5,
                "match_kind": "same_file",
                "confidence": 1.0,
            }
        ]
    }
