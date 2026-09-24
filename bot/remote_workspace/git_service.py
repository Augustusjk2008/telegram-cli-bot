"""The first-phase Git workbench, executed exclusively through an SSH connection."""
from __future__ import annotations

import posixpath
import re
import shlex
import threading
import weakref

from bot.web.git_service import (
    GIT_OVERVIEW_CHANGED_FILES_LIMIT,
    _parse_changed_files,
    _parse_porcelain_v2_z,
    _parse_status_header,
    _zero_changed_file_stats,
)

from . import windows
from .transport import MAX_COMMAND_OUTPUT, RemoteConnection, RemoteWorkspaceError, _absolute, _windows_path


READ_TIMEOUT = 30
MUTATION_TIMEOUT = 120
MAX_ARGUMENT_BYTES = 64 * 1024
_LOCKS_GUARD = threading.Lock()
_LOCKS: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_GIT_OPTIONS = ["--no-pager", "--literal-pathspecs", "--no-optional-locks",
                "-c", "core.quotepath=false", "-c", "core.fsmonitor=false",
                "-c", "color.ui=false", "-c", "i18n.logOutputEncoding=UTF-8"]


def _windows_argument(value: str) -> str:
    # CommandLineToArgvW/CRT quoting. PowerShell 5.1's native argument binder
    # strips embedded quotes, so pass this command line directly to .NET.
    value = re.sub(r'(\\*)"', lambda match: match[1] * 2 + '\\"', value)
    value = re.sub(r'\\+$', lambda match: match[0] * 2, value)
    return '"' + value + '"'


def _command(args: list[str], platform: str) -> str:
    if platform != "windows":
        return "LC_ALL=C GIT_TERMINAL_PROMPT=0 " + shlex.join(["git", *args])
    arguments = " ".join(_windows_argument(arg) for arg in args)
    # Inherit the SSH streams: no PowerShell pipeline decoding, newline
    # rewriting or buffering of the NUL-delimited status output.
    return f"""$gitStart = New-Object System.Diagnostics.ProcessStartInfo
$gitStart.FileName = 'git.exe'
$gitBinary = Get-Command -Name $gitStart.FileName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gitBinary) {{ exit 127 }}
$gitStart.FileName = $gitBinary.Source
$gitStart.Arguments = {windows.literal(arguments)}
$gitStart.WorkingDirectory = (Get-Location).ProviderPath
$gitStart.UseShellExecute = $false
$gitStart.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
$gitStart.EnvironmentVariables['LC_ALL'] = 'C'
try {{ $gitProcess = [Diagnostics.Process]::Start($gitStart) }}
catch [ComponentModel.Win32Exception] {{
    if ($_.Exception.NativeErrorCode -eq 2) {{ exit 127 }}
    throw
}}
try {{ $gitProcess.WaitForExit(); $gitExit = $gitProcess.ExitCode }}
finally {{ $gitProcess.Dispose() }}
exit $gitExit
"""


