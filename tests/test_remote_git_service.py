from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest

from bot.remote_workspace import git_service as remote
from bot.remote_workspace import windows
from bot.remote_workspace.transport import RemoteWorkspaceError
from bot.web import git_service as local
from bot.git_contract import GIT_CAPABILITIES_REQUIRING_CONFIRMATION, GIT_CAPABILITY_NAMES


ROOT = "/srv/project"
OID = "a" * 40


def result(stdout="", stderr="", returncode=0, truncated=False):
    return {"stdout": stdout, "stderr": stderr, "returncode": returncode, "output_truncated": truncated}


def tracked(path, xy=".M"):
    return f"1 {xy} N... 100644 100644 100644 {OID} {OID} {path}\x00"


def nul_fields(*fields):
    return "".join(f"{field}\x00" for field in fields)


class Connection:
    platform = "posix"

    def __init__(self, *, repository=True, initial=False, files=None, untracked=(), remotes=("origin",), upstream="origin/main", branch="main"):
        self.config = {"connection_id": "ssh-one", "host": "remote.example", "username": "dev"}
        self.repository = repository
        self.initial = initial
        self.files = files if files is not None else {"file.txt": ".M"}
        self.untracked = list(untracked)
        self.remotes = list(remotes)
        self.upstream = upstream
        self.branch = branch
        self.calls = []
        self.overrides = {}
        self.readonly_outputs = {}

    def execute(self, command, root, *, timeout, max_output):
        tokens = shlex.split(command)
        args = tokens[tokens.index("git") + 1 + len(remote._GIT_OPTIONS):]
        self.calls.append((args, root, timeout, max_output, command))
        assert timeout in (remote.READ_TIMEOUT, remote.MUTATION_TIMEOUT)
        assert max_output == remote.MAX_COMMAND_OUTPUT
        override = self.overrides.get(args[0])
        if override is not None:
            if callable(override):
                return override(args)
            if isinstance(override, Exception):
                raise override
            return override
        if args == ["--version"]:
            return result("git version 2.45.0\n")
        if args == ["rev-parse", "--show-toplevel"]:
            if not self.repository:
                return result(stderr="fatal: not a git repository (or any of the parent directories): .git\n", returncode=128)
            return result(root + "\n")
        if args == ["remote"]:
            return result("".join(remote_name + "\n" for remote_name in self.remotes))
        if args == ["symbolic-ref", "--quiet", "--short", "HEAD"]:
            return result(self.branch + "\n", returncode=0 if self.branch else 1)
        if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]:
            return result(self.upstream + "\n", returncode=0 if self.upstream else 128)
        if args == ["status", "--porcelain=1", "-z", "--ignored=matching", "--untracked-files=normal"]:
            return result(self.readonly_outputs.get("tree_status", ""))
        if args[0] == "for-each-ref" and "refs/heads" in args and "refs/remotes" not in args:
            return result(self.readonly_outputs.get("branches", ""))
        if args[0] == "for-each-ref" and "refs/remotes" in args:
            return result(self.readonly_outputs.get("graph_refs", ""))
        if args[0] == "log" and "--topo-order" in args:
            return result(self.readonly_outputs.get("graph", ""))
        if args[:2] == ["rev-parse", "--verify"]:
            return result(self.readonly_outputs.get("head", ""), returncode=0 if self.readonly_outputs.get("head") else 128)
        if args[0] == "check-ref-format":
            return result()
        if args[0] == "show-ref":
            return result()
        if args[0] == "symbolic-ref":
            return result("main\n")
        if args[0] == "merge-base":
            return result()
        if args[:2] == ["stash", "list"]:
            return result(self.readonly_outputs.get("stashes", ""))
        if args[0] == "stash":
            return result()
        if args[0] == "config":
            if "--get" not in args:
                scope, key, value = args[1:4]
                self.readonly_outputs.setdefault("config", {})[(scope, "--get", key)] = value + "\n"
                return result()
            value = self.readonly_outputs.get("config", {}).get(tuple(args[1:]), "")
            return result(value, returncode=0 if value else 1)
        if args == ["init"]:
            self.repository = True
            self.initial = True
            return result("Initialized empty Git repository\n")
        if args[0] == "status":
            return result(f"# branch.oid {'(initial)' if self.initial else OID}\x00"
                          f"# branch.head {self.branch or '(detached)'}\x00"
                          + (f"# branch.upstream {self.upstream}\x00" if self.upstream else "")
                          + "# branch.ab +2 -1\x00"
                          + "".join(tracked(path, xy) for path, xy in self.files.items()))
        if args[0] == "ls-files":
            return result("".join(path + "\x00" for path in self.untracked))
        if args[0] == "log":
            return result("\x00".join([OID, OID[:7], "开发者", "2026-09-24 12:00:00 +0800", "subject", "subject\n\nbody\n",
                                        "b" * 40, "bbbbbbb", "Dev", "2026-09-23", "previous", "previous\n"]))
        if args[0] == "diff":
            if "--numstat" in args:
                return result("2\t1\tfile.txt\x00")
            return result("diff --git a/file.txt b/file.txt\n+new\n", returncode=1 if "--no-index" in args else 0)
        if args[0] in {"add", "rm", "reset", "restore", "clean", "commit", "branch", "switch", "fetch", "pull", "push"}:
            return result()
        raise AssertionError(args)


