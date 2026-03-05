"""统一注册所有 handler"""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .basic import start, reset, change_directory, print_working_directory, list_directory, show_history
from .shell import execute_shell
from .file import upload_help, handle_document, download_file
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


def register_handlers(application: Application, include_admin: bool = False):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("cd", change_directory))
    application.add_handler(CommandHandler("pwd", print_working_directory))
    application.add_handler(CommandHandler("ls", list_directory))
    application.add_handler(CommandHandler("exec", execute_shell))
    application.add_handler(CommandHandler("history", show_history))
    application.add_handler(CommandHandler("upload", upload_help))
    application.add_handler(CommandHandler("download", download_file))

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

    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
