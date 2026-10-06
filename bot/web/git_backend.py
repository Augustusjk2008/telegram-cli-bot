"""Unified local and remote Git backends for Web API handlers."""

from __future__ import annotations

from typing import Any, Protocol

from bot.remote_workspace.git_service import RemoteGitService
from bot.remote_workspace.transport import get_remote_workspace_service
from bot.web.api_common import WebApiError, get_profile_or_raise
from bot.web import git_service as local_git


class GitBackend(Protocol):
    """The operations exposed by the Web Git API."""

    def overview(self) -> dict[str, Any]: ...
    def capabilities(self) -> dict[str, Any]: ...
    def init(self) -> dict[str, Any]: ...
    def diff(self, path: str, staged: bool = False) -> dict[str, Any]: ...
    def stage(self, paths: list[str]) -> dict[str, Any]: ...
    def unstage(self, paths: list[str]) -> dict[str, Any]: ...
    def commit(self, message: str) -> dict[str, Any]: ...

    def tree_status(self) -> dict[str, Any]: ...
    def graph(self, scope: str = "all", limit: Any = "", cursor: Any = "") -> dict[str, Any]: ...
    def branches(self) -> dict[str, Any]: ...
    def branch_create(self, name: str, start_point: str = "") -> dict[str, Any]: ...
    def branch_switch(self, name: str) -> dict[str, Any]: ...
    def branch_reset(self, commit: str, mode: str = "mixed") -> dict[str, Any]: ...
    def stashes(self) -> dict[str, Any]: ...
    def stash_apply(self, ref: str) -> dict[str, Any]: ...
    def stash_drop(self, ref: str) -> dict[str, Any]: ...
    def identity(self) -> dict[str, Any]: ...
    def identity_update(self, *, scope: str, name: Any, email: Any) -> dict[str, Any]: ...
    def discard(self, paths: list[str]) -> dict[str, Any]: ...
    def discard_all(self) -> dict[str, Any]: ...
    def fetch(self) -> dict[str, Any]: ...
    def pull(self) -> dict[str, Any]: ...
    def push(self) -> dict[str, Any]: ...
    def stash(self) -> dict[str, Any]: ...
    def stash_pop(self) -> dict[str, Any]: ...

    def commit_message_config(self) -> dict[str, Any]: ...
    async def update_commit_message_config(self, **values: Any) -> dict[str, Any]: ...
    async def reset_commit_message_config(self) -> dict[str, Any]: ...
    async def generate_commit_message(self) -> dict[str, Any]: ...

    def smart_commit_repo_hint(self) -> tuple[str, str]: ...
    def smart_commit_preflight(self) -> tuple[str, str, str]: ...
    async def generate_smart_commit_message(self, *, repo_root: str) -> dict[str, Any]: ...
    def ensure_smart_commit_snapshot(self, repo_root: str, snapshot: str) -> None: ...
    def stage_all_changes(self, repo_root: str) -> None: ...
    def commit_message(self, repo_root: str, message: str) -> None: ...


