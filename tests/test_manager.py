"""
Bot 管理器测试

测试 MultiBotManager 的配置加载/保存和验证逻辑
（不测试 Telegram API 调用，只测试纯逻辑部分）
"""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import app_settings
from bot.config import BOT_ALIAS_RE, RESERVED_ALIASES
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.sessions import get_or_create_session


class TestManagerLoadSave:
    """测试配置加载和保存"""

    def test_load_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "sub1",
                    "token": "tok1",
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                }
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert "sub1" in m.managed_profiles
        assert m.managed_profiles["sub1"].token == "tok1"

    def test_save_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1", token="tok1", cli_type="claude",
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
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        with patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            await manager.add_bot(
                "native1",
                "",
                "codex",
                "missing-cli",
                str(temp_dir),
                "cli",
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

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        profile = restored.managed_profiles["native1"]

        assert profile.supported_execution_modes == ["native_agent"]
        assert profile.default_execution_mode == "native_agent"
        assert profile.native_agent == {"backend": "pi", "pi_agent": "reviewer"}

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

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(old_dir)), str(storage))
        await manager.set_bot_workdir("main", str(new_dir))

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(old_dir)), str(storage))

        assert restored.main_profile.working_dir == str(new_dir)

    @pytest.mark.asyncio
    async def test_main_bot_execution_config_coerces_to_single_backend_and_persists_native_fields(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))
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

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))

        assert restored.main_profile.supported_execution_modes == ["native_agent"]
        assert restored.main_profile.default_execution_mode == "native_agent"
        assert restored.main_profile.native_agent == {"backend": "pi", "pi_agent": "main"}

    @pytest.mark.asyncio
    async def test_native_agent_bot_config_ignores_global_provider_fields(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))

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
                token="main_tok",
                working_dir=str(temp_dir),
                supported_execution_modes=["native_agent"],
                default_execution_mode="native_agent",
            ),
            str(storage),
        )

        await manager.set_bot_native_agent_model("main", "jojocode/gpt-5.4", "high")
        restored = MultiBotManager(
            BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)),
            str(storage),
        )

        assert restored.main_profile.native_agent == {
            "backend": "pi",
            "model": "jojocode/gpt-5.4",
            "reasoning_effort": "high",
        }

    @pytest.mark.asyncio
    async def test_background_services_do_not_start_native_agent_server(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))

        await manager.start_background_services(result_executor=AsyncMock(return_value={}))
        await manager.shutdown_all()

        assert "NATIVE_AGENT_SERVER_" + "MANAGER" not in vars(__import__("bot.manager").manager)

    @pytest.mark.asyncio
    async def test_background_services_skip_native_bot_workdir_prewarm(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        native_dir = temp_dir / "native"
        native_dir.mkdir()
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))
        manager.managed_profiles["agent-test"] = BotProfile(
            alias="agent-test",
            token="",
            working_dir=str(native_dir),
            supported_execution_modes=["native_agent"],
            default_execution_mode="native_agent",
        )

        await manager.start_background_services(result_executor=AsyncMock(return_value={}))
        await manager.shutdown_all()

        assert manager.managed_profiles["agent-test"].default_execution_mode == "native_agent"

    @pytest.mark.asyncio
    async def test_background_services_do_not_run_stale_native_cleanup(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(temp_dir)), str(storage))

        await manager.start_background_services(result_executor=AsyncMock(return_value={}))
        await manager.shutdown_all()

        assert "NATIVE_AGENT_SERVER_" + "MANAGER" not in vars(__import__("bot.manager").manager)
