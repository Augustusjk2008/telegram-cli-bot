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


ROOT = "/srv/project"
OID = "a" * 40


def result(stdout="", stderr="", returncode=0, truncated=False):
    return {"stdout": stdout, "stderr": stderr, "returncode": returncode, "output_truncated": truncated}


def tracked(path, xy=".M"):
    return f"1 {xy} N... 100644 100644 100644 {OID} {OID} {path}\x00"


class Connection:
    platform = "posix"

    def __init__(self, *, initial=False, files=None, untracked=()):
        self.config = {"connection_id": "ssh-one", "host": "remote.example", "username": "dev"}
        self.initial = initial
        self.files = files if files is not None else {"file.txt": ".M"}
        self.untracked = list(untracked)
        self.calls = []
        self.overrides = {}

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
            return result(root + "\n")
        if args[0] == "status":
            return result(f"# branch.oid {'(initial)' if self.initial else OID}\x00"
                          "# branch.head main\x00# branch.upstream origin/main\x00# branch.ab +2 -1\x00"
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
        if args[0] in {"add", "rm", "reset", "commit"}:
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


def test_top_level_must_equal_workspace():
    connection = Connection()
    connection.overrides["rev-parse"] = result("/srv\n")
    with pytest.raises(RemoteWorkspaceError) as exc:
        remote.RemoteGitService(connection, ROOT).overview()
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
                                                       ("commit", "message", "commit")])
def test_mutation_is_never_retried(code, operation, args, command):
    connection = Connection(files={"file.txt": "MM"})
    connection.overrides[command] = RemoteWorkspaceError(504, code, "response lost")
    with pytest.raises(RemoteWorkspaceError) as exc:
        getattr(remote.RemoteGitService(connection, ROOT), operation)(args)
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