def test_overview_preserves_shape_status_names_and_remote_commits():
    names = [" space ", "a -> b", "line\nfeed", "tab\tfile", 'quotes"\'‘’;$(x).txt', "*.txt", ":(glob)*", "-f", "中文.txt"]
    connection = Connection(files={name: "MM" for name in names}, untracked=[" untracked \n"])
    overview = remote.RemoteGitService(connection, ROOT).overview()
    assert [item["path"] for item in overview["changed_files"]] == [*names, " untracked \n"]
    assert overview["repo_path"] == overview["working_dir"] == ROOT
    assert overview["repo_found"] and not overview["can_init"] and not overview["is_clean"]
    assert (overview["current_branch"], overview["ahead_count"], overview["behind_count"]) == ("main", 2, 1)
    assert overview["count_exact"] and overview["count_lower_bound"] == len(names) + 1
    assert not overview["status_truncated"]
    assert all(item["staged"] and item["unstaged"] for item in overview["changed_files"][:-1])
    assert overview["changed_files"][-1]["untracked"]
    assert overview["recent_commits"][0] == {
        "hash": OID, "short_hash": OID[:7], "author_name": "开发者", "authored_at": "2026-09-24 12:00:00 +0800",
        "subject": "subject", "message": "subject\n\nbody\n",
    }
    assert overview["recent_commits"][1]["hash"] == "b" * 40
    assert connection.calls[0][0] == ["--version"]


def test_capabilities_probe_local_remote_config_and_mark_sync_features():
    connection = Connection()
    capabilities = remote.RemoteGitService(connection, ROOT).capabilities()["capabilities"]
    assert set(capabilities) == set(GIT_CAPABILITY_NAMES)
    readable = {
        "tree_status", "commit_graph", "branches", "branch_mutation", "discard", "stash", "identity",
        "fetch", "pull", "push", "commit_message_generation", "smart_commit",
    }
    assert all(
        item["available"] is (name in readable)
        and item["reason"] == ("" if name in readable else "remote_feature_unavailable")
        for name, item in capabilities.items()
    )
    assert all(
        item["requires_confirmation"] is (name in GIT_CAPABILITIES_REQUIRING_CONFIRMATION)
        for name, item in capabilities.items()
    )
    assert capabilities["stash"]["available"] is True
    assert capabilities["stash_create"] == {
        "available": False,
        "reason": "remote_feature_unavailable",
        "requires_confirmation": True,
    }
    assert [call[0] for call in connection.calls] == [
        ["--version"],
    ]


def test_capabilities_report_missing_remote_git_without_repository_probe():
    connection = Connection()
    connection.overrides["--version"] = result(stderr="git: not found", returncode=127)
    capabilities = remote.RemoteGitService(connection, ROOT).capabilities()["capabilities"]
    assert all(item["reason"] == "remote_git_not_found" for item in capabilities.values())
    assert [call[0] for call in connection.calls] == [["--version"]]


def test_capabilities_do_not_probe_remote_or_upstream_state():
    for connection in (
        Connection(remotes=()),
        Connection(upstream=""),
        Connection(repository=False),
    ):
        capabilities = remote.RemoteGitService(connection, ROOT).capabilities()["capabilities"]
        assert all(capabilities[name]["available"] for name in ("fetch", "pull", "push"))
        assert [call[0] for call in connection.calls] == [["--version"]]


def test_smart_commit_context_collects_remote_diffs_for_local_agent():
    service = remote.RemoteGitService(Connection(), ROOT)
    service._require_repo = lambda: None
    service._status = lambda: (
        "",
        [{"path": "new.txt", "untracked": True}],
        True,
    )

    def fake_git(args, **_kwargs):
        if args[0] == "status":
            return result(" M tracked.txt\n?? new.txt\n")
        if args[:2] == ["diff", "--cached"]:
            return result("diff --git a/staged.txt b/staged.txt\n+staged\n")
        if args[:2] == ["diff", "--find-renames"]:
            return result("diff --git a/tracked.txt b/tracked.txt\n+tracked\n")
        if args[:2] == ["diff", "--no-index"]:
            return result("diff --git a/NUL b/./new.txt\n+untracked\n", returncode=1)
        raise AssertionError(args)

    service._git = fake_git
    context = service.smart_commit_context()

    assert "staged" in context["diff_text"]
    assert "tracked" in context["diff_text"]
    assert "untracked" in context["diff_text"]
    assert context["status_text"] == " M tracked.txt\n?? new.txt\n"


@pytest.mark.parametrize(
    ("operation", "expected_args"),
    [
        ("fetch", ["fetch", "--all", "--prune"]),
        ("pull", ["pull", "--ff-only"]),
        ("push", ["push", "origin", "main:main"]),
    ],
)
def test_remote_sync_commands_use_remote_root_timeout_and_single_mutation(operation, expected_args):
    connection = Connection(files={})

    overview = getattr(remote.RemoteGitService(connection, ROOT), operation)()

    assert overview["repo_path"] == ROOT
    mutations = [call for call in connection.calls if call[0][0] == operation]
    assert [call[0] for call in mutations] == [expected_args]
    assert mutations[0][1] == ROOT and mutations[0][2] == remote.MUTATION_TIMEOUT
    assert len(mutations) == 1


@pytest.mark.parametrize("operation", ["fetch", "pull", "push"])
def test_remote_sync_prechecks_attach_not_started_error_data_and_do_not_mutate(operation):
    connection = Connection(remotes=()) if operation == "fetch" else Connection(upstream="")

    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)()

    assert exc.value.code == (
        "git_remote_not_configured" if operation == "fetch" else "git_upstream_not_configured"
    )
    assert exc.value.data == {"operation": operation, "outcome": "not_started", "refresh_required": False}
    assert not any(call[0][0] == operation for call in connection.calls)


