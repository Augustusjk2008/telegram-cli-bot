from __future__ import annotations

import subprocess

import pytest

from bot.web import git_service
from bot.web.api_common import WebApiError


def test_build_git_command_disables_fsmonitor() -> None:
    cmd = git_service._build_git_command(["status"])
    assert cmd[:3] == ["git", "-c", "core.fsmonitor=false"]


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
