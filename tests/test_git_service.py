from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.web import git_service


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
