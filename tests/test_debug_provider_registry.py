from __future__ import annotations

from pathlib import Path

import pytest

from bot.debug.profile_loader import load_debug_profile_v3
from bot.debug.providers.base import DebugProvider, DebugProviderSession
from bot.debug.providers.registry import DebugProviderRegistry, build_default_provider_registry


class FakeSession(DebugProviderSession):
    async def launch(self, payload: dict[str, object]) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def continue_execution(self) -> None:
        return None

    async def pause(self) -> None:
        return None

    async def next(self) -> None:
        return None

    async def step_in(self) -> None:
        return None

    async def step_out(self) -> None:
        return None

    async def set_breakpoints(self, source: str, breakpoints: list[dict[str, object]]) -> list[dict[str, object]]:
        return []

    async def stack_trace(self) -> list[dict[str, object]]:
        return []

    async def scopes(self, frame_id: str) -> list[dict[str, object]]:
        return []

    async def variables(self, variables_reference: str) -> list[dict[str, object]]:
        return []

    async def evaluate(self, expression: str, frame_id: str = "") -> dict[str, object]:
        return {}

    async def events(self):
        if False:
            yield {}

    async def close(self) -> None:
        return None


class FakeProvider(DebugProvider):
    provider_id = "python-debugpy"
    provider_label = "Python debugpy"

    def can_handle(self, profile) -> bool:
        return profile.provider_id == self.provider_id

    def create_session(self, profile):
        return FakeSession()


def test_registry_selects_provider_by_provider_id(tmp_path: Path) -> None:
    (tmp_path / "debug.json").write_text(
        '{"specVersion":3,"providerId":"python-debugpy","language":"python","target":{"program":"${workspaceFolder}/main.py","cwd":"${workspaceFolder}"}}',
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    profile = load_debug_profile_v3(tmp_path)
    assert profile is not None
    registry = DebugProviderRegistry([FakeProvider()])

    provider = registry.require_provider(profile)

    assert provider.provider_id == "python-debugpy"


def test_registry_errors_when_provider_is_missing(tmp_path: Path) -> None:
    (tmp_path / "debug.json").write_text(
        '{"specVersion":3,"providerId":"node-dap","language":"javascript","target":{"program":"${workspaceFolder}/main.js","cwd":"${workspaceFolder}"}}',
        encoding="utf-8",
    )
    (tmp_path / "main.js").write_text("console.log(1)\n", encoding="utf-8")
    profile = load_debug_profile_v3(tmp_path)
    assert profile is not None
    registry = DebugProviderRegistry([FakeProvider()])

    with pytest.raises(LookupError) as exc_info:
        registry.require_provider(profile)

    assert "node-dap" in str(exc_info.value)


def test_default_registry_can_select_godot_provider(tmp_path: Path) -> None:
    (tmp_path / "debug.json").write_text(
        '{"specVersion":3,"providerId":"godot","language":"gdscript","target":{"program":"godot","cwd":"${workspaceFolder}"}}',
        encoding="utf-8",
    )
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    profile = load_debug_profile_v3(tmp_path)
    assert profile is not None

    provider = build_default_provider_registry().require_provider(profile)

    assert provider.provider_id == "godot"
