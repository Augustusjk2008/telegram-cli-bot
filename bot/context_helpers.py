"""从 Telegram Update/Context 中提取 bot/session/profile 信息"""

import logging
from typing import TYPE_CHECKING

from telegram import Message, Update
from telegram.ext import ContextTypes

from bot.models import BotProfile, UserSession
from bot.sessions import align_session_paths, get_session
from bot.utils import check_auth

if TYPE_CHECKING:
    from bot.manager import MultiBotManager

logger = logging.getLogger(__name__)


def get_manager(context: ContextTypes.DEFAULT_TYPE) -> "MultiBotManager":
    return context.application.bot_data["manager"]


def get_bot_alias(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str(context.application.bot_data.get("bot_alias", "main"))


def is_main_application(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.application.bot_data.get("is_main", False))


def get_bot_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bot_id = context.application.bot_data.get("bot_id")
    if isinstance(bot_id, int):
        return bot_id
    if update.effective_chat:
        return int(update.effective_chat.id)
    return 0


def get_current_profile(context: ContextTypes.DEFAULT_TYPE) -> BotProfile:
    manager = get_manager(context)
    return manager.get_profile(get_bot_alias(context))


def get_current_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> UserSession:
    profile = get_current_profile(context)
    session = get_session(
        bot_id=get_bot_id(update, context),
        bot_alias=get_bot_alias(context),
        user_id=update.effective_user.id,
        default_working_dir=profile.working_dir,
    )
    return align_session_paths(session, profile.working_dir, profile.bot_mode)


def get_reply_target(update: Update) -> Message | None:
    return update.effective_message


async def reply_text(update: Update, text: str, **kwargs) -> Message | None:
    message = get_reply_target(update)
    if message is None:
        logger.warning("无法回复消息: update.effective_message is None")
        return None
    return await message.reply_text(text, **kwargs)


async def ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_main_application(context):
        await reply_text(update, "⛔ 该命令仅主Bot可用")
        return False

    user_id = update.effective_user.id
    if not check_auth(user_id):
        await reply_text(update, "⛔ 未授权的用户")
        return False

    return True
