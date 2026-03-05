"""
管理员命令处理器测试

导入真实的 admin handler 函数进行测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.admin import (
    bot_add,
    bot_help,
    bot_list,
    bot_remove,
    bot_set_cli,
    bot_set_workdir,
    bot_start,
    bot_stop,
    restart_main,
)


class TestBotHelp:
    """测试 bot_help"""

    @pytest.mark.asyncio
    async def test_help_authorized(self, mock_update, mock_context):
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "管理命令" in call_text or "Bot" in call_text

    @pytest.mark.asyncio
    async def test_help_unauthorized(self, mock_update, mock_context):
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=False):
            await bot_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_called()


class TestBotList:
    """测试 bot_list"""

    @pytest.mark.asyncio
    async def test_list(self, mock_update, mock_context):
        manager_mock = MagicMock()
        manager_mock.get_status_lines.return_value = ["<b>📊 Bot 状态概览</b>", "主 Bot"]
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock):
            await bot_list(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        # 验证使用了 HTML parse_mode
        call_args = mock_update.message.reply_text.call_args
        assert call_args.kwargs.get("parse_mode") == "HTML"


class TestBotAdd:
    """测试 bot_add"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_add(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "用法" in call_text

    @pytest.mark.asyncio
    async def test_add_success(self, mock_update, mock_context):
        mock_context.args = ["alias1", "tok123"]
        manager_mock = MagicMock()
        profile_mock = MagicMock()
        profile_mock.alias = "alias1"
        profile_mock.cli_type = "kimi"
        profile_mock.cli_path = "kimi"
        profile_mock.working_dir = "/tmp"
        manager_mock.add_bot = AsyncMock(return_value=profile_mock)
        manager_mock.applications = {"alias1": MagicMock(bot_data={"bot_username": "test_bot"})}
        msg_mock = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=msg_mock)

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch("bot.handlers.admin.safe_edit_text", new_callable=AsyncMock):
            await bot_add(mock_update, mock_context)


class TestBotRemove:
    """测试 bot_remove"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_remove(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "用法" in call_text

    @pytest.mark.asyncio
    async def test_remove_success(self, mock_update, mock_context):
        mock_context.args = ["sub1"]
        manager_mock = MagicMock()
        manager_mock.remove_bot = AsyncMock()
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock):
            await bot_remove(mock_update, mock_context)
        mock_update.message.reply_text.assert_called()


class TestBotStartStop:
    """测试 bot_start 和 bot_stop"""

    @pytest.mark.asyncio
    async def test_start_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_start(mock_update, mock_context)
        assert "用法" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_stop_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_stop(mock_update, mock_context)
        assert "用法" in mock_update.message.reply_text.call_args[0][0]


class TestBotSetCli:
    """测试 bot_set_cli"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_set_cli(mock_update, mock_context)
        assert "用法" in mock_update.message.reply_text.call_args[0][0]


class TestBotSetWorkdir:
    """测试 bot_set_workdir"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True):
            await bot_set_workdir(mock_update, mock_context)
        assert "用法" in mock_update.message.reply_text.call_args[0][0]
