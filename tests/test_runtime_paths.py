from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import bot.runtime_paths as runtime_paths
from bot.web.chat_store import ChatStore


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
    favorites_path = runtime_paths.get_chat_favorites_path(workspace)

    assert workspace_dir == home / ".tcb" / "chat-history" / "workspaces" / workspace_key
    assert db_path == workspace_dir / "chat.sqlite"
    assert metadata_path == workspace_dir / "workspace.json"
    assert favorites_path == workspace_dir / "favorites.json"


def test_legacy_project_chat_db_path_matches_chat_store_workspace_path(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert runtime_paths.get_legacy_project_chat_db_path(workspace) == workspace / ".tcb" / "state" / "chat.sqlite"
    assert ChatStore(workspace).legacy_db_path == runtime_paths.get_legacy_project_chat_db_path(workspace)


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


def test_language_server_paths_use_app_data_root(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    monkeypatch.setenv("TCB_DATA_DIR", str(data))

    assert runtime_paths.get_language_servers_root() == data / "language-servers"
    assert runtime_paths.get_language_server_managed_root() == data / "language-servers"
    assert runtime_paths.get_language_server_node_tools_dir() == data / "language-servers" / "node"
    assert runtime_paths.get_language_server_native_tools_dir() == data / "language-servers" / "native"


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


def test_normalize_workspace_dir_collapses_windows_path_variants(monkeypatch):
    monkeypatch.setattr(runtime_paths, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(runtime_paths.os.path, "abspath", lambda value: str(value).replace("/", "\\").rstrip("\\"))
    monkeypatch.setattr(runtime_paths.os.path, "normcase", lambda value: str(value).lower())

    assert runtime_paths.normalize_workspace_dir("C:/Repo/") == runtime_paths.normalize_workspace_dir("c:\\repo")