def test_remote_sync_requires_a_remote_repository_before_remote_configuration():
    connection = Connection(repository=False)

    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).fetch()

    assert exc.value.code == "git_not_repository"
    assert exc.value.data == {"operation": "fetch", "outcome": "not_started", "refresh_required": False}
    assert [call[0] for call in connection.calls] == [["--version"], ["rev-parse", "--show-toplevel"]]


def test_remote_pull_requires_clean_worktree_and_maps_conflicts_to_manual_resolution():
    dirty = Connection(files={"file.txt": ".M"})
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(dirty, ROOT).pull()
    assert exc.value.code == "git_pull_requires_manual_resolution"
    assert exc.value.data == {"operation": "pull", "outcome": "not_started", "refresh_required": False}
    assert not any(call[0][0] == "pull" for call in dirty.calls)

    conflict = Connection(files={"file.txt": "UU"})
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(conflict, ROOT).pull()
    assert exc.value.code == "git_pull_requires_manual_resolution"
    assert not any(call[0][0] == "pull" for call in conflict.calls)


@pytest.mark.parametrize(
    ("operation", "stderr", "expected_code", "outcome"),
    [
        (
            "fetch",
            "fatal: could not read Username for 'https://alice:secret@example.com/repo': terminal prompts disabled\nGIT_ASKPASS=askpass-secret",
            "git_remote_credentials_unavailable",
            "rejected",
        ),
        ("fetch", "ssh: Host key verification failed.", "git_remote_host_key_unverified", "rejected"),
        ("fetch", "fatal: unable to access 'https://example.com/repo': Could not resolve host", "git_remote_network_failed", "unknown"),
        ("pull", "fatal: Not possible to fast-forward, aborting.", "git_pull_requires_manual_resolution", "rejected"),
        ("push", "! [rejected] main -> main (non-fast-forward)\nfailed to push some refs", "git_push_rejected", "rejected"),
    ],
)
def test_remote_sync_classifies_failures_redacts_secrets_and_reports_outcome(operation, stderr, expected_code, outcome):
    connection = Connection(files={})
    connection.overrides[operation] = result(stderr=stderr, returncode=1)

    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)()

    assert exc.value.code == expected_code
    assert exc.value.data["operation"] == operation
    assert exc.value.data["outcome"] == outcome
    assert exc.value.data["refresh_required"] is True
    assert "secret" not in exc.value.message.lower()
    assert "askpass-secret" not in str(exc.value.data).lower()
    assert sum(call[0][0] == operation for call in connection.calls) == 1


@pytest.mark.parametrize("transport_code", ["remote_timeout", "remote_disconnected"])
def test_remote_sync_transport_failure_is_unknown_and_is_not_retried(transport_code):
    connection = Connection(files={})
    connection.overrides["fetch"] = RemoteWorkspaceError(504 if transport_code == "remote_timeout" else 502, transport_code, "transport failed")

    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).fetch()

    assert exc.value.code == "git_remote_network_failed"
    assert exc.value.data == {"operation": "fetch", "outcome": "unknown", "refresh_required": True}
    assert sum(call[0][0] == "fetch" for call in connection.calls) == 1


@pytest.mark.parametrize("transport_code", ["host_key_confirmation_required", "host_key_mismatch"])
def test_remote_sync_host_key_transport_errors_use_stable_diagnostic_code(transport_code):
    connection = Connection(files={})
    connection.overrides["fetch"] = RemoteWorkspaceError(409, transport_code, "SSH host key is not verified")

    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).fetch()

    assert exc.value.code == "git_remote_host_key_unverified"
    assert exc.value.data == {"operation": "fetch", "outcome": "rejected", "refresh_required": True}
    assert sum(call[0][0] == "fetch" for call in connection.calls) == 1


def test_tree_status_parses_nul_records_without_losing_special_paths():
    connection = Connection(files={})
    connection.readonly_outputs["tree_status"] = "".join([
        " M space file.txt\x00",
        "A  added\nfile\x00",
        "?? unicode-中文\\name.txt\x00",
        "!! ignored dir/\x00",
        " D deleted.txt\x00",
    ])

    payload = remote.RemoteGitService(connection, ROOT).tree_status()

    assert payload["items"] == {
        "space file.txt": "modified",
        "added\nfile": "added",
        "unicode-中文\\name.txt": "added",
        "ignored dir": "ignored",
    }
    status_calls = [call for call in connection.calls if call[0][0] == "status"]
    assert status_calls[-1][0] == ["status", "--porcelain=1", "-z", "--ignored=matching", "--untracked-files=normal"]


def test_tree_status_rejects_incomplete_output_and_does_not_return_partial_items():
    connection = Connection(files={})
    connection.readonly_outputs["tree_status"] = " M partial.txt"

    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).tree_status()

    assert exc.value.code == "remote_git_status_truncated"


