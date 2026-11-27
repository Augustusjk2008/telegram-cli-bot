from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

BOT_WRITE_POLICIES = {"main_only", "all_agents"}
AGENT_SESSION_POLICIES = {"persistent", "ephemeral", "fork"}
MODEL_TIER_KEYS = ("low", "medium", "high", "professional")
CLUSTER_CLI_TYPES = frozenset({"codex", "codex_server", "claude", "antigravity", "deepseek"})
TIER_EDITOR_ENV = "TCB_CLUSTER_TIER_EDITOR"
TIER_EDITOR_HEADER = "X-TCB-Cluster-Tier-Editor"


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


def _reasoning_efforts(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {key: str(source.get(key) or "").strip() for key in MODEL_TIER_KEYS}


def _string(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ClusterTierConfig:
    """One cluster model tier's execution selection.

    Empty CLI and path values deliberately remain empty here.  They inherit
    the main Bot profile when an execution snapshot is resolved.
    """

    cli_type: str = ""
    cli_path: str = ""
    provider: str = ""
    model: str = ""
    reasoning_effort: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        legacy_model: str = "",
        legacy_reasoning_effort: str = "",
    ) -> "ClusterTierConfig":
        source = value if isinstance(value, dict) else {}
        raw_cli_type = _string(source.get("cli_type", source.get("cliType"))).lower()
        if raw_cli_type and raw_cli_type not in CLUSTER_CLI_TYPES:
            supported = ", ".join(sorted(CLUSTER_CLI_TYPES))
            raise ValueError(f"不支持的 cluster tier cli_type: {raw_cli_type} (支持: {supported})")
        cli_type = raw_cli_type
        provider = _string(source.get("provider"))
        if provider and cli_type and cli_type != "deepseek":
            raise ValueError("provider 只能用于 DeepSeek cluster tier")
        return cls(
            cli_type=cli_type,
            cli_path=_string(source.get("cli_path", source.get("cliPath"))),
            # An empty cli_type inherits the Bot CLI.  Keep provider here so
            # an inherited DeepSeek tier can still select its provider; the
            # resolver validates the effective CLI below.
            provider=provider,
            model=_string(source.get("model")) or _string(legacy_model),
            reasoning_effort=_string(
                source.get("reasoning_effort", source.get("reasoningEffort"))
            ) or _string(legacy_reasoning_effort),
        )


def _tier_configs(value: Any, model_tiers: dict[str, str], reasoning_efforts: dict[str, str]) -> dict[str, ClusterTierConfig]:
    source = value if isinstance(value, dict) else {}
    return {
        tier: ClusterTierConfig.from_value(
            source.get(tier),
            legacy_model=model_tiers.get(tier, ""),
            legacy_reasoning_effort=reasoning_efforts.get(tier, ""),
        )
        for tier in MODEL_TIER_KEYS
    }


@dataclass(frozen=True)
class BotClusterConfig:
    enabled: bool = False
    write_policy: str = "all_agents"
    max_parallel_agents: int = 3
    default_timeout_seconds: int = 1800
    model_tiers: dict[str, str] = field(default_factory=lambda: _model_tiers({}))
    reasoning_efforts: dict[str, str] = field(default_factory=lambda: _reasoning_efforts({}))
    tier_configs: dict[str, ClusterTierConfig] = field(default_factory=lambda: _tier_configs({}, {}, {}))
    orchestration_version: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "write_policy": self.write_policy,
            "max_parallel_agents": self.max_parallel_agents,
            "default_timeout_seconds": self.default_timeout_seconds,
            "model_tiers": dict(self.model_tiers),
            "reasoning_efforts": dict(self.reasoning_efforts),
            "tier_configs": {
                tier: self.tier_configs.get(tier, ClusterTierConfig()).to_dict()
                for tier in MODEL_TIER_KEYS
            },
            "orchestration_version": 3,
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
    raw_write_policy = value.get("write_policy")
    model_tiers = _model_tiers(value.get("model_tiers"))
    reasoning_efforts = _reasoning_efforts(value.get("reasoning_efforts", value.get("reasoningEfforts")))
    tier_configs = _tier_configs(
        value.get("tier_configs", value.get("tierConfigs")),
        model_tiers,
        reasoning_efforts,
    )
    # Keep the legacy views useful to existing callers and API clients when
    # only the new tier_configs field was provided.
    model_tiers = {
        tier: tier_configs[tier].model or model_tiers[tier]
        for tier in MODEL_TIER_KEYS
    }
    reasoning_efforts = {
        tier: tier_configs[tier].reasoning_effort or reasoning_efforts[tier]
        for tier in MODEL_TIER_KEYS
    }
    return BotClusterConfig(
        enabled=_as_bool(value.get("enabled"), False),
        write_policy=(
            "all_agents"
            if raw_write_policy is None
            else _choice(raw_write_policy, BOT_WRITE_POLICIES, "main_only")
        ),
        max_parallel_agents=_as_int(value.get("max_parallel_agents"), 3, minimum=1, maximum=20),
        default_timeout_seconds=_as_int(value.get("default_timeout_seconds"), 1800, minimum=60, maximum=3600),
        model_tiers=model_tiers,
        reasoning_efforts=reasoning_efforts,
        tier_configs=tier_configs,
        orchestration_version=3,
    )


@dataclass(frozen=True)
class ClusterExecutionSnapshot:
    """Resolved, task-local execution settings for one model tier."""

    execution_mode: str
    cli_type: str
    cli_path: str
    provider: str
    model: str
    reasoning_effort: str
    params_config: Any


def _tier_value(value: Any) -> str:
    candidate = _string(value)
    return "" if candidate.casefold() == "none" else candidate


def configured_cluster_tier(cluster: BotClusterConfig, tier: str) -> ClusterTierConfig:
    selection = cluster.tier_configs.get(tier, ClusterTierConfig())
    if not isinstance(selection, ClusterTierConfig):
        selection = ClusterTierConfig.from_value(selection)
    return replace(
        selection,
        model=_tier_value(selection.model) or _tier_value(cluster.model_tiers.get(tier)),
        reasoning_effort=_tier_value(selection.reasoning_effort) or _tier_value(cluster.reasoning_efforts.get(tier)),
    )


def with_cluster_tier(cluster: BotClusterConfig, tier: str, selection: ClusterTierConfig) -> BotClusterConfig:
    """Keep modern and legacy readers in sync, including when an override is cleared."""
    return replace(
        cluster,
        tier_configs={**cluster.tier_configs, tier: selection},
        model_tiers={**cluster.model_tiers, tier: selection.model},
        reasoning_efforts={**cluster.reasoning_efforts, tier: selection.reasoning_effort},
    )


def patch_bot_cluster_config(current: BotClusterConfig, patch: dict[str, Any]) -> BotClusterConfig:
    """Merge both generations of the settings API without dropping sibling tiers."""
    data = {**current.to_dict(), **patch}
    tier_patches = patch.get("tier_configs", patch.get("tierConfigs"))
    legacy_models = patch.get("model_tiers")
    legacy_efforts = patch.get("reasoning_efforts", patch.get("reasoningEfforts"))
    tiers = {}
    for tier in MODEL_TIER_KEYS:
        row = configured_cluster_tier(current, tier).to_dict()
        if isinstance(legacy_models, dict) and tier in legacy_models:
            row["model"] = legacy_models[tier]
        if isinstance(legacy_efforts, dict) and tier in legacy_efforts:
            row["reasoning_effort"] = legacy_efforts[tier]
        changes = tier_patches.get(tier) if isinstance(tier_patches, dict) else None
        if isinstance(changes, dict):
            row.update(changes)
            for old, name in (("cliType", "cli_type"), ("cliPath", "cli_path"), ("reasoningEffort", "reasoning_effort")):
                if old in changes and name not in changes:
                    row[name] = changes[old]
        tiers[tier] = row
    data.update(tier_configs=tiers, model_tiers={}, reasoning_efforts={})
    return normalize_bot_cluster_config(data)


def resolve_cluster_cli(profile: Any, selection: ClusterTierConfig) -> tuple[str, str]:
    from bot.config import default_cli_path
    from bot.models import normalize_cli_type_config

    configured_cli_type = _string(selection.cli_type).lower()

    main_cli_type = normalize_cli_type_config(getattr(profile, "cli_type", "codex"))
    cli_type = configured_cli_type or main_cli_type
    if cli_type not in CLUSTER_CLI_TYPES:
        raise ValueError(f"不支持的 cluster tier cli_type: {cli_type}")
    if getattr(profile, "remote_workspace", None) and cli_type in {"antigravity", "deepseek"}:
        label = "Antigravity" if cli_type == "antigravity" else "DeepSeek Harness"
        raise ValueError(f"远程工作区暂不支持 {label} 集群编排")

    configured_path = _string(selection.cli_path)
    if configured_path:
        cli_path = configured_path
    elif cli_type == main_cli_type and _string(getattr(profile, "cli_path", "")):
        cli_path = _string(profile.cli_path)
    else:
        cli_path = default_cli_path(cli_type)
    return cli_type, cli_path


def resolve_cluster_execution(
    profile: Any,
    model_tier: str,
    *,
    execution_mode: str = "",
    selection: ClusterTierConfig | None = None,
) -> ClusterExecutionSnapshot:
    """Resolve a tier against a Bot profile and copy its CLI namespace.

    The returned params object is a detached copy.  Callers can therefore
    enqueue it as a task snapshot without observing later profile changes.
    """

    from bot.cli_params import CliParamsConfig, antigravity_model_effort
    from bot.models import EXECUTION_MODE_CLI

    tier = _string(model_tier).lower()
    if tier not in MODEL_TIER_KEYS:
        raise ValueError(f"Unknown model_tier. Choose one of {', '.join(MODEL_TIER_KEYS)}.")
    cluster = getattr(profile, "cluster", None) or BotClusterConfig()
    tier_config = selection or configured_cluster_tier(cluster, tier)

    cli_type, cli_path = resolve_cluster_cli(profile, tier_config)

    profile_params = getattr(profile, "cli_params", None)
    params = CliParamsConfig.from_dict(profile_params.to_dict() if profile_params is not None else None)
    target_params = params.get_params(cli_type)
    model = _tier_value(tier_config.model) or _tier_value(target_params.get("model"))
    reasoning_key = "reasoning_effort" if cli_type in {"codex", "codex_server", "deepseek"} else "effort"
    reasoning_effort = (
        _tier_value(tier_config.reasoning_effort)
        or _tier_value(target_params.get(reasoning_key))
    )
    if cli_type == "antigravity" and model:
        reasoning_effort = antigravity_model_effort(model) or ""
    if cli_type == "deepseek" and reasoning_effort not in {"", "off", "low", "high", "max"}:
        raise ValueError("DeepSeek reasoning_effort 无效")
    configured_provider = _tier_value(tier_config.provider)
    if configured_provider and cli_type != "deepseek":
        raise ValueError("provider 只能用于 DeepSeek cluster tier")
    provider = _tier_value(target_params.get("provider")) if cli_type == "deepseek" else ""
    if cli_type == "deepseek" and configured_provider:
        provider = configured_provider
        target_params["provider"] = provider
    target_params["model"] = model or None
    target_params[reasoning_key] = reasoning_effort or None

    return ClusterExecutionSnapshot(
        execution_mode=EXECUTION_MODE_CLI,
        cli_type=cli_type,
        cli_path=cli_path,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        params_config=params,
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
