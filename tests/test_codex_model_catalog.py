from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import codex_model_catalog
from bot.cli_params import coerce_param_value
from bot.models import BotProfile
from bot.web import api_service
from bot.web.api_common import WebApiError


def _live_catalog() -> dict:
    return {
        "source": "codex_cli",
        "error": "",
        "items": [
            {
                "id": "gpt-5.5",
                "label": "GPT-5.5",
                "reasoning_efforts": ["low", "medium", "high", "xhigh"],
                "default_reasoning_effort": "medium",
            },
            {
                "id": "gpt-5.6-sol",
                "label": "GPT-5.6-Sol",
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
                "default_reasoning_effort": "medium",
            },
            {
                "id": "none",
                "label": "自动（Codex 默认）",
                "reasoning_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
                "default_reasoning_effort": "",
            },
        ],
    }


def test_codex_model_catalog_uses_visible_cli_models_and_cache(monkeypatch, tmp_path: Path) -> None:
    codex_model_catalog.clear_codex_model_catalog_cache()
    executable = tmp_path / "codex"
    executable.write_text("", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(codex_model_catalog, "resolve_cli_executable", lambda *_args: str(executable))

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout='{"models": ['
            '{"slug":"gpt-5.6-sol","display_name":"GPT-5.6-Sol","visibility":"list",'
            '"default_reasoning_level":"medium","supported_reasoning_levels":['
            '{"effort":"medium"},{"effort":"ultra"}]},'
            '{"slug":"hidden","visibility":"hide","supported_reasoning_levels":[]}'
            "]}",
        )

    monkeypatch.setattr(codex_model_catalog.subprocess, "run", fake_run)

    first = codex_model_catalog.get_codex_model_catalog("codex", tmp_path, configured_options=["gpt-5.4"])
    second = codex_model_catalog.get_codex_model_catalog("codex", tmp_path, configured_options=["gpt-5.4"])

    assert first == second
    assert first["source"] == "codex_cli"
    assert [item["id"] for item in first["items"]] == ["gpt-5.6-sol", "none"]
    assert first["items"][0]["reasoning_efforts"] == ["medium", "ultra"]
    assert len(calls) == 1


def test_codex_model_catalog_falls_back_to_config(monkeypatch, tmp_path: Path) -> None:
    codex_model_catalog.clear_codex_model_catalog_cache()
    monkeypatch.setattr(codex_model_catalog, "resolve_cli_executable", lambda *_args: None)

    result = codex_model_catalog.get_codex_model_catalog(
        "missing-codex",
        tmp_path,
        configured_options=["gpt-5.4", "none"],
    )

    assert result["source"] == "config"
    assert [item["id"] for item in result["items"]] == ["gpt-5.4", "none"]


class _Manager:
    def __init__(self, profile: BotProfile) -> None:
        self.main_profile = profile
        self.managed_profiles = {}

    async def set_bot_cli_param(self, _alias: str, cli_type: str, key: str, value) -> None:
        self.main_profile.cli_params.set_param(cli_type, key, coerce_param_value(cli_type, key, value))


@pytest.mark.asyncio
async def test_cli_model_update_rejects_unavailable_model_and_normalizes_effort(monkeypatch, tmp_path: Path) -> None:
    profile = BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path))
    profile.cli_params.codex.update({"model": "gpt-5.6-sol", "reasoning_effort": "ultra"})
    manager = _Manager(profile)
    monkeypatch.setattr(api_service, "_codex_catalog_for_profile", lambda _profile: _live_catalog())

    with pytest.raises(WebApiError) as exc_info:
        await api_service.update_cli_params(manager, "main", "codex", "model", "gpt-5.6")
    assert exc_info.value.code == "unsupported_codex_model"

    result = await api_service.update_cli_params(manager, "main", "codex", "model", "gpt-5.5")

    assert result["params"]["model"] == "gpt-5.5"
    assert result["params"]["reasoning_effort"] == "medium"
    assert result["schema"]["model"]["enum"] == ["gpt-5.5", "gpt-5.6-sol", "none"]


@pytest.mark.asyncio
async def test_cli_reasoning_update_rejects_effort_not_supported_by_selected_model(monkeypatch, tmp_path: Path) -> None:
    profile = BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path))
    profile.cli_params.codex.update({"model": "gpt-5.5", "reasoning_effort": "medium"})
    manager = _Manager(profile)
    monkeypatch.setattr(api_service, "_codex_catalog_for_profile", lambda _profile: _live_catalog())

    with pytest.raises(WebApiError) as exc_info:
        await api_service.update_cli_params(manager, "main", "codex", "reasoning_effort", "ultra")

    assert exc_info.value.code == "unsupported_codex_reasoning_effort"