def test_remote_read_only_git_views_parse_branches_graph_stashes_and_identity():
    merge, first_parent, second_parent, root = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
    connection = Connection(files={})
    connection.readonly_outputs.update({
        "branches": nul_fields(
            "main", "*", "origin/main", merge[:7], "merge subject",
            "feature\nbranch", " ", "", second_parent[:7], "feature subject",
        ),
        "graph": "".join([
            "\x1f".join((merge, f"{first_parent} {second_parent}", merge[:7], "Alice", "2026-10-06T10:00:00+08:00", "merge subject", "merge subject\n\ncomplete merge body\n")) + "\x00",
            "\x1f".join((second_parent, root, second_parent[:7], "Bob", "2026-10-05T10:00:00+08:00", "side subject", "side subject\n\nside body\n")) + "\x00",
            "\x1f".join((first_parent, root, first_parent[:7], "Alice", "2026-10-04T10:00:00+08:00", "first subject", "first subject\n")) + "\x00",
        ]),
        "graph_refs": "".join([
            nul_fields("refs/heads/main", merge, "", "commit", "", "*"),
            nul_fields("refs/heads/feature", second_parent, "", "commit", "", " "),
            nul_fields("refs/remotes/origin/main", merge, "", "commit", "", " "),
            nul_fields("refs/tags/v1", root, "", "commit", "", " "),
        ]),
        "head": f"{merge}\n",
        "stashes": nul_fields("stash@{0}", merge, "2026-10-06 11:00:00 +0800", "WIP on main: full description"),
        "config": {
            ("--global", "--get", "user.name"): "Global Name\n",
            ("--global", "--get", "user.email"): "global@example.com\n",
            ("--local", "--get", "user.name"): "Local Name\n",
            ("--local", "--get", "user.email"): "local@example.com\n",
        },
    })
    service = remote.RemoteGitService(connection, ROOT)

    branches = service.branches()
    graph = service.graph(scope="all", limit=2)
    current_graph = service.graph(scope="current", limit=1)
    stashes = service.stashes()
    identity = service.identity()

    assert branches == {
        "current_branch": "main",
        "branches": [
            {"name": "main", "current": True, "upstream": "origin/main", "short_hash": merge[:7], "subject": "merge subject"},
            {"name": "feature\nbranch", "current": False, "upstream": "", "short_hash": second_parent[:7], "subject": "feature subject"},
        ],
    }
    assert graph["scope"] == "all" and graph["has_more"] and graph["next_cursor"]
    assert graph["nodes"][0]["parents"] == [first_parent, second_parent]
    assert graph["nodes"][0]["message"] == "merge subject\n\ncomplete merge body"
    assert {ref["name"] for ref in graph["nodes"][0]["refs"]} == {"HEAD", "main", "origin/main"}
    assert current_graph["scope"] == "current"
    assert any(call[0][-1] == "HEAD" for call in connection.calls if call[0][0] == "log")
    assert stashes == {"items": [{"ref": "stash@{0}", "hash": merge[:12], "created_at": "2026-10-06 11:00:00 +0800", "message": "WIP on main: full description"}]}
    assert identity == {
        "repo_found": True,
        "repo_path": ROOT,
        "global": {"name": "Global Name", "email": "global@example.com"},
        "local": {"name": "Local Name", "email": "local@example.com"},
    }


def test_remote_identity_allows_missing_config_and_non_repository():
    connection = Connection(repository=False, files={})

    payload = remote.RemoteGitService(connection, ROOT).identity()

    assert payload == {
        "repo_found": False,
        "repo_path": "",
        "global": {"name": "", "email": ""},
        "local": {"name": "", "email": ""},
    }


@pytest.mark.parametrize("operation", ["branches", "graph", "stashes"])
def test_remote_read_only_views_require_a_remote_repository(operation):
    service = remote.RemoteGitService(Connection(repository=False, files={}), ROOT)

    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(service, operation)()

    assert exc.value.code == "git_not_repository"


def test_remote_tree_status_reports_missing_repository_without_partial_data():
    payload = remote.RemoteGitService(Connection(repository=False, files={}), ROOT).tree_status()

    assert payload == {"repo_found": False, "working_dir": ROOT, "repo_path": "", "items": {}}


def test_remote_branches_support_detached_head_and_missing_upstream():
    connection = Connection(files={})
    connection.readonly_outputs["branches"] = nul_fields("topic", " ", "", OID[:7], "topic subject")

    payload = remote.RemoteGitService(connection, ROOT).branches()

    assert payload["current_branch"] == ""
    assert payload["branches"][0]["upstream"] == ""


def test_capabilities_preserve_remote_transport_errors():
    connection = Connection()
    error = RemoteWorkspaceError(502, "remote_timeout", "original")
    connection.overrides["--version"] = error
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).capabilities()
    assert exc.value is error


def test_non_repository_offers_init_without_running_repository_commands():
    connection = Connection(repository=False)
    overview = remote.RemoteGitService(connection, ROOT).overview()
    assert not overview["repo_found"] and overview["can_init"]
    assert overview["working_dir"] == ROOT
    assert overview["repo_path"] == overview["repo_name"] == overview["current_branch"] == ""
    assert overview["changed_files"] == overview["recent_commits"] == []
    assert [call[0] for call in connection.calls] == [["--version"], ["rev-parse", "--show-toplevel"]]


def test_init_creates_remote_repository_once_and_returns_initial_status():
    connection = Connection(repository=False, files={}, untracked=["new.txt"])
    service = remote.RemoteGitService(connection, ROOT)
    overview = service.init()
    assert overview["repo_found"] and not overview["can_init"]
    assert overview["repo_path"] == ROOT
    assert overview["changed_files"][0]["path"] == "new.txt"
    assert overview["changed_files"][0]["untracked"]
    assert overview["recent_commits"] == []
    assert service.init() == overview
    mutations = [call for call in connection.calls if call[0] == ["init"]]
    assert len(mutations) == 1
    assert mutations[0][1:3] == (ROOT, remote.MUTATION_TIMEOUT)


@pytest.mark.parametrize("message", [
    "fatal: detected dubious ownership in repository at '/srv/project'",
    "fatal: failed to stat '/srv/project/.git': Permission denied",
    "fatal: not a git repository: /srv/project/.git",
    "fatal: this operation must be run in a work tree",
])
def test_repo_probe_errors_are_not_treated_as_uninitialized(message):
    connection = Connection()
    connection.overrides["rev-parse"] = result(stderr=message, returncode=128)
    service = remote.RemoteGitService(connection, ROOT)
    for operation in (service.overview, service.init):
        with pytest.raises(RemoteWorkspaceError) as exc:
            operation()
        assert exc.value.message == message
    assert not any(call[0] == ["init"] for call in connection.calls)


