from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.cluster.bundles import build_cluster_bundle_schema
from bot.cluster.config import MODEL_TIER_KEYS, normalize_bot_cluster_config
from bot.cluster.runtime import ClusterRunRequest, ClusterRuntime
from bot.models import AgentProfile, BotProfile, UserSession
from bot.web import api_service
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
    [("codex", "reasoning_effort", "ultra"), ("codex_server", "reasoning_effort", "ultra"), ("claude", "effort", "max")],
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tier", "expected_model", "expected_effort"),
    [
        ("low", "provider/main-model", "medium"),
        ("medium", "provider/main-model", "high"),
        ("high", "other/strong-model", "xhigh"),
    ],
)
async def test_pi_cluster_task_applies_tier_from_queued_snapshot_without_changing_main(
    monkeypatch, tmp_path, tier, expected_model, expected_effort,
) -> None:
    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="worker", name="Worker")],
        supported_execution_modes=["native_agent"],
        default_execution_mode="native_agent",
        native_agent={
            "model": "provider/main-model",
            "reasoning_effort": "medium",
            "pi_agent": "researcher",
        },
        cluster=normalize_bot_cluster_config({
            "enabled": True,
            "model_tiers": {"high": "other/strong-model"},
            "reasoning_efforts": {"medium": "high", "high": "xhigh"},
        }),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(
        bot_alias="main", user_id=1, profile=profile, execution_mode="native_agent",
    ))
    request = runtime.validate_ask_agent(run.run_id, {
        "agent_id": "worker", "message": "review the change", "model_tier": tier,
    })
    task = runtime.create_agent_task(run.run_id, request)
    profile.native_agent = {"model": "provider/new-main-model", "reasoning_effort": "low"}
    profile.cluster.model_tiers["high"] = "provider/new-tier-model"
    runtime.ensure_run(ClusterRunRequest(
        bot_alias="main", user_id=1, profile=profile, execution_mode="native_agent",
    ), run.run_id)
    session = UserSession(
        bot_id=-1, bot_alias="main", user_id=1, agent_id="worker",
        working_dir=str(tmp_path), _persist_enabled=False,
    )
    received = []

    async def stream_chat(**kwargs):
        received.append(dict(kwargs["profile"].native_agent))
        assert kwargs["profile"] is not profile
        assert kwargs["session"] is session
        yield {"type": "done", "output": "reviewed", "returncode": 0}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args: (
        profile, profile.get_agent("worker"), session,
    ))
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: SimpleNamespace(stream_chat=stream_chat))
    monkeypatch.setattr(api_service, "_history_service_for_execution_mode", lambda *_args: object())
    monkeypatch.setattr(api_service, "pi_turn_reconnect_enabled", lambda: False)

    await api_service._run_cluster_agent_task(object(), run.run_id, task.task_id)

    assert task.status == "completed", task.error
    assert task.output == "reviewed"
    assert received == [{
        "model": expected_model,
        "reasoning_effort": expected_effort,
        "pi_agent": "researcher",
    }]
    assert profile.native_agent == {"model": "provider/new-main-model", "reasoning_effort": "low"}
    assert task.profile.native_agent["model"] == "provider/main-model"
