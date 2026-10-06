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
            return build_git_capabilities(
                available={
                    "tree_status": True,
                    "commit_graph": True,
                    "branches": True,
                    "stash": True,
                    "identity": True,
                },
                reason="remote_feature_unavailable",
            )

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
            raw = self._git([
                "stash", "list", "--format=%gd%x00%H%x00%ci%x00%gs%x00",
            ], error="git_stash_list_failed")["stdout"]
            items = [
                {"ref": ref, "hash": full_hash[:12], "created_at": created_at, "message": message}
                for ref, full_hash, created_at, message in self._parse_nul_fields(raw, 4)
            ]
            return {"items": items}

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
