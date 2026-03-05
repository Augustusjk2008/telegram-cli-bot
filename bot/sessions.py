"""按 (bot_id, user_id) 隔离的会话存储与生命周期管理"""

import logging
import threading
from typing import Dict, Tuple

from bot.models import UserSession

logger = logging.getLogger(__name__)

# 全局会话存储
sessions: Dict[Tuple[int, int], UserSession] = {}
sessions_lock = threading.Lock()


def get_session(bot_id: int, bot_alias: str, user_id: int, default_working_dir: str) -> UserSession:
    key = (bot_id, user_id)
    with sessions_lock:
        if key in sessions and sessions[key].is_expired():
            sessions[key].terminate_process()
            del sessions[key]

        if key not in sessions:
            sessions[key] = UserSession(
                bot_id=bot_id,
                bot_alias=bot_alias,
                user_id=user_id,
                working_dir=default_working_dir,
            )
        return sessions[key]


def reset_session(bot_id: int, user_id: int) -> bool:
    key = (bot_id, user_id)
    with sessions_lock:
        if key in sessions:
            sessions[key].terminate_process()
            del sessions[key]
            return True
    return False


def clear_bot_sessions(bot_id: int):
    with sessions_lock:
        keys = [k for k in sessions if k[0] == bot_id]
        for key in keys:
            sessions[key].terminate_process()
            del sessions[key]


def is_bot_processing(bot_id: int) -> bool:
    """检查指定 bot 是否有正在处理消息的会话"""
    with sessions_lock:
        for key, session in sessions.items():
            if key[0] == bot_id and session.is_processing:
                return True
    return False


def cleanup_expired_sessions():
    """清理过期的会话"""
    with sessions_lock:
        expired_keys = [
            key for key, session in sessions.items()
            if session.is_expired()
        ]
        for key in expired_keys:
            session = sessions.pop(key)
            session.terminate_process()
            logger.info(f"已清理过期会话: bot={key[0]}, user={key[1]}")
