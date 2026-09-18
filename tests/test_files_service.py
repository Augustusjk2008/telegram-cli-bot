import pytest
from unittest.mock import MagicMock

from bot.web import files_service
from bot.web.api_common import WebApiError


def test_browsing_directories_preserves_chat_session(monkeypatch, tmp_path):
    (tmp_path / "docs").mkdir()
    session = MagicMock(
        browse_dir=str(tmp_path),
        working_dir=str(tmp_path),
        active_conversation_id="conversation-1",
        codex_session_id="codex-1",
        claude_session_id="claude-1",
        native_agent_session_id="native-1",
        native_agent_run_id="run-1",
        claude_session_initialized=True,
    )
    fields = (
        "working_dir", "active_conversation_id", "codex_session_id",
        "claude_session_id", "native_agent_session_id", "native_agent_run_id",
        "claude_session_initialized",
    )
    initial_state = {name: getattr(session, name) for name in fields}
    monkeypatch.setattr(files_service, "get_session_for_alias", lambda *_args: session)

    for path, expected_dir in (("docs", tmp_path / "docs"), ("..", tmp_path)):
        result = files_service.change_working_directory(MagicMock(), "main", 1, path)
        assert result["working_dir"] == session.browse_dir == str(expected_dir)
        assert {name: getattr(session, name) for name in fields} == initial_state


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
