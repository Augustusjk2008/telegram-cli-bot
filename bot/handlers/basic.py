"""基础 Telegram 命令处理器"""

import asyncio
import html
import logging
import os

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.cli import normalize_cli_type
from bot.context_helpers import (
    get_bot_alias,
    get_bot_id,
    get_manager,
    get_current_profile,
    get_current_session,
    is_main_application,
)
from bot.messages import msg
from bot.sessions import reset_session
from bot.utils import check_auth, truncate_for_markdown

logger = logging.getLogger(__name__)


# 常驻快捷键盘布局（中文显示，手机端友好）
# 只包含不需要参数的常用命令
COMMON_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["文件浏览", "查看目录", "当前路径"],
        ["重置会话", "系统脚本", "历史记录"],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# 主Bot专属键盘（额外包含管理命令）
MAIN_BOT_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["文件浏览", "查看目录", "当前路径"],
        ["重置会话", "系统脚本", "历史记录"],
        ["机器人列表", "重启系统"],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# 键盘中文到命令的映射
KEYBOARD_TEXT_MAP = {
    "文件浏览": "/files",
    "查看目录": "/ls",
    "当前路径": "/pwd",
    "重置会话": "/reset",
    "历史记录": "/history",
    "系统脚本": "/system",
    "机器人列表": "/bot_list",
    "重启系统": "/restart",
}


def resolve_working_directory(current_dir: str, new_path: str) -> str:
    """将相对路径解析为绝对工作目录路径。"""
    target = new_path
    if not os.path.isabs(target):
        target = os.path.join(current_dir, target)
    return os.path.abspath(os.path.expanduser(target))


