from __future__ import annotations

from collections.abc import Iterable, MutableMapping

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


def append_git_config_env(
    env: MutableMapping[str, str],
    entries: Iterable[tuple[str, str]],
) -> MutableMapping[str, str]:
    """Append command-scope Git config through the environment.

    Values set this way stay out of the process argument list, so secrets such
    as an authorization header are not visible to other users through ``ps``.
    Existing ``GIT_CONFIG_*`` entries are preserved and the new ones are read
    after them.
    """
    raw_count = str(env.get("GIT_CONFIG_COUNT") or "0").strip()
    try:
        index = max(0, int(raw_count))
    except ValueError:
        index = 0
    for key, value in entries:
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
        index += 1
    env["GIT_CONFIG_COUNT"] = str(index)
    return env
