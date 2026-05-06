from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BOT_WRITE_POLICIES = {"main_only", "selected_agents", "all_agents"}
BOT_CONFLICT_POLICIES = {"warn_only", "snapshot_diff", "block_same_file"}
AGENT_SESSION_POLICIES = {"persistent", "ephemeral", "fork"}
MODEL_TIER_KEYS = ("low", "medium", "high")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _choice(value: Any, allowed: set[str], default: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in allowed else default


def _model_tiers(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {key: str(source.get(key) or "").strip() for key in MODEL_TIER_KEYS}


@dataclass(frozen=True)
class BotClusterConfig:
    enabled: bool = False
    write_policy: str = "selected_agents"
    conflict_policy: str = "snapshot_diff"
    max_parallel_agents: int = 2
    default_timeout_seconds: int = 600
    model_tiers: dict[str, str] = field(default_factory=lambda: _model_tiers({}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "write_policy": self.write_policy,
            "conflict_policy": self.conflict_policy,
            "max_parallel_agents": self.max_parallel_agents,
            "default_timeout_seconds": self.default_timeout_seconds,
            "model_tiers": dict(self.model_tiers),
        }


@dataclass(frozen=True)
class AgentClusterConfig:
    allow_cluster: bool = True
    allow_write: bool = False
    session_policy: str = "persistent"
    timeout_seconds: int = 600

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_cluster": self.allow_cluster,
            "allow_write": self.allow_write,
            "session_policy": self.session_policy,
            "timeout_seconds": self.timeout_seconds,
        }


def normalize_bot_cluster_config(value: Any) -> BotClusterConfig:
    if not isinstance(value, dict):
        value = {}
    return BotClusterConfig(
        enabled=_as_bool(value.get("enabled"), False),
        write_policy=_choice(value.get("write_policy"), BOT_WRITE_POLICIES, "selected_agents"),
        conflict_policy=_choice(value.get("conflict_policy"), BOT_CONFLICT_POLICIES, "snapshot_diff"),
        max_parallel_agents=_as_int(value.get("max_parallel_agents"), 2, minimum=1, maximum=8),
        default_timeout_seconds=_as_int(value.get("default_timeout_seconds"), 600, minimum=60, maximum=3600),
        model_tiers=_model_tiers(value.get("model_tiers")),
    )


def normalize_agent_cluster_config(value: Any) -> AgentClusterConfig:
    if not isinstance(value, dict):
        value = {}
    return AgentClusterConfig(
        allow_cluster=_as_bool(value.get("allow_cluster", value.get("allowCluster")), True),
        allow_write=_as_bool(value.get("allow_write", value.get("allowWrite")), False),
        session_policy=_choice(
            value.get("session_policy", value.get("sessionPolicy")),
            AGENT_SESSION_POLICIES,
            "persistent",
        ),
        timeout_seconds=_as_int(
            value.get("timeout_seconds", value.get("timeoutSeconds")),
            600,
            minimum=60,
            maximum=3600,
        ),
    )
