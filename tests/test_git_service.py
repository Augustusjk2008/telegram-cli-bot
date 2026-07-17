from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bot.web import git_service
from bot.web.api_common import WebApiError


def test_build_git_command_disables_fsmonitor() -> None:
    cmd = git_service._build_git_command(["status"])
    assert cmd[:3] == ["git", "-c", "core.fsmonitor=false"]


def test_bounded_git_process_stops_at_stdout_budget(tmp_path) -> None:
    result = git_service._run_bounded_process(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(
            timeout_seconds=2,
            stdout_max_bytes=128,
            stderr_max_bytes=128,
        ),
    )

    assert result.budget_reason == "stdout_bytes"
    assert len(result.stdout.encode("utf-8")) <= 128


def test_bounded_git_process_stops_at_timeout(tmp_path) -> None:
    result = git_service._run_bounded_process(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(
            timeout_seconds=0.05,
            stdout_max_bytes=128,
            stderr_max_bytes=128,
        ),
    )

    assert result.budget_reason == "timeout"


def test_bounded_git_process_deadline_includes_blocked_stdin_write(tmp_path) -> None:
    started_at = time.monotonic()
    result = git_service._run_bounded_process(
        [sys.executable, "-c", "import time; time.sleep(0.4)"],
        cwd=str(tmp_path),
        env=None,
        input_text="x" * (5 * 1024 * 1024),
        profile=git_service._GitCommandProfile(
            timeout_seconds=0.05,
            stdout_max_bytes=128,
            stderr_max_bytes=128,
        ),
    )

    assert time.monotonic() - started_at < 0.3
    assert result.budget_reason == "timeout"


