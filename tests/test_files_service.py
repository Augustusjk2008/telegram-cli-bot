import os
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot.web import files_service
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_READ_FILE_CONTENT, CAP_WRITE_FILES
from bot.web.server import WebApiServer


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


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only file attributes")
@pytest.mark.parametrize("is_directory", [False, True])
def test_readonly_deletion_requires_confirmation(monkeypatch, tmp_path, is_directory):
    target = tmp_path / ("docs" if is_directory else "reference.pdf")
    if is_directory:
        target.mkdir()
        (target / "ordinary.txt").write_text("keep until confirmed", encoding="utf-8")
        (target / "nested").mkdir()
    readonly_file = target / "nested" / "reference.pdf" if is_directory else target
    readonly_file.write_bytes(b"reference")
    readonly_file.chmod(stat.S_IREAD)
    session = MagicMock(browse_dir=str(tmp_path), working_dir=str(tmp_path))
    monkeypatch.setattr(files_service, "ensure_file_browser_supported", lambda *_args: None)
    monkeypatch.setattr(files_service, "get_session_for_alias", lambda *_args: session)
    monkeypatch.setattr(files_service, "invalidate_workspace_indexes", lambda *_args: None)

    try:
        with pytest.raises(WebApiError) as error:
            files_service.delete_path(MagicMock(), "main", 1, target.name)

        assert error.value.status == 409
        assert error.value.code == "readonly_confirmation_required"
        assert readonly_file.read_bytes() == b"reference"
        assert readonly_file.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        if is_directory:
            assert (target / "ordinary.txt").exists()

        result = files_service.delete_path(MagicMock(), "main", 1, target.name, confirm_readonly=True)
        assert result["deleted_type"] == ("directory" if is_directory else "file")
        assert not target.exists()
    finally:
        if readonly_file.exists():
            readonly_file.chmod(stat.S_IWRITE)


def test_readonly_confirmation_preserves_other_deletion_errors(monkeypatch, tmp_path):
    (tmp_path / "locked.pdf").write_bytes(b"reference")
    session = MagicMock(browse_dir=str(tmp_path), working_dir=str(tmp_path))
    monkeypatch.setattr(files_service, "ensure_file_browser_supported", lambda *_args: None)
    monkeypatch.setattr(files_service, "get_session_for_alias", lambda *_args: session)
    remove = MagicMock(side_effect=PermissionError("file is locked"))
    monkeypatch.setattr(files_service.os, "remove", remove)

    with pytest.raises(WebApiError) as error:
        files_service.delete_path(MagicMock(), "main", 1, "locked.pdf", confirm_readonly=True)

    assert error.value.code == "delete_path_failed"
    assert error.value.message == "file is locked"
    remove.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("confirmation", "expected"), [(None, False), (True, True), ("true", False)])
async def test_delete_path_view_forwards_explicit_readonly_confirmation(monkeypatch, confirmation, expected):
    auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_WRITE_FILES})
    manager = MagicMock()
    server = SimpleNamespace(
        manager=manager,
        _with_capability=AsyncMock(return_value=auth),
        _manager_alias=lambda request: request.match_info["alias"],
        _chat_user_id=lambda _auth: 7,
        _parse_json=AsyncMock(return_value={"path": "reference.pdf", "confirm_readonly": confirmation}),
    )
    delete = MagicMock(return_value={"path": "reference.pdf", "deleted_type": "file"})
    monkeypatch.setattr("bot.web.server.delete_path", delete)
    request = make_mocked_request("POST", "/api/bots/main/files/delete", match_info={"alias": "main"})

    await WebApiServer.delete_path_view(server, request)

    delete.assert_called_once_with(
        manager, "main", 7, "reference.pdf", allow_external_paths=False, confirm_readonly=expected,
    )


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


@pytest.mark.asyncio
async def test_media_download_uses_inline_disposition_and_media_mime(monkeypatch, tmp_path):
    media = tmp_path / "sample.mp3"
    media.write_bytes(b"audio")
    auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_READ_FILE_CONTENT})
    server = SimpleNamespace(
        manager=MagicMock(),
        _with_capability=AsyncMock(return_value=auth),
        _manager_alias=lambda request: request.match_info["alias"],
        _chat_user_id=lambda current_auth: current_auth.user_id,
    )
    monkeypatch.setattr(
        "bot.web.server.get_file_metadata",
        lambda *_args, **_kwargs: {
            "path": str(media),
            "filename": "sample.mp3",
            "content_type": "audio/mpeg",
        },
    )

    request = make_mocked_request(
        "GET",
        "/api/bots/main/files/download?filename=sample.mp3&inline=1",
        match_info={"alias": "main"},
    )
    response = await WebApiServer.download_file(server, request)

    assert response.headers["Content-Type"] == "audio/mpeg"
    assert response.headers["Content-Disposition"] == 'inline; filename="sample.mp3"'
