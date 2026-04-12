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

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class FilePathError(ValueError):
    """路径校验失败。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def resolve_session_path(session, filename: str, *, use_browser_dir: bool = False) -> str:
    """将用户输入文件名解析到当前工作目录，并做路径安全校验。"""
    if not is_safe_filename(filename):
        raise FilePathError("unsafe_filename")

    base_dir = getattr(session, "browse_dir", None) if use_browser_dir else None
    if not isinstance(base_dir, str) or not base_dir.strip():
        base_dir = session.working_dir
    base_dir = os.path.abspath(base_dir)
    real_working = base_dir
    real_path = os.path.abspath(os.path.join(base_dir, filename))
    try:
        common = os.path.commonpath([real_working, real_path])
    except ValueError as exc:
        raise FilePathError("unsafe_path") from exc

    if common != real_working:
        raise FilePathError("unsafe_path")

    return real_path


async def send_document_from_path(message, file_path: str):
    with open(file_path, "rb") as handle:
        await message.reply_document(document=handle)


async def send_photo_from_path(message, file_path: str):
    with open(file_path, "rb") as handle:
        await message.reply_photo(photo=handle)


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
    session = get_current_session(update, context)
    try:
        file_path = resolve_session_path(session, filename)
    except FilePathError as exc:
        if exc.code == "unsafe_filename":
            await update.message.reply_text(msg("download", "unsafe_filename"))
        else:
            await update.message.reply_text(msg("download", "unsafe_path"))
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(msg("download", "not_found"))
        return

    if os.path.getsize(file_path) > 50 * 1024 * 1024:
        await update.message.reply_text(msg("download", "error", error="文件太大 (>50MB)，无法通过 Telegram 发送"))
        return

    try:
        await send_document_from_path(update.message, file_path)
    except Exception as e:
        await update.message.reply_text(msg("download", "error", error=str(e)))


async def cat_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示文件完整内容"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /cat <文件名>")
        return

    filename = " ".join(context.args)
    if not is_safe_filename(filename):
        await update.message.reply_text("文件名不安全")
        return

    session = get_current_session(update, context)
    file_path = os.path.join(session.working_dir, filename)

    real_path = os.path.abspath(file_path)
    real_working = os.path.abspath(session.working_dir)
    if not real_path.startswith(real_working):
        await update.message.reply_text("路径不安全")
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(f"文件不存在: {html.escape(filename)}", parse_mode="HTML")
        return

    file_size = os.path.getsize(file_path)
    if file_size > 1024 * 1024:
        await update.message.reply_text(f"文件太大 ({file_size / (1024 * 1024):.1f} MB)，请使用 /download 下载")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if len(content) > 4000:
            chunks = [content[i:i+4000] for i in range(0, len(content), 4000)]
            await update.message.reply_text(
                f"📄 <b>{html.escape(filename)}</b> (共 {len(chunks)} 部分)\n\n<pre>{html.escape(chunks[0])}</pre>",
                parse_mode="HTML"
            )
            for i, chunk in enumerate(chunks[1:], 2):
                await update.message.reply_text(f"<pre>{html.escape(chunk)}</pre>", parse_mode="HTML")
        else:
            await update.message.reply_text(
                f"📄 <b>{html.escape(filename)}</b>\n\n<pre>{html.escape(content)}</pre>",
                parse_mode="HTML"
            )
    except UnicodeDecodeError:
        await update.message.reply_text("文件不是文本文件或编码不支持，请使用 /download 下载")
    except Exception as e:
        await update.message.reply_text(f"读取文件失败: {str(e)}")


async def head_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示文件前N行（默认20行）"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /head <文件名> [行数]\n默认显示前20行")
        return

    args = context.args
    lines_to_show = 20

    if len(args) >= 2 and args[-1].isdigit():
        lines_to_show = int(args[-1])
        filename = " ".join(args[:-1])
    else:
        filename = " ".join(args)

    if not is_safe_filename(filename):
        await update.message.reply_text("文件名不安全")
        return

    session = get_current_session(update, context)
    file_path = os.path.join(session.working_dir, filename)

    real_path = os.path.abspath(file_path)
    real_working = os.path.abspath(session.working_dir)
    if not real_path.startswith(real_working):
        await update.message.reply_text("路径不安全")
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(f"文件不存在: {html.escape(filename)}", parse_mode="HTML")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= lines_to_show:
                    break
                lines.append(line.rstrip("\n"))

        content = "\n".join(lines)
        total_lines = i + 1

        if len(content) > 4000:
            content = content[:4000] + "\n..."

        await update.message.reply_text(
            f"📄 <b>{html.escape(filename)}</b> (前 {len(lines)} 行)\n\n<pre>{html.escape(content)}</pre>",
            parse_mode="HTML"
        )
    except UnicodeDecodeError:
        await update.message.reply_text("文件不是文本文件或编码不支持")
    except Exception as e:
        await update.message.reply_text(f"读取文件失败: {str(e)}")
