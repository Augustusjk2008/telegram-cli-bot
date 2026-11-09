from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bot.web import git_service
from bot.web.api_common import WebApiError
from bot.web.github_service import build_github_git_auth_config


TOKEN = "ghp_" + "Q" * 36


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    monkeypatch.setattr(git_service, "_get_git_working_dir", lambda _manager, _alias: str(work))
    return work, bare


def _capabilities():
    payload = git_service.get_git_capabilities(None, "main", 1)["capabilities"]
    return {name: payload[name]["available"] for name in ("fetch", "pull", "push", "remotes", "publish")}


def _error(call) -> WebApiError:
    with pytest.raises(WebApiError) as exc:
        call()
    return exc.value


def test_remote_management_validates_input_and_redacts_credentials(repo):
    work, bare = repo
    added = git_service.add_git_remote(None, "main", 1, "origin", "git@github.com:octo/demo.git")
    assert [(item["name"], item["protocol"], item["github"]["full_name"]) for item in added["remotes"]] == [
        ("origin", "ssh", "octo/demo"),
    ]
    assert added["github_account_auth"] is True

    assert _error(lambda: git_service.add_git_remote(None, "main", 1, "origin", "https://x.test/r")).code == "git_remote_exists"
    for name, url, code in (
        ("-upload-pack=touch", "https://github.com/octo/demo.git", "invalid_git_remote_name"),
        ("bad name", "https://github.com/octo/demo.git", "invalid_git_remote_name"),
        ("x", "ext::sh -c touch", "invalid_git_remote_url"),
        ("x", "--upload-pack=touch", "invalid_git_remote_url"),
        ("x", "https://alice:secret@github.com/octo/demo.git", "git_remote_url_has_credentials"),
        ("x", f"https://{TOKEN}@github.com/octo/demo.git", "git_remote_url_has_credentials"),
    ):
        assert _error(lambda: git_service.add_git_remote(None, "main", 1, name, url)).code == code
    assert _git(work, "remote") == "origin"

    # Remotes created outside Orbit may carry credentials; they are never echoed.
    _git(work, "remote", "add", "legacy", "https://alice:secret@github.com/octo/demo.git")
    _git(work, "remote", "set-url", "--push", "origin", "https://example.com/old-push.git")
    listed = git_service.list_git_remotes(None, "main", 1)
    legacy = next(item for item in listed["remotes"] if item["name"] == "legacy")
    assert legacy["fetch_url"] == "https://github.com/octo/demo.git"
    assert legacy["has_embedded_credentials"] is True
    assert "secret" not in json.dumps(listed)

    updated = git_service.update_git_remote_url(None, "main", 1, "origin", f"file://{bare.as_posix()}")
    origin = next(item for item in updated["remotes"] if item["name"] == "origin")
    assert origin["fetch_url"] == origin["push_url"] == f"file://{bare.as_posix()}"

    assert _error(lambda: git_service.remove_git_remote(None, "main", 1, "missing")).code == "git_remote_not_found"
    removed = git_service.remove_git_remote(None, "main", 1, "legacy")
    assert [item["name"] for item in removed["remotes"]] == ["origin"]


def test_publish_sets_upstream_and_enables_push_and_pull(repo):
    work, bare = repo
    git_service.add_git_remote(None, "main", 1, "origin", f"file://{bare.as_posix()}")
    assert _capabilities() == {"fetch": True, "pull": False, "push": False, "remotes": True, "publish": True}
    assert _error(lambda: git_service.publish_git_branch(None, "main", 1, "origin")).code == "git_no_commits"

    _git(work, "-c", "user.name=Dev", "-c", "user.email=dev@example.com", "commit", "--allow-empty", "-m", "init")
    overview = git_service.publish_git_branch(None, "main", 1, "origin")

    assert overview["current_branch"] == "main"
    assert _git(work, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") == "origin/main"
    assert _git(bare, "rev-parse", "main") == _git(work, "rev-parse", "HEAD")
    assert _capabilities() == {name: True for name in ("fetch", "pull", "push", "remotes", "publish")}
    assert git_service.list_git_remotes(None, "main", 1)["upstream"] == "origin/main"

    _git(work, "checkout", "-q", "--detach")
    assert _error(lambda: git_service.publish_git_branch(None, "main", 1, "origin")).code == "git_detached_head"


def test_publish_passes_account_credentials_through_the_environment_only(repo, monkeypatch):
    work, bare = repo
    git_service.add_git_remote(None, "main", 1, "origin", f"file://{bare.as_posix()}")
    _git(work, "-c", "user.name=Dev", "-c", "user.email=dev@example.com", "commit", "--allow-empty", "-m", "init")
    captured = []
    original = git_service._run_bounded_process

    def recording(command, **kwargs):
        captured.append((list(command), dict(kwargs.get("env") or {})))
        return original(command, **kwargs)

    monkeypatch.setattr(git_service, "_run_bounded_process", recording)

    git_service.publish_git_branch(
        None, "main", 1, "origin",
        auth_config=build_github_git_auth_config("octocat", TOKEN),
    )

    command, env = next(item for item in captured if "push" in item[0])
    assert command[-5:] == ["push", "--set-upstream", "--", "origin", "refs/heads/main:refs/heads/main"]
    assert not any(TOKEN in part for part in command)
    header_values = [value for key, value in env.items() if key.startswith("GIT_CONFIG_VALUE_") and value.startswith("Authorization:")]
    assert len(header_values) == 1
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_github_auth_failures_explain_the_connected_account():
    auth = build_github_git_auth_config("octocat", TOKEN)
    rejected = git_service.GitCommandError(
        "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
    )
    assert "GitHub 账号" in git_service._git_network_error_message(rejected, auth)
    assert "GitHub 账号" not in git_service._git_network_error_message(rejected, ())
    other_host = git_service.GitCommandError("fatal: Authentication failed for 'https://gitlab.com/x/y.git/'")
    assert "GitHub 账号" not in git_service._git_network_error_message(other_host, auth)
