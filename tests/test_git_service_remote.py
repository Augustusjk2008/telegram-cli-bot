from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from bot.web import git_service


GitRemoteAction = Callable[[Any, str, int], dict[str, Any]]


def _stub_git_remote_action(
    monkeypatch: pytest.MonkeyPatch,
    repo_dir: Path,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        git_service,
        "_require_repo_root",
        lambda manager, alias, user_id: (str(repo_dir), str(repo_dir)),
    )
    monkeypatch.setattr(git_service, "_invalidate_git_status_cache", lambda repo_root: None)
    monkeypatch.setattr(
        git_service,
        "_build_git_overview",
        lambda working_dir, repo_root: {"repo_path": repo_root},
    )

    def fake_run_git(
        repo_root: str,
        args: list[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        captured["repo_root"] = repo_root
        captured["args"] = args
        captured["check"] = check
        captured["env"] = env
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(git_service, "_run_git", fake_run_git)
    return captured


def test_fetch_git_remote_accepts_first_ssh_host_key(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    monkeypatch.delenv("GIT_SSH", raising=False)
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setattr(git_service, "_get_configured_git_ssh_command", lambda repo_root: "")
    captured = _stub_git_remote_action(monkeypatch, temp_dir)

    result = git_service.fetch_git_remote(object(), "main", 1001)

    assert result == {"repo_path": str(temp_dir)}
    assert captured["args"] == ["fetch", "--all", "--prune"]
    assert captured["env"]["GIT_SSH_COMMAND"] == "ssh -o StrictHostKeyChecking=accept-new"


@pytest.mark.parametrize(
    ("action", "expected_args"),
    [
        (git_service.pull_git_remote, ["pull", "--ff-only"]),
        (git_service.push_git_remote, ["push"]),
    ],
)
def test_remote_git_actions_extend_existing_ssh_command(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
    action: GitRemoteAction,
    expected_args: list[str],
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i ~/.ssh/work_key")
    monkeypatch.setattr(git_service, "_get_configured_git_ssh_command", lambda repo_root: "")
    captured = _stub_git_remote_action(monkeypatch, temp_dir)

    action(object(), "main", 1001)

    assert captured["args"] == expected_args
    assert captured["env"]["GIT_SSH_COMMAND"] == (
        "ssh -i ~/.ssh/work_key -o StrictHostKeyChecking=accept-new"
    )


def test_git_remote_env_keeps_explicit_strict_host_key_setting(
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -o stricthostkeychecking=no")
    monkeypatch.setattr(git_service, "_get_configured_git_ssh_command", lambda repo_root: "")

    env = git_service._build_git_remote_env(str(temp_dir))

    assert env["GIT_SSH_COMMAND"] == "ssh -o stricthostkeychecking=no"


