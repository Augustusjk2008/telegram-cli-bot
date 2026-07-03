from __future__ import annotations

from pathlib import Path

from bot.git_runtime import (
    GIT_FSMONITOR_DISABLED,
    GIT_FSMONITOR_DISABLED_ARG,
    GIT_FSMONITOR_KEY,
    apply_git_fsmonitor_disabled_env,
    build_git_fsmonitor_disabled_command,
)
from bot.native_agent.pi_rpc_client import _base_env
from bot.web import git_service
from bot.web.api_service import _build_cli_env


def _git_config_pairs(env: dict[str, str]) -> list[tuple[str, str]]:
    count = int(str(env.get("GIT_CONFIG_COUNT") or "0").strip() or "0")
    return [
        (env.get(f"GIT_CONFIG_KEY_{index}", ""), env.get(f"GIT_CONFIG_VALUE_{index}", ""))
        for index in range(max(0, count))
    ]


def _assert_fsmonitor_disabled(env: dict[str, str]) -> None:
    assert (GIT_FSMONITOR_KEY, GIT_FSMONITOR_DISABLED) in _git_config_pairs(env)


def test_build_git_fsmonitor_disabled_command_adds_config_override() -> None:
    assert build_git_fsmonitor_disabled_command(["status"]) == [
        "git",
        "-c",
        GIT_FSMONITOR_DISABLED_ARG,
        "status",
    ]


def test_apply_git_fsmonitor_disabled_env_adds_git_config() -> None:
    env: dict[str, str] = {}
    apply_git_fsmonitor_disabled_env(env)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
    assert env["GIT_CONFIG_VALUE_0"] == "false"


def test_apply_git_fsmonitor_disabled_env_updates_existing_key() -> None:
    env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "true",
    }
    apply_git_fsmonitor_disabled_env(env)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_VALUE_0"] == "false"


def test_apply_git_fsmonitor_disabled_env_appends_without_overwriting_existing_config() -> None:
    env = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.proxy",
        "GIT_CONFIG_VALUE_0": "http://127.0.0.1:7890",
        "GIT_CONFIG_KEY_1": "https.proxy",
        "GIT_CONFIG_VALUE_1": "http://127.0.0.1:7890",
    }
    apply_git_fsmonitor_disabled_env(env)
    assert env["GIT_CONFIG_COUNT"] == "3"
    assert env["GIT_CONFIG_KEY_0"] == "http.proxy"
    assert env["GIT_CONFIG_VALUE_0"] == "http://127.0.0.1:7890"
    assert env["GIT_CONFIG_KEY_1"] == "https.proxy"
    assert env["GIT_CONFIG_VALUE_1"] == "http://127.0.0.1:7890"
    assert env["GIT_CONFIG_KEY_2"] == "core.fsmonitor"
    assert env["GIT_CONFIG_VALUE_2"] == "false"


def test_build_cli_env_disables_git_fsmonitor() -> None:
    env = _build_cli_env("codex")
    assert env["CI"] == "true"
    _assert_fsmonitor_disabled(env)


def test_pi_base_env_disables_git_fsmonitor_after_extra_env(tmp_path: Path) -> None:
    pi_home = tmp_path / "pi-home"
    env = _base_env(
        {
            "NATIVE_AGENT_PI_HOME": str(pi_home),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "true",
        }
    )
    assert env["HOME"] == str(pi_home)
    assert env["USERPROFILE"] == str(pi_home)
    _assert_fsmonitor_disabled(env)


def test_git_commit_cli_env_disables_git_fsmonitor() -> None:
    env = git_service._build_git_commit_cli_env()
    _assert_fsmonitor_disabled(env)

