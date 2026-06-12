from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

LEGACY_EXECUTION_MODE = "opencode"
LEGACY_EXECUTION_MODE_REMOVED_MESSAGE = (
    f"execution_mode={LEGACY_EXECUTION_MODE} 已移除，请改用 native_agent"
)
LEGACY_NATIVE_AGENT_ENV_KEY = "NATIVE_AGENT_OPENCODE_AGENT"
LEGACY_NATIVE_AGENT_DOCUMENT_KEYS = (
    "opencode_config_path",
    "opencodeConfigPath",
)

_PI_AGENT_ALIAS_KEYS = (
    "pi_agent",
    "piAgent",
    "opencode_agent",
    "opencodeAgent",
    "agent",
)
_REMOVED_PI_AGENT_ALIAS_KEYS = tuple(key for key in _PI_AGENT_ALIAS_KEYS if key != "pi_agent")


def is_legacy_execution_mode(value: Any) -> bool:
    return str(value or "").strip().lower() == LEGACY_EXECUTION_MODE


def resolve_pi_agent_value(*sources: Any) -> str:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in _PI_AGENT_ALIAS_KEYS:
            value = source.get(key)
            if value is not None:
                normalized = str(value or "").strip()
                if normalized:
                    return normalized
    return ""


def _has_pi_agent_alias(source: Mapping[str, Any]) -> bool:
    return any(key in source for key in _PI_AGENT_ALIAS_KEYS)


def migrate_native_agent_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    payload = dict(value)
    had_alias = _has_pi_agent_alias(payload)
    pi_agent = resolve_pi_agent_value(payload)
    if pi_agent or had_alias:
        payload["pi_agent"] = pi_agent
    for key in _REMOVED_PI_AGENT_ALIAS_KEYS:
        payload.pop(key, None)
    return payload


def migrate_native_session_meta(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    payload = dict(value)
    had_alias = _has_pi_agent_alias(payload)
    pi_agent = resolve_pi_agent_value(payload)
    if pi_agent or had_alias:
        payload["pi_agent"] = pi_agent
    for key in _REMOVED_PI_AGENT_ALIAS_KEYS:
        payload.pop(key, None)
    return payload


def resolve_pi_agent_env(getter: Callable[[str, str], str]) -> str:
    value = getter("NATIVE_AGENT_PI_AGENT", "").strip()
    if value:
        return value
    return getter(LEGACY_NATIVE_AGENT_ENV_KEY, "").strip()
