"""按 (bot_id, user_id) 隔离的会话存储与生命周期管理"""

import logging
import threading
from typing import Dict, Tuple

from bot.models import UserSession
from bot.session_store import load_session, remove_session, remove_all_sessions_for_bot, save_session

logger = logging.getLogger(__name__)

# 全局会话存储
sessions: Dict[Tuple[int, int], UserSession] = {}
sessions_lock = threading.Lock()


def get_or_create_session(bot_id: int, bot_alias: str, user_id: int, default_working_dir: str = None) -> UserSession:
    key = (bot_id, user_id)

    with sessions_lock:
        if key in sessions and sessions[key].is_expired():
            expired_session = sessions[key]
            del sessions[key]
        else:
            expired_session = None

    # 在锁外终止进程，避免持锁期间阻塞其他会话操作
    if expired_session is not None:
        try:
            expired_session.terminate_process()
        except Exception:
            pass

    with sessions_lock:
        if key not in sessions:
            # 尝试从持久化存储恢复会话
            stored_data = load_session(bot_id, user_id)
            
            codex_session_id = None
            kimi_session_id = None
            claude_session_id = None
            claude_session_initialized = False
            
            if stored_data:
                codex_session_id = stored_data.get("codex_session_id")
                kimi_session_id = stored_data.get("kimi_session_id")
                claude_session_id = stored_data.get("claude_session_id")
                # 恢复时标记为已初始化（因为我们有 session_id）
                claude_session_initialized = bool(claude_session_id)
                if codex_session_id or kimi_session_id or claude_session_id:
                    logger.info(f"已恢复会话: bot={bot_id}, user={user_id}, "
                              f"codex={codex_session_id is not None}, "
                              f"kimi={kimi_session_id is not None}, "
                              f"claude={claude_session_id is not None}")
            
            sessions[key] = UserSession(
                bot_id=bot_id,
                bot_alias=bot_alias,
                user_id=user_id,
                working_dir=default_working_dir,
                codex_session_id=codex_session_id,
                kimi_session_id=kimi_session_id,
                claude_session_id=claude_session_id,
                claude_session_initialized=claude_session_initialized,
            )
        return sessions[key]


# 保持向后兼容的别名
get_session = get_or_create_session


def _save_session_to_store(session: UserSession):
    """保存会话到持久化存储"""
    save_session(
        bot_id=session.bot_id,
        user_id=session.user_id,
        codex_session_id=session.codex_session_id,
        kimi_session_id=session.kimi_session_id,
        claude_session_id=session.claude_session_id,
    )


def reset_session(bot_id: int, user_id: int) -> bool:
    key = (bot_id, user_id)
    with sessions_lock:
        if key in sessions:
            sessions[key].terminate_process()
            del sessions[key]
            # 清除持久化存储
            remove_session(bot_id, user_id)
            return True
    return False


def clear_bot_sessions(bot_id: int):
    with sessions_lock:
        keys = [k for k in sessions if k[0] == bot_id]
        for key in keys:
            sessions[key].terminate_process()
            del sessions[key]
    # 清除持久化存储
    remove_all_sessions_for_bot(bot_id)


def is_bot_processing(bot_id: int) -> bool:
    """检查指定 bot 是否有正在处理消息的会话"""
    # 使用非阻塞方式快速检查，避免长时间持有锁
    if not sessions_lock.acquire(timeout=1.0):
        # 如果获取锁超时，假设正在处理（保守策略）
        return True
    try:
        for key, session in sessions.items():
            if key[0] == bot_id and session.is_processing:
                return True
        return False
    finally:
        sessions_lock.release()


def cleanup_expired_sessions():
    """清理过期的会话"""
    with sessions_lock:
        expired_keys = [
            key for key, session in sessions.items()
            if session.is_expired()
        ]
        expired_sessions = [(key, sessions.pop(key)) for key in expired_keys]

    # 在锁外终止进程和持久化，避免持锁期间阻塞
    for key, session in expired_sessions:
        session.terminate_process()
        _save_session_to_store(session)
        logger.info(f"已清理过期会话: bot={key[0]}, user={key[1]}")


def update_bot_working_dir(bot_alias: str, working_dir: str) -> int:
    """更新指定 bot 的所有会话的工作目录
    
    返回更新的会话数量
    """
    updated_count = 0
    with sessions_lock:
        for session in sessions.values():
            if session.bot_alias == bot_alias:
                session.working_dir = working_dir
                updated_count += 1
    return updated_count


def save_all_sessions():
    """保存所有会话到持久化存储
    
    用于程序正常退出时保存状态
    """
    with sessions_lock:
        for session in sessions.values():
            _save_session_to_store(session)
    logger.info("已保存所有会话到持久化存储")
