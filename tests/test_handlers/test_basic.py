"""
基础命令处理器测试

导入真实的 basic handler 函数进行测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.basic import (
    change_directory,
    list_directory,
    print_working_directory,
    reset,
    show_history,
    start,
)


class TestStartHandler:
    """测试 /start"""

    @pytest.mark.asyncio
    async def test_start_responds(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True):
            await start(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_unauthorized(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=False):
            await start(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "未授权" in call_text


class TestResetHandler:
    """测试 /reset"""

    @pytest.mark.asyncio
    async def test_reset_responds(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_bot_id", return_value=111), \
             patch("bot.handlers.basic.reset_session", return_value=True):
            await reset(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_no_session(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_bot_id", return_value=111), \
             patch("bot.handlers.basic.reset_session", return_value=False):
            await reset(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()


class TestChangeDirectory:
    """测试 /cd"""

    @pytest.mark.asyncio
    async def test_cd_no_args(self, mock_update, mock_context, temp_dir):
        mock_context.args = []
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await change_directory(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cd_valid_dir(self, mock_update, mock_context, temp_dir):
        mock_context.args = [str(temp_dir)]
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await change_directory(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()


class TestPrintWorkingDirectory:
    """测试 /pwd"""

    @pytest.mark.asyncio
    async def test_pwd(self, mock_update, mock_context):
        session_mock = MagicMock()
        session_mock.working_dir = "/tmp/test"
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await print_working_directory(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "/tmp/test" in call_text


class TestListDirectory:
    """测试 /ls"""

    @pytest.mark.asyncio
    async def test_ls(self, mock_update, mock_context, temp_dir):
        (temp_dir / "file.txt").write_text("hello")
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await list_directory(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()


class TestShowHistory:
    """测试 /history"""

    @pytest.mark.asyncio
    async def test_history_empty(self, mock_update, mock_context):
        session_mock = MagicMock()
        session_mock.history = []
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await show_history(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_history_with_items(self, mock_update, mock_context):
        session_mock = MagicMock()
        session_mock.history = [
            {"role": "user", "content": "hello", "timestamp": "2024-01-01"},
            {"role": "assistant", "content": "hi", "timestamp": "2024-01-01"},
        ]
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await show_history(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "hello" in call_text or "user" in call_text.lower()