class LocalGitBackend:
    def __init__(self, manager, alias: str, user_id: int):
        self.manager = manager
        self.alias = alias
        self.user_id = user_id

    def overview(self) -> dict[str, Any]:
        return local_git.get_git_overview(self.manager, self.alias, self.user_id)

    def capabilities(self) -> dict[str, Any]:
        return local_git.get_git_capabilities(self.manager, self.alias, self.user_id)

    def init(self) -> dict[str, Any]:
        return local_git.init_git_repository(self.manager, self.alias, self.user_id)

    def diff(self, path: str, staged: bool = False) -> dict[str, Any]:
        return local_git.get_git_diff(self.manager, self.alias, self.user_id, path, staged=staged)

    def stage(self, paths: list[str]) -> dict[str, Any]:
        return local_git.stage_git_paths(self.manager, self.alias, self.user_id, paths)

    def unstage(self, paths: list[str]) -> dict[str, Any]:
        return local_git.unstage_git_paths(self.manager, self.alias, self.user_id, paths)

    def commit(self, message: str) -> dict[str, Any]:
        return local_git.commit_git_changes(self.manager, self.alias, self.user_id, message)

    def tree_status(self) -> dict[str, Any]:
        return local_git.get_git_tree_status(self.manager, self.alias, self.user_id)

    def graph(self, scope: str = "all", limit: Any = "", cursor: Any = "") -> dict[str, Any]:
        return local_git.get_git_commit_graph(self.manager, self.alias, self.user_id, scope, limit, cursor)

    def branches(self) -> dict[str, Any]:
        return local_git.list_git_branches(self.manager, self.alias, self.user_id)

    def branch_create(self, name: str, start_point: str = "") -> dict[str, Any]:
        return local_git.create_git_branch(self.manager, self.alias, self.user_id, name, start_point)

    def branch_switch(self, name: str) -> dict[str, Any]:
        return local_git.switch_git_branch(self.manager, self.alias, self.user_id, name)

    def branch_reset(self, commit: str, mode: str = "mixed") -> dict[str, Any]:
        return local_git.reset_git_branch_to_commit(self.manager, self.alias, self.user_id, commit, mode)

    def stashes(self) -> dict[str, Any]:
        return local_git.list_git_stashes(self.manager, self.alias, self.user_id)

    def stash_apply(self, ref: str) -> dict[str, Any]:
        return local_git.apply_git_stash(self.manager, self.alias, self.user_id, ref)

    def stash_drop(self, ref: str) -> dict[str, Any]:
        return local_git.drop_git_stash(self.manager, self.alias, self.user_id, ref)

    def identity(self) -> dict[str, Any]:
        return local_git.get_git_identity_config(self.manager, self.alias, self.user_id)

    def identity_update(self, *, scope: str, name: Any, email: Any) -> dict[str, Any]:
        return local_git.update_git_identity_config(
            self.manager, self.alias, self.user_id, scope=scope, name=name, email=email,
        )

    def discard(self, paths: list[str]) -> dict[str, Any]:
        return local_git.discard_git_paths(self.manager, self.alias, self.user_id, paths)

    def discard_all(self) -> dict[str, Any]:
        return local_git.discard_all_git_changes(self.manager, self.alias, self.user_id)

    def fetch(self) -> dict[str, Any]:
        return local_git.fetch_git_remote(self.manager, self.alias, self.user_id)

    def pull(self) -> dict[str, Any]:
        return local_git.pull_git_remote(self.manager, self.alias, self.user_id)

    def push(self) -> dict[str, Any]:
        return local_git.push_git_remote(self.manager, self.alias, self.user_id)

    def stash(self) -> dict[str, Any]:
        return local_git.stash_git_changes(self.manager, self.alias, self.user_id)

    def stash_pop(self) -> dict[str, Any]:
        return local_git.pop_git_stash(self.manager, self.alias, self.user_id)

    def commit_message_config(self) -> dict[str, Any]:
        return local_git.get_git_commit_message_cli_config(self.manager, self.alias)

    async def update_commit_message_config(self, **values: Any) -> dict[str, Any]:
        return await local_git.update_git_commit_message_cli_config(self.manager, self.alias, **values)

    async def reset_commit_message_config(self) -> dict[str, Any]:
        return await local_git.reset_git_commit_message_cli_config(self.manager, self.alias)

    async def generate_commit_message(self) -> dict[str, Any]:
        return await local_git.generate_git_commit_message(self.manager, self.alias, self.user_id)

    def smart_commit_repo_hint(self) -> tuple[str, str]:
        return local_git.get_git_smart_commit_repo_hint(self.manager, self.alias)

    def smart_commit_preflight(self) -> tuple[str, str, str]:
        return local_git.preflight_git_smart_commit(self.manager, self.alias, self.user_id)

    async def generate_smart_commit_message(self, *, repo_root: str) -> dict[str, Any]:
        return await local_git.generate_git_smart_commit_message(
            self.manager, self.alias, self.user_id, repo_root=repo_root,
        )

    def ensure_smart_commit_snapshot(self, repo_root: str, snapshot: str) -> None:
        local_git.ensure_git_status_snapshot_unchanged(repo_root, snapshot)

    def stage_all_changes(self, repo_root: str) -> None:
        local_git.stage_all_git_changes(repo_root)

    def commit_message(self, repo_root: str, message: str) -> None:
        local_git.commit_git_message(repo_root, message)


