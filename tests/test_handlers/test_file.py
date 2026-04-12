"""
文件处理器测试

导入真实的 file handler 函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.file import download_file, handle_document, upload_help


class TestUploadHelp:
    """测试 upload_help"""

    @pytest.mark.asyncio
    async def test_upload_help(self, mock_update, mock_context):
        with patch("bot.handlers.file.check_auth", return_value=True):
            await upload_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "上传" in call_text

    @pytest.mark.asyncio
    async def test_upload_help_unauthorized(self, mock_update, mock_context):
        with patch("bot.handlers.file.check_auth", return_value=False):
            await upload_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_called()


class TestHandleDocument:
    """测试 handle_document"""

    @pytest.mark.asyncio
    async def test_file_too_large(self, mock_update, mock_context, temp_dir):
        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "big.bin"
        mock_update.message.document.file_size = 100 * 1024 * 1024  # 100MB
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.file.check_auth", return_value=True), \
             patch("bot.handlers.file.get_current_session", return_value=session_mock), \
             patch("bot.handlers.file.is_safe_filename", return_value=True):
            await handle_document(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "太大" in call_text

    @pytest.mark.asyncio
    async def test_unsafe_filename(self, mock_update, mock_context, temp_dir):
        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "../etc/passwd"
        mock_update.message.document.file_size = 100
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.file.check_auth", return_value=True), \
             patch("bot.handlers.file.get_current_session", return_value=session_mock):
            await handle_document(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "非法" in call_text


class TestDownloadFile:
    """测试 download_file"""

    @pytest.mark.asyncio
    async def test_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with patch("bot.handlers.file.check_auth", return_value=True):
            await download_file(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "用法" in call_text or "download" in call_text.lower()

    @pytest.mark.asyncio
    async def test_path_traversal(self, mock_update, mock_context, temp_dir):
        mock_context.args = ["../../../etc/passwd"]
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.file.check_auth", return_value=True), \
             patch("bot.handlers.file.get_current_session", return_value=session_mock), \
             patch("bot.handlers.file.is_safe_filename", return_value=True):
            await download_file(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "无效" in call_text or "非法" in call_text or "路径" in call_text

    @pytest.mark.asyncio
    async def test_file_not_found(self, mock_update, mock_context, temp_dir):
        mock_context.args = ["nonexistent.txt"]
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.file.check_auth", return_value=True), \
             patch("bot.handlers.file.get_current_session", return_value=session_mock), \
             patch("bot.handlers.file.is_safe_filename", return_value=True):
            await download_file(mock_update, mock_context)
        call_text = mock_update.message.reply_text.call_args[0][0]
        assert "不存在" in call_text

    @pytest.mark.asyncio
    async def test_download_success(self, mock_update, mock_context, temp_dir):
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")
        mock_context.args = ["test.txt"]
        session_mock = MagicMock()
        session_mock.working_dir = str(temp_dir)
        with patch("bot.handlers.file.check_auth", return_value=True), \
             patch("bot.handlers.file.get_current_session", return_value=session_mock), \
             patch("bot.handlers.file.is_safe_filename", return_value=True):
            await download_file(mock_update, mock_context)
        mock_update.message.reply_document.assert_called_once()
