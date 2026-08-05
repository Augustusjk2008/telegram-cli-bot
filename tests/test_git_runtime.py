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
