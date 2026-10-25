from __future__ import annotations

import json
from types import SimpleNamespace
from subprocess import TimeoutExpired

from bot import deepseek_cli


def _payload() -> dict:
    return {
        "providers": [
            {
                "id": "official",
                "label": "Official",
                "modelOptions": [{"id": "deepseek-flash", "reasoningEfforts": ["off", "high"]}],
            },
        ],
        "selectedProvider": "official",
        "selectedModel": "deepseek-flash",
        "modelOptionsByProvider": {"official": [{"id": "deepseek-flash"}]},
        "reasoningEfforts": ["off", "high"],
        "status": "ready",
    }


def _reset_cache(monkeypatch):
    monkeypatch.setattr(deepseek_cli, "_deepseek_catalog_cache", {})
    monkeypatch.setattr(deepseek_cli, "_build_deepseek_catalog_command", lambda _cli: ["fake-dsh"])
    monkeypatch.setattr(deepseek_cli, "_deepseek_catalog_fingerprint", lambda *_args: ())


def test_catalog_is_bounded_and_cached(monkeypatch):
    _reset_cache(monkeypatch)
    calls = 0

    def run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(stdout=json.dumps(_payload()), returncode=0)

    monkeypatch.setattr(deepseek_cli.subprocess, "run", run)
    first = deepseek_cli.discover_deepseek_catalog("dsh", params={})
    second = deepseek_cli.discover_deepseek_catalog("dsh", params={})

    assert calls == 1
    assert first["selectedProvider"] == second["selectedProvider"] == "official"
    assert first["modelOptionsByProvider"]["official"][0]["id"] == "deepseek-flash"


def test_catalog_timeout_returns_structured_diagnostic(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        deepseek_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutExpired("fake-dsh", 1)),
    )

    result = deepseek_cli.discover_deepseek_catalog("dsh", params={})

    assert result["status"] == "error"
    assert "超时" in result["diagnostic"]


def test_catalog_rejects_oversized_and_redacts_diagnostic(monkeypatch):
    _reset_cache(monkeypatch)
    oversized = {
        **_payload(),
        "diagnostic": "api_key=secret-value",
    }
    monkeypatch.setattr(
        deepseek_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps(oversized) + ("x" * (deepseek_cli._DEEPSEEK_CATALOG_MAX_BYTES + 1)),
            returncode=0,
        ),
    )

    result = deepseek_cli.discover_deepseek_catalog("dsh", params={})

    assert result["status"] == "error"
    assert "secret-value" not in result["diagnostic"]


def test_catalog_fallback_keeps_saved_selection(monkeypatch):
    monkeypatch.setattr(deepseek_cli, "_build_deepseek_catalog_command", lambda _cli: None)
    result = deepseek_cli.discover_deepseek_catalog(
        "custom-dsh",
        params={"provider": "legacy", "model": "legacy-model"},
        force=True,
    )

    assert result["status"] == "unavailable"
    assert result["selectedProvider"] == "legacy"
    assert result["selectedModel"] == "legacy-model"
    assert "legacy-model" in result["modelOptions"]
