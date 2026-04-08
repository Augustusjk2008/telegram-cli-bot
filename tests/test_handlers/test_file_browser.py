"""交互式文件浏览处理器测试"""

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.models import UserSession


def _load_file_browser_module():
    spec = importlib.util.find_spec("bot.handlers.file_browser")
    assert spec is not None, "expected bot.handlers.file_browser module to exist"
    return importlib.import_module("bot.handlers.file_browser")


def _build_callback_update(mock_update, data: str):
    update = MagicMock()
    update.effective_user = mock_update.effective_user
    update.effective_chat = mock_update.effective_chat

    message = MagicMock()
    message.edit_text = AsyncMock()
    message.reply_text = AsyncMock()
    message.reply_document = AsyncMock()
    message.reply_photo = AsyncMock()

    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = message

    update.callback_query = query
    update.effective_message = message
    return update, query, message


def _flatten_callback_data(reply_markup) -> list[str]:
    return [
        button.callback_data
        for row in reply_markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


class TestShowFileBrowser:
    @pytest.mark.asyncio
    async def test_files_empty_directory(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.show_file_browser(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        text = mock_update.message.reply_text.call_args.args[0]
        assert str(temp_dir) in text
        assert "空目录" in text

    @pytest.mark.asyncio
    async def test_files_directory_has_pagination(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        for index in range(browser.PAGE_SIZE + 2):
            (temp_dir / f"file_{index:02d}.txt").write_text("hello", encoding="utf-8")

        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.show_file_browser(mock_update, mock_context)

        reply_markup = mock_update.message.reply_text.call_args.kwargs["reply_markup"]
        callback_data = _flatten_callback_data(reply_markup)
        assert "fb:page:1" in callback_data

        callback_update, query, message = _build_callback_update(mock_update, "fb:page:1")
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        query.answer.assert_awaited_once()
        message.edit_text.assert_awaited_once()
        text = message.edit_text.call_args.args[0]
        assert f"file_{browser.PAGE_SIZE:02d}.txt" in text


class TestNavigationCallbacks:
    @pytest.mark.asyncio
    async def test_open_directory_updates_working_dir_and_clears_sessions(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        subdir = temp_dir / "nested"
        subdir.mkdir()

        session = MagicMock()
        session.working_dir = str(temp_dir)

        callback_update, _, message = _build_callback_update(mock_update, "fb:open:nested")

        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        session.clear_session_ids.assert_called_once()
        assert session.working_dir == str(subdir)
        message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_open_directory_persists_sub_bot_workdir(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        subdir = temp_dir / "nested"
        subdir.mkdir()

        mock_context.application.bot_data["is_main"] = False
        mock_context.application.bot_data["bot_alias"] = "sub1"
        mock_context.application.bot_data["manager"].set_bot_workdir = AsyncMock()

        session = MagicMock()
        session.working_dir = str(temp_dir)

        callback_update, _, _ = _build_callback_update(mock_update, "fb:open:nested")

        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        mock_context.application.bot_data["manager"].set_bot_workdir.assert_awaited_once_with("sub1", str(subdir))
        session.clear_session_ids.assert_called_once()
        assert session.working_dir == str(subdir)

    @pytest.mark.asyncio
    async def test_nav_up_returns_parent_directory(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        child = temp_dir / "child"
        child.mkdir()

        session = MagicMock()
        session.working_dir = str(child)

        callback_update, _, _ = _build_callback_update(mock_update, "fb:nav:up")

        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        assert session.working_dir == str(temp_dir)


class TestFileActions:
    @pytest.mark.asyncio
    async def test_text_preview_supports_next_page(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        text_file = temp_dir / "notes.txt"
        text_file.write_text("\n".join(f"Line {index}" for index in range(1, 151)), encoding="utf-8")
        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        preview_update, _, preview_message = _build_callback_update(mock_update, "fb:act:preview:notes.txt")
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(preview_update, mock_context)

        preview_message.edit_text.assert_awaited_once()
        preview_text = preview_message.edit_text.call_args.args[0]
        assert "Line 1" in preview_text

        preview_markup = preview_message.edit_text.call_args.kwargs["reply_markup"]
        next_callback = next(data for data in _flatten_callback_data(preview_markup) if data.startswith("fb:next:"))

        next_update, _, next_message = _build_callback_update(mock_update, next_callback)
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(next_update, mock_context)

        next_text = next_message.edit_text.call_args.args[0]
        next_offset = int(next_callback.rsplit(":", 1)[1])
        assert f"Line {next_offset + 1}" in next_text

    @pytest.mark.asyncio
    async def test_image_preview_sends_photo(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        image_file = temp_dir / "preview.png"
        image_file.write_bytes(b"fake png")
        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        callback_update, _, message = _build_callback_update(mock_update, "fb:act:preview:preview.png")
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        message.reply_photo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_action_sends_document(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        file_path = temp_dir / "archive.txt"
        file_path.write_text("payload", encoding="utf-8")
        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        callback_update, _, message = _build_callback_update(mock_update, "fb:act:download:archive.txt")
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        message.reply_document.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_file_returns_error_message(self, mock_update, mock_context, temp_dir):
        browser = _load_file_browser_module()
        session = UserSession(bot_id=111, bot_alias="main", user_id=123, working_dir=str(temp_dir))

        callback_update, _, message = _build_callback_update(mock_update, "fb:act:preview:missing.txt")
        with patch("bot.handlers.file_browser.check_auth", return_value=True), patch(
            "bot.handlers.file_browser.get_current_session", return_value=session
        ):
            await browser.handle_file_browser_callback(callback_update, mock_context)

        message.edit_text.assert_awaited_once()
        assert "不存在" in message.edit_text.call_args.args[0]
