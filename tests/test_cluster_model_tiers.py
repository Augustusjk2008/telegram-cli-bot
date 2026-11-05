from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.cluster.config import (
    MODEL_TIER_KEYS,
    resolve_cluster_execution,
    normalize_bot_cluster_config,
)
from bot.cli_params import CliParamsConfig
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
                "professional": "max",
            }
        }
    )
    legacy = normalize_bot_cluster_config({"model_tiers": {"low": "fast-model"}})

    assert configured.reasoning_efforts == {
        "low": "medium",
        "medium": "xhigh",
        "high": "ultra",
        "professional": "max",
    }
    assert configured.to_dict()["reasoning_efforts"] == configured.reasoning_efforts
    assert legacy.reasoning_efforts == {tier: "" for tier in MODEL_TIER_KEYS}
    assert "reasoning_efforts" in configured.to_dict()


def test_cluster_config_normalizes_per_tier_cli_and_rejects_invalid_cli_provider_pair() -> None:
    configured = normalize_bot_cluster_config(
        {
            "tier_configs": {
                "low": {
                    "cli_type": "deepseek",
                    "cli_path": "dsh-custom",
                    "provider": "account",
                    "model": "account-model",
                    "reasoning_effort": "high",
                },
                "high": {"cli_type": "claude", "model": "claude-model"},
            },
        }
    )

    assert configured.orchestration_version == 3
    assert configured.tier_configs["low"].cli_type == "deepseek"
    assert configured.tier_configs["low"].provider == "account"
    assert configured.tier_configs["high"].cli_type == "claude"
    assert configured.to_dict()["tier_configs"]["low"]["cli_path"] == "dsh-custom"

    with pytest.raises(ValueError, match="cli_type"):
        normalize_bot_cluster_config({"tier_configs": {"low": {"cli_type": "unknown"}}})
    with pytest.raises(ValueError, match="provider"):
        normalize_bot_cluster_config({"tier_configs": {"low": {"cli_type": "claude", "provider": "account"}}})


def test_cluster_execution_snapshot_uses_target_cli_namespace_and_path() -> None:
    profile = BotProfile(
        alias="main",
        cli_type="codex",
        cli_path="codex-main",
        cli_params=CliParamsConfig.from_dict({
            "codex": {"model": "codex-main-model", "reasoning_effort": "low"},
            "claude": {"model": "claude-main-model", "effort": "medium"},
        }),
        cluster=normalize_bot_cluster_config({
            "tier_configs": {
                "low": {
                    "cli_type": "claude",
                    "cli_path": "claude-tier",
                    "model": "claude-tier-model",
                    "reasoning_effort": "high",
                },
            },
        }),
    )

    snapshot = resolve_cluster_execution(profile, "low", execution_mode="cli")

    assert snapshot.cli_type == "claude"
    assert snapshot.cli_path == "claude-tier"
    assert snapshot.model == "claude-tier-model"
    assert snapshot.reasoning_effort == "high"
    assert snapshot.params_config.get_param("claude", "model") == "claude-tier-model"
    assert snapshot.params_config.get_param("codex", "model") == "codex-main-model"


def test_native_cluster_rejects_cli_path_or_provider_tier_override() -> None:
    profile = BotProfile(
        alias="pi",
        supported_execution_modes=["native_agent"],
        default_execution_mode="native_agent",
        native_agent={"model": "pi-model", "reasoning_effort": "medium"},
        cluster=normalize_bot_cluster_config({
            "tier_configs": {"low": {"cli_path": "claude", "provider": "account"}},
        }),
    )

    with pytest.raises(ValueError, match="native/Pi"):
        resolve_cluster_execution(profile, "low", execution_mode="native_agent")


def test_bot_profile_round_trips_tier_configs() -> None:
    profile = BotProfile(
        alias="main",
        cluster=normalize_bot_cluster_config({
            "tier_configs": {
                "medium": {"cli_type": "claude", "model": "claude-balanced"},
            },
        }),
    )

    restored = BotProfile.from_dict(profile.to_dict())

    assert restored.cluster.tier_configs["medium"].cli_type == "claude"
    assert restored.cluster.tier_configs["medium"].model == "claude-balanced"


def test_deepseek_tier_rejects_provider_outside_catalog(monkeypatch, tmp_path) -> None:
    from bot.web import api_service

    profile = BotProfile(alias="main", cli_type="deepseek", working_dir=str(tmp_path))
    cluster = normalize_bot_cluster_config({
        "tier_configs": {"low": {"provider": "unknown-provider"}},
    })
    monkeypatch.setattr(
        api_service,
        "_get_deepseek_catalog",
        lambda _profile, _params: {
            "_allowed_providers": ["official"],
            "_allowed_models_by_provider": {},
            "_allowed_reasoning_efforts_by_provider": {},
        },
    )

    with pytest.raises(ValueError, match="provider"):
        api_service._validate_cluster_deepseek_tiers(profile, cluster)


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
        ("professional", "provider/professional-model", "max"),
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
            "model_tiers": {"high": "other/strong-model", "professional": "provider/professional-model"},
            "reasoning_efforts": {"medium": "high", "high": "xhigh", "professional": "max"},
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


@pytest.mark.asyncio
async def test_cli_cluster_task_uses_queued_cli_snapshot_and_run_id(monkeypatch, tmp_path) -> None:
    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="worker", name="Worker")],
        cli_type="codex",
        cli_path="codex-main",
        cluster=normalize_bot_cluster_config({
            "enabled": True,
            "tier_configs": {
                "low": {
                    "cli_type": "claude",
                    "cli_path": "claude-tier",
                    "model": "claude-fast",
                    "reasoning_effort": "low",
                },
            },
        }),
    )
    runtime = ClusterRuntime()
    run = runtime.start_run(ClusterRunRequest(
        bot_alias="main", user_id=1, profile=profile, execution_mode="cli",
    ))
    request = runtime.validate_ask_agent(run.run_id, {
        "agent_id": "worker", "message": "review", "model_tier": "low",
    })
    task = runtime.create_agent_task(run.run_id, request)
    replacement = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        agents=[AgentProfile(id="worker", name="Worker")],
        cli_type="codex",
        cli_path="codex-replaced",
        cluster=normalize_bot_cluster_config({"enabled": True}),
    )
    runtime.ensure_run(
        ClusterRunRequest(bot_alias="main", user_id=1, profile=replacement, execution_mode="cli"),
        run.run_id,
    )
    seen: dict[str, object] = {}

    async def stream_chat(*_args, **kwargs):
        seen.update(kwargs)
        yield {"type": "done", "output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api_service, "_stream_cli_chat", stream_chat)

    await api_service._run_cluster_agent_task(object(), run.run_id, task.task_id)

    assert task.status == "completed", task.error
    assert seen["cluster_run_id"] == run.run_id
    queued_profile = seen["profile_override"]
    assert isinstance(queued_profile, BotProfile)
    assert queued_profile.cli_type == "claude"
    assert queued_profile.cli_path == "claude-tier"
    assert seen["cli_params_override"].get_param("claude", "model") == "claude-fast"