def test_init_preserves_failure_without_returning_a_successful_overview():
    connection = Connection(repository=False)
    connection.overrides["init"] = result(stderr="Permission denied", returncode=128)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).init()
    assert exc.value.code == "git_init_failed"
    assert exc.value.message == "Permission denied"
    assert connection.calls[-1][0] == ["init"]


@pytest.mark.parametrize("path", ["", ".", "..", "../secret", "dir/../secret", "/outside", "C:/outside",
                                    "a//b", "dir/", ".git/config", "dir/.git/config", "a\x00b", None, 1])
def test_invalid_paths_fail_before_ssh(path):
    connection = Connection()
    with pytest.raises(RemoteWorkspaceError):
        remote.RemoteGitService(connection, ROOT).stage([path])
    assert not connection.calls


@pytest.mark.parametrize("paths", [[], None, "file.txt", {}])
def test_path_list_is_required(paths):
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(Connection(), ROOT).unstage(paths)
    assert exc.value.code == "missing_git_paths"


@pytest.mark.parametrize("path", ["dir", "*.txt", ":(glob)*"])
def test_only_exact_status_files_can_be_mutated(path):
    connection = Connection(files={"dir/file.txt": ".M"})
    with pytest.raises(RemoteWorkspaceError):
        remote.RemoteGitService(connection, ROOT).stage([path])
    assert not any(call[0][0] == "add" for call in connection.calls)


def test_posix_shell_and_git_pathspecs_preserve_unusual_names():
    paths = ["*.txt", ":(glob)*", "-f", "a'; touch injected; #", "  file \n", r"back\slash"]
    connection = Connection(files={path: ".M" for path in paths})
    overview = remote.RemoteGitService(connection, "/repo ' $(whoami)").stage(paths + paths)
    call = next(call for call in connection.calls if call[0][0] == "add")
    assert call[0] == ["add", "--", *paths]
    assert call[1] == overview["repo_path"] == "/repo ' $(whoami)"
    assert "--literal-pathspecs" in shlex.split(call[4])
    assert "--no-optional-locks" in shlex.split(call[4])


@pytest.mark.parametrize("initial, command", [(True, ["rm", "--cached", "-f"]), (False, ["reset", "--quiet", "HEAD"])])
def test_unstage_uses_one_exact_index_operation_including_initial_commit(initial, command):
    connection = Connection(initial=initial, files={"new.txt": "AM", "keep.txt": "A."})
    overview = remote.RemoteGitService(connection, ROOT).unstage(["new.txt"])
    mutations = [call[0] for call in connection.calls if call[0][0] in {"rm", "reset", "restore"}]
    assert mutations == [[*command, "--", "new.txt"]]
    assert all("--hard" not in args and "-r" not in args for args in mutations)
    if initial:
        assert not overview["recent_commits"]
        assert not any(call[0][0] == "log" for call in connection.calls)


@pytest.mark.parametrize("staged", [False, True])
def test_tracked_diff_has_existing_shape_and_disables_external_drivers(staged):
    connection = Connection()
    diff = remote.RemoteGitService(connection, ROOT).diff("file.txt", staged)
    args = connection.calls[-1][0]
    assert ("--cached" in args) == staged
    assert "--no-ext-diff" in args and "--no-textconv" in args
    assert args[-2:] == ["--", "file.txt"]
    assert diff == {"path": "file.txt", "staged": staged, "diff": "diff --git a/file.txt b/file.txt\n+new\n", "truncated": False}


def test_untracked_diff_accepts_exit_one_and_marks_truncation():
    connection = Connection(files={}, untracked=[":(glob)*"])
    connection.overrides["diff"] = result("partial", returncode=1, truncated=True)
    diff = remote.RemoteGitService(connection, ROOT).diff(":(glob)*")
    assert connection.calls[-1][0][-4:] == ["--no-index", "--", "/dev/null", "./:(glob)*"]
    assert diff["truncated"] and "truncated" in diff["diff"] and diff["diff"].startswith("partial")


@pytest.mark.parametrize("command", ["status", "ls-files"])
@pytest.mark.parametrize("truncated, text", [(True, ""), (False, "incomplete")])
def test_incomplete_status_never_reports_clean_or_mutates(command, truncated, text):
    connection = Connection(files={})
    connection.overrides[command] = result(text, truncated=truncated)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).stage(["file.txt"])
    assert exc.value.code == "remote_git_status_truncated"
    assert not any(call[0][0] == "add" for call in connection.calls)


@pytest.mark.parametrize("operation", ["overview", "init"])
def test_top_level_must_equal_workspace(operation):
    connection = Connection()
    connection.overrides["rev-parse"] = result("/srv\n")
    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)()
    assert exc.value.code == "remote_git_root_required"
    assert exc.value.data == {"repo_path": "/srv", "working_dir": ROOT}
    assert len(connection.calls) == 2


def test_top_level_preserves_posix_path_whitespace():
    connection = Connection(files={})
    root = "/srv/line\n "
    assert remote.RemoteGitService(connection, root).overview()["repo_path"] == root


