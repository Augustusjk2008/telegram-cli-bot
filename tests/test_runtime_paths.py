from __future__ import annotations

import hashlib
import importlib
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


def test_runtime_paths_loads_tcb_data_dir_from_dotenv(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    (repo / ".env").write_text(f"TCB_DATA_DIR={data}\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("TCB_DATA_DIR", raising=False)

    import bot.runtime_paths as runtime_paths

    reloaded = importlib.reload(runtime_paths)

    assert reloaded.get_app_data_root() == data
