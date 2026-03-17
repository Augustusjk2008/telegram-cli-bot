"""主Bot专属的多Bot管理命令"""

import asyncio
import html
import logging
import os
import subprocess
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.config import CLI_TYPE, CLI_PATH, WORKING_DIR, request_restart
from bot.context_helpers import ensure_admin, get_manager
from bot.handlers.shell import strip_ansi_escape
from bot.messages import msg
from bot.sessions import sessions, sessions_lock
from bot.utils import safe_edit_text

logger = logging.getLogger(__name__)

# scripts 目录路径
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

# 支持的脚本扩展名
SCRIPT_EXTENSIONS = {'.bat', '.cmd', '.ps1', '.py', '.exe'}


def get_script_display_name(script_path: Path) -> str:
    """从脚本第一行注释提取中文显示名
    
    返回: 中文显示名，如果没有则返回脚本名（不含扩展名）
    """
    try:
        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[:5]  # 只读前5行
    except Exception:
        return script_path.stem
    
    ext = script_path.suffix.lower()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 根据脚本类型提取注释
        display_name = None
        if ext in ['.bat', '.cmd']:
            # batch 脚本: :: 或 REM 开头
            if line.startswith('::'):
                display_name = line[2:].strip()
            elif line.upper().startswith('REM '):
                display_name = line[4:].strip()
        elif ext == '.ps1':
            # PowerShell: # 开头
            if line.startswith('#'):
                display_name = line[1:].strip()
        elif ext == '.py':
            # Python: # 开头
            if line.startswith('#'):
                display_name = line[1:].strip()
        
        if display_name:
            # 返回第一个非空的注释内容
            return display_name
    
    return script_path.stem


def get_script_description(script_path: Path) -> str:
    """从脚本文件中提取功能简介（读取前10行内的注释）"""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[:15]  # 读取前15行
    except Exception:
        return "无简介"
    
    descriptions = []
    ext = script_path.suffix.lower()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 根据脚本类型提取注释
        if ext in ['.bat', '.cmd']:
            # batch 脚本: :: 或 REM 开头
            if line.startswith('::'):
                desc = line[2:].strip()
                if desc:
                    descriptions.append(desc)
            elif line.upper().startswith('REM '):
                desc = line[4:].strip()
                if desc:
                    descriptions.append(desc)
        elif ext == '.ps1':
            # PowerShell: # 开头
            if line.startswith('#'):
                desc = line[1:].strip()
                if desc:
                    descriptions.append(desc)
        elif ext == '.py':
            # Python: # 开头 或 docstring
            if line.startswith('#'):
                desc = line[1:].strip()
                if desc:
                    descriptions.append(desc)
            elif line.startswith(('"""', "'''")):
                # 多行 docstring 简化处理，取第一行
                desc = line.strip('"\'').strip()
                if desc:
                    descriptions.append(desc)
        else:
            # 其他类型，尝试通用注释格式
            if line.startswith(('#', '//', '::', ';', '@REM', 'REM')):
                for prefix in ['#', '//', '::', ';', '@REM', 'REM']:
                    if line.upper().startswith(prefix):
                        desc = line[len(prefix):].strip()
                        if desc:
                            descriptions.append(desc)
                        break
        
        # 最多取3行简介
        if len(descriptions) >= 3:
            break
    
    if descriptions:
        return ' | '.join(descriptions[:3])
    return "无简介"


def list_available_scripts() -> list[tuple[str, str, str, Path]]:
    """列出 scripts 目录下所有可执行脚本
    
    返回: [(脚本名, 显示名, 简介, 完整路径), ...]
    """
    if not SCRIPTS_DIR.exists():
        return []
    
    scripts = []
    for item in SCRIPTS_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in SCRIPT_EXTENSIONS:
            # 去除扩展名的脚本名作为命令名
            script_name = item.stem
            display_name = get_script_display_name(item)
            description = get_script_description(item)
            scripts.append((script_name, display_name, description, item))
    
    # 按名称排序
    scripts.sort(key=lambda x: x[0])
    return scripts


