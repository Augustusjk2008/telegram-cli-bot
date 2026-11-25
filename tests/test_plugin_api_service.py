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


def test_dev_source_path_allows_remote_admin_with_dev_flag() -> None:
    from bot.web.api_common import AuthContext
    from bot.web.plugin_api_service import _get_dev_source_path

    admin = AuthContext(user_id=1, token_used=True, account_id="local-admin", is_local_admin=True)
    assert _get_dev_source_path({"sourcePath": "/srv/plugins", "allowDevSourcePath": True}, admin) == "/srv/plugins"


def test_dev_source_path_rejects_non_admin_and_missing_dev_flag() -> None:
    from bot.web.api_common import AuthContext
    from bot.web.plugin_api_service import _get_dev_source_path

    member = AuthContext(user_id=2, token_used=True)
    for body in ({"sourcePath": "/srv/plugins", "allowDevSourcePath": True}, {"sourcePath": "/srv/plugins"}):
        with pytest.raises(WebApiError) as exc_info:
            _get_dev_source_path(dict(body), member)
        assert exc_info.value.status == 403
        assert exc_info.value.code == "plugin_source_path_forbidden"
