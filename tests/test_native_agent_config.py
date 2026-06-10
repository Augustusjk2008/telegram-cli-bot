from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.native_agent import config_store


def _sample_config() -> dict[str, object]:
    return {
        "backend": "pi",
        "model": "jojocode_max/gpt-5.4",
        "reasoning_effort": "medium",
        "pi_agent": "main",
        "pi_command": "pi",
        "workspace_history_enabled": True,
        "models": [
            {
                "id": "jojocode_max/gpt-5.4",
                "provider": "jojocode_max",
                "model": "gpt-5.4",
                "name": "gpt-5.4",
                "reasoning_efforts": ["low", "medium", "high"],
                "default_reasoning_effort": "medium",
                "context_window": 1_000_000,
                "output_limit": 128_000,
            }
        ],
    }


def test_native_agent_config_store_saves_pi_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))

    payload = config_store.save_native_agent_config(_sample_config())

    assert payload["needs_restart"] is True
    assert payload["backend"] == "pi"
    assert payload["config_path"] == str(settings_path)
    assert payload["selected_model"] == "jojocode_max/gpt-5.4"
    assert payload["workspace_history_enabled"] is True
    assert "opencode_config_path" not in payload
    assert "backup_path" not in payload
    assert json.loads(settings_path.read_text(encoding="utf-8")) == payload["config"]
    assert payload["models"] == [
        {
            "id": "jojocode_max/gpt-5.4",
            "provider": "jojocode_max",
            "model": "gpt-5.4",
            "name": "gpt-5.4",
            "label": "jojocode_max / gpt-5.4",
            "context_window": 1_000_000,
            "output_limit": 128_000,
            "reasoning_efforts": ["low", "medium", "high"],
            "default_reasoning_effort": "medium",
        }
    ]


def test_native_agent_config_store_loads_pi_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(_sample_config()), encoding="utf-8")
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))

    assert config_store.first_configured_model()["id"] == "jojocode_max/gpt-5.4"
    assert config_store.load_native_agent_config()["backend"] == "pi"


def test_native_agent_config_store_uses_variants_as_reasoning_efforts() -> None:
    payload = {
        "provider": {
            "openai": {
                "models": {
                    "gpt-5.5": {
                        "name": "GPT-5.5",
                        "variants": {
                            "low": {},
                            "medium": {},
                            "high": {},
                            "xhigh": {},
                        },
                    }
                }
            }
        }
    }

    models = config_store.list_configured_models(payload)

    assert models[0]["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert models[0]["default_reasoning_effort"] == ""


def test_normalize_native_agent_config_accepts_pi_and_legacy_agents() -> None:
    from bot.models import normalize_native_agent_config, public_native_agent_config, build_native_agent_model_id

    normalized = normalize_native_agent_config(
        {
            "provider": "legacy-provider",
            "native_agent_model": "selected/model",
            "opencode_agent": "legacy",
            "agent": "agent-legacy",
            "piAgent": "reviewer",
            "pi_command": "pi-custom",
            "workspace_history_enabled": False,
            "reasoningEffort": "high",
        }
    )

    assert normalized["backend"] == "pi"
    assert normalized["model"] == "selected/model"
    assert normalized["pi_agent"] == "reviewer"
    assert normalized["pi_command"] == "pi-custom"
    assert normalized["workspace_history_enabled"] is False
    assert normalized["reasoning_effort"] == "high"
    assert "opencode_agent" not in normalized
    public = public_native_agent_config(normalized)
    assert public["pi_agent"] == "reviewer"
    assert "opencode_agent" not in public
    assert build_native_agent_model_id(normalized) == "selected/model"


def test_effective_native_agent_config_normalizes_invalid_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot import config
    from bot.native_agent.configuration import effective_native_agent_config

    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))
    config_store.save_native_agent_config(_sample_config())
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_COMMAND", "pi")
    monkeypatch.setattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "ultra")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    native_agent = effective_native_agent_config({
        "model": "jojocode_max/gpt-5.4",
    })

    assert native_agent["reasoning_effort"] == "medium"


def test_effective_native_agent_config_defaults_to_first_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot import config
    from bot.native_agent.configuration import effective_native_agent_config

    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))
    config_store.save_native_agent_config({
        "models": [
            {
                "id": "jojocode_max/gpt-5.4",
                "provider": "jojocode_max",
                "model": "gpt-5.4",
                "name": "gpt-5.4",
                "variants": {
                    "low": {},
                    "high": {},
                },
            }
        ]
    })
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_COMMAND", "pi")
    monkeypatch.setattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    native_agent = effective_native_agent_config({
        "model": "jojocode_max/gpt-5.4",
    })

    assert native_agent["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "config, message",
    [
        ({"provider": []}, "provider 必须是对象"),
        ({"provider": {"p": {"models": []}}}, "provider.p.models 必须是对象"),
        ({"provider": {"p": {"models": {"m": {"limit": []}}}}}, "provider.p.models.m.limit 必须是对象"),
        ({"provider": {"p": {"models": {"m": {"limit": {"context": 0}}}}}}, "limit.context 必须是正整数"),
    ],
)
def test_native_agent_config_store_validates_shape(config: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config_store.normalize_native_agent_config_document(config)
