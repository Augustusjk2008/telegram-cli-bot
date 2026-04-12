"""统一注册所有 handler"""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .basic import start, reset, kill_process, change_directory, print_working_directory, list_directory, show_history, codex_status, handle_keyboard_command
from .shell import execute_shell, remove_file
from .file import upload_help, handle_document, download_file, cat_file, head_file
from .file_browser import show_file_browser, handle_file_browser_callback
from .chat import handle_text_message, handle_stop_callback
from .admin import (
    assistant_approve,
    assistant_proposals,
    assistant_reject,
    bot_help,
    bot_list,
    restart_main,
    bot_add,
    bot_remove,
    bot_start,
    bot_stop,
    bot_set_cli,
    bot_set_workdir,
    bot_kill,
    system_command,
    system_button_callback,
    bot_goto_callback,
    bot_params,
    bot_params_set,
    bot_params_reset,
    bot_params_help,
)

logger = logging.getLogger(__name__)

# 尝试导入语音处理器（如果依赖未安装则跳过）
try:
    from .voice import handle_voice_message, handle_audio_message
    VOICE_HANDLER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"语音处理器不可用（缺少依赖）: {e}")
    VOICE_HANDLER_AVAILABLE = False

def _register_cli_handlers(application: Application, include_admin: bool):
    """注册 CLI 模式的 handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("kill", kill_process))
    application.add_handler(CommandHandler("cd", change_directory))
    application.add_handler(CommandHandler("pwd", print_working_directory))
    application.add_handler(CommandHandler("files", show_file_browser))
    application.add_handler(CommandHandler("ls", list_directory))
    application.add_handler(CommandHandler("exec", execute_shell))
    application.add_handler(CommandHandler("rm", remove_file))
    application.add_handler(CommandHandler("history", show_history))
    application.add_handler(CommandHandler("codex_status", codex_status))
    application.add_handler(CommandHandler("upload", upload_help))
    application.add_handler(CommandHandler("download", download_file))
    application.add_handler(CommandHandler("cat", cat_file))
    application.add_handler(CommandHandler("head", head_file))

    if include_admin:
        application.add_handler(CommandHandler("restart", restart_main))
        application.add_handler(CommandHandler("bot_help", bot_help))
        application.add_handler(CommandHandler("bot_list", bot_list))
        application.add_handler(CommandHandler("bot_add", bot_add))
        application.add_handler(CommandHandler("bot_remove", bot_remove))
        application.add_handler(CommandHandler("bot_start", bot_start))
        application.add_handler(CommandHandler("bot_stop", bot_stop))
        application.add_handler(CommandHandler("bot_set_cli", bot_set_cli))
        application.add_handler(CommandHandler("bot_set_workdir", bot_set_workdir))
        application.add_handler(CommandHandler("bot_kill", bot_kill))
        application.add_handler(CommandHandler("system", system_command))
        # CLI 参数配置命令
        application.add_handler(CommandHandler("bot_params", bot_params))
        application.add_handler(CommandHandler("bot_params_set", bot_params_set))
        application.add_handler(CommandHandler("bot_params_reset", bot_params_reset))
        application.add_handler(CommandHandler("bot_params_help", bot_params_help))
        application.add_handler(CommandHandler("assistant_proposals", assistant_proposals))
        application.add_handler(CommandHandler("assistant_approve", assistant_approve))
        application.add_handler(CommandHandler("assistant_reject", assistant_reject))
        application.add_handler(CallbackQueryHandler(system_button_callback, pattern="^sys:"))
        application.add_handler(CallbackQueryHandler(bot_goto_callback, pattern="^goto:"))
    application.add_handler(CallbackQueryHandler(handle_file_browser_callback, pattern="^fb:"))

    # 语音和音频处理（优先级高于文档和文字）
    if VOICE_HANDLER_AVAILABLE:
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        application.add_handler(MessageHandler(filters.AUDIO, handle_audio_message))
        logger.info("语音处理器已注册")

    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # 键盘命令处理（匹配"/命令 中文"格式）
    # 停止任务回调（必须在文本消息处理器之前）
    application.add_handler(CallbackQueryHandler(handle_stop_callback, pattern="^stop_task$"))
    
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^(文件浏览|查看目录|当前路径|重置会话|系统脚本|历史记录|机器人列表|重启系统|/(files|ls|pwd|reset|history|bot_list|restart|system))'), handle_keyboard_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))


def _register_assistant_handlers(application: Application, include_admin: bool):
    """注册 assistant 模式 handlers。

    assistant 已收敛为 CLI 的受限变体，命令面保持一致。
    """
    _register_cli_handlers(application, include_admin)


def register_handlers(application: Application, include_admin: bool = False):
    """根据 bot_mode 注册对应的 handlers"""
    bot_mode = application.bot_data.get("bot_mode", "cli")

    if bot_mode == "assistant":
        logger.info("注册 assistant 兼容模式 handlers")
        _register_assistant_handlers(application, include_admin)
    else:
        logger.info("注册 CLI 模式 handlers")
        _register_cli_handlers(application, include_admin)
