from bot.config import WEB_DEFAULT_USER_ID

CHAT_SHARED_USER_ID = int(WEB_DEFAULT_USER_ID)


def chat_session_user_id(_: int | None = None) -> int:
    return CHAT_SHARED_USER_ID