class RemoteGitService:
    def __init__(self, connection: RemoteConnection, root: str):
        self.connection = connection
        self.platform = connection.platform
        self.root = _absolute(root, self.platform)
        config = connection.config
        key = tuple(config.get(field, "") for field in (
            "connection_id", "host", "port", "username", "host_key_fingerprint", "platform",
        )) + (self.root.casefold() if self.platform == "windows" else self.root,)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(key, threading.RLock())

    def _git(self, args: list[str], *, error: str = "remote_git_failed",
             allowed: tuple[int, ...] = (0,), truncated: bool = False,
             mutation: bool = False) -> dict:
        result = self.connection.execute(
            _command([*_GIT_OPTIONS, *args], self.platform), self.root,
            timeout=MUTATION_TIMEOUT if mutation else READ_TIMEOUT,
            max_output=MAX_COMMAND_OUTPUT,
        )
        if result["output_truncated"] and not truncated:
            code = "remote_git_status_truncated" if error == "git_status_failed" else "remote_git_output_truncated"
            raise RemoteWorkspaceError(413, code, "Remote Git output exceeded the limit; no partial status was used")
        if result["returncode"] not in allowed:
            message = (result["stderr"] or result["stdout"] or "Remote Git command failed").strip()
            if result["output_truncated"]:
                message += "\n[Remote Git output truncated]"
            raise RemoteWorkspaceError(400, error, message)
        return result

    def _require_repo(self) -> None:
        version = self._git(["--version"], allowed=(0, 127))
        if version["returncode"] == 127:
            raise RemoteWorkspaceError(
                400, "remote_git_not_found",
                "Git was not found in the SSH account's noninteractive PATH. Install Git on the remote machine "
                "or update that account's PATH, then retry.",
            )
        top = self._git(["rev-parse", "--show-toplevel"], error="git_not_repository")["stdout"].removesuffix("\n")
        if self.platform == "windows":
            top = top.removesuffix("\r")
        top = _absolute(top, self.platform)
        expected, actual = self.root, top
        if self.platform == "windows":
            expected, actual = expected.casefold(), actual.casefold()
        if actual != expected:
            raise RemoteWorkspaceError(400, "remote_git_root_required",
                                       "Select the repository root as the remote workspace to use Git.",
                                       {"repo_path": top, "working_dir": self.root})

    def _path(self, path: str) -> str:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise RemoteWorkspaceError(400, "invalid_git_path", "A repository-relative file path is required")
        if self.platform == "windows":
            path = _windows_path(path)
        if (path.startswith("/") or re.match(r"^[A-Za-z]:", path)
                or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in path.split("/"))):
            raise RemoteWorkspaceError(400, "invalid_git_path", "Select an exact file inside the repository")
        if len(path.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise RemoteWorkspaceError(413, "invalid_git_path", "Git path is too long")
        return path

    def _paths(self, paths: list[str]) -> list[str]:
        if not isinstance(paths, list) or not paths:
            raise RemoteWorkspaceError(400, "missing_git_paths", "Select at least one file")
        if len(paths) > GIT_OVERVIEW_CHANGED_FILES_LIMIT:
            raise RemoteWorkspaceError(413, "too_many_git_paths", "Too many Git paths")
        normalized = list(dict.fromkeys(self._path(path) for path in paths))
        if sum(len(path.encode("utf-8")) + 1 for path in normalized) > MAX_ARGUMENT_BYTES:
            raise RemoteWorkspaceError(413, "too_many_git_paths", "Git paths exceed the argument limit")
        return normalized

    def _status(self) -> tuple[str, list[dict], bool]:
        raw = self._git(["status", "--porcelain=v2", "--branch", "-z", "--no-renames",
                         "--untracked-files=no"], error="git_status_failed")["stdout"]
        untracked = self._git(["ls-files", "--others", "--exclude-standard", "-z"],
                              error="git_status_failed")["stdout"]
        records = raw.split("\x00")
        if (not raw.endswith("\x00") or not any(record.startswith("# branch.oid ") for record in records)
                or (untracked and not untracked.endswith("\x00"))):
            raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")
        header, lines = _parse_porcelain_v2_z(raw)
        lines.extend("?? " + path for path in untracked.split("\x00") if path)
        files = []
        for line in lines:
            # Reuse the pure status flags parser, but do not let its legacy
            # line-oriented path trimming/rename handling corrupt a filename.
            item = _parse_changed_files([line[:3] + "file"])[0]
            item["path"] = line[3:]
            item.update(_zero_changed_file_stats())
            files.append(item)
        return header, files, "# branch.oid (initial)" not in records

    @staticmethod
    def _select(paths: list[str], files: list[dict], *, staged: bool = False) -> None:
        available = {item["path"] for item in files if not staged or item["staged"]}
        if any(path not in available for path in paths):
            raise RemoteWorkspaceError(400, "invalid_git_path", "Select an exact changed file from the current Git status")

    def _recent_commits(self, has_head: bool) -> list[dict]:
        if not has_head:
            return []
        raw = self._git(["log", "-n8", "--date=iso", "-z",
                         "--pretty=format:%H%x00%h%x00%an%x00%ad%x00%s%x00%B"])["stdout"]
        fields = raw.split("\x00")
        return [dict(zip(("hash", "short_hash", "author_name", "authored_at", "subject", "message"),
                         fields[index:index + 6])) for index in range(0, len(fields) - 5, 6)]

    def _stats(self, files: list[dict]) -> None:
        if not any(not item["untracked"] for item in files):
            return
        by_path = {item["path"]: item for item in files}
        for staged in (False, True):
            args = ["diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv"]
            if staged:
                args.append("--cached")
            raw = self._git(args, error="git_status_failed")["stdout"]
            for record in raw.split("\x00"):
                fields = record.split("\t", 2)
                if len(fields) != 3 or fields[2] not in by_path:
                    continue
                item = by_path[fields[2]]
                for name, value in zip(("additions", "deletions"), fields[:2]):
                    count = int(value) if value.isdecimal() else 0
                    item[("staged_" if staged else "unstaged_") + name] = count
                    item[name] += count

    def _overview(self) -> dict:
        header, files, has_head = self._status()
        branch, ahead, behind = _parse_status_header(header)
        total = len(files)
        files = files[:GIT_OVERVIEW_CHANGED_FILES_LIMIT]
        self._stats(files)
        return {
            "repo_found": True, "can_init": False, "working_dir": self.root,
            "repo_path": self.root, "repo_name": posixpath.basename(self.root.rstrip("/")),
            "current_branch": branch, "is_clean": total == 0,
            "ahead_count": ahead, "behind_count": behind, "changed_files": files,
            "changed_files_truncated": total > len(files), "changed_files_total_estimate": total,
            "status_truncated": False, "untracked_files_truncated": False,
            "count_lower_bound": total, "count_exact": True, "truncation_reason": "",
            "recent_commits": self._recent_commits(has_head),
        }

    def overview(self) -> dict:
        with self._lock:
            self._require_repo()
            return self._overview()

    def diff(self, path: str, staged: bool = False) -> dict:
        path = self._path(path)
        if not isinstance(staged, bool):
            raise RemoteWorkspaceError(400, "invalid_git_diff", "staged must be a boolean")
        with self._lock:
            self._require_repo()
            _, files, _ = self._status()
            self._select([path], files)
            untracked = any(item["path"] == path and item["untracked"] for item in files)
            args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=2147483647"]
            if staged:
                args.append("--cached")
            if untracked and not staged:
                args.extend(["--no-index", "--", "NUL" if self.platform == "windows" else "/dev/null", "./" + path])
            else:
                args.extend(["--", path])
            result = self._git(args, error="git_diff_failed", allowed=(0, 1) if untracked and not staged else (0,),
                               truncated=True)
            text = result["stdout"]
            if result["output_truncated"]:
                text += "\n\n[Remote Git diff truncated: output limit reached]\n"
            return {"path": path, "staged": staged, "diff": text, "truncated": result["output_truncated"]}

    def stage(self, paths: list[str]) -> dict:
        paths = self._paths(paths)
        with self._lock:
            self._require_repo()
            _, files, _ = self._status()
            self._select(paths, files)
            self._git(["add", "--", *paths], error="git_stage_failed", mutation=True, truncated=True)
            return self._overview()

    def unstage(self, paths: list[str]) -> dict:
        paths = self._paths(paths)
        with self._lock:
            self._require_repo()
            _, files, has_head = self._status()
            self._select(paths, files, staged=True)
            args = ["reset", "--quiet", "HEAD"] if has_head else ["rm", "--cached", "-f"]
            self._git([*args, "--", *paths], error="git_unstage_failed", mutation=True, truncated=True)
            return self._overview()

    def commit(self, message: str) -> dict:
        if not isinstance(message, str) or not message.strip() or "\x00" in message:
            raise RemoteWorkspaceError(400, "empty_commit_message", "A commit message is required")
        if len(message.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise RemoteWorkspaceError(413, "invalid_commit_message", "Commit message is too long")
        with self._lock:
            self._require_repo()
            self._git(["commit", "-m", message.strip()], error="git_commit_failed", mutation=True, truncated=True)
            return self._overview()
