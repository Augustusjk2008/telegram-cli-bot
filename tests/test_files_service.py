import pytest
from unittest.mock import MagicMock

from bot.web import files_service
from bot.web.api_common import WebApiError


def test_rename_path_renames_directory_with_contents(monkeypatch, tmp_path):
    source_dir = tmp_path / "old-folder"
    source_dir.mkdir()
    (source_dir / "nested.txt").write_text("content", encoding="utf-8")
    session = MagicMock(browse_dir=str(tmp_path), working_dir=str(tmp_path))

    monkeypatch.setattr(files_service, "ensure_file_browser_supported", lambda *_args: None)
    monkeypatch.setattr(files_service, "get_session_for_alias", lambda *_args: session)
    monkeypatch.setattr(files_service, "invalidate_workspace_indexes", lambda *_args: None)

    result = files_service.rename_path(MagicMock(), "main", 1, "old-folder", "new-folder")

    assert result == {"old_path": "old-folder", "path": "new-folder"}
    assert not source_dir.exists()
    assert (tmp_path / "new-folder" / "nested.txt").read_text(encoding="utf-8") == "content"


def test_absolute_file_paths_require_explicit_external_access(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside", encoding="utf-8")

    with pytest.raises(WebApiError) as read_error:
        files_service.resolve_safe_path(str(workspace), str(outside_file))
    with pytest.raises(WebApiError) as write_error:
        files_service.resolve_safe_write_path(str(workspace), str(outside_file))

    assert read_error.value.code == "unsafe_path"
    assert write_error.value.code == "unsafe_write_path"
    assert files_service.resolve_safe_path(
        str(workspace),
        str(outside_file),
        allow_external_paths=True,
    ) == str(outside_file.resolve())
    assert files_service.resolve_safe_write_path(
        str(workspace),
        str(outside_file),
        allow_external_paths=True,
    ) == str(outside_file.resolve())

    session = MagicMock(browse_dir=str(workspace), working_dir=str(workspace))
    with pytest.raises(WebApiError) as relative_escape_error:
        files_service.resolve_action_parent_dir(session, "..", allow_external_paths=True)
    assert relative_escape_error.value.code == "unsafe_write_path"
