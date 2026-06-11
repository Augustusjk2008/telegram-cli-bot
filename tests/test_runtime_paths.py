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


def test_native_agent_paths_use_app_data_root(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    monkeypatch.setenv("TCB_DATA_DIR", str(data))

    assert runtime_paths.get_native_agent_data_dir() == data / "native-agent"
    assert runtime_paths.get_pi_session_store_path() == data / "native-agent" / "pi_sessions.json"
    assert runtime_paths.get_pi_workspace_history_diagnostics_dir() == data / "native-agent" / "workspace-history-diagnostics"
    assert not runtime_paths.get_pi_session_store_path().exists()


def test_native_agent_paths_default_under_home(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.delenv("TCB_DATA_DIR", raising=False)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(runtime_paths, "dotenv_values", lambda _path: {})
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    assert runtime_paths.get_pi_session_store_path() == home / ".tcb" / "orbit-safe-claw" / "native-agent" / "pi_sessions.json"
    assert str(repo) not in str(runtime_paths.get_pi_session_store_path())
