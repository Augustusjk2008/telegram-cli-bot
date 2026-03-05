"""
测试共享 fixtures

提供测试所需的通用 fixtures，包括：
- 模拟的 Telegram Update 和 Context（含 application.bot_data 结构）
- 临时目录和文件
- 会话清理
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """提供临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_update() -> MagicMock:
    """创建模拟的 Telegram Update 对象"""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 123456789
    update.effective_user.username = "test_user"
    update.effective_user.first_name = "Test"
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123456789
    update.message = MagicMock()
    update.message.message_id = 1
    update.message.text = "test message"
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.document = None
    update.message.photo = None
    update.message.caption = None
    return update


@pytest.fixture
def mock_context() -> MagicMock:
    """创建模拟的 Telegram Context 对象，含 application.bot_data 结构"""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    context.bot.get_file = AsyncMock()
    context.args = []

    # 设置 application.bot_data 结构（与 manager.py 中 _start_profile 一致）
    context.application = MagicMock()
    context.application.bot_data = {
        "manager": MagicMock(),
        "bot_alias": "main",
        "is_main": True,
        "bot_id": 111222333,
        "bot_username": "test_bot",
        "stopping": False,
    }

    return context


@pytest.fixture
def admin_update(mock_update: MagicMock) -> MagicMock:
    """创建管理员用户的 Update"""
    mock_update.effective_user.id = 999999999
    return mock_update


@pytest.fixture(autouse=True)
def clean_sessions():
    """每个测试前清理全局会话存储"""
    from bot.sessions import sessions, sessions_lock

    with sessions_lock:
        sessions.clear()
    yield
    with sessions_lock:
        sessions.clear()
