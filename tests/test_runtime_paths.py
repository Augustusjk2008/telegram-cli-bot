import hashlib
from pathlib import Path

import bot.runtime_paths as runtime_paths


def test_chat_history_paths_resolve_under_home_tcb_root(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    workspace_key = runtime_paths.get_chat_workspace_key(workspace)
    workspace_dir = runtime_paths.get_chat_workspace_dir(workspace)
    db_path = runtime_paths.get_chat_history_db_path(workspace)
    metadata_path = runtime_paths.get_chat_workspace_metadata_path(workspace)

    assert workspace_dir == home / ".tcb" / "chat-history" / "workspaces" / workspace_key
    assert db_path == workspace_dir / "chat.sqlite"
    assert metadata_path == workspace_dir / "workspace.json"


def test_chat_attachment_dir_reuses_same_home_root(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    attachment_dir = runtime_paths.get_chat_attachments_dir(" main/bot ", 1001)

    assert attachment_dir == home / ".tcb" / "chat-attachments" / "main-bot" / "1001"


def test_workspace_key_normalization_applies_normcase_on_windows(monkeypatch):
    monkeypatch.setattr(runtime_paths, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(runtime_paths.os.path, "expanduser", lambda value: value)
    monkeypatch.setattr(runtime_paths.os.path, "abspath", lambda value: value)
    monkeypatch.setattr(runtime_paths.os.path, "normpath", lambda value: value.replace("/", "\\"))
    monkeypatch.setattr(runtime_paths.os.path, "normcase", lambda value: value.lower())

    normalized = runtime_paths.normalize_workspace_dir(r"C:/Repo/Demo")

    assert normalized == r"c:\repo\demo"
    assert runtime_paths.get_chat_workspace_key(r"C:\Repo\Demo") == hashlib.sha256(
        r"c:\repo\demo".encode("utf-8")
    ).hexdigest()