def test_bounded_git_process_drains_readers_before_closing_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_finished = threading.Event()

    class DelayedEofStream:
        def __init__(self) -> None:
            self.read_started = threading.Event()
            self.reading = threading.Event()
            self.closed = False
            self.closed_while_reading = False

        def read(self, _size: int) -> bytes:
            self.read_started.set()
            self.reading.set()
            try:
                assert process_finished.wait(timeout=1)
                time.sleep(0.04)
                return b""
            finally:
                self.reading.clear()

        def close(self) -> None:
            self.closed_while_reading = self.reading.is_set()
            self.closed = True

    class DelayedEofProcess:
        def __init__(self) -> None:
            self.stdin = None
            self.stdout = DelayedEofStream()
            self.stderr = DelayedEofStream()
            self.returncode = 0

        def poll(self) -> int:
            assert self.stdout.read_started.wait(timeout=1)
            assert self.stderr.read_started.wait(timeout=1)
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            process_finished.set()
            return self.returncode

        def kill(self) -> None:
            self.returncode = 1
            process_finished.set()

    process = DelayedEofProcess()
    monkeypatch.setattr(git_service.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = git_service._run_bounded_process(
        ["git", "status"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(timeout_seconds=1),
    )

    assert result.returncode == 0
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert process.stdout.closed_while_reading is False
    assert process.stderr.closed_while_reading is False


def test_bounded_git_process_suppresses_reader_errors_during_forced_stream_close(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    thread_errors: list[BaseException] = []

    class CloseInterruptedStream:
        def __init__(self) -> None:
            self.read_started = threading.Event()
            self.closed = threading.Event()

        def read(self, _size: int) -> bytes:
            self.read_started.set()
            assert self.closed.wait(timeout=1)
            raise ValueError("I/O operation on closed file")

        def close(self) -> None:
            self.closed.set()

    class CompletedProcessWithBlockedReaders:
        def __init__(self) -> None:
            self.stdin = None
            self.stdout = CloseInterruptedStream()
            self.stderr = CloseInterruptedStream()
            self.returncode = 0

        def poll(self) -> int:
            assert self.stdout.read_started.wait(timeout=1)
            assert self.stderr.read_started.wait(timeout=1)
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return self.returncode

        def kill(self) -> None:
            self.returncode = 1

    process = CompletedProcessWithBlockedReaders()
    monkeypatch.setattr(git_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_value))

    git_service._run_bounded_process(
        ["git", "status"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(timeout_seconds=1),
    )

    assert thread_errors == []


def test_real_porcelain_v2_z_parses_rename_and_space_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    old_path = repo / "old name.txt"
    old_path.write_text("same content\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", old_path.name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    old_path.rename(repo / "new name.txt")
    (repo / "untracked file.txt").write_text("new\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A", "--", "old name.txt", "new name.txt"], cwd=repo, check=True)

    raw = git_service._run_git_status_command_with_retry(
        str(repo),
        ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=no"],
    ).stdout
    header, tree_lines = git_service._parse_porcelain_v2_z(raw)
    snapshot = git_service._build_repo_status_snapshot(str(repo))

    assert "\x00" in raw
    assert header.startswith("## ")
    assert tree_lines == ["R  new name.txt"]
    assert "?? untracked file.txt" in snapshot["tree_lines"]


def test_get_git_tree_status_includes_ignored_files_and_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / ".gitignore").write_text("ignored-dir/\n*.log\n", encoding="utf-8")
    (repo / "ignored-dir").mkdir()
    (repo / "ignored-dir" / "nested.txt").write_text("ignored\n", encoding="utf-8")
    (repo / "ignored.log").write_text("ignored\n", encoding="utf-8")
    (repo / "visible.txt").write_text("visible\n", encoding="utf-8")
    monkeypatch.setattr(git_service, "_get_git_working_dir", lambda _manager, _alias: str(repo))

    status = git_service.get_git_tree_status(object(), "main", 1)

    assert status["items"]["ignored-dir"] == "ignored"
    assert status["items"]["ignored.log"] == "ignored"
    assert status["items"]["visible.txt"] == "added"


def test_git_status_command_retries_transient_index_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run_git(repo_root: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if len(calls) == 1:
            raise git_service.GitCommandError("fatal: index file open failed: Permission denied")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="## main\n", stderr="")

    monkeypatch.setattr(git_service, "_run_git", fake_run_git)
    monkeypatch.setattr(git_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = git_service._run_git_status_command_with_retry("repo", ["status", "--porcelain=1", "--branch"])

    assert result.stdout == "## main\n"
    assert calls == [["status", "--porcelain=1", "--branch"], ["status", "--porcelain=1", "--branch"]]
    assert sleeps == [0.15]


def test_git_status_command_converts_repeated_index_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_git(repo_root: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        raise git_service.GitCommandError("unable to create .git/index.lock: File exists")

    monkeypatch.setattr(git_service, "_run_git", fake_run_git)
    monkeypatch.setattr(git_service.time, "sleep", lambda _seconds: None)

    with pytest.raises(WebApiError) as exc_info:
        git_service._run_git_status_command_with_retry("repo", ["status", "--porcelain=1", "--branch"])

    assert exc_info.value.status == 409
    assert exc_info.value.code == "git_index_busy"
    assert exc_info.value.message == "Git 索引暂时被其它进程占用，请稍后重试"


def test_git_status_text_preserves_non_transient_check_false_result(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    def fake_run_git(repo_root: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        assert check is False
        return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(git_service, "_run_git", fake_run_git)
    monkeypatch.setattr(git_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert git_service._read_git_status_text_with_retry("repo", ["status", "--short"]) == ""
    assert sleeps == []


def test_build_repo_status_snapshot_rechecks_cache_after_repo_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = {
        "created_at": 1.0,
        "head_token": "head",
        "index_token": (1, 1),
        "branch_lines": ["## main"],
        "tree_lines": [],
        "status_path_token": (),
    }
    reads: list[str] = []

    def fake_read_fresh_cache(repo_root: str) -> tuple[dict[str, object] | None, str, tuple[int, int]]:
        reads.append(repo_root)
        if len(reads) == 1:
            return None, "head", (1, 1)
        return cached, "head", (1, 1)

    def fail_status_command(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("status command should not run after cache is populated under the repo lock")

    monkeypatch.setattr(git_service, "_read_fresh_git_status_cache", fake_read_fresh_cache)
    monkeypatch.setattr(git_service, "_run_git_status_command_with_retry", fail_status_command)

    assert git_service._build_repo_status_snapshot("repo") is cached
    assert reads == ["repo", "repo"]


def test_build_repo_status_snapshot_caches_clean_repo_and_uses_one_status_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    cache: dict[str, object] = {}

    monkeypatch.setattr(git_service, "_read_fresh_git_status_cache", lambda _repo_root: (cache or None, "head", (1, 1)))
    monkeypatch.setattr(git_service, "_write_git_status_cache", lambda _repo_root, entry: cache.update(entry))

    def fake_status(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        assert repo_root == "repo"
        calls.append(args)
        if args[0] == "status":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="# branch.oid abc\x00# branch.head main\x00",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_service, "_run_git_status_command_with_retry", fake_status)

    first = git_service._build_repo_status_snapshot("repo")
    second = git_service._build_repo_status_snapshot("repo")

    assert first["branch_lines"] == ["## main"]
    assert first["tree_lines"] == []
    assert second["branch_lines"] == ["## main"]
    assert len(calls) == 2
    assert "--branch" in calls[0]
    assert "--untracked-files=no" in calls[0]
    assert calls[1][:2] == ["ls-files", "--others"]


def test_build_repo_status_snapshot_bounds_untracked_and_marks_uncertain_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(git_service, "GIT_OVERVIEW_CHANGED_FILES_LIMIT", 2)
    monkeypatch.setattr(git_service, "_read_fresh_git_status_cache", lambda _root: (None, "head", (1, 1)))
    monkeypatch.setattr(git_service, "_write_git_status_cache", lambda _root, _entry: None)

    def fake_status(_repo_root: str, args: list[str]):
        if args[0] == "status":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="# branch.oid abc\x00# branch.head main\x001 .M N... 100644 100644 100644 a b tracked.py\x00",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="u1.txt\x00u2.txt\x00u3.txt\x00",
            stderr="",
        )

    monkeypatch.setattr(git_service, "_run_git_status_command_with_retry", fake_status)
    snapshot = git_service._build_repo_status_snapshot("repo")

    assert snapshot["branch_lines"][1] == " M tracked.py"
    assert snapshot["untracked_files_truncated"] is True
    assert snapshot["count_exact"] is False
    assert snapshot["count_lower_bound"] == 3
    assert snapshot["truncation_reason"] == "untracked_limit"


def test_list_recent_commits_reuses_head_scoped_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(git_service, "_GIT_RECENT_COMMITS_CACHE", {})
    monkeypatch.setattr(git_service, "_read_git_head_token", lambda _repo_root: "head-1")

    def fake_run_git(repo_root: str, args: list[str], *, check: bool = True):
        assert repo_root == "repo"
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="abc\x1fabc\x1fAlice\x1f2026-07-10\x1fsubject\x1fbody\x1e",
            stderr="",
        )

    monkeypatch.setattr(git_service, "_run_git", fake_run_git)

    first = git_service._list_recent_commits("repo")
    second = git_service._list_recent_commits("repo")

    assert first == second
    assert len(calls) == 1


def test_parse_git_numstat_counts_text_and_binary_fallback() -> None:
    stats = git_service._parse_git_numstat(
        "\n".join(
            [
                "3\t2\tsrc/a.py",
                "-\t-\tassets/logo.png",
                "5\t1\told => new.txt",
                "4\t0\tsrc/{old => new}.py",
            ]
        )
    )

    assert stats["src/a.py"] == {"additions": 3, "deletions": 2}
    assert stats["assets/logo.png"] == {"additions": 0, "deletions": 0}
    assert stats["new.txt"] == {"additions": 5, "deletions": 1}
    assert stats["src/new.py"] == {"additions": 4, "deletions": 0}


def test_build_git_overview_merges_staged_unstaged_and_untracked_stats(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "new.txt").write_text("first\nsecond\n", encoding="utf-8")

    def fake_snapshot(repo_root: str) -> dict[str, object]:
        assert repo_root == str(repo)
        return {
            "branch_lines": [
                "## main...origin/main [ahead 1, behind 2]",
                "M  staged.py",
                " M worktree.py",
                "MM both.py",
                "?? new.txt",
            ],
            "tree_lines": [],
        }

    def fake_numstat(repo_root: str, args: list[str]) -> dict[str, dict[str, int]]:
        assert repo_root == str(repo)
        if "--cached" in args:
            return {
                "staged.py": {"additions": 4, "deletions": 1},
                "both.py": {"additions": 2, "deletions": 0},
            }
        return {
            "worktree.py": {"additions": 1, "deletions": 3},
            "both.py": {"additions": 5, "deletions": 6},
        }

    monkeypatch.setattr(git_service, "_build_repo_status_snapshot", fake_snapshot)
    monkeypatch.setattr(git_service, "_read_git_numstat", fake_numstat)
    monkeypatch.setattr(git_service, "_list_recent_commits", lambda _repo_root: [])

    overview = git_service._build_git_overview(str(repo), str(repo))
    files = {item["path"]: item for item in overview["changed_files"]}

    def stats_for(path: str) -> dict[str, int]:
        return {
            "additions": files[path]["additions"],
            "deletions": files[path]["deletions"],
            "staged_additions": files[path]["staged_additions"],
            "staged_deletions": files[path]["staged_deletions"],
            "unstaged_additions": files[path]["unstaged_additions"],
            "unstaged_deletions": files[path]["unstaged_deletions"],
        }

    assert overview["current_branch"] == "main"
    assert overview["ahead_count"] == 1
    assert overview["behind_count"] == 2
    assert stats_for("staged.py") == {
        "additions": 4,
        "deletions": 1,
        "staged_additions": 4,
        "staged_deletions": 1,
        "unstaged_additions": 0,
        "unstaged_deletions": 0,
    }
    assert stats_for("worktree.py") == {
        "additions": 1,
        "deletions": 3,
        "staged_additions": 0,
        "staged_deletions": 0,
        "unstaged_additions": 1,
        "unstaged_deletions": 3,
    }
    assert stats_for("both.py") == {
        "additions": 7,
        "deletions": 6,
        "staged_additions": 2,
        "staged_deletions": 0,
        "unstaged_additions": 5,
        "unstaged_deletions": 6,
    }
    assert stats_for("new.txt") == {
        "additions": 2,
        "deletions": 0,
        "staged_additions": 0,
        "staged_deletions": 0,
        "unstaged_additions": 2,
        "unstaged_deletions": 0,
    }


def test_merge_changed_file_stats_skips_irrelevant_numstat_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_numstat(_repo_root: str, args: list[str]) -> dict[str, dict[str, int]]:
        calls.append(args)
        return {"staged.py": {"additions": 1, "deletions": 0}}

    monkeypatch.setattr(git_service, "_read_git_numstat", fake_numstat)

    merged = git_service._merge_changed_file_stats(
        "repo",
        [
            {
                "path": "staged.py",
                "status": "M ",
                "staged": True,
                "unstaged": False,
                "untracked": False,
            }
        ],
    )

    assert merged[0]["staged_additions"] == 1
    assert calls == [["diff", "--cached", "--numstat", "--"]]


def test_build_git_overview_marks_changed_files_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_service, "GIT_OVERVIEW_CHANGED_FILES_LIMIT", 2)
    monkeypatch.setattr(
        git_service,
        "_build_repo_status_snapshot",
        lambda _repo_root: {
            "branch_lines": ["## main", " M a.py", " M b.py", " M c.py"],
            "tree_lines": [],
        },
    )
    monkeypatch.setattr(git_service, "_merge_changed_file_stats", lambda _repo_root, files: files)
    monkeypatch.setattr(git_service, "_list_recent_commits", lambda _repo_root: [])

    overview = git_service._build_git_overview("repo", "repo")

    assert [item["path"] for item in overview["changed_files"]] == ["a.py", "b.py"]
    assert overview["changed_files_truncated"] is True
    assert overview["changed_files_total_estimate"] == 3
