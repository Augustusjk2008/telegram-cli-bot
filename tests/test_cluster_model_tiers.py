from __future__ import annotations

import pytest

from bot.cluster.bundles import build_cluster_bundle_schema
from bot.cluster.config import MODEL_TIER_KEYS, normalize_bot_cluster_config
from bot.models import BotProfile
from bot.web.api_service import build_cluster_cli_params_override


def test_cluster_config_normalizes_reasoning_efforts_and_keeps_missing_values_compatible() -> None:
    configured = normalize_bot_cluster_config(
        {
            "reasoning_efforts": {
                "low": "medium",
                "medium": "xhigh",
                "high": "ultra",
            }
        }
    )
    legacy = normalize_bot_cluster_config({"model_tiers": {"low": "fast-model"}})

    assert configured.reasoning_efforts == {
        "low": "medium",
        "medium": "xhigh",
        "high": "ultra",
    }
    assert configured.to_dict()["reasoning_efforts"] == configured.reasoning_efforts
    assert legacy.reasoning_efforts == {tier: "" for tier in MODEL_TIER_KEYS}
    assert "reasoning_efforts" in build_cluster_bundle_schema()["schema"]["properties"]["cluster"]["properties"]


@pytest.mark.parametrize(
    ("cli_type", "parameter_name", "reasoning_effort"),
    [("codex", "reasoning_effort", "ultra"), ("claude", "effort", "max")],
)
def test_cluster_cli_override_applies_model_and_reasoning_for_selected_tier(
    cli_type: str,
    parameter_name: str,
    reasoning_effort: str,
) -> None:
    profile = BotProfile(
        alias="main",
        cli_type=cli_type,
        cluster=normalize_bot_cluster_config(
            {
                "model_tiers": {"high": "strong-model"},
                "reasoning_efforts": {"high": reasoning_effort},
            }
        ),
    )

    override = build_cluster_cli_params_override(profile, "high")

    assert override.get_param(cli_type, "model") == "strong-model"
    assert override.get_param(cli_type, parameter_name) == reasoning_effort
