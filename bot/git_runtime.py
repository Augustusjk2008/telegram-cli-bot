from __future__ import annotations

from collections.abc import MutableMapping

GIT_FSMONITOR_KEY = "core.fsmonitor"
GIT_FSMONITOR_DISABLED = "false"
GIT_FSMONITOR_DISABLED_ARG = f"{GIT_FSMONITOR_KEY}={GIT_FSMONITOR_DISABLED}"


def build_git_fsmonitor_disabled_command(args: list[str]) -> list[str]:
    return ["git", "-c", GIT_FSMONITOR_DISABLED_ARG, *args]


def apply_git_fsmonitor_disabled_env(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    raw_count = str(env.get("GIT_CONFIG_COUNT") or "0").strip()
    try:
        count = int(raw_count)
    except ValueError:
        count = 0

    for index in range(max(0, count)):
        if env.get(f"GIT_CONFIG_KEY_{index}") == GIT_FSMONITOR_KEY:
            env[f"GIT_CONFIG_VALUE_{index}"] = GIT_FSMONITOR_DISABLED
            return env

    index = max(0, count)
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    env[f"GIT_CONFIG_KEY_{index}"] = GIT_FSMONITOR_KEY
    env[f"GIT_CONFIG_VALUE_{index}"] = GIT_FSMONITOR_DISABLED
    return env
