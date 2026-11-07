from __future__ import annotations

from pathlib import Path

import pytest

from bot.web.api_common import WebApiError
from bot.web.plugin_api_service import _resolve_safe_path


def test_resolve_safe_path_accepts_absolute_picker_path_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    current = workspace / "src"
    current.mkdir()
    selected = workspace / "docs"
    selected.mkdir()

    assert _resolve_safe_path(str(workspace), str(current), str(selected)) == "docs"


def test_resolve_safe_path_keeps_relative_inputs_under_current_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    current = workspace / "src"
    current.mkdir()
    (workspace / "docs").mkdir()

    assert _resolve_safe_path(str(workspace), str(current), "main.py") == "src/main.py"
    with pytest.raises(WebApiError) as exc_info:
        _resolve_safe_path(str(workspace), str(current), "../docs")
    assert exc_info.value.status == 403
    assert exc_info.value.code == "path_outside_workspace"


def test_resolve_safe_path_rejects_absolute_picker_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    current = workspace / "src"
    current.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(WebApiError) as exc_info:
        _resolve_safe_path(str(workspace), str(current), str(outside))
    assert exc_info.value.status == 403
    assert exc_info.value.code == "path_outside_workspace"
