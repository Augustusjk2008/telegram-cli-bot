"""测试文件预览命令（cat 和 head）"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.file import cat_file, head_file
from bot.models import UserSession


@pytest.fixture
def temp_test_file():
    """创建临时测试文件"""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8", suffix=".txt") as f:
        for i in range(1, 51):
            f.write(f"Line {i}\n")
        temp_path = f.name

    yield temp_path

    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.mark.asyncio
async def test_cat_small_file(mock_update, mock_context, temp_test_file):
    """测试 cat 命令读取小文件"""
    filename = os.path.basename(temp_test_file)
    mock_context.args = [filename]

    mock_session = UserSession(
        bot_id=111,
        bot_alias="test",
        user_id=123,
        working_dir=os.path.dirname(temp_test_file)
    )

    with patch("bot.handlers.file.check_auth", return_value=True), \
         patch("bot.handlers.file.get_current_session", return_value=mock_session):
        await cat_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert filename in call_args[0][0]
    assert "Line 1" in call_args[0][0]
    assert "Line 50" in call_args[0][0]


@pytest.mark.asyncio
async def test_cat_nonexistent_file(mock_update, mock_context, temp_dir):
    """测试 cat 命令读取不存在的文件"""
    mock_context.args = ["nonexistent.txt"]
    mock_session = UserSession(
        bot_id=111,
        bot_alias="test",
        user_id=123,
        working_dir=str(temp_dir)
    )

    with patch("bot.handlers.file.check_auth", return_value=True), \
         patch("bot.handlers.file.get_current_session", return_value=mock_session):
        await cat_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "不存在" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_cat_no_args(mock_update, mock_context):
    """测试 cat 命令无参数"""
    mock_context.args = []

    with patch("bot.handlers.file.check_auth", return_value=True):
        await cat_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "用法" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_cat_unauthorized(mock_update, mock_context):
    """测试 cat 命令未授权"""
    mock_context.args = ["test.txt"]

    with patch("bot.handlers.file.check_auth", return_value=False):
        await cat_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_head_default_lines(mock_update, mock_context, temp_test_file):
    """测试 head 命令默认显示20行"""
    filename = os.path.basename(temp_test_file)
    mock_context.args = [filename]

    mock_session = UserSession(
        bot_id=111,
        bot_alias="test",
        user_id=123,
        working_dir=os.path.dirname(temp_test_file)
    )

    with patch("bot.handlers.file.check_auth", return_value=True), \
         patch("bot.handlers.file.get_current_session", return_value=mock_session):
        await head_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert filename in call_args[0][0]
    assert "Line 1" in call_args[0][0]
    assert "Line 20" in call_args[0][0]


@pytest.mark.asyncio
async def test_head_custom_lines(mock_update, mock_context, temp_test_file):
    """测试 head 命令自定义行数"""
    filename = os.path.basename(temp_test_file)
    mock_context.args = [filename, "5"]

    mock_session = UserSession(
        bot_id=111,
        bot_alias="test",
        user_id=123,
        working_dir=os.path.dirname(temp_test_file)
    )

    with patch("bot.handlers.file.check_auth", return_value=True), \
         patch("bot.handlers.file.get_current_session", return_value=mock_session):
        await head_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "Line 1" in call_args[0][0]
    assert "Line 5" in call_args[0][0]
    assert "Line 6" not in call_args[0][0]


@pytest.mark.asyncio
async def test_head_no_args(mock_update, mock_context):
    """测试 head 命令无参数"""
    mock_context.args = []

    with patch("bot.handlers.file.check_auth", return_value=True):
        await head_file(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "用法" in mock_update.message.reply_text.call_args[0][0]


