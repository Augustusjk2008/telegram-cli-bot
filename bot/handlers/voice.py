"""语音消息处理器"""

import html
import logging
import os
import time

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import WHISPER_TEMP_DIR
from bot.context_helpers import get_current_session
from bot.handlers.chat import handle_text_message
from bot.messages import msg
from bot.utils import check_auth, safe_edit_text
from bot.whisper_service import get_whisper_service

logger = logging.getLogger(__name__)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理语音消息"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    whisper = get_whisper_service()
    if not whisper.is_available():
        await update.message.reply_text(msg("voice", "disabled"))
        return

    voice = update.message.voice
    if voice is None:
        return

    # 检查时长
    from bot.config import WHISPER_MAX_DURATION
    if voice.duration > WHISPER_MAX_DURATION:
        await update.message.reply_text(
            msg("voice", "too_long", max_duration=WHISPER_MAX_DURATION)
        )
        return

    # 显示处理提示
    status_msg = await update.message.reply_text(
        msg("voice", "downloading", duration=voice.duration)
    )

    oga_path = None
    wav_path = None

    try:
        # 1. 下载语音文件
        timestamp = int(time.time() * 1000)
        oga_path = os.path.join(WHISPER_TEMP_DIR, f"voice_{user_id}_{timestamp}.oga")
        wav_path = os.path.join(WHISPER_TEMP_DIR, f"voice_{user_id}_{timestamp}.wav")

        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(oga_path)

        # 2. 转换格式
        await safe_edit_text(status_msg, msg("voice", "converting"))
        success = await whisper.convert_oga_to_wav(oga_path, wav_path)
        if not success:
            await safe_edit_text(status_msg, msg("voice", "convert_failed"))
            return

        # 3. 语音识别
        await safe_edit_text(status_msg, msg("voice", "recognizing"))
        success, result = await whisper.transcribe(wav_path)

        if not success:
            await safe_edit_text(status_msg, msg("voice", "recognize_failed", error=result))
            return

        # 4. 显示识别结果
        await safe_edit_text(
            status_msg,
            msg("voice", "recognized", text=html.escape(result)),
            parse_mode="HTML"
        )

        # 5. 将识别的文字作为普通消息处理
        await handle_text_message(update, context, text_override=result)

    except Exception as e:
        logger.error(f"处理语音消息失败: {e}", exc_info=True)
        await safe_edit_text(status_msg, msg("voice", "error", error=str(e)))

    finally:
        # 清理临时文件
        if oga_path or wav_path:
            whisper.cleanup_temp_files(oga_path, wav_path)


async def handle_audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理音频文件（与语音消息类似，但支持更长时长）"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    whisper = get_whisper_service()
    if not whisper.is_available():
        await update.message.reply_text(msg("voice", "disabled"))
        return

    audio = update.message.audio
    if audio is None:
        return

    # 音频文件支持更长时长，但仍有限制
    from bot.config import WHISPER_MAX_DURATION
    if audio.duration and audio.duration > WHISPER_MAX_DURATION:
        await update.message.reply_text(
            msg("voice", "too_long", max_duration=WHISPER_MAX_DURATION)
        )
        return

    status_msg = await update.message.reply_text(
        msg("voice", "downloading", duration=audio.duration or 0)
    )

    audio_path = None

    try:
        # 下载音频文件
        timestamp = int(time.time() * 1000)
        from pathlib import Path
        file_ext = Path(audio.file_name or "audio.mp3").suffix or ".mp3"
        audio_path = os.path.join(WHISPER_TEMP_DIR, f"audio_{user_id}_{timestamp}{file_ext}")

        file = await context.bot.get_file(audio.file_id)
        await file.download_to_drive(audio_path)

        # 语音识别
        await safe_edit_text(status_msg, msg("voice", "recognizing"))
        success, result = await whisper.transcribe(audio_path)

        if not success:
            await safe_edit_text(status_msg, msg("voice", "recognize_failed", error=result))
            return

        # 显示识别结果并处理
        await safe_edit_text(
            status_msg,
            msg("voice", "recognized", text=html.escape(result)),
            parse_mode="HTML"
        )

        await handle_text_message(update, context, text_override=result)

    except Exception as e:
        logger.error(f"处理音频消息失败: {e}", exc_info=True)
        await safe_edit_text(status_msg, msg("voice", "error", error=str(e)))

    finally:
        if audio_path:
            whisper.cleanup_temp_files(audio_path)
