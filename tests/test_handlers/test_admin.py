"""
管理员命令处理器测试

导入真实的 admin handler 函数进行测试
"""

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.admin import (
    bot_add,
    bot_goto_callback,
    bot_help,
    bot_list,
    bot_params,
    bot_remove,
    bot_set_cli,
    bot_set_workdir,
    bot_start,
    bot_stop,
    execute_script,
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


class TestBotParams:
    """测试 bot_params"""

    @pytest.mark.asyncio
    async def test_reply_with_effective_message(self, mock_update, mock_context):
        mock_context.args = ["main"]
        manager_mock = MagicMock()
        manager_mock.main_profile.alias = "main"
        manager_mock.managed_profiles = {}
        manager_mock.get_bot_cli_params = AsyncMock(return_value={"claude": {"effort": "high"}})

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch("bot.cli_params.format_params_display", return_value="<b>claude</b>"):
            await bot_params(mock_update, mock_context)


class TestBotGotoCallback:
    """测试 goto 回调"""

    @pytest.mark.asyncio
    async def test_uses_main_bot_session_signature_correctly(self, mock_update, mock_context, temp_dir):
        query = MagicMock()
        query.data = "goto:main"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        mock_update.callback_query = query

        manager_mock = MagicMock()
        manager_mock.main_profile.alias = "main"
        manager_mock.main_profile.working_dir = str(temp_dir)
        manager_mock.applications = {"main": MagicMock(bot_data={"bot_id": 123})}
        manager_mock.managed_profiles = {}

        session_mock = MagicMock()
        session_mock.working_dir = "C:/old"

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch("bot.sessions.get_or_create_session", autospec=True, return_value=session_mock) as mock_get_session:
            await bot_goto_callback(mock_update, mock_context)

        mock_get_session.assert_called_once_with(
            123,
            "main",
            mock_update.effective_user.id,
            default_working_dir=str(temp_dir),
        )
        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_effective_message_does_not_crash(self, mock_update, mock_context):
        mock_context.args = ["main"]
        mock_update.effective_message = None
        mock_update.message = None

        manager_mock = MagicMock()
        manager_mock.main_profile.alias = "main"
        manager_mock.managed_profiles = {}
        manager_mock.get_bot_cli_params = AsyncMock(return_value={"claude": {"effort": "high"}})

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch("bot.cli_params.format_params_display", return_value="<b>claude</b>"):
            await bot_params(mock_update, mock_context)


class TestExecuteScript:
    """测试系统脚本执行"""

    def test_powershell_invocation_uses_noninteractive_mode_and_decodes_gbk_errors(self):
        script_path = Path("scripts/turn_off_monitor.ps1")
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=1,
                stdout=b"",
                stderr="脚本错误".encode("gbk"),
            )

        with patch("bot.handlers.admin.subprocess.run", side_effect=fake_run):
            success, output = execute_script(script_path)

        assert success is False
        assert output == "执行失败: 脚本错误"
        assert captured["args"][0][:5] == [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
        ]
        assert captured["kwargs"]["text"] is False


