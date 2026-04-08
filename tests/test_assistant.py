"""测试助手模式功能"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models import BotProfile


class TestAssistantMode:
    """测试助手模式的基础功能"""

    def test_bot_profile_with_bot_mode(self):
        """测试 BotProfile 支持 bot_mode 字段"""
        profile = BotProfile(
            alias="test_assistant",
            token="test_token",
            bot_mode="assistant"
        )
        assert profile.bot_mode == "assistant"
        assert profile.to_dict()["bot_mode"] == "assistant"

    def test_bot_profile_default_bot_mode(self):
        """测试 BotProfile 默认 bot_mode 为 cli"""
        profile = BotProfile(
            alias="test_cli",
            token="test_token"
        )
        assert profile.bot_mode == "cli"
        assert profile.to_dict()["bot_mode"] == "cli"


class TestAssistantHandler:
    """测试助手处理器"""

    @pytest.mark.asyncio
    async def test_assistant_handler_without_anthropic(self, mock_update, mock_context):
        """测试在没有 anthropic SDK 时的错误处理"""
        with patch("bot.handlers.assistant.ANTHROPIC_AVAILABLE", False):
            from bot.handlers.assistant import handle_assistant_message

            mock_update.message.text = "你好"
            await handle_assistant_message(mock_update, mock_context)

            # 应该回复错误消息
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "anthropic SDK 未安装" in call_args

    @pytest.mark.asyncio
    async def test_assistant_handler_with_api_call(self, mock_update, mock_context):
        """测试助手处理器调用 API"""
        with patch("bot.handlers.assistant.ANTHROPIC_AVAILABLE", True):
            with patch("bot.handlers.assistant.call_claude_api") as mock_api:
                mock_api.return_value = "这是 AI 的回复"

                from bot.handlers.assistant import handle_assistant_message

                mock_update.message.text = "你好"
                await handle_assistant_message(mock_update, mock_context)

                # 应该调用 API
                mock_api.assert_called_once()
                call_kwargs = mock_api.call_args[1]
                assert "messages" in call_kwargs
                assert call_kwargs["messages"][-1]["content"] == "你好"

                # 应该回复 AI 的消息
                assert mock_update.message.reply_text.call_count >= 1


class TestRegisterHandlers:
    """测试 handler 注册逻辑"""

    def test_register_cli_handlers(self):
        """测试注册 CLI 模式的 handlers"""
        from bot.handlers import register_handlers

        app = MagicMock()
        app.bot_data = {"bot_mode": "cli"}
        app.add_handler = MagicMock()

        register_handlers(app, include_admin=False)

        # 应该注册了多个 handler
        assert app.add_handler.call_count > 0

        command_handlers = [
            call.args[0]
            for call in app.add_handler.call_args_list
            if hasattr(call.args[0], "commands")
        ]
        assert any("kill" in handler.commands for handler in command_handlers)

    def test_register_assistant_handlers(self):
        """测试注册助手模式的 handlers"""
        from bot.handlers import register_handlers

        app = MagicMock()
        app.bot_data = {"bot_mode": "assistant"}
        app.add_handler = MagicMock()

        register_handlers(app, include_admin=False)

        # 应该注册了 handler
        assert app.add_handler.call_count > 0


class TestMultiBotManagerWithAssistant:
    """测试 MultiBotManager 对助手模式的支持"""

    @pytest.mark.asyncio
    async def test_load_assistant_profile_from_json(self, temp_dir):
        """测试从 JSON 加载助手 bot 配置"""
        import json
        from bot.manager import MultiBotManager

        # 创建测试配置文件
        config_file = temp_dir / "test_bots.json"
        config_data = {
            "bots": [
                {
                    "alias": "assistant1",
                    "token": "test_token_123",
                    "bot_mode": "assistant",
                    "working_dir": str(temp_dir),
                    "enabled": True
                }
            ]
        }
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        # 创建主 bot profile
        main_profile = BotProfile(
            alias="main",
            token="main_token",
            working_dir=str(temp_dir)
        )

        # 加载配置
        manager = MultiBotManager(main_profile, str(config_file))

        # 验证加载的配置
        assert "assistant1" in manager.managed_profiles
        profile = manager.managed_profiles["assistant1"]
        assert profile.bot_mode == "assistant"
        assert profile.alias == "assistant1"
        assert profile.enabled is True

    @pytest.mark.asyncio
    async def test_add_assistant_bot(self, temp_dir):
        """测试通过 add_bot 添加助手 bot"""
        from bot.manager import MultiBotManager

        config_file = temp_dir / "test_bots.json"
        main_profile = BotProfile(
            alias="main",
            token="main_token",
            working_dir=str(temp_dir)
        )

        manager = MultiBotManager(main_profile, str(config_file))

        # 模拟 _start_profile 方法
        with patch.object(manager, "_start_profile", new_callable=AsyncMock):
            profile = await manager.add_bot(
                alias="test_assistant",
                token="test_token",
                working_dir=str(temp_dir),
                bot_mode="assistant"
            )

            assert profile.bot_mode == "assistant"
            assert profile.alias == "test_assistant"
            assert "test_assistant" in manager.managed_profiles

    def test_load_legacy_webcli_profile_falls_back_to_cli(self, temp_dir):
        """测试旧 webcli 配置加载时显式回退到 cli"""
        import json
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

        manager = MultiBotManager(BotProfile(alias="main", token="main_token", working_dir=str(temp_dir)), str(config_file))
        assert manager.managed_profiles["legacy_web"].bot_mode == "cli"

    @pytest.mark.asyncio
    async def test_add_webcli_bot_is_rejected(self, temp_dir):
        """测试新增 webcli bot 被显式拒绝"""
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
