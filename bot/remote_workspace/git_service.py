"""The first-phase Git workbench, executed exclusively through an SSH connection."""
from __future__ import annotations

import posixpath
import re
import shlex
import threading
import weakref

from bot.git_contract import build_git_capabilities
from bot.git_shared import (
    GIT_OVERVIEW_CHANGED_FILES_LIMIT,
    _decode_git_graph_cursor,
    _encode_git_graph_cursor,
    _git_graph_ref_kind,
    _layout_git_graph_nodes,
    _normalize_git_graph_limit,
    _normalize_git_graph_scope,
    _parse_changed_files,
    _parse_porcelain_v2_z,
    _parse_status_header,
    _parse_tree_status_kind,
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
_STASH_REF_RE = re.compile(r"^stash@\{\d+\}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_UNMERGED_STATUSES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
_SYNC_OPERATIONS = frozenset({"fetch", "pull", "push"})


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

    @staticmethod
    def _is_not_repository(message: str) -> bool:
        # This is Git's unambiguous response for a directory that simply has
        # no repository. Other `not a git repository: ...` diagnostics can
        # describe a broken or inaccessible repository and must remain errors.
        return message.lower().startswith("fatal: not a git repository (or any of the parent directories):")

    def _repo_root(self) -> str | None:
        version = self._git(["--version"], allowed=(0, 127))
        if version["returncode"] == 127:
            raise RemoteWorkspaceError(
                400, "remote_git_not_found",
                "Git was not found in the SSH account's noninteractive PATH. Install Git on the remote machine "
                "or update that account's PATH, then retry.",
            )
        return self._repo_root_without_version()

    def _repo_root_without_version(self) -> str | None:
        result = self._git(
            ["rev-parse", "--show-toplevel"],
            error="git_repo_probe_failed",
            allowed=(0, 128),
        )
        if result["returncode"]:
            message = (result["stderr"] or result["stdout"] or "Remote Git repository probe failed").strip()
            if self._is_not_repository(message):
                return None
            raise RemoteWorkspaceError(400, "git_repo_probe_failed", message)

        top = result["stdout"].removesuffix("\n")
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
        return top

    def _remote_names(self) -> list[str]:
        raw = self._git(["remote"], error="git_remote_probe_failed")["stdout"]
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _upstream_target(self, remotes: list[str]) -> tuple[str, str, str] | None:
        head = self._git(
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            allowed=(0, 1),
            error="git_upstream_probe_failed",
        )
        if head["returncode"]:
            return None
        branch = head["stdout"].strip()
        if not branch or "\n" in branch or "\r" in branch:
            return None

        upstream = self._git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            allowed=(0, 128),
            error="git_upstream_probe_failed",
        )
        if upstream["returncode"]:
            return None
        upstream_name = upstream["stdout"].strip()
        if not upstream_name or "\n" in upstream_name or "\r" in upstream_name:
            return None

        # Match the longest configured remote name so remotes containing a
        # slash remain unambiguous. A local tracking branch is not a valid
        # remote target for Pull/Push.
        for remote_name in sorted(remotes, key=len, reverse=True):
            prefix = remote_name + "/"
            if upstream_name.startswith(prefix) and upstream_name[len(prefix):]:
                return branch, remote_name, upstream_name[len(prefix):]
        return None

    def _require_repo(self) -> None:
        if self._repo_root() is None:
            raise RemoteWorkspaceError(400, "git_not_repository", "The remote workspace is not a Git repository")

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

    @staticmethod
    def _porcelain_v2_original_paths(raw: str) -> dict[str, str]:
        original_paths: dict[str, str] = {}
        records = raw.split("\x00")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record or not record.startswith("2 "):
                continue
            fields = record.split(" ", 9)
            if len(fields) < 10 or index >= len(records) or not records[index]:
                raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")
            original_paths[fields[9]] = records[index]
            index += 1
        return original_paths

    def _status(self, *, include_original: bool = False) -> tuple[str, list[dict], bool]:
        raw = self._git(["status", "--porcelain=v2", "--branch", "-z", "--no-renames",
                         "--untracked-files=no"], error="git_status_failed")["stdout"]
        untracked = self._git(["ls-files", "--others", "--exclude-standard", "-z"],
                              error="git_status_failed")["stdout"]
        records = raw.split("\x00")
        if (not raw.endswith("\x00") or not any(record.startswith("# branch.oid ") for record in records)
                or (untracked and not untracked.endswith("\x00"))):
            raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")
        all_original_paths = self._porcelain_v2_original_paths(raw)
        original_paths = all_original_paths if include_original else {}
        header, lines = _parse_porcelain_v2_z(raw)
        lines.extend("?? " + path for path in untracked.split("\x00") if path)
        files = []
        for line in lines:
            # Reuse the pure status flags parser, but do not let its legacy
            # line-oriented path trimming/rename handling corrupt a filename.
            item = _parse_changed_files([line[:3] + "file"])[0]
            item["path"] = line[3:]
            if item["path"] in original_paths:
                item["original_path"] = original_paths[item["path"]]
            item.update(_zero_changed_file_stats())
            files.append(item)
        return header, files, "# branch.oid (initial)" not in records

    @staticmethod
    def _select(paths: list[str], files: list[dict], *, staged: bool = False) -> None:
        available = {item["path"] for item in files if not staged or item["staged"]}
        if any(path not in available for path in paths):
            raise RemoteWorkspaceError(400, "invalid_git_path", "Select an exact changed file from the current Git status")

    @staticmethod
    def _normalize_branch_name(name: object) -> str:
        if not isinstance(name, str):
            raise RemoteWorkspaceError(400, "invalid_git_branch", "A Git branch name is required")
        value = name.strip()
        if (not value or len(value) > 120 or value.startswith("-")
                or any(char.isspace() for char in value)
                or "\x00" in value or "\\" in value or value.endswith(("/", "."))):
            raise RemoteWorkspaceError(400, "invalid_git_branch", "Invalid Git branch name")
        return value

    def _assert_valid_branch_name(self, name: object) -> str:
        value = self._normalize_branch_name(name)
        result = self._git(
            ["check-ref-format", "--branch", value],
            allowed=(0, 1),
            error="git_branch_validation_failed",
        )
        if result["returncode"]:
            raise RemoteWorkspaceError(400, "invalid_git_branch", "Invalid Git branch name")
        return value

    def _resolve_commit_ref(self, ref: object) -> str:
        value = ref.strip() if isinstance(ref, str) else ""
        if not _COMMIT_SHA_RE.fullmatch(value):
            raise RemoteWorkspaceError(400, "invalid_git_commit", "Invalid commit reference")
        result = self._git(
            ["rev-parse", "--verify", f"{value}^{{commit}}"],
            allowed=(0, 128),
            error="git_commit_lookup_failed",
        )
        if result["returncode"]:
            raise RemoteWorkspaceError(400, "invalid_git_commit", "Commit does not exist")
        full_sha = result["stdout"].strip()
        if not full_sha:
            raise RemoteWorkspaceError(400, "invalid_git_commit", "Commit does not exist")
        return full_sha

    @staticmethod
    def _normalize_reset_mode(mode: object) -> str:
        value = mode.strip().lower() if isinstance(mode, str) else "mixed" if mode is None else ""
        if value not in {"soft", "mixed", "hard"}:
            raise RemoteWorkspaceError(400, "invalid_git_reset_mode", "Invalid reset mode")
        return value

    @staticmethod
    def _normalize_stash_ref(ref: object) -> str:
        value = ref.strip() if isinstance(ref, str) else ""
        if not _STASH_REF_RE.fullmatch(value):
            raise RemoteWorkspaceError(400, "invalid_git_stash_ref", "Invalid stash reference")
        return value

    @staticmethod
    def _normalize_identity_scope(scope: object) -> str:
        value = scope.strip().lower() if isinstance(scope, str) else ""
        if value not in {"global", "local"}:
            raise RemoteWorkspaceError(400, "invalid_git_identity_scope", "Invalid Git identity scope")
        return value

    @staticmethod
    def _normalize_identity_value(value: object, *, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise RemoteWorkspaceError(400, f"empty_git_{field}", "Git name and email are required")
        if len(text) > 200 or "\x00" in text or "\n" in text or "\r" in text:
            raise RemoteWorkspaceError(400, f"invalid_git_{field}", "Invalid Git name or email")
        if field == "email" and ("@" not in text or any(char.isspace() for char in text)):
            raise RemoteWorkspaceError(400, "invalid_git_email", "Invalid Git email")
        return text

    @staticmethod
    def _has_conflict(files: list[dict]) -> bool:
        return any(
            str(item.get("status") or "") in _UNMERGED_STATUSES
            or "U" in str(item.get("status") or "")
            for item in files
        )

    @classmethod
    def _require_clean_worktree(cls, files: list[dict]) -> None:
        if cls._has_conflict(files):
            raise RemoteWorkspaceError(409, "git_conflict", "The remote worktree contains unresolved conflicts")
        if files:
            raise RemoteWorkspaceError(409, "git_dirty_worktree", "The remote worktree has uncommitted changes")

    def _require_branch(self, name: str) -> None:
        result = self._git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
            allowed=(0, 1),
            error="git_branch_lookup_failed",
        )
        if result["returncode"]:
            raise RemoteWorkspaceError(404, "git_branch_not_found", "The target branch does not exist")

    def _require_stash(self, ref: str) -> None:
        result = self._git(
            ["rev-parse", "--verify", f"{ref}^{{commit}}"],
            allowed=(0, 128),
            error="git_stash_lookup_failed",
        )
        if result["returncode"]:
            raise RemoteWorkspaceError(404, "git_stash_not_found", "The target stash does not exist")

    @staticmethod
    def _conflict_output(result: dict) -> bool:
        output = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr")).lower()
        return any(marker in output for marker in (
            "conflict", "would be overwritten", "needs merge", "could not restore untracked",
        ))

    def _stash_mutation(self, args: list[str], *, error: str) -> dict:
        result = self._git(
            args,
            allowed=(0, 1, 128),
            error=error,
            mutation=True,
            truncated=True,
        )
        if result["returncode"]:
            if self._conflict_output(result):
                data = {}
                try:
                    data["overview"] = self._overview()
                except RemoteWorkspaceError:
                    pass
                raise RemoteWorkspaceError(409, "git_conflict", "The stash operation produced merge conflicts", data)
            message = (result["stderr"] or result["stdout"] or "Remote Git stash operation failed").strip()
            raise RemoteWorkspaceError(400, error, message)
        return result

    def _stash_items(self) -> list[dict]:
        raw = self._git([
            "stash", "list", "--format=%gd%x00%H%x00%ci%x00%gs%x00",
        ], error="git_stash_list_failed")["stdout"]
        return [
            {"ref": ref, "hash": full_hash[:12], "created_at": created_at, "message": message}
            for ref, full_hash, created_at, message in self._parse_nul_fields(raw, 4)
        ]

    def _discard_entries(self, files: list[dict], has_head: bool, *, error: str) -> None:
        if not files:
            return

        restore_paths: list[str] = []
        remove_from_index_paths: list[str] = []
        remove_from_worktree_paths: list[str] = []
        untracked_paths: list[str] = []
        for item in files:
            path = item["path"]
            status = str(item.get("status") or "")
            if item.get("untracked"):
                untracked_paths.append(path)
            elif status.startswith("R"):
                remove_from_index_paths.append(path)
                remove_from_worktree_paths.append(path)
                if item.get("original_path"):
                    restore_paths.append(item["original_path"])
            elif status.startswith("C"):
                remove_from_index_paths.append(path)
                remove_from_worktree_paths.append(path)
            elif status.startswith("A"):
                remove_from_index_paths.append(path)
                remove_from_worktree_paths.append(path)
            else:
                restore_paths.append(path)

        remove_from_index_paths = list(dict.fromkeys(remove_from_index_paths))
        restore_paths = list(dict.fromkeys(restore_paths))
        remove_from_worktree_paths = list(dict.fromkeys(remove_from_worktree_paths))
        untracked_paths = list(dict.fromkeys(untracked_paths))
        if remove_from_index_paths:
            self._git(["rm", "--cached", "-f", "--", *remove_from_index_paths],
                      error=error, mutation=True, truncated=True)
        if restore_paths:
            if not has_head:
                raise RemoteWorkspaceError(400, error, "The initial repository has no commit to restore")
            self._git(["restore", "--source=HEAD", "--staged", "--worktree", "--", *restore_paths],
                      error=error, mutation=True, truncated=True)
        clean_paths = [*remove_from_worktree_paths, *untracked_paths]
        if clean_paths:
            self._git(["clean", "-f", "--", *clean_paths],
                      error=error, mutation=True, truncated=True)

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

    def _empty_overview(self) -> dict:
        return {
            "repo_found": False, "can_init": True, "working_dir": self.root,
            "repo_path": "", "repo_name": "", "current_branch": "", "is_clean": True,
            "ahead_count": 0, "behind_count": 0, "changed_files": [],
            "changed_files_truncated": False, "changed_files_total_estimate": 0,
            "status_truncated": False, "untracked_files_truncated": False,
            "count_lower_bound": 0, "count_exact": True, "truncation_reason": "",
            "recent_commits": [],
        }

    def overview(self) -> dict:
        with self._lock:
            if self._repo_root() is None:
                return self._empty_overview()
            return self._overview()

    def capabilities(self) -> dict:
        with self._lock:
            result = self._git(["--version"], allowed=(0, 127))
            if result["returncode"] == 127:
                return build_git_capabilities(available=False, reason="remote_git_not_found")
            payload = build_git_capabilities(
                available={
                    "tree_status": True,
                    "commit_graph": True,
                    "branches": True,
                    "branch_mutation": True,
                    "discard": True,
                    "stash": True,
                    "stash_create": False,
                    "identity": True,
                },
                reason="remote_feature_unavailable",
            )
            capabilities = payload["capabilities"]
            sync_available = {name: False for name in _SYNC_OPERATIONS}
            sync_reason = "git_not_repository"
            if self._repo_root_without_version() is not None:
                remotes = self._remote_names()
                if remotes:
                    sync_available["fetch"] = True
                    sync_reason = "git_upstream_not_configured"
                    if self._upstream_target(remotes) is not None:
                        sync_available["pull"] = sync_available["push"] = True
                        sync_reason = ""
                else:
                    sync_reason = "git_remote_not_configured"
            for name, available in sync_available.items():
                capabilities[name]["available"] = available
                capabilities[name]["reason"] = "" if available else sync_reason
            return payload

    @staticmethod
    def _redact_remote_text(value: object) -> str:
        text = str(value or "")
        text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1", text)
        text = re.sub(
            r"(?i)(?<![\w])[^@\s/:]+@(?=[A-Za-z0-9._-]+(?::\d+)?[:/])",
            "",
            text,
        )
        text = re.sub(
            r"(?i)([?&](?:access[_-]?token|auth[_-]?token|password|passwd|secret|token)\s*=\s*)[^&\s]+",
            r"\1<redacted>",
            text,
        )
        text = re.sub(
            r"(?i)(\b(?:authorization\s*:\s*bearer|(?:git|ssh)_askpass|askpass(?:_command)?|password|passwd|secret|token)\s*(?:[:=]|\s)\s*)[^\s\r\n]+",
            r"\1<redacted>",
            text,
        )
        return text

    @classmethod
    def _redact_remote_data(cls, value: object) -> object:
        if isinstance(value, str):
            return cls._redact_remote_text(value)
        if isinstance(value, dict):
            return {key: cls._redact_remote_data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_remote_data(item) for item in value]
        return value

    @classmethod
    def _classify_sync_error(cls, operation: str, exc: RemoteWorkspaceError) -> str:
        if exc.code in {
            "git_not_repository",
            "git_remote_not_configured",
            "git_upstream_not_configured",
            "git_pull_requires_manual_resolution",
        }:
            return exc.code
        text = cls._redact_remote_text(
            "\n".join([exc.code, exc.message, *(str(value) for value in exc.data.values())])
        ).lower()
        if exc.code in {"host_key_confirmation_required", "host_key_mismatch", "remote_host_key_unknown"} or any(
            marker in text for marker in (
                "host key verification failed", "host key has changed", "offending", "known_hosts",
                "remote host identification has changed", "no matching host key type",
            )
        ):
            return "git_remote_host_key_unverified"
        if any(marker in text for marker in (
            "authentication failed", "authentication required", "permission denied (publickey)",
            "could not read username", "could not read password", "terminal prompts disabled",
            "invalid username or token", "credential", "access denied",
        )):
            return "git_remote_credentials_unavailable"
        if exc.code in {"remote_timeout", "remote_disconnected", "remote_connection_closed"} or any(
            marker in text for marker in (
                "could not resolve host", "failed to connect", "connection refused",
                "connection timed out", "connection reset", "network is unreachable",
                "no route to host", "name or service not known", "temporary failure in name resolution",
                "timed out", "unable to access",
            )
        ):
            return "git_remote_network_failed"
        if operation == "pull" and any(marker in text for marker in (
            "not possible to fast-forward", "cannot fast-forward", "diverg", "conflict",
            "would be overwritten", "local changes to the following files",
            "please commit your changes",
        )):
            return "git_pull_requires_manual_resolution"
        if operation == "push" and any(marker in text for marker in (
            "[rejected]", "rejected", "non-fast-forward", "failed to push some refs",
            "remote rejected", "hook declined", "pre-receive hook declined",
            "protected branch", "deny updating a hidden ref",
        )):
            return "git_push_rejected"
        return exc.code

    @classmethod
    def _sync_error(
        cls,
        operation: str,
        exc: RemoteWorkspaceError,
        *,
        executed: bool,
    ) -> RemoteWorkspaceError:
        code = cls._classify_sync_error(operation, exc)
        if code == "git_remote_network_failed":
            outcome, refresh_required = "unknown", True
        elif not executed:
            outcome, refresh_required = "not_started", False
        else:
            outcome, refresh_required = "rejected", True
        data = cls._redact_remote_data(exc.data)
        if not isinstance(data, dict):
            data = {}
        data.update({
            "operation": operation,
            "outcome": outcome,
            "refresh_required": refresh_required,
        })
        return RemoteWorkspaceError(
            exc.status,
            code,
            cls._redact_remote_text(exc.message),
            data,
        )

    def _remote_sync_precheck(self, *, require_upstream: bool, require_clean: bool) -> tuple[str, str, str] | None:
        self._require_repo()
        remotes = self._remote_names()
        if not remotes:
            raise RemoteWorkspaceError(409, "git_remote_not_configured", "The remote repository has no configured remote")
        target = self._upstream_target(remotes) if require_upstream else None
        if require_upstream and target is None:
            raise RemoteWorkspaceError(409, "git_upstream_not_configured", "The current branch has no configured upstream")
        if require_clean:
            _, files, _ = self._status()
            if self._has_conflict(files) or files:
                raise RemoteWorkspaceError(
                    409,
                    "git_pull_requires_manual_resolution",
                    "Pull requires a clean worktree without unresolved conflicts",
                )
        return target

    def _run_remote_sync(self, operation: str, args: list[str], *, require_upstream: bool = False,
                         require_clean: bool = False) -> dict:
        if operation not in _SYNC_OPERATIONS:
            raise ValueError(f"Unsupported remote sync operation: {operation}")
        with self._lock:
            try:
                target = self._remote_sync_precheck(
                    require_upstream=require_upstream,
                    require_clean=require_clean,
                )
            except RemoteWorkspaceError as exc:
                raise self._sync_error(operation, exc, executed=False) from exc

            if operation == "push":
                assert target is not None
                branch, remote_name, remote_branch = target
                args = ["push", remote_name, f"{branch}:{remote_branch}"]
            try:
                result = self._git(
                    args,
                    error=f"git_{operation}_failed",
                    allowed=tuple(range(256)),
                    truncated=True,
                    mutation=True,
                )
                if result["returncode"]:
                    message = (result["stderr"] or result["stdout"] or "Remote Git command failed").strip()
                    if result["output_truncated"]:
                        message += "\n[Remote Git output truncated]"
                    raise RemoteWorkspaceError(400, f"git_{operation}_failed", message)
                return self._overview()
            except RemoteWorkspaceError as exc:
                raise self._sync_error(operation, exc, executed=True) from exc

    def fetch(self) -> dict:
        return self._run_remote_sync("fetch", ["fetch", "--all", "--prune"])

    def pull(self) -> dict:
        return self._run_remote_sync("pull", ["pull", "--ff-only"], require_upstream=True, require_clean=True)

    def push(self) -> dict:
        return self._run_remote_sync("push", ["push"], require_upstream=True)

    @staticmethod
    def _status_items(raw: str) -> dict[str, str]:
        if raw and not raw.endswith("\x00"):
            raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")

        items: dict[str, str] = {}
        records = raw.split("\x00") if raw else []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4 or record[2] != " ":
                raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")
            status = record[:2]
            path = record[3:]
            kind = _parse_tree_status_kind(status)
            if kind:
                items[path.rstrip("/")] = kind
            if status[0] in {"R", "C"}:
                if index >= len(records) or not records[index]:
                    raise RemoteWorkspaceError(502, "remote_git_status_truncated", "Remote Git status was incomplete")
                index += 1
        return items

    def tree_status(self) -> dict:
        with self._lock:
            if self._repo_root() is None:
                return {"repo_found": False, "working_dir": self.root, "repo_path": "", "items": {}}
            raw = self._git(
                ["status", "--porcelain=1", "-z", "--ignored=matching", "--untracked-files=normal"],
                error="git_status_failed",
            )["stdout"]
            return {
                "repo_found": True,
                "working_dir": self.root,
                "repo_path": self.root,
                "items": self._status_items(raw),
            }

    @staticmethod
    def _parse_nul_fields(raw: str, width: int, *, error: str = "remote_git_output_truncated") -> list[list[str]]:
        if not raw:
            return []
        # Git's ref and log formatters append a line ending after each format
        # record. Strip only the line ending after a NUL delimiter so newlines
        # inside branch names and commit messages remain data.
        raw = raw.replace("\x00\r\n", "\x00").replace("\x00\n", "\x00")
        if not raw.endswith("\x00"):
            raise RemoteWorkspaceError(502, error, "Remote Git output was incomplete")
        fields = raw.split("\x00")[:-1]
        if len(fields) % width:
            raise RemoteWorkspaceError(502, error, "Remote Git output was incomplete")
        return [fields[index:index + width] for index in range(0, len(fields), width)]

    def branches(self) -> dict:
        with self._lock:
            self._require_repo()
            raw = self._git([
                "for-each-ref",
                "--format=%(refname:short)%00%(HEAD)%00%(upstream:short)%00%(objectname:short)%00%(contents:subject)%00",
                "refs/heads",
            ], error="git_branches_failed")["stdout"]
            branches = [
                {
                    "name": name,
                    "current": head_marker == "*",
                    "upstream": upstream,
                    "short_hash": short_hash,
                    "subject": subject,
                }
                for name, head_marker, upstream, short_hash, subject in self._parse_nul_fields(raw, 5)
            ]
            return {
                "current_branch": next((item["name"] for item in branches if item["current"]), ""),
                "branches": branches,
            }

    @staticmethod
    def _parse_graph_commits(raw: str) -> list[dict]:
        commits = []
        if raw:
            raw = raw.replace("\x00\r\n", "\x00").replace("\x00\n", "\x00")
        if raw and not raw.endswith("\x00"):
            raise RemoteWorkspaceError(502, "remote_git_graph_truncated", "Remote Git output was incomplete")
        for record in (raw.split("\x00")[:-1] if raw else []):
            fields = record.split("\x1f", 6)
            if len(fields) != 7:
                raise RemoteWorkspaceError(502, "remote_git_graph_truncated", "Remote Git output was incomplete")
            full_hash, parents_text, short_hash, author_name, authored_at, subject, message = fields
            commits.append({
                "hash": full_hash,
                "parents": [item for item in parents_text.split() if item],
                "short_hash": short_hash,
                "author_name": author_name,
                "authored_at": authored_at,
                "subject": subject,
                "message": message.rstrip("\r\n"),
            })
        return commits

    @staticmethod
    def _parse_graph_refs(raw: str) -> dict[str, list[dict]]:
        refs_by_commit: dict[str, list[dict]] = {}
        for fields in RemoteGitService._parse_nul_fields(raw, 6, error="remote_git_graph_truncated"):
            refname, object_hash, peeled_hash, object_type, peeled_type, head_marker = fields
            kind_name = _git_graph_ref_kind(refname)
            if kind_name is None:
                continue
            kind, name = kind_name
            commit_hash = peeled_hash if peeled_hash and peeled_type == "commit" else object_hash if object_type == "commit" else ""
            if not commit_hash:
                continue
            refs_by_commit.setdefault(commit_hash, []).append({
                "name": name,
                "kind": kind,
                "current": kind == "local_branch" and head_marker == "*",
            })
        return refs_by_commit

    def graph(self, scope: str = "all", limit: object = "", cursor: object = "") -> dict:
        with self._lock:
            try:
                normalized_scope = _normalize_git_graph_scope(scope)
                normalized_limit = _normalize_git_graph_limit(limit)
                offset = _decode_git_graph_cursor(cursor, scope=normalized_scope)
            except ValueError as exc:
                raise RemoteWorkspaceError(400, getattr(exc, "code", "invalid_cursor"), str(exc)) from exc
            self._require_repo()
            commits_raw = self._git([
                "log", "--topo-order", f"--skip={offset}", f"-n{normalized_limit + 1}",
                "--date=iso-strict",
                "--format=%H%x1f%P%x1f%h%x1f%an%x1f%aI%x1f%s%x1f%B%x00",
                "--all" if normalized_scope == "all" else "HEAD",
            ], error="git_graph_failed")["stdout"]
            commits = self._parse_graph_commits(commits_raw)
            refs_raw = self._git([
                "for-each-ref",
                "--format=%(refname)%00%(objectname)%00%(*objectname)%00%(objecttype)%00%(*objecttype)%00%(HEAD)%00",
                "refs/heads", "refs/remotes", "refs/tags",
            ], error="git_graph_failed")["stdout"]
            refs_by_commit = self._parse_graph_refs(refs_raw)
            head_result = self._git(["rev-parse", "--verify", "HEAD^{commit}"], allowed=(0, 128), error="git_graph_failed")
            head_hash = head_result["stdout"].strip() if head_result["returncode"] == 0 else ""
            if head_hash:
                refs_by_commit.setdefault(head_hash, []).append({"name": "HEAD", "kind": "head", "current": True})
            order = {"head": 0, "local_branch": 1, "remote_branch": 2, "tag": 3}
            for refs in refs_by_commit.values():
                refs.sort(key=lambda item: (order.get(str(item.get("kind")), 99), str(item.get("name") or "")))
            nodes = _layout_git_graph_nodes(commits, refs_by_commit)
            has_more = len(nodes) > normalized_limit
            return {
                "repo_found": True,
                "scope": normalized_scope,
                "nodes": nodes[:normalized_limit],
                "has_more": has_more,
                "next_cursor": _encode_git_graph_cursor(
                    offset=offset + normalized_limit,
                    scope=normalized_scope,
                    head_token=head_hash,
                ) if has_more else "",
            }

    def stashes(self) -> dict:
        with self._lock:
            self._require_repo()
            return {"items": self._stash_items()}

    def identity(self) -> dict:
        with self._lock:
            repo_path = self._repo_root()

            def read(scope: str, key: str) -> str:
                result = self._git(["config", f"--{scope}", "--get", key], allowed=(0, 1), error="git_identity_failed")
                return result["stdout"].strip() if result["returncode"] == 0 else ""

            return {
                "repo_found": repo_path is not None,
                "repo_path": repo_path or "",
                "global": {"name": read("global", "user.name"), "email": read("global", "user.email")},
                "local": {
                    "name": read("local", "user.name") if repo_path else "",
                    "email": read("local", "user.email") if repo_path else "",
                },
            }

    def branch_create(self, name: str, start_point: str = "") -> dict:
        with self._lock:
            self._require_repo()
            branch_name = self._assert_valid_branch_name(name)
            args = ["branch", branch_name]
            if isinstance(start_point, str) and start_point.strip():
                args.append(self._resolve_commit_ref(start_point))
            elif start_point is not None and not (isinstance(start_point, str) and not start_point.strip()):
                raise RemoteWorkspaceError(400, "invalid_git_commit", "Invalid commit reference")
            self._git(args, error="git_branch_create_failed", mutation=True, truncated=True)
            return self.branches()

    def branch_switch(self, name: str) -> dict:
        with self._lock:
            self._require_repo()
            branch_name = self._assert_valid_branch_name(name)
            self._require_branch(branch_name)
            _, files, _ = self._status()
            self._require_clean_worktree(files)
            self._git(["switch", branch_name], error="git_branch_switch_failed", mutation=True, truncated=True)
            branches = self.branches()
            return {"branches": branches["branches"], "current_branch": branches["current_branch"]}

    def branch_reset(self, commit: str, mode: str = "mixed") -> dict:
        with self._lock:
            self._require_repo()
            reset_mode = self._normalize_reset_mode(mode)
            full_sha = self._resolve_commit_ref(commit)
            head_result = self._git(
                ["symbolic-ref", "--short", "HEAD"],
                allowed=(0, 1),
                error="git_head_probe_failed",
            )
            if head_result["returncode"] or not head_result["stdout"].strip():
                raise RemoteWorkspaceError(409, "git_detached_head", "Cannot reset a detached HEAD")
            _, files, _ = self._status()
            self._require_clean_worktree(files)
            ancestor = self._git(
                ["merge-base", "--is-ancestor", full_sha, "HEAD"],
                allowed=(0, 1),
                error="git_branch_reset_failed",
            )
            if ancestor["returncode"]:
                raise RemoteWorkspaceError(409, "git_commit_not_ancestor", "The target commit is not an ancestor of HEAD")
            self._git(["reset", f"--{reset_mode}", full_sha],
                      error="git_branch_reset_failed", mutation=True, truncated=True)
            overview = self._overview()
            branches = self.branches()
            final_head = self._git(
                ["rev-parse", "--verify", "HEAD^{commit}"],
                allowed=(0, 128),
                error="git_branch_reset_failed",
            )
            if final_head["returncode"] or not final_head["stdout"].strip():
                raise RemoteWorkspaceError(400, "git_branch_reset_failed", "Reset completed without a readable HEAD")
            return {
                "message": "分支已重置",
                "overview": overview,
                "branches": branches["branches"],
                "current_branch": branches["current_branch"],
                "head_commit": final_head["stdout"].strip(),
            }

    def stash_apply(self, ref: str) -> dict:
        stash_ref = self._normalize_stash_ref(ref)
        with self._lock:
            self._require_repo()
            self._require_stash(stash_ref)
            _, files, _ = self._status()
            if self._has_conflict(files):
                raise RemoteWorkspaceError(409, "git_conflict", "The remote worktree contains unresolved conflicts")
            self._stash_mutation(["stash", "apply", stash_ref], error="git_stash_apply_failed")
            return self._overview()

    def stash_drop(self, ref: str) -> dict:
        stash_ref = self._normalize_stash_ref(ref)
        with self._lock:
            self._require_repo()
            self._require_stash(stash_ref)
            self._stash_mutation(["stash", "drop", stash_ref], error="git_stash_drop_failed")
            # A drop leaves the worktree untouched; reread the stash namespace
            # before returning the refreshed overview so stale refs are never
            # inferred from the mutation's exit status.
            self._stash_items()
            return self._overview()

    def stash_pop(self) -> dict:
        with self._lock:
            self._require_repo()
            items = self._stash_items()
            if not items:
                raise RemoteWorkspaceError(404, "git_stash_not_found", "No stash entry exists")
            _, files, _ = self._status()
            if self._has_conflict(files):
                raise RemoteWorkspaceError(409, "git_conflict", "The remote worktree contains unresolved conflicts")
            self._stash_mutation(["stash", "pop"], error="git_stash_pop_failed")
            self._stash_items()
            return self._overview()

    def identity_update(self, *, scope: str, name: object, email: object) -> dict:
        normalized_scope = self._normalize_identity_scope(scope)
        normalized_name = self._normalize_identity_value(name, field="name")
        normalized_email = self._normalize_identity_value(email, field="email")
        with self._lock:
            repo_path = self._repo_root()
            if normalized_scope == "local" and repo_path is None:
                raise RemoteWorkspaceError(409, "not_git_repo", "The remote workspace is not a Git repository")
            self._git(["config", f"--{normalized_scope}", "user.name", normalized_name],
                      error="git_identity_update_failed", mutation=True, truncated=True)
            self._git(["config", f"--{normalized_scope}", "user.email", normalized_email],
                      error="git_identity_update_failed", mutation=True, truncated=True)
            return self.identity()

    def discard(self, paths: list[str]) -> dict:
        normalized = self._paths(paths)
        with self._lock:
            self._require_repo()
            _, files, has_head = self._status(include_original=True)
            self._select(normalized, files)
            if self._has_conflict(files):
                raise RemoteWorkspaceError(409, "git_conflict", "The remote worktree contains unresolved conflicts")
            selected = [item for item in files if item["path"] in set(normalized)]
            self._discard_entries(selected, has_head, error="git_discard_failed")
            return self._overview()

    def discard_all(self) -> dict:
        with self._lock:
            self._require_repo()
            _, files, has_head = self._status(include_original=True)
            if self._has_conflict(files):
                raise RemoteWorkspaceError(409, "git_conflict", "The remote worktree contains unresolved conflicts")
            self._discard_entries(files, has_head, error="git_discard_all_failed")
            return self._overview()

    def init(self) -> dict:
        with self._lock:
            if self._repo_root() is not None:
                return self._overview()
            self._git(["init"], error="git_init_failed", mutation=True, truncated=True)
            try:
                if self._repo_root() is None:
                    raise RemoteWorkspaceError(
                        400, "git_init_failed", "Git initialization did not create a repository at the remote workspace",
                    )
            except RemoteWorkspaceError as exc:
                if exc.code == "git_repo_probe_failed":
                    raise RemoteWorkspaceError(400, "git_init_failed", exc.message, exc.data) from exc
                raise
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