def test_overview_caps_display_only_with_exact_count(monkeypatch):
    monkeypatch.setattr(remote, "GIT_OVERVIEW_CHANGED_FILES_LIMIT", 1)
    connection = Connection(files={}, untracked=["one", "two"])
    overview = remote.RemoteGitService(connection, ROOT).overview()
    assert len(overview["changed_files"]) == 1
    assert overview["changed_files_truncated"] and not overview["is_clean"]
    assert not overview["status_truncated"] and overview["count_exact"]
    assert overview["changed_files_total_estimate"] == overview["count_lower_bound"] == 2


def test_argument_caps_fail_before_mutations():
    connection = Connection()
    service = remote.RemoteGitService(connection, ROOT)
    with pytest.raises(RemoteWorkspaceError) as exc:
        service.commit("x" * (remote.MAX_ARGUMENT_BYTES + 1))
    assert exc.value.status == 413
    with pytest.raises(RemoteWorkspaceError) as exc:
        service.stage(["x" * (remote.MAX_ARGUMENT_BYTES + 1)])
    assert exc.value.status == 413
    assert not connection.calls


def test_missing_git_has_guidance_and_does_not_probe_repo():
    connection = Connection()
    connection.overrides["--version"] = result(stderr="git: not found", returncode=127)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).overview()
    assert exc.value.code == "remote_git_not_found" and "PATH" in exc.value.message
    assert len(connection.calls) == 1


@pytest.mark.parametrize("code", ["remote_auth_failed", "remote_disconnected", "remote_timeout", "path_not_found"])
def test_ssh_and_missing_root_errors_are_preserved(code):
    connection = Connection()
    error = RemoteWorkspaceError(502, code, "original")
    connection.overrides["--version"] = error
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).overview()
    assert exc.value is error


@pytest.mark.parametrize("code", ["remote_timeout", "remote_disconnected"])
@pytest.mark.parametrize("operation, args, command", [("stage", ["file.txt"], "add"), ("unstage", ["file.txt"], "reset"),
                                                       ("commit", "message", "commit"), ("init", None, "init")])
def test_mutation_is_never_retried(code, operation, args, command):
    connection = Connection(repository=operation != "init", files={"file.txt": "MM"})
    connection.overrides[command] = RemoteWorkspaceError(504, code, "response lost")
    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)(*(() if args is None else (args,)))
    assert exc.value.code == code
    assert sum(call[0][0] == command for call in connection.calls) == 1
    assert connection.calls[-1][0][0] == command


def test_commit_preserves_remote_identity_error_and_message():
    connection = Connection()
    message = 'subject "quote"\n\nbody $(touch nope); ‘text’'
    connection.overrides["commit"] = result(stderr="Author identity unknown\nPlease tell me who you are.\nfatal: unable to auto-detect email address", returncode=128)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).commit(message)
    assert exc.value.code == "git_commit_failed" and "Author identity unknown" in exc.value.message
    assert connection.calls[-1][0] == ["commit", "-m", message]
    assert "user.name" not in connection.calls[-1][4] and "user.email" not in connection.calls[-1][4]


def test_remote_service_never_invokes_local_git_or_alters_control_directory(monkeypatch, tmp_path):
    control = tmp_path / ".git"
    control.mkdir()
    (control / "index").write_bytes(b"local index")
    (control / "HEAD").write_bytes(b"ref: refs/heads/local")
    before = {path.name: path.read_bytes() for path in control.iterdir()}
    monkeypatch.chdir(tmp_path)
    for name in ("_run_git_process", "_run_bounded_process", "_git_repo_lock", "_read_git_head_token", "_read_git_index_token"):
        monkeypatch.setattr(local, name, Mock(side_effect=AssertionError("Local Git is forbidden")))
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("Local process is forbidden")))
    monkeypatch.setattr(Path, "resolve", Mock(side_effect=AssertionError("Local path resolution is forbidden")))
    remote.RemoteGitService(Connection(repository=False, files={}), ROOT).init()
    service = remote.RemoteGitService(Connection(files={"file.txt": "MM"}, untracked=["new.txt"]), ROOT)
    service.overview()
    service.diff("file.txt")
    service.diff("new.txt")
    service.stage(["file.txt"])
    service.unstage(["file.txt"])
    service.commit("remote change")
    assert {path.name: path.read_bytes() for path in control.iterdir()} == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [".git"]


def test_mutation_lock_is_shared_across_instances_and_isolated_by_connection_and_root():
    first, second = Connection(), Connection()
    entered, release = threading.Event(), threading.Event()

    def block(args):
        entered.set()
        assert release.wait(5)
        return result()

    first.overrides["add"] = block
    a, b = remote.RemoteGitService(first, ROOT), remote.RemoteGitService(second, ROOT)
    assert a._lock is b._lock
    other = Connection()
    other.config["connection_id"] = "ssh-two"
    assert remote.RemoteGitService(other, ROOT)._lock is not a._lock
    assert remote.RemoteGitService(first, ROOT + "/other")._lock is not a._lock
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(a.stage, ["file.txt"])
        assert entered.wait(5)
        waiting = pool.submit(b.stage, ["file.txt"])
        try:
            assert not b._lock.acquire(blocking=False)
            assert not second.calls
        finally:
            release.set()
        assert pending.result(timeout=5)["repo_found"]
        assert waiting.result(timeout=5)["repo_found"]


