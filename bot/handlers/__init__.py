"""统一注册所有 handler"""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .basic import start, reset, change_directory, print_working_directory, list_directory, show_history
from .shell import execute_shell
from .file import upload_help, handle_document, download_file, cat_file, head_file
from .chat import handle_text_message
from .admin import (
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
)

logger = logging.getLogger(__name__)

# 尝试导入语音处理器（如果依赖未安装则跳过）
try:
    from .voice import handle_voice_message, handle_audio_message
    VOICE_HANDLER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"语音处理器不可用（缺少依赖）: {e}")
    VOICE_HANDLER_AVAILABLE = False

# 尝试导入助手处理器（如果依赖未安装则跳过）
try:
    from .assistant import handle_assistant_message
    ASSISTANT_HANDLER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"助手处理器不可用（缺少依赖）: {e}")
    ASSISTANT_HANDLER_AVAILABLE = False


def _register_cli_handlers(application: Application, include_admin: bool):
    """注册 CLI 模式的 handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("cd", change_directory))
    application.add_handler(CommandHandler("pwd", print_working_directory))
    application.add_handler(CommandHandler("ls", list_directory))
    application.add_handler(CommandHandler("exec", execute_shell))
    application.add_handler(CommandHandler("history", show_history))
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
        application.add_handler(CallbackQueryHandler(system_button_callback, pattern="^sys:"))

    # 语音和音频处理（优先级高于文档和文字）
    if VOICE_HANDLER_AVAILABLE:
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        application.add_handler(MessageHandler(filters.AUDIO, handle_audio_message))
        logger.info("语音处理器已注册")

    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))


def _register_assistant_handlers(application: Application, include_admin: bool):
    """注册助手模式的 handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("history", show_history))

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
        application.add_handler(CallbackQueryHandler(system_button_callback, pattern="^sys:"))

    # 语音和音频处理（优先级高于文字）
    if VOICE_HANDLER_AVAILABLE:
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        application.add_handler(MessageHandler(filters.AUDIO, handle_audio_message))
        logger.info("语音处理器已注册")

    # 助手模式的文本消息处理
    if ASSISTANT_HANDLER_AVAILABLE:
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_assistant_message))
        logger.info("助手处理器已注册")
    else:
        logger.warning("助手处理器不可用，文本消息将无法处理")


def register_handlers(application: Application, include_admin: bool = False):
    """根据 bot_mode 注册对应的 handlers"""
    bot_mode = application.bot_data.get("bot_mode", "cli")

    if bot_mode == "assistant":
        logger.info("注册助手模式 handlers")
        _register_assistant_handlers(application, include_admin)
    else:
        logger.info("注册 CLI 模式 handlers")
        _register_cli_handlers(application, include_admin)
