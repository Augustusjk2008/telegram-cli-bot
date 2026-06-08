from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.native_agent import config_store


def _sample_config() -> dict[str, object]:
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "jojocode_max": {
                "models": {
                    "gpt-5.4": {
                        "name": "gpt-5.4",
                        "reasoningEfforts": ["low", "medium", "high"],
                        "options": {"reasoningEffort": "medium"},
                        "limit": {"context": 1_000_000, "output": 128_000},
                    }
                }
            }
        },
    }


def test_native_agent_config_store_saves_opencode_and_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opencode_path = tmp_path / "opencode.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")

    payload = config_store.save_native_agent_config(_sample_config())

    backup_path = tmp_path / "data" / "native_agent" / "opencode.config.backup.json"
    assert payload["needs_restart"] is True
    assert payload["opencode_config_path"] == str(opencode_path)
    assert payload["backup_path"] == str(backup_path)
    assert json.loads(opencode_path.read_text(encoding="utf-8")) == payload["config"]
    assert json.loads(backup_path.read_text(encoding="utf-8")) == payload["config"]
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


def test_native_agent_config_store_loads_backup_before_opencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opencode_path = tmp_path / "opencode.json"
    backup_path = tmp_path / "data" / "native_agent" / "opencode.config.backup.json"
    backup_path.parent.mkdir(parents=True)
    opencode_path.write_text(json.dumps({"provider": {"old": {"models": {}}}}), encoding="utf-8")
    backup_path.write_text(json.dumps(_sample_config()), encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")

    assert config_store.first_configured_model()["id"] == "jojocode_max/gpt-5.4"


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


def test_effective_native_agent_config_normalizes_invalid_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot import config
    from bot.native_agent.configuration import effective_native_agent_config

    opencode_path = tmp_path / "opencode.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    config_store.save_native_agent_config(_sample_config())
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "ultra")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    native_agent = effective_native_agent_config({
        "native_agent_model": "jojocode_max/gpt-5.4",
    })

    assert native_agent["reasoning_effort"] == "medium"


def test_effective_native_agent_config_defaults_to_first_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot import config
    from bot.native_agent.configuration import effective_native_agent_config

    opencode_path = tmp_path / "opencode.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    config_store.save_native_agent_config({
        "provider": {
            "jojocode_max": {
                "models": {
                    "gpt-5.4": {
                        "name": "gpt-5.4",
                        "variants": {
                            "low": {},
                            "high": {},
                        },
                    }
                }
            }
        }
    })
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    native_agent = effective_native_agent_config({
        "native_agent_model": "jojocode_max/gpt-5.4",
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