def test_remote_branch_mutations_validate_refs_and_refresh_remote_state():
    connection = Connection(files={})
    connection.readonly_outputs.update({
        "head": OID + "\n",
        "branches": nul_fields("main", "*", "", OID[:7], "main subject"),
    })
    service = remote.RemoteGitService(connection, ROOT)

    created = service.branch_create("feature", OID)
    switched = service.branch_switch("feature")
    reset = service.branch_reset(OID, "hard")

    assert created == {"current_branch": "main", "branches": [
        {"name": "main", "current": True, "upstream": "", "short_hash": OID[:7], "subject": "main subject"},
    ]}
    assert switched == {"current_branch": "main", "branches": created["branches"]}
    assert reset["head_commit"] == OID
    assert reset["branches"] == created["branches"]
    assert [call[0] for call in connection.calls if (
        call[0][0] in {"check-ref-format", "branch", "show-ref", "switch", "symbolic-ref", "merge-base", "reset"}
        or call[0][:2] == ["rev-parse", "--verify"]
    )] == [
        ["check-ref-format", "--branch", "feature"],
        ["rev-parse", "--verify", OID + "^{commit}"],
        ["branch", "feature", OID],
        ["check-ref-format", "--branch", "feature"],
        ["show-ref", "--verify", "--quiet", "refs/heads/feature"],
        ["switch", "feature"],
        ["rev-parse", "--verify", OID + "^{commit}"],
        ["symbolic-ref", "--short", "HEAD"],
        ["merge-base", "--is-ancestor", OID, "HEAD"],
        ["reset", "--hard", OID],
        ["rev-parse", "--verify", "HEAD^{commit}"],
    ]
    mutation_calls = [call for call in connection.calls if call[0][0] in {"branch", "switch", "reset"}]
    assert all(call[2] == remote.MUTATION_TIMEOUT for call in mutation_calls)


@pytest.mark.parametrize(
    ("operation", "override", "expected_code"),
    [
        ("branch_switch", result(returncode=1), "git_branch_not_found"),
        ("branch_reset", result(returncode=1), "git_detached_head"),
    ],
)
def test_remote_branch_mutations_reject_missing_target_or_detached_head(operation, override, expected_code):
    connection = Connection(files={})
    connection.readonly_outputs["head"] = OID + "\n"
    if operation == "branch_switch":
        connection.overrides["show-ref"] = override
        args = ("missing",)
    else:
        connection.overrides["symbolic-ref"] = override
        args = (OID,)

    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)(*args)

    assert exc.value.code == expected_code
    assert not any(call[0][0] in {"switch", "reset"} for call in connection.calls)


@pytest.mark.parametrize(
    ("files", "untracked", "mutation_args"),
    [
        ({"tracked.txt": ".M"}, (), ["restore", "--source=HEAD", "--staged", "--worktree", "--", "tracked.txt"]),
        ({"added.txt": "A."}, (), ["rm", "--cached", "-f", "--", "added.txt"]),
        ({}, ("new.txt",), ["clean", "-f", "--", "new.txt"]),
        ({"deleted.txt": "D."}, (), ["restore", "--source=HEAD", "--staged", "--worktree", "--", "deleted.txt"]),
    ],
)
def test_remote_discard_handles_each_exact_status_kind(files, untracked, mutation_args):
    connection = Connection(files=files, untracked=untracked)
    overview = remote.RemoteGitService(connection, ROOT).discard_all()

    assert overview["repo_found"]
    assert mutation_args in [call[0] for call in connection.calls]
    mutations = [call for call in connection.calls if call[0][0] in {"rm", "restore", "clean"}]
    assert mutations and all(call[2] == remote.MUTATION_TIMEOUT for call in mutations)


def test_remote_discard_requires_complete_status_and_exact_paths():
    connection = Connection(files={"tracked.txt": ".M"})
    connection.overrides["status"] = result(truncated=True)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).discard(["tracked.txt"])
    assert exc.value.code == "remote_git_status_truncated"
    assert not any(call[0][0] in {"rm", "restore", "clean"} for call in connection.calls)

    connection = Connection(files={"tracked.txt": ".M"})
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).discard(["missing.txt"])
    assert exc.value.code == "invalid_git_path"
    assert not any(call[0][0] in {"rm", "restore", "clean"} for call in connection.calls)


def test_remote_discard_restores_the_source_and_removes_a_reported_rename():
    connection = Connection(files={})
    connection.overrides["status"] = result(
        f"# branch.oid {OID}\x00# branch.head main\x00"
        f"2 R. N... 100644 100644 100644 {OID} {OID} R100 renamed.txt\x00original.txt\x00"
    )

    remote.RemoteGitService(connection, ROOT).discard(["renamed.txt"])

    mutations = [call[0] for call in connection.calls if call[0][0] in {"rm", "restore", "clean"}]
    assert mutations == [
        ["rm", "--cached", "-f", "--", "renamed.txt"],
        ["restore", "--source=HEAD", "--staged", "--worktree", "--", "original.txt"],
        ["clean", "-f", "--", "renamed.txt"],
    ]


def test_remote_discard_rejects_a_status_record_missing_a_rename_source():
    connection = Connection(files={})
    connection.overrides["status"] = result(
        f"# branch.oid {OID}\x00# branch.head main\x00"
        f"2 R. N... 100644 100644 100644 {OID} {OID} R100 renamed.txt\x00"
    )
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).discard(["renamed.txt"])
    assert exc.value.code == "remote_git_status_truncated"
    assert not any(call[0][0] in {"rm", "restore", "clean"} for call in connection.calls)


