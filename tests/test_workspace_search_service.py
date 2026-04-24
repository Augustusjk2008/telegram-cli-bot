from __future__ import annotations

from pathlib import Path


def test_quick_open_files_ranks_filename_matches_before_path_matches(tmp_path):
    from bot.web.workspace_search_service import quick_open_files

    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "api_service.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "api-notes.md").write_text("# API\n", encoding="utf-8")

    result = quick_open_files(tmp_path, "api", limit=10)

    assert [item["path"] for item in result["items"]] == ["src/api_service.py", "docs/api-notes.md"]


def test_quick_open_files_reuses_cached_workspace_index(tmp_path, monkeypatch):
    from bot.web import workspace_search_service as service

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api_service.py").write_text("x = 1\n", encoding="utf-8")

    calls: list[Path] = []
    real_list = service._list_workspace_files

    def counted_list(root):
        calls.append(root)
        return real_list(root)

    monkeypatch.setattr(service, "_list_workspace_files", counted_list)

    first = service.quick_open_files(tmp_path, "api", limit=10)
    second = service.quick_open_files(tmp_path, "api", limit=10)

    assert [item["path"] for item in first["items"]] == ["src/api_service.py"]
    assert second == first
    assert len(calls) == 1


def test_search_workspace_text_ignores_common_heavy_dirs(tmp_path):
    from bot.web.workspace_search_service import search_workspace_text

    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src" / "main.py").write_text("needle = True\n", encoding="utf-8")
    (tmp_path / "node_modules" / "ignore.js").write_text("needle\n", encoding="utf-8")

    result = search_workspace_text(tmp_path, "needle", limit=20)

    assert [item["path"] for item in result["items"]] == ["src/main.py"]
    assert result["items"][0]["line"] == 1


def test_build_file_outline_returns_python_symbols(tmp_path):
    from bot.web.workspace_search_service import build_file_outline

    (tmp_path / "service.py").write_text("class Api:\n    def run(self):\n        pass\n", encoding="utf-8")

    result = build_file_outline(tmp_path, "service.py")

    assert result["items"] == [
        {"name": "Api", "kind": "class", "line": 1},
        {"name": "run", "kind": "function", "line": 2},
    ]
