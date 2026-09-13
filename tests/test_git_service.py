from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.web import git_service
from bot.web.api_common import WebApiError


@pytest.mark.asyncio
async def test_generate_git_commit_message_records_codex_terminal_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture = object()
    started: list[tuple[dict[str, str], list[str]]] = []
    recorded: list[tuple[object, object]] = []
    manager = SimpleNamespace(
        get_git_commit_cli_config=lambda _alias: SimpleNamespace(
            cli_type="codex",
            cli_path="codex",
            cli_params=object(),
        )
    )

    monkeypatch.setattr(git_service, "get_profile_or_raise", lambda *_args: object())
    monkeypatch.setattr(git_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(git_service, "build_commit_message_prompt", lambda **_kwargs: "prompt")
    monkeypatch.setattr(git_service, "with_global_extra_args", lambda params, _extra: params)
    monkeypatch.setattr(
        git_service,
        "build_cli_command",
        lambda **_kwargs: (["codex", "exec", "--json"], True),
    )
    monkeypatch.setattr(git_service, "_start_cli_process", lambda *_args, **_kwargs: object())

    async def communicate(_process: object, *, input_text: str | None = None) -> tuple[str, int]:
        assert input_text == "prompt\n"
        return (
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"git-usage-thread"}',
                    '{"type":"item.completed","item":{"type":"assistant_message","text":"<COMMIT_MESSAGE>feat: record git usage</COMMIT_MESSAGE>"}}',
                    '{"type":"turn.completed","usage":{"input_tokens":17,"cached_input_tokens":6,"output_tokens":5,"reasoning_output_tokens":2}}',
                ]
            ),
            0,
        )

    async def start_capture(*, env: dict[str, str], command: list[str]) -> object:
        started.append((env, command))
        return capture

    async def record_capture(current_capture: object, parsed_result: object) -> None:
        recorded.append((current_capture, parsed_result))

    monkeypatch.setattr(git_service, "_communicate_process", communicate)
    monkeypatch.setattr(git_service, "start_codex_rate_limit_capture", start_capture)
    monkeypatch.setattr(git_service, "record_codex_rate_limit_capture", record_capture)

    result = await git_service._generate_git_commit_message_from_context(
        manager,
        "main",
        1001,
        repo_root=str(tmp_path),
        context={},
    )

    assert result == {"message": "feat: record git usage"}
    assert len(started) == 1
    assert started[0][1] == ["codex", "exec", "--json"]
    assert len(recorded) == 1
    assert recorded[0][0] is capture
    parsed_result = recorded[0][1]
    assert parsed_result.session_id == "git-usage-thread"
    assert "feat: record git usage" in parsed_result.final_text


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