def test_remote_stash_mutations_validate_refs_refresh_and_map_conflicts():
    connection = Connection(files={})
    connection.readonly_outputs.update({
        "head": OID + "\n",
        "stashes": nul_fields("stash@{0}", OID, "2026-10-06 12:00:00 +0800", "WIP"),
    })
    service = remote.RemoteGitService(connection, ROOT)

    assert service.stash_apply("stash@{0}")["repo_found"]
    assert service.stash_drop("stash@{0}")["repo_found"]
    assert service.stash_pop()["repo_found"]
    assert [call[0] for call in connection.calls if call[0][0] == "stash" and call[0][1] != "list"] == [
        ["stash", "apply", "stash@{0}"],
        ["stash", "drop", "stash@{0}"],
        ["stash", "pop"],
    ]
    assert all(
        call[2] == remote.MUTATION_TIMEOUT
        for call in connection.calls
        if call[0][0] == "stash" and call[0][1] != "list"
    )

    conflict = Connection(files={})
    conflict.readonly_outputs.update({"head": OID + "\n", "stashes": nul_fields(
        "stash@{0}", OID, "2026-10-06 12:00:00 +0800", "WIP",
    )})
    conflict.overrides["stash"] = result(stderr="CONFLICT (content): merge conflict", returncode=1)
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(conflict, ROOT).stash_apply("stash@{0}")
    assert exc.value.code == "git_conflict"
    assert sum(call[0] == ["stash", "apply", "stash@{0}"] for call in conflict.calls) == 1


def test_remote_identity_update_validates_values_and_uses_remote_config_only():
    connection = Connection(files={})
    connection.readonly_outputs["config"] = {
        ("--global", "--get", "user.name"): "Old Name\n",
        ("--global", "--get", "user.email"): "old@example.com\n",
        ("--local", "--get", "user.name"): "Local Name\n",
        ("--local", "--get", "user.email"): "local@example.com\n",
    }
    identity = remote.RemoteGitService(connection, ROOT).identity_update(
        scope="global", name="New Name", email="new@example.com",
    )

    assert identity["global"] == {"name": "New Name", "email": "new@example.com"}
    updates = [call for call in connection.calls if call[0][0] == "config" and "--get" not in call[0]]
    assert [call[0] for call in updates] == [
        ["config", "--global", "user.name", "New Name"],
        ["config", "--global", "user.email", "new@example.com"],
    ]
    assert all(call[2] == remote.MUTATION_TIMEOUT for call in updates)

    for kwargs in (
        {"scope": "other", "name": "Name", "email": "name@example.com"},
        {"scope": "global", "name": "bad\nname", "email": "name@example.com"},
        {"scope": "global", "name": "Name", "email": "invalid"},
    ):
        invalid = Connection(files={})
        with pytest.raises(RemoteWorkspaceError):
            remote.RemoteGitService(invalid, ROOT).identity_update(**kwargs)
        assert not invalid.calls


@pytest.mark.parametrize("path", [r"..\outside", r"C:\outside", r"\\server\share", "file:stream", "NUL.txt", "file. "])
def test_windows_path_validation(path):
    connection = Connection()
    connection.platform = "windows"
    with pytest.raises(RemoteWorkspaceError):
        remote.RemoteGitService(connection, "/C:/repo").stage([path])
    assert not connection.calls


def test_windows_drive_root_comparison_and_lock_are_case_insensitive():
    connection = Connection()
    connection.platform = "windows"
    connection.execute = Mock(side_effect=[result("git version 2.45.0.windows.1\n"), result("c:/REPO\n")])
    a = remote.RemoteGitService(connection, "/C:/repo")
    b = remote.RemoteGitService(connection, "c:/REPO")
    assert a._lock is b._lock
    a._require_repo()


@pytest.mark.skipif(os.name != "nt", reason="Requires actual Windows PowerShell 5.1")
def test_powershell_51_command_preserves_argv_raw_streams_and_exit_code(tmp_path):
    # Substitute an argv-reporting executable for Git; no local Git is used.
    arguments = ["space name", 'quote" and trailing\\', "$(Write-Output INJECTED); & ‘curly’", "中文\nline", "", "--", ":(glob)*"]
    probe = "import json,sys; sys.stdout.buffer.write(json.dumps(sys.argv[1:],ensure_ascii=False).encode('utf8')+b'\\x00raw\\n'); sys.stderr.buffer.write(b'error'); sys.exit(7)"
    command = remote._command(["-c", probe, *arguments], "windows")
    command = command.replace("$gitStart.FileName = 'git.exe'", "$gitStart.FileName = " + windows.literal(sys.executable))
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run([str(powershell), *windows.STDIN_COMMAND.split()[1:]],
                               input=windows.command_script(command, "/" + tmp_path.as_posix()).encode("utf-8"),
                               capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 7, completed.stderr
    data, suffix = completed.stdout.split(b"\x00")
    assert json.loads(data) == arguments
    assert suffix == b"raw\n" and completed.stderr == b"error"


def test_windows_command_keeps_data_outside_powershell_parser():
    argument = 'a"; Write-Output INJECTED; #'
    command = remote._command(["commit", "-m", argument], "windows")
    assert argument not in command and "INJECTED" not in command
    encoded = command.split("FromBase64String('")[1].split("'")[0]
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == '"commit" "-m" "a\\"; Write-Output INJECTED; #"'
    assert "UseShellExecute = $false" in command and "exit $gitExit" in command


@pytest.mark.skipif(os.name != "nt", reason="Requires actual Windows PowerShell 5.1")
def test_powershell_missing_executable_returns_missing_git_sentinel(tmp_path):
    command = remote._command(["--version"], "windows")
    command = command.replace("$gitStart.FileName = 'git.exe'",
                              "$gitStart.FileName = " + windows.literal(str(tmp_path / "absent-git.exe")))
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run([str(powershell), *windows.STDIN_COMMAND.split()[1:]],
                               input=windows.command_script(command, "/" + tmp_path.as_posix()).encode("utf-8"),
                               capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 127, completed.stderr
