from unittest.mock import MagicMock

from bot.web import files_service


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
