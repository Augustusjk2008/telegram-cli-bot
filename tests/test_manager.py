"""
Bot 管理器测试

测试 MultiBotManager 的配置加载/保存和验证逻辑
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot import app_settings
from bot.manager import MultiBotManager
from bot.models import BotProfile


class TestManagerLoadSave:
    """测试配置加载和保存"""

    def test_legacy_bot_mode_is_ignored_without_runtime_surface(self):
        profile = BotProfile.from_dict({"alias": "legacy", "bot_mode": "assistant"})

        assert not hasattr(profile, "bot_mode")
        assert "bot_mode" not in profile.to_dict()

    def test_load_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "sub1",
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                }
            ]
        }))
        profile = BotProfile(alias="main")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert "sub1" in m.managed_profiles

    def test_save_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        profile = BotProfile(alias="main")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1", cli_type="claude",
            cli_path="claude", working_dir=str(temp_dir),
        )
        m._save_profiles()
        data = json.loads(storage.read_text(encoding="utf-8"))
        assert "bots" in data
        assert isinstance(data["bots"], list)
        assert len(data["bots"]) == 1
        assert data["bots"][0]["alias"] == "sub1"

    @pytest.mark.asyncio
    async def test_agent_crud_is_scoped_to_existing_cli_bot(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))

        created = await manager.create_bot_agent(
            "main",
            {"id": "reviewer", "name": "代码审查", "system_prompt": "先审查"},
        )
        updated = await manager.update_bot_agent("main", "reviewer", {"enabled": False})

        assert created["id"] == "reviewer"
        assert updated["enabled"] is False
        assert manager.get_profile("main").get_agent("reviewer").system_prompt == "先审查"

        await manager.delete_bot_agent("main", "reviewer")

        with pytest.raises(KeyError):
            manager.get_profile("main").get_agent("reviewer")

    @pytest.mark.asyncio
    async def test_add_native_agent_bot_skips_cli_validation_and_persists_native_config(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main"), str(storage))

        await manager.add_bot(
            "native1",
            "codex",
            "missing-cli",
            str(temp_dir),
            supported_execution_modes=["native_agent"],
            default_execution_mode="native_agent",
            native_agent={
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "pi_agent": "reviewer",
                "base_url": "https://cdn.codeflow.asia/v1",
                "api_key": "sk-create-1234",
            },
        )

        restored = MultiBotManager(BotProfile(alias="main"), str(storage))
        profile = restored.managed_profiles["native1"]

        assert profile.supported_execution_modes == ["native_agent"]
        assert profile.default_execution_mode == "native_agent"
        assert profile.native_agent == {"backend": "pi", "pi_agent": "reviewer"}

    @pytest.mark.asyncio
    async def test_add_bot_defaults_yolo_false_without_persisting_cli_params(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main"), str(storage))

        with patch("bot.manager.resolve_cli_executable", return_value="codex"):
            profile = await manager.add_bot(
                "safe1",
                "codex",
                "codex",
                str(temp_dir),
            )

        data = json.loads(storage.read_text(encoding="utf-8"))
        assert profile.cli_params.get_param("codex", "yolo") is False
        assert "cli_params" not in data["bots"][0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cli_type", ["codex", "claude"])
    async def test_add_bot_persists_bypass_approval_and_sandbox_yolo(self, temp_dir: Path, cli_type: str):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main"), str(storage))

        with patch("bot.manager.resolve_cli_executable", return_value=cli_type):
            await manager.add_bot(
                f"{cli_type}unsafe",
                cli_type,
                cli_type,
                str(temp_dir),
                bypass_approval_and_sandbox=True,
            )

        data = json.loads(storage.read_text(encoding="utf-8"))
        assert data["bots"][0]["cli_params"][cli_type]["yolo"] is True

        restored = MultiBotManager(BotProfile(alias="main"), str(storage))
        assert restored.managed_profiles[f"{cli_type}unsafe"].cli_params.get_param(cli_type, "yolo") is True

class TestManagerValidation:
    """测试验证逻辑"""

    @pytest.mark.asyncio
    async def test_main_bot_workdir_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        manager = MultiBotManager(BotProfile(alias="main", working_dir=str(old_dir)), str(storage))
        await manager.set_bot_workdir("main", str(new_dir))

        restored = MultiBotManager(BotProfile(alias="main", working_dir=str(old_dir)), str(storage))

        assert restored.main_profile.working_dir == str(new_dir)

    @pytest.mark.asyncio
    async def test_main_bot_execution_config_coerces_to_single_backend_and_persists_native_fields(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))
        await manager.set_bot_execution_config(
            "main",
            {
                "supported_execution_modes": ["cli", "native_agent"],
                "default_execution_mode": "native_agent",
                "native_agent": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5",
                    "pi_agent": "reviewer",
                    "baseUrl": "https://cdn.codeflow.asia/v1",
                    "apiKey": "sk-old-1234",
                },
            },
        )
        assert manager.main_profile.supported_execution_modes == ["native_agent"]
        assert manager.main_profile.default_execution_mode == "native_agent"
        await manager.set_bot_execution_config(
            "main",
            {
                "supported_execution_modes": ["cli", "native_agent"],
                "default_execution_mode": "cli",
                "native_agent": {
                    "provider": "openai",
                    "model": "gpt-5",
                    "pi_agent": "planner",
                    "base_url": "https://api.example.test/v1",
                },
            },
        )
        assert manager.main_profile.native_agent == {"pi_agent": "planner"}
        await manager.set_bot_execution_config(
            "main",
            {
                "supported_execution_modes": ["native_agent"],
                "default_execution_mode": "native_agent",
                "native_agent": {
                    "provider": "codeflow",
                    "model": "gpt-5.1-codex",
                    "pi_agent": "main",
                    "base_url": "https://cdn.codeflow.asia/v1",
                    "api_key": "sk-new-5678",
                },
            },
        )
        assert manager.main_profile.native_agent == {"pi_agent": "main"}
        await manager.set_bot_execution_config(
            "main",
            {
                "supported_execution_modes": ["native_agent"],
                "default_execution_mode": "native_agent",
                "native_agent": {
                    "provider": "codeflow",
                    "model": "gpt-5.1-codex",
                    "pi_agent": "main",
                    "base_url": "https://cdn.codeflow.asia/v1",
                    "clear_api_key": True,
                },
            },
        )

        restored = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))

        assert restored.main_profile.supported_execution_modes == ["native_agent"]
        assert restored.main_profile.default_execution_mode == "native_agent"
        assert restored.main_profile.native_agent == {"backend": "pi", "pi_agent": "main"}

    @pytest.mark.asyncio
    async def test_native_agent_bot_config_ignores_global_provider_fields(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))

        await manager.set_bot_execution_config(
            "main",
            {
                "supported_execution_modes": ["native_agent"],
                "default_execution_mode": "native_agent",
                "native_agent": {
                    "provider": "codeflow",
                    "model": "gpt-5.1-codex",
                    "base_url": "file:///secret",
                    "api_key": "sk-ignored",
                    "pi_agent": "reviewer",
                },
            },
        )

        assert manager.main_profile.native_agent == {"pi_agent": "reviewer"}

    @pytest.mark.asyncio
    async def test_native_agent_model_selection_persists(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(
            BotProfile(
                alias="main",
                working_dir=str(temp_dir),
                supported_execution_modes=["native_agent"],
                default_execution_mode="native_agent",
            ),
            str(storage),
        )

        await manager.set_bot_native_agent_model("main", "jojocode/gpt-5.4", "high")
        restored = MultiBotManager(
            BotProfile(alias="main", working_dir=str(temp_dir)),
            str(storage),
        )

        assert restored.main_profile.native_agent == {
            "backend": "pi",
            "model": "jojocode/gpt-5.4",
            "reasoning_effort": "high",
        }
