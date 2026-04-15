"""测试 assistant 模式收敛后的兼容行为。"""

import json
from unittest.mock import AsyncMock, patch

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

    def test_load_profiles_rejects_multiple_assistant_entries(self, temp_dir):
        from bot.manager import MultiBotManager

        storage = temp_dir / "bots.json"
        root1 = temp_dir / "a1"
        root2 = temp_dir / "a2"
        root1.mkdir()
        root2.mkdir()
        storage.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "assistant1",
                            "token": "",
                            "cli_type": "codex",
                            "cli_path": "codex",
                            "working_dir": str(root1),
                            "bot_mode": "assistant",
                        },
                        {
                            "alias": "assistant2",
                            "token": "",
                            "cli_type": "codex",
                            "cli_path": "codex",
                            "working_dir": str(root2),
                            "bot_mode": "assistant",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="只允许一个 assistant"):
            MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

    def test_load_legacy_webcli_profile_falls_back_to_cli_and_rewrites_file(self, temp_dir):
        from bot.manager import MultiBotManager
        from bot.web.api_service import build_bot_summary

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
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["bots"][0]["bot_mode"] == "cli"

        summary = build_bot_summary(manager, "legacy_web")
        assert summary["bot_mode"] == "cli"
        assert "status" not in summary["capabilities"]
        assert {"chat", "exec", "files"}.issubset(summary["capabilities"])

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
