from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

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


def test_remote_backend_delegates_supported_views_and_mutations():
    backend = git_backend.RemoteGitBackend(Mock(), CONFIG["root"])
    backend.service = Mock()
    backend.service.tree_status.return_value = {"items": {}}
    backend.service.graph.return_value = {"nodes": []}
    backend.service.branches.return_value = {"branches": []}
    backend.service.stashes.return_value = {"items": []}
    backend.service.identity.return_value = {"repo_found": False}
    backend.service.branch_create.return_value = {"branches": []}
    backend.service.branch_switch.return_value = {"branches": [], "current_branch": "main"}
    backend.service.branch_reset.return_value = {"head_commit": "a" * 40}
    backend.service.stash_apply.return_value = {"repo_found": True}
    backend.service.stash_drop.return_value = {"repo_found": True}
    backend.service.stash_pop.return_value = {"repo_found": True}
    backend.service.identity_update.return_value = {"repo_found": True}
    backend.service.discard.return_value = {"repo_found": True}
    backend.service.discard_all.return_value = {"repo_found": True}

    assert backend.tree_status() == {"items": {}}
    assert backend.graph("current", 2, "cursor") == {"nodes": []}
    assert backend.branches() == {"branches": []}
    assert backend.stashes() == {"items": []}
    assert backend.identity() == {"repo_found": False}
    backend.service.graph.assert_called_once_with("current", 2, "cursor")
    assert backend.branch_create("feature", "") == {"branches": []}
    assert backend.branch_switch("feature") == {"branches": [], "current_branch": "main"}
    assert backend.branch_reset("a" * 40, "mixed")["head_commit"] == "a" * 40
    assert backend.stash_apply("stash@{0}") == {"repo_found": True}
    assert backend.stash_drop("stash@{0}") == {"repo_found": True}
    assert backend.stash_pop() == {"repo_found": True}
    assert backend.identity_update(scope="global", name="Name", email="name@example.com") == {"repo_found": True}
    assert backend.discard(["file.txt"]) == {"repo_found": True}
    assert backend.discard_all() == {"repo_found": True}
    backend.service.branch_create.assert_called_once_with("feature", "")
    backend.service.branch_switch.assert_called_once_with("feature")
    backend.service.branch_reset.assert_called_once_with("a" * 40, "mixed")
    backend.service.stash_apply.assert_called_once_with("stash@{0}")
    backend.service.stash_drop.assert_called_once_with("stash@{0}")
    backend.service.stash_pop.assert_called_once_with()
    backend.service.identity_update.assert_called_once_with(
        scope="global", name="Name", email="name@example.com",
    )
    backend.service.discard.assert_called_once_with(["file.txt"])
    backend.service.discard_all.assert_called_once_with()
