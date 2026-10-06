from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import git_backend


CONFIG = {
    "connection_id": "a" * 32,
    "host": "remote.example",
    "port": 22,
    "username": "developer",
    "root": "/srv/project",
    "host_key_fingerprint": "SHA256:" + "a" * 43,
    "key_filename": "",
}


def _manager(tmp_path, *, remote_workspace=None):
    storage = tmp_path / "bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(alias="main", working_dir=str(tmp_path), remote_workspace=remote_workspace or {}),
        str(storage),
    )


def test_resolver_selects_local_backend(tmp_path):
    manager = _manager(tmp_path)

    backend = git_backend.resolve_git_backend(manager, "main", 42)

    assert isinstance(backend, git_backend.LocalGitBackend)
    assert backend.manager is manager
    assert backend.alias == "main"
    assert backend.user_id == 42


def test_resolver_selects_remote_backend_with_saved_root_and_connection(tmp_path, monkeypatch):
    manager = _manager(tmp_path, remote_workspace=CONFIG)
    connection = SimpleNamespace(platform="posix", config=dict(CONFIG))
    service = Mock()
    service.get.return_value = connection
    monkeypatch.setattr(git_backend, "get_remote_workspace_service", lambda: service)

    backend = git_backend.resolve_git_backend(manager, "main", 42)

    assert isinstance(backend, git_backend.RemoteGitBackend)
    assert backend.connection is connection
    assert backend.root == CONFIG["root"]
    assert backend.service.root == CONFIG["root"]
    service.get.assert_called_once_with(CONFIG)


def test_remote_backend_delegates_read_only_views_and_rejects_mutations():
    backend = git_backend.RemoteGitBackend(Mock(), CONFIG["root"])
    backend.service = Mock()
    backend.service.tree_status.return_value = {"items": {}}
    backend.service.graph.return_value = {"nodes": []}
    backend.service.branches.return_value = {"branches": []}
    backend.service.stashes.return_value = {"items": []}
    backend.service.identity.return_value = {"repo_found": False}

    assert backend.tree_status() == {"items": {}}
    assert backend.graph("current", 2, "cursor") == {"nodes": []}
    assert backend.branches() == {"branches": []}
    assert backend.stashes() == {"items": []}
    assert backend.identity() == {"repo_found": False}
    backend.service.graph.assert_called_once_with("current", 2, "cursor")

    for method, args in ((backend.branch_create, ("feature",)), (backend.stash_apply, ("stash@{0}",)), (backend.identity_update, ())):
        with pytest.raises(git_backend.WebApiError) as exc:
            method(*args)
        assert exc.value.code == "remote_feature_unavailable"
