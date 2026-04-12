"""Shell 命令执行处理器"""

import asyncio
import html
import logging
import os
import re
import subprocess

from telegram import Update
from telegram.ext import ContextTypes

from bot.context_helpers import get_current_session
from bot.messages import msg
from bot.utils import check_auth, is_dangerous_command, safe_edit_text, truncate_for_markdown, is_safe_filename


def strip_ansi_escape(text: str) -> str:
    """去除 ANSI 转义序列（颜色代码等）"""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)

logger = logging.getLogger(__name__)


async def remove_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除文件或目录 (/rm 命令)"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text("用法: /rm <文件或目录名> [-r]\n-r: 递归删除目录")
        return

    session = get_current_session(update, context)
    
    # 解析参数
    recursive = False
    args = context.args
    if args[-1] == "-r":
        recursive = True
        args = args[:-1]
    
    if not args:
        await update.message.reply_text("用法: /rm <文件或目录名> [-r]\n-r: 递归删除目录")
        return

    target_name = " ".join(args)
    if not is_safe_filename(target_name):
        await update.message.reply_text("文件名不安全")
        return

    target_path = os.path.join(session.working_dir, target_name)
    real_path = os.path.abspath(target_path)
    real_working = os.path.abspath(session.working_dir)
    
    # 安全检查：确保路径在工作目录内
    if not real_path.startswith(real_working):
        await update.message.reply_text("路径不安全")
        return

    # 检查文件/目录是否存在
    if not os.path.exists(target_path):
        await update.message.reply_text(f"文件或目录不存在: {html.escape(target_name)}", parse_mode="HTML")
        return

    try:
        import shutil
        if os.path.isdir(target_path):
            if recursive:
                shutil.rmtree(target_path)
                await update.message.reply_text(f"🗑️ 已删除目录: <code>{html.escape(target_name)}</code>", parse_mode="HTML")
            else:
                await update.message.reply_text(f"⚠️ <code>{html.escape(target_name)}</code> 是目录，使用 <code>-r</code> 选项删除", parse_mode="HTML")
        else:
            os.remove(target_path)
            await update.message.reply_text(f"🗑️ 已删除文件: <code>{html.escape(target_name)}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"删除失败: {str(e)}")


async def execute_shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text(msg("shell", "usage"))
        return

    command = " ".join(context.args)
    if is_dangerous_command(command):
        await update.message.reply_text(msg("shell", "dangerous"))
        return

    session = get_current_session(update, context)
    status_msg = await update.message.reply_text(f"🚀 执行: <code>{html.escape(command)}</code>", parse_mode="HTML")

    def run_shell_sync():
        return subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=session.working_dir,
            timeout=60,
        )

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_shell_sync)

        output = strip_ansi_escape(result.stdout or "")
        stderr = strip_ansi_escape(result.stderr or "")
        if stderr:
            output += f"\n\n[stderr]\n{stderr}"
        if not output:
            output = msg("shell", "no_output")

        safe_output = truncate_for_markdown(output, 3800)
        icon = "✅" if result.returncode == 0 else "❌"
        await safe_edit_text(status_msg, msg("shell", "result", command=html.escape(command), output=html.escape(safe_output)), parse_mode="HTML")
    except subprocess.TimeoutExpired:
        await safe_edit_text(status_msg, msg("shell", "error", error="命令执行超时 (60秒)"))
    except Exception as e:
        await safe_edit_text(status_msg, msg("shell", "error", error=str(e)))
