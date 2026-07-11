from __future__ import annotations

from pathlib import Path
from io import BytesIO

from bot.web import workspace_search_service


def test_workspace_search_reports_limit_truncation_and_backend(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_text("\n".join(["needle"] * 20), encoding="utf-8")

    result = workspace_search_service.search_workspace_text(tmp_path, "needle", limit=2)

    assert len(result["items"]) == 2
    assert result["truncated"] is True
    assert result["reason"] == "limit"
    assert result["backend"] in {"rg", "python"}


def test_python_search_stops_at_total_scan_budget(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("x" * 4096, encoding="utf-8")
    monkeypatch.setattr(workspace_search_service, "SEARCH_PYTHON_MAX_SCAN_BYTES", 128)
    monkeypatch.setattr(workspace_search_service.shutil, "which", lambda _name: None)

    result = workspace_search_service.search_workspace_text(tmp_path, "missing", limit=10)

    assert result["items"] == []
    assert result["truncated"] is True
    assert result["reason"] == "scan_bytes"
    assert result["backend"] == "python"


def test_rg_non_match_exit_is_truncated_error(monkeypatch, tmp_path: Path) -> None:
    class FailedProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = BytesIO(b"")
            self.stderr = BytesIO(b"fatal rg error")
            self.returncode = 2

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(workspace_search_service.shutil, "which", lambda _name: "rg")
    monkeypatch.setattr(workspace_search_service.subprocess, "Popen", FailedProcess)

    result = workspace_search_service.search_workspace_text(tmp_path, "needle", limit=10)

    assert result["items"] == []
    assert result["truncated"] is True
    assert result["reason"] == "rg_error"


def test_python_search_stops_at_single_line_budget(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "long.txt").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    monkeypatch.setattr(workspace_search_service.shutil, "which", lambda _name: None)

    result = workspace_search_service.search_workspace_text(tmp_path, "missing", limit=10)

    assert result["items"] == []
    assert result["truncated"] is True
    assert result["reason"] == "line_bytes"
