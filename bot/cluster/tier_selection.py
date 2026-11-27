"""The model-facing projection and editable fields of a Bot's cluster tiers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from bot.cluster import ClusterToolError
from bot.cluster.config import (
    CLUSTER_CLI_TYPES, MODEL_TIER_KEYS, ClusterExecutionSnapshot, ClusterTierConfig, configured_cluster_tier,
    resolve_cluster_execution,
)
from bot.config import default_cli_path
from bot.models import BotProfile
from bot.platform.executables import resolve_cli_executable


EDITABLE_FIELDS = ("cli_type", "model", "reasoning_effort")


def read_tier_request(payload: dict[str, Any], *, editing: bool) -> tuple[str, dict[str, str]]:
    allowed = {"model_tier", *EDITABLE_FIELDS, "expected_revision"} if editing else {"model_tier", "cli_type"}
    unknown = payload.keys() - allowed
    if unknown:
        raise ClusterToolError("cluster_tier_invalid", f"Unknown fields: {', '.join(sorted(unknown))}")
    if not editing and not payload:
        return "", {}
    tier = payload.get("model_tier")
    if not isinstance(tier, str) or tier not in MODEL_TIER_KEYS:
        raise ClusterToolError("cluster_tier_invalid", f"model_tier must be one of {', '.join(MODEL_TIER_KEYS)}.")
    patch = {}
    for name in EDITABLE_FIELDS:
        if name not in payload:
            continue
        value = payload[name]
        if not isinstance(value, str) or value != value.strip():
            raise ClusterToolError("cluster_tier_invalid", f"Use an exact listed {name} or an empty string to inherit.")
        patch[name] = value
    if "cli_type" in patch and patch["cli_type"] and patch["cli_type"] not in CLUSTER_CLI_TYPES:
        raise ClusterToolError("cluster_tier_invalid", f"Unknown cli_type. Choose from {', '.join(sorted(CLUSTER_CLI_TYPES))}.")
    if editing and (not patch or not isinstance(payload.get("expected_revision"), str) or not payload["expected_revision"]):
        raise ClusterToolError("cluster_tier_invalid", "Supply at least one setting and the revision from get_agent_tiers.")
    return tier, patch


def tier_revision(profile: BotProfile, tier: str, target_cli: str | None = None) -> str:
    saved = configured_cluster_tier(profile.cluster, tier)
    selector = saved.cli_type if target_cli is None else target_cli
    backend = selector or profile.cli_type
    params = profile.cli_params.get_params(backend)
    # Bind a preview to its target and the inputs to inheritance. Two backends
    # can advertise the same model ID or effort.
    inputs = [
        profile.alias, tier, saved.to_dict(), selector, profile.cli_type, profile.cli_path,
        default_cli_path(backend), profile.working_dir, profile.remote_workspace,
        {key: params.get(key) for key in ("provider", "model", "reasoning_effort", "effort")},
    ]
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:24]


def check_tier_revision(profile: BotProfile, tier: str, expected: str, target_cli: str | None = None) -> None:
    if not isinstance(expected, str) or not expected:
        raise ClusterToolError("cluster_tier_invalid", "Use the revision returned by get_agent_tiers.")
    if tier_revision(profile, tier, target_cli) != expected:
        raise ClusterToolError("cluster_tier_changed", "The tier or target CLI changed. Read get_agent_tiers for the intended CLI again.")


def patched_tier(profile: BotProfile, tier: str, patch: dict[str, str]) -> ClusterTierConfig:
    current = configured_cluster_tier(profile.cluster, tier)
    cli = patch.get("cli_type", current.cli_type)
    if (cli or profile.cli_type) != (current.cli_type or profile.cli_type):
        # Paths, providers, models and efforts belong to the old backend.
        current = ClusterTierConfig(cli_type=cli)
    elif current.cli_type and not cli:
        current = replace(current, cli_path="")
    return replace(current, **patch)


def public_tier_settings(selection: ClusterTierConfig | ClusterExecutionSnapshot) -> dict[str, str]:
    return {field: getattr(selection, field) for field in (*EDITABLE_FIELDS, "provider")}


def tier_summary(profile: BotProfile, tier: str, target_cli: str | None = None) -> dict[str, Any]:
    config = configured_cluster_tier(profile.cluster, tier)
    item = {
        "configured": public_tier_settings(config),
        "revision": tier_revision(profile, tier, target_cli),
    }
    try:
        execution = resolve_cluster_execution(profile, tier)
    except ValueError as exc:
        return {**item, "availability": "unsupported", "effective": None, "error": str(exc)}
    available = resolve_cli_executable(execution.cli_path, profile.working_dir)
    return {**item, "effective": public_tier_settings(execution), "availability": "available" if available else "missing"}


def validate_tier_selection(
    selection: ClusterTierConfig, execution: ClusterExecutionSnapshot, options: dict[str, Any],
) -> None:
    if options["availability"] != "available":
        raise ClusterToolError("cluster_cli_unavailable", "The selected CLI is unavailable in this workspace.", options)
    if selection.model and selection.model not in options["models"]:
        raise ClusterToolError("cluster_tier_invalid", "Choose a listed model or use an empty string to inherit.", options)
    if (
        execution.cli_type == "deepseek" and options.get("catalog_status") == "ready"
        and execution.model and options["models"] and execution.model not in options["models"]
    ):
        raise ClusterToolError(
            "cluster_tier_invalid", "The inherited model is outside this provider's catalog. Select a listed model.", options,
        )
    efforts = options["reasoning_efforts_by_model"].get(
        execution.model or options["default_model"], options["reasoning_efforts"],
    )
    effort = selection.reasoning_effort or execution.reasoning_effort
    if effort and effort not in efforts:
        raise ClusterToolError("cluster_tier_invalid", "Choose a reasoning effort supported by the selected model.", options)