def execute_script(script_path: Path) -> tuple[bool, str]:
    """执行脚本，返回 (成功, 输出/错误信息)"""
    try:
        ext = script_path.suffix.lower()
        
        if ext == '.exe':
            # 直接执行 exe
            result = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
                shell=False
            )
        elif ext == '.ps1':
            # PowerShell 脚本
            result = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(script_path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
                shell=False
            )
        elif ext == '.py':
            # Python 脚本
            result = subprocess.run(
                ['python', str(script_path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
                shell=False
            )
        else:
            # bat/cmd 等使用 shell 执行
            result = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
                shell=True
            )
        
        if result.returncode == 0:
            stdout = strip_ansi_escape(result.stdout or "")
            output = stdout.strip() if stdout.strip() else "执行成功（无输出）"
            return True, output
        else:
            stderr = strip_ansi_escape(result.stderr or "")
            error_msg = stderr.strip() if stderr.strip() else f"退出码: {result.returncode}"
            return False, f"执行失败: {error_msg}"
            
    except subprocess.TimeoutExpired:
        return False, "执行超时（超过60秒）"
    except Exception as e:
        return False, f"执行异常: {str(e)}"


async def bot_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    await update.message.reply_text(msg("admin", "help_text"))


async def bot_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    manager = get_manager(context)
    lines = manager.get_status_lines()
    
    # 构建 inline keyboard，为每个子 bot 添加 goto 按钮
    keyboard = []
    row = []
    
    # 为主 bot 添加 goto 按钮（使用主 bot 的工作目录）
    row.append(InlineKeyboardButton(
        text="👑 切换到主 Bot",
        callback_data=f"goto:{manager.main_profile.alias}"
    ))
    
    # 为每个托管 bot 添加 goto 按钮
    for alias in sorted(manager.managed_profiles.keys()):
        profile = manager.managed_profiles[alias]
        # 按钮显示：别名 + 工作目录（截断）
        display_text = f"🤖 {alias}"
        row.append(InlineKeyboardButton(
            text=display_text,
            callback_data=f"goto:{alias}"
        ))
        if len(row) == 2:  # 每行2个按钮
            keyboard.append(row)
            row = []
    
    if row:  # 添加剩余按钮
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        "\n".join(lines), 
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def restart_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    await update.message.reply_text(msg("admin", "restart"))
    await asyncio.sleep(1)
    request_restart()


async def bot_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(msg("admin", "bot_add_usage"))
        return

    alias = context.args[0].strip().lower()
    token = context.args[1].strip()
    bot_mode = context.args[2].strip().lower() if len(context.args) >= 3 else "cli"
    cli_type = context.args[3].strip() if len(context.args) >= 4 else CLI_TYPE
    cli_path = context.args[4].strip() if len(context.args) >= 5 else CLI_PATH
    workdir = " ".join(context.args[5:]).strip() if len(context.args) >= 6 else WORKING_DIR

    manager = get_manager(context)
    status_msg = await update.message.reply_text(f"⏳ 正在添加子Bot <code>{html.escape(alias)}</code> ...", parse_mode="HTML")

    try:
        profile = await manager.add_bot(alias, token, cli_type, cli_path, workdir, bot_mode)
        app = manager.applications.get(profile.alias)
        username = app.bot_data.get("bot_username", "") if app else ""
        await safe_edit_text(
            status_msg,
            msg("admin", "bot_add_success",
                alias=html.escape(profile.alias),
                username=html.escape(username or 'unknown'),
                bot_mode=html.escape(profile.bot_mode),
                cli_type=html.escape(profile.cli_type),
                cli_path=html.escape(profile.cli_path),
                workdir=html.escape(profile.working_dir)),
            parse_mode="HTML",
        )
    except Exception as e:
        await safe_edit_text(status_msg, msg("admin", "bot_add_failed", error=str(e)))


async def bot_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(msg("admin", "bot_remove_usage"))
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)

    try:
        await manager.remove_bot(alias)
        await update.message.reply_text(msg("admin", "bot_remove_success", alias=html.escape(alias)), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(msg("admin", "bot_remove_failed", error=str(e)))


async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(msg("admin", "bot_start_usage"))
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)
    try:
        await manager.start_bot(alias)
        await update.message.reply_text(msg("admin", "bot_start_success", alias=html.escape(alias)), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(msg("admin", "bot_start_failed", error=str(e)))


async def bot_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(msg("admin", "bot_stop_usage"))
        return

    alias = context.args[0].strip().lower()
    manager = get_manager(context)
    try:
        await manager.stop_bot(alias)
        await update.message.reply_text(msg("admin", "bot_stop_success", alias=html.escape(alias)), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(msg("admin", "bot_stop_failed", error=str(e)))


async def bot_set_cli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 3:
        await update.message.reply_text(msg("admin", "bot_set_cli_usage"))
        return

    alias = context.args[0].strip().lower()
    cli_type = context.args[1].strip()
    cli_path = " ".join(context.args[2:]).strip()

    manager = get_manager(context)
    try:
        await manager.set_bot_cli(alias, cli_type, cli_path)
        await update.message.reply_text(
            msg("admin", "bot_set_cli_success", alias=html.escape(alias), cli_type=html.escape(cli_type), cli_path=html.escape(cli_path)),
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(msg("admin", "bot_set_cli_failed", error=str(e)))


async def bot_set_workdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(msg("admin", "bot_set_workdir_usage"))
        return

    alias = context.args[0].strip().lower()
    workdir = " ".join(context.args[1:]).strip()

    manager = get_manager(context)
    try:
        await manager.set_bot_workdir(alias, workdir)
        await update.message.reply_text(
            msg("admin", "bot_set_workdir_success", alias=html.escape(alias), workdir=html.escape(os.path.abspath(os.path.expanduser(workdir)))),
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(msg("admin", "bot_set_workdir_failed", error=str(e)))


async def system_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统脚本管理命令（仅主Bot可用）
    
    用法:
        /system           - 显示脚本按钮菜单
        /system <脚本名>   - 执行指定脚本
    """
    if not await ensure_admin(update, context):
        return

    # 检查 scripts 目录是否存在
    if not SCRIPTS_DIR.exists():
        await update.message.reply_text(msg("admin", "system_no_scripts_dir", path=SCRIPTS_DIR))
        return

    # 如果没有参数，显示按钮菜单
    if not context.args:
        scripts = list_available_scripts()
        
        if not scripts:
            await update.message.reply_text(
                msg("admin", "system_no_scripts",
                    extensions=', '.join(SCRIPT_EXTENSIONS),
                    path=html.escape(str(SCRIPTS_DIR))),
                parse_mode="HTML"
            )
            return
        
        # 创建按钮网格（每行2个按钮）
        keyboard = []
        row = []
        for script_name, display_name, description, script_path in scripts:
            # 按钮显示中文名，回调数据包含脚本名
            btn = InlineKeyboardButton(
                text=display_name,
                callback_data=f"sys:{script_name}"
            )
            row.append(btn)
            if len(row) == 2:  # 每行2个按钮
                keyboard.append(row)
                row = []
        if row:  # 添加剩余按钮
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            msg("admin", "system_menu_title"),
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return

    # 有参数，执行指定脚本
    script_name = context.args[0].strip()
    
    # 查找匹配的脚本
    scripts = list_available_scripts()
    target_script = None
    for name, display_name, desc, path in scripts:
        if name.lower() == script_name.lower():
            target_script = path
            break
    
    if target_script is None:
        # 尝试添加扩展名查找
        for ext in SCRIPT_EXTENSIONS:
            candidate = SCRIPTS_DIR / f"{script_name}{ext}"
            if candidate.exists():
                target_script = candidate
                break
        
        if target_script is None:
            available = ", ".join([name for name, _, _, _ in scripts]) if scripts else "无"
            await update.message.reply_text(
                msg("admin", "system_script_not_found",
                    script_name=html.escape(script_name),
                    available=html.escape(available)),
                parse_mode="HTML"
            )
            return

    # 执行脚本
    await _execute_and_reply(update, target_script)


async def _execute_and_reply(update_or_query, target_script: Path):
    """执行脚本并发送结果"""
    reply_func = update_or_query.message.reply_text if hasattr(update_or_query, 'message') else update_or_query.reply_text
    edit_func = update_or_query.edit_message_text if hasattr(update_or_query, 'edit_message_text') else None
    
    # 发送执行中消息
    status_msg = await reply_func(msg("admin", "system_executing", script_name=html.escape(target_script.name)), parse_mode="HTML")
    
    # 在后台执行，避免阻塞
    loop = asyncio.get_event_loop()
    success, output = await loop.run_in_executor(None, execute_script, target_script)
    
    # 限制输出长度
    if len(output) > 2000:
        output = output[:1900] + "\n\n... (输出过长，已截断)"
    
    if success:
        result_text = msg("admin", "system_exec_success",
                          script_name=html.escape(target_script.name),
                          output=html.escape(output))
    else:
        result_text = msg("admin", "system_exec_failed",
                          script_name=html.escape(target_script.name),
                          output=html.escape(output))
    
    # 尝试编辑原消息，如果失败则发送新消息
    if edit_func:
        try:
            await edit_func(result_text, parse_mode="HTML")
            return
        except Exception:
            pass
    
    await reply_func(result_text, parse_mode="HTML")


async def system_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理系统脚本按钮点击"""
    query = update.callback_query
    await query.answer()
    
    # 检查权限
    if not await ensure_admin(update, context):
        return
    
    # 解析回调数据
    data = query.data
    if not data.startswith("sys:"):
        return
    
    script_name = data[4:]  # 去掉 "sys:" 前缀
    
    # 查找匹配的脚本
    scripts = list_available_scripts()
    target_script = None
    for name, display_name, desc, path in scripts:
        if name.lower() == script_name.lower():
            target_script = path
            break
    
    if target_script is None:
        await query.edit_message_text(msg("admin", "system_script_not_found", script_name=html.escape(script_name), available=""), parse_mode="HTML")
        return
    
    # 执行脚本
    await _execute_and_reply(query, target_script)


async def bot_goto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 goto 按钮点击，临时切换到指定 bot 的工作目录"""
    query = update.callback_query
    await query.answer()
    
    # 检查权限
    if not await ensure_admin(update, context):
        return
    
    # 解析回调数据
    data = query.data
    if not data.startswith("goto:"):
        return
    
    alias = data[5:]  # 去掉 "goto:" 前缀
    manager = get_manager(context)
    
    # 获取目标工作目录
    if alias == manager.main_profile.alias:
        target_workdir = manager.main_profile.working_dir
        display_name = "主 Bot"
    else:
        profile = manager.managed_profiles.get(alias)
        if not profile:
            await query.edit_message_text(
                f"❌ 未找到别名 <code>{html.escape(alias)}</code> 的 Bot",
                parse_mode="HTML"
            )
            return
        target_workdir = profile.working_dir
        display_name = f"Bot <code>{html.escape(alias)}</code>"
    
    # 检查目录是否存在
    if not os.path.isdir(target_workdir):
        await query.edit_message_text(
            f"❌ {display_name} 的工作目录不存在:\n<code>{html.escape(target_workdir)}</code>",
            parse_mode="HTML"
        )
        return
    
    # 获取当前用户的主 bot session（在主 bot 的上下文中切换目录）
    from bot.sessions import get_or_create_session
    from bot.context_helpers import get_bot_id
    
    main_app = manager.applications.get(manager.main_profile.alias)
    if not main_app:
        await query.edit_message_text(
            "❌ 主 Bot 未运行，无法切换工作目录",
            parse_mode="HTML"
        )
        return
    
    main_bot_id = main_app.bot_data.get("bot_id")
    if not isinstance(main_bot_id, int):
        await query.edit_message_text(
            "❌ 无法获取主 Bot ID",
            parse_mode="HTML"
        )
        return
    
    user_id = update.effective_user.id
    session = get_or_create_session(main_bot_id, user_id, manager.main_profile.alias)
    
    # 临时切换工作目录（不修改配置文件）
    # 如果 session 没有设置过工作目录，使用主 bot 的默认工作目录
    old_workdir = session.working_dir or manager.main_profile.working_dir
    session.working_dir = target_workdir
    
    await query.edit_message_text(
        f"✅ 已临时切换到 {display_name} 的工作目录\n\n"
        f"📁 新目录: <code>{html.escape(target_workdir)}</code>\n"
        f"📁 原目录: <code>{html.escape(old_workdir)}</code>\n\n"
        f"<i>提示：这是临时切换，使用 /reset 或重启后会恢复默认目录</i>",
        parse_mode="HTML"
    )


async def bot_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """终止指定 Bot 的当前任务（支持指定用户ID）"""
    if not await ensure_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(msg("admin", "bot_kill_usage"))
        return

    alias = context.args[0].strip().lower()
    target_user_id = None

    if len(context.args) >= 2:
        try:
            target_user_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text(msg("admin", "bot_kill_invalid_user_id"))
            return

    manager = get_manager(context)

    # 获取目标 bot_id
    target_bot_id = None
    if alias == manager.main_profile.alias:
        main_app = manager.applications.get(manager.main_profile.alias)
        if main_app:
            target_bot_id = main_app.bot_data.get("bot_id")
    else:
        profile = manager.managed_profiles.get(alias)
        if profile:
            app = manager.applications.get(alias)
            if app:
                target_bot_id = app.bot_data.get("bot_id")

    if target_bot_id is None:
        await update.message.reply_text(msg("admin", "bot_kill_not_running", alias=html.escape(alias)), parse_mode="HTML")
        return

    # 查找并终止匹配的会话
    terminated = []
    with sessions_lock:
        for (bot_id, user_id), session in list(sessions.items()):
            if bot_id != target_bot_id:
                continue
            if target_user_id is not None and user_id != target_user_id:
                continue

            if session.is_processing and session.process is not None:
                process = session.process
                try:
                    if process.poll() is None:
                        process.terminate()
                        # 给进程1秒时间优雅退出
                        import time
                        time.sleep(0.5)
                        if process.poll() is None:
                            process.kill()
                        terminated.append((user_id, session.bot_alias))
                except Exception as e:
                    logger.error(f"终止进程时出错: {e}")

    if terminated:
        lines = [msg("admin", "bot_kill_success", alias=html.escape(alias))]
        for user_id, bot_alias in terminated:
            lines.append(msg("admin", "bot_kill_user_line", user_id=user_id))
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    else:
        if target_user_id is not None:
            await update.message.reply_text(
                msg("admin", "bot_kill_no_task_user", alias=html.escape(alias), user_id=target_user_id),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                msg("admin", "bot_kill_no_task", alias=html.escape(alias)),
                parse_mode="HTML"
            )



