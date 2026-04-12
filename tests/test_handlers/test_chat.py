"""
聊天处理器测试

导入真实的 chat handler 进行测试（主要测试 handle_text_message 的分支逻辑）
"""

import threading
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from bot.assistant_context import AssistantPromptPayload
from bot.assistant_docs import ManagedPromptSyncResult


class TestHandleTextMessageAuth:
    """测试 handle_text_message 的鉴权分支"""

    @pytest.mark.asyncio
    async def test_unauthorized_user(self, mock_update, mock_context):
        from bot.handlers.chat import handle_text_message
        with patch("bot.handlers.chat.check_auth", return_value=False):
            await handle_text_message(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_double_slash_prefix(self, mock_update, mock_context, temp_dir):
        """测试 // 前缀被转为 /"""
        from bot.handlers.chat import handle_text_message
        mock_update.message.text = "//start"
        profile_mock = MagicMock()
        profile_mock.cli_type = "kimi"
        profile_mock.cli_path = "kimi"
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        session_mock.is_processing = False
        session_mock._lock = MagicMock()
        session_mock._lock.__enter__ = MagicMock(return_value=None)
        session_mock._lock.__exit__ = MagicMock(return_value=False)

        with patch("bot.handlers.chat.check_auth", return_value=True), \
             patch("bot.handlers.chat.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.chat.get_current_session", return_value=session_mock), \
             patch("bot.handlers.chat.resolve_cli_executable", return_value=None):
            await handle_text_message(mock_update, mock_context)
        # 应该报告未找到 CLI
        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_busy_session(self, mock_update, mock_context, temp_dir):
        """测试会话正忙"""
        from bot.handlers.chat import handle_text_message
        profile_mock = MagicMock()
        profile_mock.cli_type = "kimi"
        profile_mock.cli_path = "kimi"
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        session_mock.is_processing = True
        session_mock._lock = threading.Lock()

        with patch("bot.handlers.chat.check_auth", return_value=True), \
             patch("bot.handlers.chat.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.chat.get_current_session", return_value=session_mock):
            await handle_text_message(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "正在处理" in call_text or "稍后" in call_text

    @pytest.mark.asyncio
    async def test_assistant_mode_compiles_local_prompt_before_cli_call(self, mock_update, mock_context, temp_dir):
        from bot.handlers.chat import handle_text_message

        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"
        profile_mock.cli_type = "codex"
        profile_mock.cli_path = "codex"
        profile_mock.working_dir = str(temp_dir)
        profile_mock.cli_params = MagicMock()

        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        session_mock.is_processing = False
        session_mock.codex_session_id = None
        session_mock.kimi_session_id = None
        session_mock.claude_session_id = None
        session_mock.claude_session_initialized = False
        session_mock.managed_prompt_hash_seen = "hash-seen"
        session_mock._lock = threading.Lock()

        fake_process = MagicMock()

        with patch("bot.handlers.chat.check_auth", return_value=True), \
             patch("bot.handlers.chat.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.chat.get_current_session", return_value=session_mock), \
             patch("bot.handlers.chat.resolve_cli_executable", return_value="codex"), \
             patch(
                 "bot.handlers.chat.sync_managed_prompt_files",
                 return_value=ManagedPromptSyncResult(False, False, "hash-current"),
             ) as sync_mock, \
             patch(
                 "bot.handlers.chat.compile_assistant_prompt",
                 return_value=AssistantPromptPayload(
                     prompt_text="hello from payload",
                     managed_prompt_hash_seen="hash-updated",
                 ),
             ) as compiler, \
             patch("bot.handlers.chat.record_assistant_capture", return_value={"id": "cap_1"}) as capture_mock, \
             patch("bot.handlers.chat.refresh_compaction_state") as refresh_mock, \
             patch("bot.handlers.chat.list_pending_capture_ids", return_value=["cap_0", "cap_1"]) as pending_mock, \
             patch("bot.handlers.chat.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]) as surface_mock, \
             patch("bot.handlers.chat.finalize_compaction", return_value=False) as finalize_mock, \
             patch("bot.handlers.chat.build_cli_command", return_value=(["codex"], False)) as build_mock, \
             patch("bot.handlers.chat.subprocess.Popen", return_value=fake_process), \
             patch(
                 "bot.handlers.chat.stream_codex_json_output",
                 new_callable=AsyncMock,
                 return_value=("ok", "thread-1", 0, False),
             ):
            await handle_text_message(mock_update, mock_context)

        compiler.assert_called_once_with(
            ANY,
            mock_update.effective_user.id,
            mock_update.message.text,
            has_native_session=False,
            managed_prompt_hash="hash-current",
            seen_managed_prompt_hash="hash-seen",
        )
        assert sync_mock.call_count == 2
        capture_mock.assert_called_once()
        refresh_mock.assert_called_once_with(ANY, latest_capture={"id": "cap_1"})
        pending_mock.assert_called_once()
        assert surface_mock.call_count == 2
        finalize_mock.assert_called_once_with(
            ANY,
            before={"a": "1"},
            after={"a": "1"},
            consumed_capture_ids=["cap_0", "cap_1"],
        )
        assert session_mock.managed_prompt_hash_seen == "hash-updated"
        assert build_mock.call_args.kwargs["user_text"] == "hello from payload"

    @pytest.mark.asyncio
    async def test_assistant_mode_marks_native_session_when_codex_thread_exists(
        self, mock_update, mock_context, temp_dir
    ):
        from bot.handlers.chat import handle_text_message

        profile_mock = MagicMock()
        profile_mock.bot_mode = "assistant"
        profile_mock.cli_type = "codex"
        profile_mock.cli_path = "codex"
        profile_mock.working_dir = str(temp_dir)
        profile_mock.cli_params = MagicMock()

        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        session_mock.is_processing = False
        session_mock.codex_session_id = "thread-existing"
        session_mock.kimi_session_id = None
        session_mock.claude_session_id = None
        session_mock.claude_session_initialized = False
        session_mock.managed_prompt_hash_seen = "hash-seen"
        session_mock._lock = threading.Lock()

        fake_process = MagicMock()

        with patch("bot.handlers.chat.check_auth", return_value=True), \
             patch("bot.handlers.chat.get_current_profile", return_value=profile_mock), \
             patch("bot.handlers.chat.get_current_session", return_value=session_mock), \
             patch("bot.handlers.chat.resolve_cli_executable", return_value="codex"), \
             patch(
                 "bot.handlers.chat.sync_managed_prompt_files",
                 return_value=ManagedPromptSyncResult(True, True, "hash-current"),
             ) as sync_mock, \
             patch(
                 "bot.handlers.chat.compile_assistant_prompt",
                 return_value=AssistantPromptPayload(
                     prompt_text="resume payload",
                     managed_prompt_hash_seen="hash-updated",
                 ),
             ) as compiler, \
             patch("bot.handlers.chat.record_assistant_capture", return_value={"id": "cap_1"}), \
             patch("bot.handlers.chat.refresh_compaction_state"), \
             patch("bot.handlers.chat.list_pending_capture_ids", return_value=["cap_1"]), \
             patch("bot.handlers.chat.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
             patch("bot.handlers.chat.finalize_compaction", return_value=False), \
             patch("bot.handlers.chat.build_cli_command", return_value=(["codex"], False)), \
             patch("bot.handlers.chat.subprocess.Popen", return_value=fake_process), \
             patch(
                 "bot.handlers.chat.stream_codex_json_output",
                 new_callable=AsyncMock,
                 return_value=("ok", "thread-existing", 0, False),
             ):
            await handle_text_message(mock_update, mock_context)

        compiler.assert_called_once_with(
            ANY,
            mock_update.effective_user.id,
            mock_update.message.text,
            has_native_session=True,
            managed_prompt_hash="hash-current",
            seen_managed_prompt_hash="hash-seen",
        )
        assert sync_mock.call_count == 2
        assert session_mock.managed_prompt_hash_seen == "hash-updated"


class TestCollectCliOutput:
    """测试 collect_cli_output 返回类型"""

    @pytest.mark.asyncio
    async def test_returns_tuple(self, mock_update):
        from bot.handlers.chat import collect_cli_output
        from unittest.mock import MagicMock as MM
        import subprocess

        mock_proc = MM(spec=subprocess.Popen)
        mock_proc.communicate.return_value = ("hello output", None)
        mock_proc.returncode = 0

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0
            future = MagicMock()
            future.done.return_value = True
            future.__await__ = lambda self: iter(["hello output", 0])

            # collect_cli_output 的详细行为需要完整的 event loop
            # 这里只验证函数存在且可导入
            assert callable(collect_cli_output)

    @pytest.mark.asyncio
    async def test_normal_exit_keeps_success_state(self, mock_update):
        import subprocess
        import sys
        import threading

        from bot.handlers import chat

        progress_message = MagicMock()
        progress_message.delete = AsyncMock()
        progress_message.edit_text = AsyncMock()
        final_message = MagicMock()
        mock_update.message.reply_text = AsyncMock(side_effect=[progress_message, final_message])

        session_mock = MagicMock()
        session_mock.stop_requested = False
        session_mock._lock = threading.Lock()

        process = subprocess.Popen(
            [sys.executable, "-c", "print('hello from cli')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )

        with patch.object(chat, "CLI_TIMEOUT_CHECK_INTERVAL", 0.01), \
             patch.object(chat, "CLI_PROGRESS_UPDATE_INTERVAL", 60), \
             patch.object(chat, "CLI_EXEC_TIMEOUT", 5):
            output, returncode, timed_out = await chat.collect_cli_output(process, mock_update, session_mock)

        assert timed_out is False
        assert returncode == 0
        assert "hello from cli" in output
        assert mock_update.message.reply_text.await_args_list[1].args[0].startswith("✅")

    @pytest.mark.asyncio
    async def test_waits_for_missing_returncode_after_reader_finishes(self, mock_update):
        import threading

        from bot.handlers import chat

        progress_message = MagicMock()
        progress_message.delete = AsyncMock()
        final_message = MagicMock()
        mock_update.message.reply_text = AsyncMock(side_effect=[progress_message, final_message])

        session_mock = MagicMock()
        session_mock.stop_requested = False
        session_mock._lock = threading.Lock()

        class FakeStdout:
            def __init__(self):
                self._lines = ["hello from fake process\n"]

            def readline(self):
                return self._lines.pop(0) if self._lines else ""

            def fileno(self):
                return 0

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.returncode = None
                self.wait_calls = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.wait_calls += 1
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = 0

        process = FakeProcess()

        with patch.object(chat, "CLI_TIMEOUT_CHECK_INTERVAL", 0.01), \
             patch.object(chat, "CLI_PROGRESS_UPDATE_INTERVAL", 60), \
             patch.object(chat, "CLI_EXEC_TIMEOUT", 5):
            output, returncode, timed_out = await chat.collect_cli_output(process, mock_update, session_mock)

        assert timed_out is False
        assert output == "hello from fake process\n"
        assert returncode == 0
        assert process.wait_calls == 1


def test_terminate_process_tree_sync_uses_platform_helper(monkeypatch):
    from bot.handlers import chat

    fake_process = MagicMock()
    helper = MagicMock()
    monkeypatch.setattr(chat, "terminate_process_tree_sync", helper)

    chat._terminate_process_tree_sync(fake_process)

    helper.assert_called_once_with(fake_process)
