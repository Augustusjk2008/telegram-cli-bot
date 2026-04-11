"""
管理员命令处理器测试

导入真实的 admin handler 函数进行测试
"""

import subprocess
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from bot.handlers.admin import (
    assistant_approve,
    assistant_proposals,
    assistant_reject,
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
    list_available_scripts,
    restart_main,
    stream_execute_script,
)
from bot.app_settings import update_git_proxy_port


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


class TestAssistantProposalCommands:
    @pytest.mark.asyncio
    async def test_assistant_proposals_lists_items(self, mock_update, mock_context, temp_dir):
        mock_context.args = ["assistant1"]
        manager_mock = MagicMock()
        manager_mock.get_profile.return_value = MagicMock(bot_mode="assistant", working_dir=str(temp_dir))

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch(
                 "bot.handlers.admin.list_proposals",
                 return_value=[{"id": "pr_1", "title": "scope", "status": "proposed"}],
             ):
            await assistant_proposals(mock_update, mock_context)

        reply_text = mock_update.message.reply_text.call_args[0][0]
        assert "pr_1" in reply_text

    @pytest.mark.asyncio
    async def test_assistant_approve_and_reject_update_status(self, mock_update, mock_context, temp_dir):
        manager_mock = MagicMock()
        manager_mock.get_profile.return_value = MagicMock(bot_mode="assistant", working_dir=str(temp_dir))

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch(
                 "bot.handlers.admin.set_proposal_status",
                 return_value={"id": "pr_1", "status": "approved"},
             ) as set_mock:
            mock_context.args = ["assistant1", "pr_1"]
            await assistant_approve(mock_update, mock_context)
            set_mock.assert_called_with(ANY, "pr_1", "approved", reviewer=str(mock_update.effective_user.id))

        with patch("bot.handlers.admin.ensure_admin", new_callable=AsyncMock, return_value=True), \
             patch("bot.handlers.admin.get_manager", return_value=manager_mock), \
             patch(
                 "bot.handlers.admin.set_proposal_status",
                 return_value={"id": "pr_1", "status": "rejected"},
             ) as set_mock:
            mock_context.args = ["assistant1", "pr_1"]
            await assistant_reject(mock_update, mock_context)
            set_mock.assert_called_with(ANY, "pr_1", "rejected", reviewer=str(mock_update.effective_user.id))


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

    def test_list_available_scripts_only_returns_sh_and_py_on_linux(self, tmp_path, monkeypatch):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "build_web_frontend.sh").write_text("# build web\nnpm run build\n", encoding="utf-8")
        (scripts_dir / "turn_off_monitor.ps1").write_text("# monitor\n", encoding="utf-8")

        monkeypatch.setattr("bot.handlers.admin.SCRIPTS_DIR", scripts_dir)
        monkeypatch.setattr("bot.platform.runtime.os.name", "posix")

        scripts = list_available_scripts()

        assert [item[0] for item in scripts] == ["build_web_frontend"]

    def test_execute_script_uses_bash_for_sh(self):
        script_path = Path("scripts/build_web_frontend.sh")
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args[0]
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")

        with patch("bot.handlers.admin.subprocess.run", side_effect=fake_run):
            success, output = execute_script(script_path)

        assert success is True
        assert captured["args"] == ["bash", str(script_path)]

    def test_build_web_frontend_batch_is_ascii_safe_for_cmd(self):
        script_path = Path("scripts/build_web_frontend.bat")
        raw = script_path.read_bytes()
        lines = script_path.read_text(encoding="utf-8").splitlines()

        first_nonempty = next((line.strip() for line in lines if line.strip()), "")

        assert first_nonempty.lower() == "@echo off"
        assert all(byte < 128 for byte in raw)

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

    def test_execute_script_overrides_git_proxy_with_empty_values(self, temp_dir, monkeypatch):
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", settings_file)
        update_git_proxy_port("")
        script_path = Path("scripts/turn_off_monitor.ps1")
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")

        with patch("bot.handlers.admin.subprocess.run", side_effect=fake_run):
            success, output = execute_script(script_path)

        assert success is True
        assert output == "执行成功（无输出）"
        env = captured["kwargs"]["env"]
        assert env["GIT_CONFIG_COUNT"] == "2"
        assert env["GIT_CONFIG_KEY_0"] == "http.proxy"
        assert env["GIT_CONFIG_VALUE_0"] == ""
        assert env["GIT_CONFIG_KEY_1"] == "https.proxy"
        assert env["GIT_CONFIG_VALUE_1"] == ""

    def test_stream_execute_script_overrides_git_proxy_with_configured_port(self, temp_dir, monkeypatch):
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", settings_file)
        update_git_proxy_port("7897")
        script_path = Path("scripts/turn_off_monitor.ps1")
        captured: dict[str, object] = {}

        class FakeStdout:
            def __init__(self):
                self._lines = [b"building\n", b""]

            def readline(self):
                return self._lines.pop(0)

            def read(self):
                return b""

            def close(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.returncode = 0

            def poll(self):
                return 0 if not self.stdout._lines else None

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                return None

            def kill(self):
                return None

        def fake_popen(*args, **kwargs):
            captured["kwargs"] = kwargs
            return FakeProcess()

        with patch("bot.handlers.admin.subprocess.Popen", side_effect=fake_popen):
            events = list(stream_execute_script(script_path))

        env = captured["kwargs"]["env"]
        assert env["GIT_CONFIG_COUNT"] == "2"
        assert env["GIT_CONFIG_VALUE_0"] == "http://127.0.0.1:7897"
        assert env["GIT_CONFIG_VALUE_1"] == "http://127.0.0.1:7897"
        assert events[0] == {"type": "log", "text": "building"}
        assert events[-1]["type"] == "done"
        assert events[-1]["success"] is True


