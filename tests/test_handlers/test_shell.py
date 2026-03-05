"""
Shell 命令处理器测试

导入真实的 shell handler 进行测试
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.shell import execute_shell


class TestExecuteShell:
    """测试 execute_shell"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.shell.check_auth", return_value=True):
            await execute_shell(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "用法" in call_text

    @pytest.mark.asyncio
    async def test_unauthorized(self, mock_update, mock_context):
        mock_context.args = ["ls"]
        with patch("bot.handlers.shell.check_auth", return_value=False):
            await execute_shell(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_dangerous_command(self, mock_update, mock_context):
        mock_context.args = ["rm", "-rf", "/"]
        with patch("bot.handlers.shell.check_auth", return_value=True):
            await execute_shell(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "禁止" in call_text

    @pytest.mark.asyncio
    async def test_safe_command(self, mock_update, mock_context, temp_dir):
        mock_context.args = ["echo", "hello"]
        msg_mock = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=msg_mock)
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)

        import subprocess
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("bot.handlers.shell.check_auth", return_value=True), \
             patch("bot.handlers.shell.get_current_session", return_value=session_mock), \
             patch("bot.handlers.shell.safe_edit_text", new_callable=AsyncMock) as mock_edit, \
             patch("asyncio.get_running_loop") as mock_loop:
            future = asyncio.Future()
            future.set_result(mock_result)
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_result)
            await execute_shell(mock_update, mock_context)
