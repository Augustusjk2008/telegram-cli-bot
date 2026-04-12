"""
基础命令处理器测试

导入真实的 basic handler 函数进行测试
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_state import attach_assistant_persist_hook
from bot.handlers.basic import (
    change_directory,
    codex_status,
    handle_keyboard_command,
    list_directory,
    print_working_directory,
    reset,
    show_history,
    start,
)
from bot.sessions import get_or_create_session


class TestStartHandler:
    """测试 /start"""

    @pytest.mark.asyncio
    async def test_start_responds(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True):
            await start(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_help_mentions_files_command(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True):
            await start(mock_update, mock_context)

        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "/files" in call_text

    @pytest.mark.asyncio
    async def test_start_help_mentions_codex_status_command(self, mock_update, mock_context):
        with patch("bot.handlers.basic.check_auth", return_value=True):
            await start(mock_update, mock_context)

        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "/codex_status" in call_text

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

    @pytest.mark.asyncio
    async def test_reset_assistant_clears_private_runtime_state(self, mock_update, mock_context, temp_dir):
        workdir = temp_dir / "assistant-root"
        workdir.mkdir()
        state_file = workdir / ".assistant" / "state" / "users" / f"{mock_update.effective_user.id}.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{}", encoding="utf-8")
        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"
        profile_mock.working_dir = str(workdir)

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_bot_id", return_value=111), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.basic.reset_session", return_value=False) as reset_mock, \
             patch("bot.handlers.basic.bootstrap_assistant_home") as bootstrap_mock, \
             patch("bot.handlers.basic.clear_assistant_runtime_state", return_value=True) as clear_mock:
            home = MagicMock()
            bootstrap_mock.return_value = home
            await reset(mock_update, mock_context)

        bootstrap_mock.assert_called_once_with(str(workdir))
        clear_mock.assert_called_once_with(home, mock_update.effective_user.id)
        reset_mock.assert_called_once_with(111, mock_update.effective_user.id)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_assistant_noop_does_not_bootstrap_home(self, mock_update, mock_context, temp_dir):
        workdir = temp_dir / "assistant-root"
        workdir.mkdir()
        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"
        profile_mock.working_dir = str(workdir)

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_bot_id", return_value=111), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.basic.reset_session", return_value=False), \
             patch("bot.handlers.basic.bootstrap_assistant_home") as bootstrap_mock, \
             patch("bot.handlers.basic.clear_assistant_runtime_state") as clear_mock:
            await reset(mock_update, mock_context)

        bootstrap_mock.assert_not_called()
        clear_mock.assert_not_called()
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_assistant_with_live_session_does_not_recreate_state_file(
        self,
        mock_update,
        mock_context,
        temp_dir,
    ):
        workdir = temp_dir / "assistant-root"
        workdir.mkdir()
        user_id = mock_update.effective_user.id
        bot_id = 111

        home = bootstrap_assistant_home(workdir)
        session = get_or_create_session(
            bot_id=bot_id,
            bot_alias="main",
            user_id=user_id,
            default_working_dir=str(workdir),
            load_persisted_state=False,
        )
        attach_assistant_persist_hook(session, home, user_id)
        session.add_to_history("user", "hello")
        state_file = home.root / "state" / "users" / f"{user_id}.json"
        assert state_file.exists()

        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"
        profile_mock.working_dir = str(workdir)

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.basic.get_bot_id", return_value=bot_id):
            await reset(mock_update, mock_context)

        assert not state_file.exists()
        session.clear_running_reply()
        assert not state_file.exists()


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

    @pytest.mark.asyncio
    async def test_cd_sub_bot_persists_workdir(self, mock_update, mock_context, temp_dir):
        mock_context.args = [str(temp_dir)]
        mock_context.application.bot_data["is_main"] = False
        mock_context.application.bot_data["bot_alias"] = "sub1"
        mock_context.application.bot_data["manager"].set_bot_workdir = AsyncMock()

        session_mock = MagicMock()
        session_mock.working_dir = "C:/old"

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await change_directory(mock_update, mock_context)

        mock_context.application.bot_data["manager"].set_bot_workdir.assert_awaited_once_with("sub1", str(temp_dir))
        assert session_mock.working_dir == str(temp_dir)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cd_sub_bot_persist_failure_returns_error(self, mock_update, mock_context, temp_dir):
        mock_context.args = [str(temp_dir)]
        mock_context.application.bot_data["is_main"] = False
        mock_context.application.bot_data["bot_alias"] = "sub1"
        mock_context.application.bot_data["manager"].set_bot_workdir = AsyncMock(
            side_effect=ValueError("写入 managed_bots.json 失败")
        )

        session_mock = MagicMock()
        session_mock.working_dir = "C:/old"

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await change_directory(mock_update, mock_context)

        assert session_mock.working_dir == "C:/old"
        reply_text = mock_update.message.reply_text.call_args[0][0]
        assert "子Bot工作目录保存失败" in reply_text


    @pytest.mark.asyncio
    async def test_cd_clears_session_ids(self, mock_update, mock_context, temp_dir):
        """测试切换目录时清除会话ID"""
        mock_context.args = [str(temp_dir)]
        
        # 创建一个有 session_id 的会话 mock
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir.parent)
        
        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock):
            await change_directory(mock_update, mock_context)
        
        # 验证 clear_session_ids 被调用
        session_mock.clear_session_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_cd_assistant_mode_rejects_workdir_change(self, mock_update, mock_context, temp_dir):
        mock_context.args = [str(temp_dir)]
        session_mock = MagicMock()
        session_mock.working_dir = "C:/locked"

        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock):
            await change_directory(mock_update, mock_context)

        reply_text = mock_update.message.reply_text.call_args[0][0]
        assert "不允许修改工作目录" in reply_text
        assert session_mock.working_dir == "C:/locked"
        session_mock.clear_session_ids.assert_not_called()


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


class TestCodexStatus:
    """测试 /codex_status"""

    @pytest.mark.asyncio
    async def test_codex_status_rejects_non_codex_cli(self, mock_update, mock_context):
        profile_mock = MagicMock()
        profile_mock.cli_type = "claude"

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock):
            await codex_status(mock_update, mock_context)

        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "不是 Codex" in call_text

    @pytest.mark.asyncio
    async def test_codex_status_returns_status_line(self, mock_update, mock_context, temp_dir):
        profile_mock = MagicMock()
        profile_mock.cli_type = "codex"
        profile_mock.cli_path = "codex"
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock), \
             patch(
                 "bot.handlers.basic.read_codex_status_from_terminal",
                 return_value={"ok": True, "status_line": "100% context left"},
             ):
            await codex_status(mock_update, mock_context)

        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "100% context left" in call_text

    @pytest.mark.asyncio
    async def test_codex_status_returns_error_message(self, mock_update, mock_context, temp_dir):
        profile_mock = MagicMock()
        profile_mock.cli_type = "codex"
        profile_mock.cli_path = "codex"
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)

        with patch("bot.handlers.basic.check_auth", return_value=True), \
             patch("bot.handlers.basic.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.basic.get_current_session", return_value=session_mock), \
             patch(
                 "bot.handlers.basic.read_codex_status_from_terminal",
                 return_value={"ok": False, "error": "timeout"},
             ):
            await codex_status(mock_update, mock_context)

        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "查询 Codex 状态失败" in call_text


class TestKeyboardCommands:
    """测试快捷键盘命令映射"""

    @pytest.mark.asyncio
    async def test_keyboard_files_button_routes_to_file_browser(self, mock_update, mock_context):
        mock_update.message.text = "文件浏览"
        browser_module = SimpleNamespace(show_file_browser=AsyncMock())

        with patch.dict(sys.modules, {"bot.handlers.file_browser": browser_module}):
            await handle_keyboard_command(mock_update, mock_context)

        browser_module.show_file_browser.assert_awaited_once_with(mock_update, mock_context)
