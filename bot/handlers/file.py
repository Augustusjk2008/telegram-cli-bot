"""文件上传/下载处理器"""

import html
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from bot.context_helpers import get_current_session
from bot.messages import msg
from bot.utils import check_auth, is_safe_filename, safe_edit_text

logger = logging.getLogger(__name__)


async def upload_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    await update.message.reply_text(msg("upload", "help"), parse_mode="HTML")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    document = update.message.document

    if document is None:
        await update.message.reply_text(msg("upload", "no_file"))
        return

    if not is_safe_filename(document.file_name):
        await update.message.reply_text(msg("upload", "unsafe_filename"))
        return

    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(msg("upload", "file_too_large"))
        return

    status_msg = await update.message.reply_text("📥 正在接收文件...")

    try:
        file = await context.bot.get_file(document.file_id)
        file_path = os.path.join(session.working_dir, document.file_name)
        await file.download_to_drive(file_path)
        await safe_edit_text(
            status_msg,
            f"{msg('upload', 'success', filename=html.escape(file_path))}\n\n可以发送消息让 AI 分析此文件",
            parse_mode="HTML",
        )
    except Exception as e:
        await safe_edit_text(status_msg, msg("upload", "failed", error=str(e)))


async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text(msg("download", "usage"))
        return

    filename = " ".join(context.args)
    if not is_safe_filename(filename):
        await update.message.reply_text(msg("download", "unsafe_filename"))
        return

    session = get_current_session(update, context)
    file_path = os.path.join(session.working_dir, filename)

    real_path = os.path.abspath(file_path)
    real_working = os.path.abspath(session.working_dir)
    if not real_path.startswith(real_working):
        await update.message.reply_text(msg("download", "unsafe_path"))
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(msg("download", "not_found"))
        return

    if os.path.getsize(file_path) > 50 * 1024 * 1024:
        await update.message.reply_text(msg("download", "error", error="文件太大 (>50MB)，无法通过 Telegram 发送"))
        return

    try:
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f)
    except Exception as e:
        await update.message.reply_text(msg("download", "error", error=str(e)))