class RemoteGitBackend:
    def __init__(self, connection, root: str):
        self.connection = connection
        self.root = root
        self.service = RemoteGitService(connection, root)

    def overview(self) -> dict[str, Any]:
        return self.service.overview()

    def capabilities(self) -> dict[str, Any]:
        return self.service.capabilities()

    def init(self) -> dict[str, Any]:
        return self.service.init()

    def diff(self, path: str, staged: bool = False) -> dict[str, Any]:
        return self.service.diff(path, staged=staged)

    def stage(self, paths: list[str]) -> dict[str, Any]:
        return self.service.stage(paths)

    def unstage(self, paths: list[str]) -> dict[str, Any]:
        return self.service.unstage(paths)

    def commit(self, message: str) -> dict[str, Any]:
        return self.service.commit(message)

    def tree_status(self) -> dict[str, Any]:
        return self.service.tree_status()

    def graph(self, scope: str = "all", limit: Any = "", cursor: Any = "") -> dict[str, Any]:
        return self.service.graph(scope, limit, cursor)

    def branches(self) -> dict[str, Any]:
        return self.service.branches()

    def branch_create(self, name: str, start_point: str = "") -> dict[str, Any]:
        return self.service.branch_create(name, start_point)

    def branch_switch(self, name: str) -> dict[str, Any]:
        return self.service.branch_switch(name)

    def branch_reset(self, commit: str, mode: str = "mixed") -> dict[str, Any]:
        return self.service.branch_reset(commit, mode)

    def stashes(self) -> dict[str, Any]:
        return self.service.stashes()

    def stash_apply(self, ref: str) -> dict[str, Any]:
        return self.service.stash_apply(ref)

    def stash_drop(self, ref: str) -> dict[str, Any]:
        return self.service.stash_drop(ref)

    def identity(self) -> dict[str, Any]:
        return self.service.identity()

    def identity_update(self, *, scope: str, name: Any, email: Any) -> dict[str, Any]:
        return self.service.identity_update(scope=scope, name=name, email=email)

    def discard(self, paths: list[str]) -> dict[str, Any]:
        return self.service.discard(paths)

    def discard_all(self) -> dict[str, Any]:
        return self.service.discard_all()

    def fetch(self) -> dict[str, Any]:
        return self.service.fetch()

    def pull(self) -> dict[str, Any]:
        return self.service.pull()

    def push(self) -> dict[str, Any]:
        return self.service.push()

    def stash_pop(self) -> dict[str, Any]:
        return self.service.stash_pop()

    @staticmethod
    def _unsupported(*_args: Any, **_kwargs: Any):
        raise WebApiError(409, "remote_feature_unavailable", "远程工作区暂不支持此操作")

    stash = _unsupported
    commit_message_config = _unsupported
    update_commit_message_config = _unsupported
    reset_commit_message_config = _unsupported
    generate_commit_message = _unsupported
    smart_commit_repo_hint = _unsupported
    smart_commit_preflight = _unsupported
    generate_smart_commit_message = _unsupported
    ensure_smart_commit_snapshot = _unsupported
    stage_all_changes = _unsupported
    commit_message = _unsupported


def resolve_git_backend(manager, alias: str, user_id: int) -> GitBackend:
    profile = get_profile_or_raise(manager, alias)
    if profile.remote_workspace:
        config = dict(profile.remote_workspace)
        connection = get_remote_workspace_service().get(config)
        return RemoteGitBackend(connection, str(config["root"]))
    return LocalGitBackend(manager, alias, user_id)


get_git_backend = resolve_git_backend
