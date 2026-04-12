"""语音处理器测试"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.voice import handle_audio_message, handle_voice_message


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_voice_disabled(mock_auth, mock_update, mock_context):
    """测试 Whisper 禁用时的行为"""
    mock_update.message.voice = MagicMock(file_id="test", duration=10)

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper:
        service = MagicMock()
        service.is_available.return_value = False
        mock_whisper.return_value = service

        await handle_voice_message(mock_update, mock_context)

        # 验证返回了禁用消息
        mock_update.message.reply_text.assert_called_once()
        assert "未启用" in str(mock_update.message.reply_text.call_args)


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_voice_recognition_success(mock_auth, mock_update, mock_context):
    """测试语音识别成功"""
    mock_update.message.voice = MagicMock(file_id="test_file_id", duration=10)

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper:
        service = MagicMock()
        service.is_available.return_value = True
        service.convert_oga_to_wav = AsyncMock(return_value=True)
        service.transcribe = AsyncMock(return_value=(True, "测试文本"))
        service.cleanup_temp_files = MagicMock()
        mock_whisper.return_value = service

        with patch("bot.handlers.voice.handle_text_message") as mock_handle_text:
            await handle_voice_message(mock_update, mock_context)

            # 验证识别流程
            service.convert_oga_to_wav.assert_called_once()
            service.transcribe.assert_called_once()
            mock_handle_text.assert_called_once()

            # 验证 handle_text_message 被调用并传入了识别结果
            mock_handle_text.assert_called_once_with(mock_update, mock_context, text_override="测试文本")

            # 验证临时文件被清理
            service.cleanup_temp_files.assert_called_once()


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_voice_recognition_failed(mock_auth, mock_update, mock_context):
    """测试语音识别失败"""
    mock_update.message.voice = MagicMock(file_id="test", duration=10)

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper, \
         patch("bot.handlers.voice.safe_edit_text") as mock_edit:
        service = MagicMock()
        service.is_available.return_value = True
        service.convert_oga_to_wav = AsyncMock(return_value=True)
        service.transcribe = AsyncMock(return_value=(False, "识别失败"))
        service.cleanup_temp_files = MagicMock()
        mock_whisper.return_value = service

        await handle_voice_message(mock_update, mock_context)

        # 验证错误消息（通过 safe_edit_text 调用）
        assert mock_edit.call_count > 0
        last_call = str(mock_edit.call_args_list[-1])
        assert "失败" in last_call

        # 验证临时文件被清理
        service.cleanup_temp_files.assert_called_once()


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_voice_convert_failed(mock_auth, mock_update, mock_context):
    """测试音频格式转换失败"""
    mock_update.message.voice = MagicMock(file_id="test", duration=10)

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper, \
         patch("bot.handlers.voice.safe_edit_text") as mock_edit:
        service = MagicMock()
        service.is_available.return_value = True
        service.convert_oga_to_wav = AsyncMock(return_value=False)
        service.cleanup_temp_files = MagicMock()
        mock_whisper.return_value = service

        await handle_voice_message(mock_update, mock_context)

        # 验证转换失败消息
        assert mock_edit.call_count > 0
        last_call = str(mock_edit.call_args_list[-1])
        assert "转换失败" in last_call

        # 验证没有调用识别
        assert service.transcribe.call_count == 0


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_audio_message_success(mock_auth, mock_update, mock_context):
    """测试音频文件识别成功"""
    mock_update.message.audio = MagicMock(
        file_id="test_audio_id", duration=30, file_name="test.mp3"
    )
    mock_update.message.voice = None

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper:
        service = MagicMock()
        service.is_available.return_value = True
        service.transcribe = AsyncMock(return_value=(True, "音频识别文本"))
        service.cleanup_temp_files = MagicMock()
        mock_whisper.return_value = service

        with patch("bot.handlers.voice.handle_text_message") as mock_handle_text:
            await handle_audio_message(mock_update, mock_context)

            # 验证识别流程
            service.transcribe.assert_called_once()
            mock_handle_text.assert_called_once()

            # 验证 handle_text_message 被调用并传入了识别结果
            mock_handle_text.assert_called_once_with(mock_update, mock_context, text_override="音频识别文本")


@pytest.mark.asyncio
@patch("bot.handlers.voice.check_auth", return_value=True)
async def test_voice_exception_handling(mock_auth, mock_update, mock_context):
    """测试异常处理"""
    mock_update.message.voice = MagicMock(file_id="test", duration=10)

    with patch("bot.handlers.voice.get_whisper_service") as mock_whisper, \
         patch("bot.handlers.voice.safe_edit_text") as mock_edit:
        service = MagicMock()
        service.is_available.return_value = True
        service.convert_oga_to_wav = AsyncMock(side_effect=Exception("测试异常"))
        service.cleanup_temp_files = MagicMock()
        mock_whisper.return_value = service

        await handle_voice_message(mock_update, mock_context)

        # 验证错误消息
        assert mock_edit.call_count > 0
        last_call = str(mock_edit.call_args_list[-1])
        assert "出错" in last_call

        # 验证临时文件被清理
        service.cleanup_temp_files.assert_called_once()

