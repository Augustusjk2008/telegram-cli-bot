from __future__ import annotations

import pytest

from bot.cli_params import CliParamsConfig, normalize_deepseek_selection
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession
from bot.web import api_service
from bot.web.api_common import WebApiError
from bot.web.api_service import build_cluster_cli_params_override, get_cli_params_payload


def _manager_with_deepseek(tmp_path, alias: str = "worker") -> MultiBotManager:
    manager = MultiBotManager(
        BotProfile(alias="main", working_dir=str(tmp_path)),
        str(tmp_path / "bots.json"),
    )
    manager.managed_profiles[alias] = BotProfile(
        alias=alias,
        cli_type="deepseek",
        cli_path="dsh",
        working_dir=str(tmp_path),
    )
    return manager


def _catalog(*, selected_provider: str = "official") -> dict:
    return {
        "providers": [
            {
                "id": "official",
                "label": "DeepSeek Official",
                "modelOptions": [
                    {"id": "deepseek-flash", "label": "deepseek-flash"},
                    {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
                ],
            },
            {
                "id": "account",
                "label": "Account Provider",
                "modelOptions": [{"id": "account-model", "label": "account-model"}],
            },
        ],
        "selectedProvider": selected_provider,
        "selectedModel": "deepseek-flash",
        "modelOptionsByProvider": {
            "official": [
                {"id": "deepseek-flash", "label": "deepseek-flash"},
                {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
            ],
            "account": [{"id": "account-model", "label": "account-model"}],
        },
        "reasoningEfforts": ["low", "high"],
        "status": "ready",
        "diagnostic": "credentials: api_key=should-not-leak",
    }


def test_deepseek_selection_normalization() -> None:
    config = CliParamsConfig.from_dict(
        {
            "deepseek": {
                "provider": " none ",
                "model": " custom-model ",
                "reasoning_effort": " none ",
            }
        }
    )
    assert config.deepseek["provider"] is None
    assert config.deepseek["model"] == "custom-model"
    assert config.deepseek["reasoning_effort"] is None
    assert normalize_deepseek_selection(" account ", " model ", " high ") == {
        "provider": "account",
        "model": "model",
        "reasoning_effort": "high",
    }


def test_deepseek_catalog_payload_is_provider_scoped_and_redacted(tmp_path, monkeypatch) -> None:
    manager = _manager_with_deepseek(tmp_path)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "dsh")
    monkeypatch.setattr(
        api_service,
        "discover_deepseek_catalog",
        lambda resolved_cli, working_dir, params: _catalog(),
    )

    payload = get_cli_params_payload(manager, "worker", "deepseek")

    assert payload["catalog_status"] == "ready"
    assert payload["selected_provider"] == "official"
    assert payload["provider_options"][0]["id"] == "official"
    assert payload["model_options_by_provider"] == {
        "official": ["deepseek-flash", "deepseek-v4-pro"],
        "account": ["account-model"],
    }
    assert payload["schema"]["model"]["enum"] == [
        "deepseek-flash",
        "deepseek-v4-pro",
        "none",
    ]
    assert "should-not-leak" not in repr(payload)
    assert "api_key" not in repr(payload)


@pytest.mark.asyncio
async def test_deepseek_selection_is_atomic_and_provider_switch_invalidates_target_session(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager_with_deepseek(tmp_path)
    profile = manager.managed_profiles["worker"]
    session = UserSession(
        bot_id=-1,
        bot_alias="worker",
        user_id=1,
        agent_id="reviewer",
        working_dir=str(tmp_path),
        deepseek_session_id="old-provider-session",
        _persist_enabled=False,
    )
    monkeypatch.setattr("bot.sessions.get_bot_sessions", lambda alias: [session])
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "dsh")
    monkeypatch.setattr(
        api_service,
        "discover_deepseek_catalog",
        lambda resolved_cli, working_dir, params: _catalog(),
    )

    result = await api_service.update_deepseek_selection(
        manager,
        "worker",
        1,
        provider="account",
        model=None,
        reasoning_effort="high",
        agent_id="reviewer",
    )

    assert result["params"]["provider"] == "account"
    assert result["params"]["model"] == "account-model"
    assert result["params"]["reasoning_effort"] == "high"
    assert result["provider_changed"] is True
    assert result["session_reset"] is True
    assert profile.cli_params.deepseek["provider"] == "account"
    assert session.deepseek_session_id is None
    restored = MultiBotManager(
        BotProfile(alias="main", working_dir=str(tmp_path)),
        str(tmp_path / "bots.json"),
    )
    assert restored.managed_profiles["worker"].cli_params.deepseek["provider"] == "account"
    assert restored.managed_profiles["worker"].cli_params.deepseek["model"] == "account-model"

    session.deepseek_session_id = "same-provider-session"
    await manager.update_deepseek_selection(
        "worker",
        "account",
        "account-model",
        "high",
        user_id=1,
        agent_id="reviewer",
        allowed_providers=["official", "account"],
        allowed_models_by_provider={"account": ["account-model"]},
        allowed_reasoning_efforts_by_provider={"account": ["high"]},
    )
    assert session.deepseek_session_id == "same-provider-session"

    with pytest.raises(WebApiError, match="provider"):
        await api_service.update_deepseek_selection(
            manager,
            "worker",
            1,
            provider="unknown",
            model="model",
            reasoning_effort="high",
            agent_id="reviewer",
        )
    assert profile.cli_params.deepseek["provider"] == "account"


def test_deepseek_catalog_fallback_preserves_saved_provider_and_model(tmp_path, monkeypatch) -> None:
    manager = _manager_with_deepseek(tmp_path)
    manager.managed_profiles["worker"].cli_params.deepseek.update(
        {"provider": "legacy", "model": "legacy-model"}
    )
    monkeypatch.setattr(api_service, "discover_deepseek_catalog", None)

    payload = get_cli_params_payload(manager, "worker", "deepseek")

    assert payload["catalog_status"] == "fallback"
    assert payload["selected_provider"] == "legacy"
    assert payload["selected_model"] == "legacy-model"
    assert "legacy-model" in payload["schema"]["model"]["enum"]
    assert "deepseek-flash" in payload["schema"]["model"]["enum"]
    assert payload["provider_options"] == [
        {
            "id": "legacy",
            "label": "legacy",
            "model_options": [],
            "reasoning_efforts": [],
            "default_model": None,
            "default_reasoning_effort": None,
        }
    ]


def test_deepseek_cluster_override_inherits_provider(tmp_path) -> None:
    profile = BotProfile(alias="main", cli_type="deepseek", working_dir=str(tmp_path))
    profile.cli_params.deepseek["provider"] = "account"
    profile.cluster.model_tiers["high"] = "account-model"
    profile.cluster.reasoning_efforts["high"] = "high"

    override = build_cluster_cli_params_override(profile, "high")

    assert override.get_param("deepseek", "provider") == "account"
    assert override.get_param("deepseek", "model") == "account-model"
    assert override.get_param("deepseek", "reasoning_effort") == "high"