async def update_session_working_directory(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    new_path: str,
) -> str:
    """复用 /cd 语义更新当前会话工作目录。"""
    resolved_path = resolve_working_directory(session.working_dir, new_path)
    if not os.path.isdir(resolved_path):
        raise FileNotFoundError(resolved_path)

    if not is_main_application(context):
        await get_manager(context).set_bot_workdir(get_bot_alias(context), resolved_path)

    session.clear_session_ids()
    session.working_dir = resolved_path
    return resolved_path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        await update.message.reply_text(msg("auth", "unauthorized"))
        return

    profile = get_current_profile(context)
    session = get_current_session(update, context)
    alias = get_bot_alias(context)

    admin_block = ""
    if is_main_application(context):
        admin_block = (
            f"\n\n{msg('greeting', 'admin_commands_header')}\n"
            f"{msg('greeting', 'admin_cmd_help')}\n"
            f"{msg('greeting', 'admin_cmd_list')}\n"
            f"{msg('greeting', 'admin_cmd_restart')}\n"
            f"{msg('greeting', 'admin_cmd_system')}\n"
            f"{msg('greeting', 'admin_cmd_add')}\n"
            f"{msg('greeting', 'admin_cmd_remove')}\n"
            f"{msg('greeting', 'admin_cmd_start_stop')}\n"
            f"{msg('greeting', 'admin_cmd_set_cli')}\n"
            f"{msg('greeting', 'admin_cmd_set_workdir')}\n"
            f"{msg('greeting', 'admin_cmd_kill')}"
        )

    native_session_block = ""
    current_cli = normalize_cli_type(profile.cli_type)
    if current_cli == "codex":
        session_id = session.codex_session_id or msg("greeting", "session_id_not_created")
        native_session_block = msg("greeting", "session_id_labels.codex", session_id=session_id) + "\n"
    elif current_cli == "kimi":
        session_id = session.kimi_session_id or msg("greeting", "session_id_not_created")
        native_session_block = msg("greeting", "session_id_labels.kimi", session_id=session_id) + "\n"
    elif current_cli == "claude":
        session_id = session.claude_session_id or msg("greeting", "session_id_not_created")
        status = msg("greeting", "claude_initialized") if session.claude_session_initialized else msg("greeting", "claude_pending")
        native_session_block = msg("greeting", "session_id_labels.claude", session_id=session_id, status=status) + "\n"

    # 根据是否是主Bot选择对应的键盘
    keyboard = MAIN_BOT_KEYBOARD if is_main_application(context) else COMMON_KEYBOARD
    
    await update.message.reply_text(
        f"{msg('greeting', 'header', alias=alias)}\n\n"
        f"{msg('greeting', 'current_config')}\n"
        f"{msg('greeting', 'cli_label', cli_type=profile.cli_type)}\n"
        f"{msg('greeting', 'cli_path_label', cli_path=profile.cli_path)}\n"
        f"{msg('greeting', 'workdir_label', working_dir=session.working_dir)}\n"
        f"{msg('greeting', 'msg_count_label', message_count=session.message_count)}\n"
        f"{native_session_block}\n"
        f"{msg('greeting', 'usage')}\n"
        f"{msg('greeting', 'usage_direct')}\n"
        f"{msg('greeting', 'usage_slash')}\n"
        f"{msg('greeting', 'usage_file')}\n\n"
        f"{msg('greeting', 'commands')}\n"
        f"{msg('greeting', 'cmd_start')}\n"
        f"{msg('greeting', 'cmd_reset')}\n"
        f"{msg('greeting', 'cmd_cd')}\n"
        f"{msg('greeting', 'cmd_pwd')}\n"
        f"{msg('greeting', 'cmd_files')}\n"
        f"{msg('greeting', 'cmd_ls')}\n"
        f"{msg('greeting', 'cmd_exec')}\n"
        f"{msg('greeting', 'cmd_history')}\n"
        f"{msg('greeting', 'cmd_upload')}\n"
        f"{msg('greeting', 'cmd_download')}\n"
        f"{msg('greeting', 'cmd_kill_note')}"
        f"{admin_block}",
        reply_markup=keyboard
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    removed = reset_session(get_bot_id(update, context), user_id)
    if removed:
        await update.message.reply_text(msg("reset", "success"))
    else:
        await update.message.reply_text(msg("reset", "no_session"))


async def kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """强制终止当前正在运行的 CLI 进程"""
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    
    with session._lock:
        if not session.is_processing or session.process is None:
            await update.message.reply_text(msg("kill", "no_task"))
            return
        
        process = session.process
        
    # 在锁外终止进程
    try:
        if process.poll() is None:
            # 先关闭 stdout 管道（对 Codex 等流式输出 CLI 至关重要）
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
            process.terminate()
            await asyncio.sleep(1)
            if process.poll() is None:
                process.kill()
            await update.message.reply_text(msg("kill", "killed"))
        else:
            await update.message.reply_text(msg("kill", "already_done"))
    except Exception as e:
        logger.error(f"终止进程时出错: {e}")
        await update.message.reply_text(msg("kill", "error", error=str(e)))


async def change_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    if not context.args:
        await update.message.reply_text(msg("cd", "usage"))
        return

    session = get_current_session(update, context)
    new_path = " ".join(context.args)
    resolved_path = resolve_working_directory(session.working_dir, new_path)

    try:
        await update_session_working_directory(context, session, new_path)
    except FileNotFoundError:
        await update.message.reply_text(msg("cd", "not_exist", path=html.escape(resolved_path)), parse_mode="HTML")
        return
    except Exception as e:
        logger.warning(
            "保存子Bot工作目录失败 alias=%s path=%s error=%s",
            get_bot_alias(context),
            resolved_path,
            e,
        )
        await update.message.reply_text(
            msg("cd", "persist_failed", error=html.escape(str(e))),
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(msg("cd", "success", path=html.escape(resolved_path)), parse_mode="HTML")


async def print_working_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    await update.message.reply_text(msg("pwd", "current_dir", path=html.escape(session.working_dir)), parse_mode="HTML")


async def list_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)

    try:
        items = []
        for item in os.listdir(session.working_dir):
            full_path = os.path.join(session.working_dir, item)
            if os.path.isdir(full_path):
                items.append(f"📁 {item}/")
            else:
                size = os.path.getsize(full_path)
                if size < 1024:
                    size_str = f"{size:,} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                items.append(f"📄 {item} ({size_str})")

        content = "\n".join(items[:50])
        if len(items) > 50:
            content += f"\n\n... 还有 {len(items) - 50} 项"

        safe_content = truncate_for_markdown(content or msg("ls", "empty"), 3800)
        await update.message.reply_text(
            f"{msg('ls', 'dir_header', path=html.escape(session.working_dir))}\n\n<pre>{html.escape(safe_content)}</pre>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(msg("ls", "error", error=str(e)))


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)

    if not session.history:
        await update.message.reply_text(msg("history", "empty"))
        return

    recent = session.history[-20:]
    lines = []
    for entry in recent:
        icon = "👤" if entry["role"] == "user" else "🤖"
        content = entry["content"]
        if len(content) > 100:
            content = content[:100] + "..."
        lines.append(f"{icon} {content}")

    await update.message.reply_text(msg("history", "header") + "\n".join(lines))


# 键盘命令映射（用于处理"/命令 中文描述"格式）
KEYBOARD_COMMAND_MAP = {
    "/ls": list_directory,
    "/pwd": print_working_directory,
    "/reset": reset,
    "/history": show_history,
}

# 主Bot专属的键盘命令
MAIN_BOT_KEYBOARD_COMMANDS = {
    "/bot_list": None,  # 在admin.py中定义，延迟导入
    "/restart": None,   # 在admin.py中定义，延迟导入
    "/system": None,    # 在admin.py中定义，延迟导入
}


async def handle_keyboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理键盘按钮点击（中文标签映射到对应命令）"""
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    
    # 首先检查是否是中文键盘按钮
    command = KEYBOARD_TEXT_MAP.get(text)
    if command:
        if command == "/files":
            from .file_browser import show_file_browser

            await show_file_browser(update, context)
            return

        # 检查是否是键盘命令
        handler = KEYBOARD_COMMAND_MAP.get(command)
        if handler:
            await handler(update, context)
            return
        
        # 检查主Bot专属命令
        if command in MAIN_BOT_KEYBOARD_COMMANDS:
            # 延迟导入避免循环依赖
            from .admin import bot_list, restart_main, system_command
            if command == "/bot_list":
                await bot_list(update, context)
            elif command == "/restart":
                await restart_main(update, context)
            elif command == "/system":
                await system_command(update, context)
            return
    
    # 检查传统的 "/命令 中文" 格式（向后兼容）
    parts = text.split(maxsplit=1)
    if parts:
        command = parts[0].lower()
        if command == "/files":
            from .file_browser import show_file_browser

            await show_file_browser(update, context)
            return

        handler = KEYBOARD_COMMAND_MAP.get(command)
        if handler:
            await handler(update, context)
            return
        
        if command in MAIN_BOT_KEYBOARD_COMMANDS:
            from .admin import bot_list, restart_main, system_command
            if command == "/bot_list":
                await bot_list(update, context)
            elif command == "/restart":
                await restart_main(update, context)
            elif command == "/system":
                await system_command(update, context)
            return
    
    # 不是键盘命令，让其他处理器处理
    return
