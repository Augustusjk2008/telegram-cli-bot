"""测试 assistant 模式收敛后的兼容行为。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.models import BotProfile


class TestAssistantMode:
    def test_bot_profile_keeps_assistant_mode(self):
        profile = BotProfile(alias="assistant1", token="test_token", bot_mode="assistant")
        assert profile.bot_mode == "assistant"
        assert profile.to_dict()["bot_mode"] == "assistant"

    def test_bot_profile_default_mode_is_cli(self):
        profile = BotProfile(alias="cli1", token="test_token")
        assert profile.bot_mode == "cli"
        assert profile.to_dict()["bot_mode"] == "cli"


class TestRegisterHandlers:
    def test_register_cli_handlers(self):
        from bot.handlers import register_handlers

        app = MagicMock()
        app.bot_data = {"bot_mode": "cli"}
        app.add_handler = MagicMock()

        register_handlers(app, include_admin=False)

        command_handlers = [
            call.args[0]
            for call in app.add_handler.call_args_list
            if hasattr(call.args[0], "commands")
        ]
        assert any("kill" in handler.commands for handler in command_handlers)
        assert any("codex_status" in handler.commands for handler in command_handlers)

    def test_register_assistant_handlers_match_cli_surface(self):
        from bot.handlers import register_handlers

        app = MagicMock()
        app.bot_data = {"bot_mode": "assistant"}
        app.add_handler = MagicMock()

        register_handlers(app, include_admin=False)

        command_handlers = [
            call.args[0]
            for call in app.add_handler.call_args_list
            if hasattr(call.args[0], "commands")
        ]
        assert any("kill" in handler.commands for handler in command_handlers)
        assert any("codex_status" in handler.commands for handler in command_handlers)
        assert not any("memory" in handler.commands for handler in command_handlers)
        assert not any("tool_stats" in handler.commands for handler in command_handlers)


class TestMultiBotManagerWithAssistant:
    @pytest.mark.asyncio
    async def test_load_assistant_profile_from_json(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        config_file.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "assistant1",
                            "token": "test_token_123",
                            "bot_mode": "assistant",
                            "working_dir": str(temp_dir),
                            "enabled": True,
                            "cli_type": "codex",
                            "cli_path": "codex",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = MultiBotManager(
            BotProfile(alias="main", token="main_token", working_dir=str(temp_dir)),
            str(config_file),
        )

        assert "assistant1" in manager.managed_profiles
        profile = manager.managed_profiles["assistant1"]
        assert profile.bot_mode == "assistant"
        assert profile.alias == "assistant1"
        assert profile.enabled is True

    @pytest.mark.asyncio
    async def test_add_assistant_bot(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        main_profile = BotProfile(alias="main", token="main_token", working_dir=str(temp_dir))
        manager = MultiBotManager(main_profile, str(config_file))

        with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
             patch.object(manager, "_start_profile", new_callable=AsyncMock):
            profile = await manager.add_bot(
                alias="test_assistant",
                token="test_token",
                cli_type="codex",
                cli_path="codex",
                working_dir=str(temp_dir),
                bot_mode="assistant",
            )

        assert profile.bot_mode == "assistant"
        assert profile.alias == "test_assistant"
        assert "test_assistant" in manager.managed_profiles

    def test_load_legacy_webcli_profile_falls_back_to_cli(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        config_file.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "legacy_web",
                            "token": "test_token_456",
                            "bot_mode": "webcli",
                            "working_dir": str(temp_dir),
                            "enabled": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = MultiBotManager(
            BotProfile(alias="main", token="main_token", working_dir=str(temp_dir)),
            str(config_file),
        )
        assert manager.managed_profiles["legacy_web"].bot_mode == "cli"

    @pytest.mark.asyncio
    async def test_add_webcli_bot_is_rejected(self, temp_dir):
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        manager = MultiBotManager(
            BotProfile(alias="main", token="main_token", working_dir=str(temp_dir)),
            str(config_file),
        )

        with pytest.raises(ValueError, match="webcli"):
            await manager.add_bot(
                alias="legacy_web",
                token="test_token",
                working_dir=str(temp_dir),
                bot_mode="webcli",
            )
