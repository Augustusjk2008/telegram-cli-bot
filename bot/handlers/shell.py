"""Shell 命令执行处理器"""

import asyncio
import html
import logging
import subprocess

from telegram import Update
from telegram.ext import ContextTypes

from bot.context_helpers import get_current_session
from bot.messages import msg
from bot.utils import check_auth, is_dangerous_command, safe_edit_text, truncate_for_markdown

logger = logging.getLogger(__name__)


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

        output = result.stdout or ""
        if result.stderr:
            output += f"\n\n[stderr]\n{result.stderr}"
        if not output:
            output = msg("shell", "no_output")

        safe_output = truncate_for_markdown(output, 3800)
        icon = "✅" if result.returncode == 0 else "❌"
        await safe_edit_text(status_msg, msg("shell", "result", command=html.escape(command), output=html.escape(safe_output)), parse_mode="HTML")
    except subprocess.TimeoutExpired:
        await safe_edit_text(status_msg, msg("shell", "error", error="命令执行超时 (60秒)"))
    except Exception as e:
        await safe_edit_text(status_msg, msg("shell", "error", error=str(e)))