def test_bounded_git_process_waits_for_tree_termination_before_return(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    termination_finished = threading.Event()

    class TimedOutProcess:
        def __init__(self) -> None:
            self.stdin = None
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired("git", timeout)
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    process = TimedOutProcess()

    def terminate_tree(current: TimedOutProcess) -> None:
        time.sleep(0.05)
        current.returncode = 1
        termination_finished.set()

    monkeypatch.setattr(git_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(git_service, "terminate_process_tree_sync", terminate_tree)

    result = git_service._run_bounded_process(
        ["git", "add", "-A"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(timeout_seconds=0.01),
    )

    assert result.budget_reason == "timeout"
    assert termination_finished.is_set()


def test_bounded_git_process_uses_attached_process_job_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class TimedOutProcess:
        def __init__(self) -> None:
            self.stdin = None
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired("git", timeout)
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    class ProcessJob:
        def __init__(self, process: TimedOutProcess) -> None:
            self.process = process
            self.terminated = False
            self.closed = False

        def terminate(self) -> None:
            self.terminated = True
            self.process.returncode = 1

        def close(self) -> None:
            self.closed = True

    process = TimedOutProcess()
    process_job = ProcessJob(process)
    fallback_called = False

    def fallback_termination(current: TimedOutProcess) -> None:
        nonlocal fallback_called
        fallback_called = True
        current.returncode = 1

    monkeypatch.setattr(git_service.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(git_service, "attach_process_tree_job", lambda _process: process_job, raising=False)
    monkeypatch.setattr(git_service, "terminate_process_tree_sync", fallback_termination)

    result = git_service._run_bounded_process(
        ["git", "commit", "-m", "message"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(timeout_seconds=0.01),
    )

    assert result.budget_reason == "timeout"
    assert process_job.terminated is True
    assert process_job.closed is True
    assert fallback_called is False


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

    git_service._run_bounded_process(
        ["git", "status"],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(timeout_seconds=1),
    )

    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert process.stdout.closed_while_reading is False
    assert process.stderr.closed_while_reading is False


@pytest.mark.parametrize("with_input", [False, True])
def test_timed_out_index_write_removes_only_lock_created_by_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    with_input: bool,
) -> None:
    repo = tmp_path / ("with-input" if with_input else "without-input")
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    index_lock = git_dir / "index.lock"

    def timed_out_process(*_args, **_kwargs):
        if not index_lock.exists():
            index_lock.write_text("created-by-command", encoding="utf-8")
        on_budget_exceeded = _kwargs.get("on_budget_exceeded")
        if on_budget_exceeded is not None:
            on_budget_exceeded()
        result = subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="")
        result.budget_reason = "timeout"
        return result

    monkeypatch.setattr(git_service, "_run_bounded_process", timed_out_process)

    with pytest.raises(git_service.GitCommandError, match="timeout"):
        if with_input:
            git_service._run_git_with_input(str(repo), ["commit", "-F", "-"], input_text="message")
        else:
            git_service._run_git(str(repo), ["add", "-A"])

    assert index_lock.exists() is False

    index_lock.write_text("pre-existing", encoding="utf-8")
    with pytest.raises(git_service.GitCommandError, match="timeout"):
        if with_input:
            git_service._run_git_with_input(str(repo), ["commit", "-F", "-"], input_text="message")
        else:
            git_service._run_git(str(repo), ["add", "-A"])

    assert index_lock.read_text(encoding="utf-8") == "pre-existing"


def test_git_commands_for_same_repo_do_not_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def bounded_process(*_args, **_kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
            is_first = active == 1 and not first_started.is_set()
        if is_first:
            first_started.set()
            assert release_first.wait(timeout=1)
        with state_lock:
            active -= 1
        result = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
        result.budget_reason = ""
        return result

    monkeypatch.setattr(git_service, "_run_bounded_process", bounded_process)

    first = threading.Thread(target=git_service._run_git, args=(str(tmp_path), ["status"]))
    second = threading.Thread(target=git_service._run_git, args=(str(tmp_path), ["status"]))
    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    time.sleep(0.05)
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert first.is_alive() is False
    assert second.is_alive() is False
    assert max_active == 1


def test_git_status_disables_optional_index_locks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_env: dict[str, str] | None = None

    def bounded_process(*_args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs["env"]
        result = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
        result.budget_reason = ""
        return result

    monkeypatch.setattr(git_service, "_run_bounded_process", bounded_process)

    git_service._run_git(str(tmp_path), ["status", "--porcelain=v2"])

    assert captured_env is not None
    assert captured_env["GIT_OPTIONAL_LOCKS"] == "0"


def test_index_write_uses_longer_timeout_than_read_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_timeouts: list[float] = []

    def bounded_process(*_args, **kwargs):
        captured_timeouts.append(kwargs["profile"].timeout_seconds)
        result = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
        result.budget_reason = ""
        return result

    monkeypatch.setattr(git_service, "_run_bounded_process", bounded_process)

    git_service._run_git(str(tmp_path), ["status", "--short"])
    git_service._run_git(str(tmp_path), ["add", "-A"])

    assert captured_timeouts[1] > captured_timeouts[0]


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


def test_git_status_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_service, "GIT_CACHE_MAX_REPOSITORIES", 2)
    monkeypatch.setattr(git_service, "_GIT_STATUS_CACHE", {})
    monkeypatch.setattr(git_service, "_GIT_RECENT_COMMITS_CACHE", {})

    git_service._write_git_status_cache("repo-1", {"created_at": 1.0})
    git_service._write_git_status_cache("repo-2", {"created_at": 2.0})
    git_service._write_git_status_cache("repo-3", {"created_at": 3.0})

    assert [Path(key).name for key in git_service._GIT_STATUS_CACHE] == ["repo-2", "repo-3"]
    assert git_service.git_service_diagnostics()["status_cache_entries"] == 2


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
def _create_repo_with_large_unstaged_diff(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    tracked_files = [
        repo / name
        for name in ["alpha.txt", "beta.txt", "gamma.txt", "delta [1].txt"]
    ]
    for tracked in tracked_files:
        tracked.write_text(("before-" + "x" * 80 + "\n") * 5_000, encoding="utf-8")
    subprocess.run(["git", "add", *[path.name for path in tracked_files]], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    for tracked in tracked_files:
        tracked.write_text(("after-" + "y" * 80 + "\n") * 5_000, encoding="utf-8")
    return repo, tracked_files[0]


def _use_small_git_stdout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git_service,
        "_GIT_LOCAL_PROFILE",
        git_service._GitCommandProfile(
            timeout_seconds=5,
            stdout_max_bytes=512,
            stderr_max_bytes=64 * 1024,
        ),
    )


@pytest.mark.parametrize(
    "read_context",
    [
        git_service._read_git_commit_message_context,
        git_service._read_git_smart_commit_message_context,
    ],
    ids=["generate", "smart-commit"],
)
def test_commit_message_context_uses_truncated_diff_when_stdout_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    read_context,
) -> None:
    repo, _tracked = _create_repo_with_large_unstaged_diff(tmp_path)
    _use_small_git_stdout_budget(monkeypatch)

    context = read_context(str(repo))

    assert context["diff_truncated"] is True
    for name in ["alpha.txt", "beta.txt", "gamma.txt", "delta [1].txt"]:
        assert f"diff --git a/{name} b/{name}" in context["diff_text"]


def test_git_worktree_snapshot_hashes_oversized_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo, _tracked = _create_repo_with_large_unstaged_diff(tmp_path)
    tail = repo / "z-tail.txt"
    tail.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "z-tail.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add tail"], cwd=repo, check=True, capture_output=True)
    tail.write_text("after\n", encoding="utf-8")
    _use_small_git_stdout_budget(monkeypatch)

    before_prefix, before_truncated = git_service._read_git_commit_message_diff(
        str(repo),
        ["diff", "--find-renames"],
    )
    before = git_service._build_git_worktree_snapshot(str(repo))
    tail.write_text("later\n", encoding="utf-8")
    after_prefix, after_truncated = git_service._read_git_commit_message_diff(
        str(repo),
        ["diff", "--find-renames"],
    )
    after = git_service._build_git_worktree_snapshot(str(repo))

    assert before_truncated is True
    assert after_truncated is True
    assert before_prefix == after_prefix
    assert before != after


def test_smart_commit_keeps_all_scope_summaries_and_untracked_sample(
    tmp_path: Path,
) -> None:
    repo, _tracked = _create_repo_with_large_unstaged_diff(tmp_path)
    subprocess.run(["git", "add", "alpha.txt"], cwd=repo, check=True)
    (repo / "omega.txt").write_text("UNTRACKED_SENTINEL\n", encoding="utf-8")

    context = git_service._read_git_smart_commit_message_context(str(repo))

    assert "=== STAGED FILE STATS ===" in context["diff_text"]
    assert "=== UNSTAGED FILE STATS ===" in context["diff_text"]
    assert "=== UNTRACKED FILES ===" in context["diff_text"]
    assert "omega.txt" in context["diff_text"]
    assert "UNTRACKED_SENTINEL" in context["diff_text"]


def test_commit_message_diff_preserves_staged_rename_pair(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    old_path = repo / "old [x].txt"
    old_path.write_text("same content\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", old_path.name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    old_path.rename(repo / "new ![x].txt")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    context = git_service._read_git_commit_message_context(str(repo))

    assert "similarity index" in context["diff_text"]
    assert "rename from old [x].txt" in context["diff_text"]
    assert "rename to new ![x].txt" in context["diff_text"]
    assert "new file mode" not in context["diff_text"]


def test_commit_message_diff_uses_global_file_sample_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    tracked_files = [repo / f"tracked-{index:02d}.txt" for index in range(33)]
    for path in tracked_files:
        path.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    for path in tracked_files:
        path.write_text("after\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    context = git_service._read_git_commit_message_context(str(repo))

    assert context["diff_text"].count("\ndiff --git ") == 32
    assert context["diff_text"].count("change scope: untracked") == 1
    assert "tracked-00.txt" in context["diff_text"]
    assert "tracked-32.txt" in context["diff_text"]

    subprocess.run(
        ["git", "add", *[path.name for path in tracked_files[:16]]],
        cwd=repo,
        check=True,
    )
    smart_context = git_service._read_git_smart_commit_message_context(str(repo))

    assert smart_context["diff_text"].count("\ndiff --git ") == 32
    assert smart_context["diff_text"].count("change scope: staged") == 16
    assert smart_context["diff_text"].count("change scope: unstaged") == 15
    assert smart_context["diff_text"].count("change scope: untracked") == 1


@pytest.mark.parametrize(
    ("budget_reason", "budget_exceeded_streams", "expected_reason"),
    [
        ("timeout", (), "timeout"),
        ("stderr_bytes", ("stderr",), "stderr_bytes"),
        ("stdout_bytes", ("stdout", "stderr"), "stderr_bytes"),
    ],
)
def test_stdout_truncation_keeps_hard_budget_failures(
    monkeypatch: pytest.MonkeyPatch,
    budget_reason: str,
    budget_exceeded_streams: tuple[str, ...],
    expected_reason: str,
) -> None:
    result = SimpleNamespace(
        stdout="partial diff",
        stderr="partial error",
        returncode=-1,
        budget_reason=budget_reason,
        budget_exceeded_streams=budget_exceeded_streams,
    )
    monkeypatch.setattr(git_service, "_run_git_process", lambda *_args, **_kwargs: result)

    with pytest.raises(git_service.GitCommandError, match=expected_reason):
        git_service._run_git(
            "C:/repo",
            ["diff"],
            check=False,
            allow_stdout_truncation=True,
        )


def test_bounded_process_prioritizes_stderr_when_both_streams_exceed(
    tmp_path: Path,
) -> None:
    child_code = (
        "import os,threading,time;"
        "a=threading.Thread(target=os.write,args=(1,bytes(65536)));"
        "b=threading.Thread(target=os.write,args=(2,bytes(65536)));"
        "a.start();b.start();a.join();b.join();time.sleep(1)"
    )

    result = git_service._run_bounded_process(
        [sys.executable, "-c", child_code],
        cwd=str(tmp_path),
        env=None,
        profile=git_service._GitCommandProfile(
            timeout_seconds=0.5,
            stdout_max_bytes=128,
            stderr_max_bytes=128,
        ),
    )

    assert result.budget_reason == "stderr_bytes"
    assert result.budget_exceeded_streams == ("stdout", "stderr")


def test_get_git_diff_requests_full_file_context(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(git_service, "_require_repo_root", lambda *_args: ("C:/repo", "C:/repo"))

    def run_git(repo_root: str, args: list[str]) -> SimpleNamespace:
        calls.append((repo_root, args))
        return SimpleNamespace(stdout="@@ -1 +1 @@\n-old\n+new\n")

    monkeypatch.setattr(git_service, "_run_git", run_git)

    result = git_service.get_git_diff(object(), "main", 123, "src/app.py")

    assert calls == [
        ("C:/repo", ["diff", "--no-color", "--unified=2147483647", "--", "src/app.py"]),
    ]
    assert result["diff"] == "@@ -1 +1 @@\n-old\n+new\n"


def test_changed_file_stats_fall_back_when_numstat_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_budget_error(*_args: object, **_kwargs: object) -> None:
        raise git_service.GitCommandError("Git 命令超过资源预算: timeout")

    monkeypatch.setattr(git_service, "_run_git", raise_budget_error)

    changed_file = {
        "path": "tracked.txt",
        "status": " M",
        "staged": False,
        "unstaged": True,
        "untracked": False,
    }

    assert git_service._merge_changed_file_stats("C:/repo", [changed_file]) == [
        {
            **changed_file,
            "additions": 0,
            "deletions": 0,
            "staged_additions": 0,
            "staged_deletions": 0,
            "unstaged_additions": 0,
            "unstaged_deletions": 0,
        }
    ]
