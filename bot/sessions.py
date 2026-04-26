"""按 (bot_id, user_id) 隔离的会话存储与生命周期管理"""

import logging
import threading
from datetime import datetime
from typing import Dict, Tuple

from bot.models import UserSession
from bot.session_store import (
    LOCAL_HISTORY_BACKEND,
    load_session,
    migrate_local_history_snapshot,
    remove_all_sessions_for_bot,
    remove_session,
    save_session,
)

logger = logging.getLogger(__name__)

# 全局会话存储
sessions: Dict[Tuple[int, int], UserSession] = {}
sessions_lock = threading.Lock()


def _parse_stored_datetime(value) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


def _session_rank(session: UserSession) -> tuple[int, int, int, str]:
    with session._lock:
        return (
            max(0, int(getattr(session, "message_count", 0) or 0)),
            int(bool(getattr(session, "codex_session_id", None))) + int(bool(getattr(session, "claude_session_id", None))),
            max(0, int(getattr(session, "session_epoch", 0) or 0)),
            getattr(session, "last_activity", datetime.min).isoformat() if getattr(session, "last_activity", None) else "",
        )


def _merge_session_state(preferred: UserSession, fallback: UserSession, *, bot_id: int, bot_alias: str) -> UserSession:
    with preferred._lock, fallback._lock:
        preferred.bot_id = bot_id
        preferred.bot_alias = bot_alias
        preferred.working_dir = preferred.working_dir or fallback.working_dir
        preferred.browse_dir = preferred.browse_dir or fallback.browse_dir or preferred.working_dir
        preferred.codex_session_id = preferred.codex_session_id or fallback.codex_session_id
        preferred.claude_session_id = preferred.claude_session_id or fallback.claude_session_id
        preferred.claude_session_initialized = (
            preferred.claude_session_initialized or fallback.claude_session_initialized
        )
        preferred.message_count = max(preferred.message_count, fallback.message_count)
        preferred.session_epoch = max(preferred.session_epoch, fallback.session_epoch)
        preferred.managed_prompt_hash_seen = (
            preferred.managed_prompt_hash_seen or fallback.managed_prompt_hash_seen
        )
        preferred.local_history_backend = preferred.local_history_backend or fallback.local_history_backend
        if fallback.last_activity > preferred.last_activity:
            preferred.last_activity = fallback.last_activity
        if (not preferred.is_processing and fallback.is_processing) or (
            preferred.process is None and fallback.process is not None
        ):
            preferred.process = fallback.process
            preferred.is_processing = fallback.is_processing
            preferred.running_user_text = fallback.running_user_text
            preferred.running_preview_text = fallback.running_preview_text
            preferred.running_started_at = fallback.running_started_at
            preferred.running_updated_at = fallback.running_updated_at
            preferred.stop_requested = fallback.stop_requested
        if not preferred.web_turn_overlays and fallback.web_turn_overlays:
            preferred.web_turn_overlays = list(fallback.web_turn_overlays)
    return preferred


def get_or_create_session(
    bot_id: int,
    bot_alias: str,
    user_id: int,
    default_working_dir: str = None,
    load_persisted_state: bool = True,
) -> UserSession:
    key = (bot_id, user_id)
    should_persist_migration = False

    with sessions_lock:
        if key not in sessions:
            # 尝试从持久化存储恢复会话
            stored_data = load_session(bot_id, user_id) if load_persisted_state else None
            
            codex_session_id = None
            claude_session_id = None
            claude_session_initialized = False
            working_dir = default_working_dir
            browse_dir = None
            history = []
            web_turn_overlays = []
            message_count = 0
            last_activity = datetime.now()
            running_user_text = None
            running_preview_text = ""
            running_started_at = None
            running_updated_at = None
            local_history_backend = LOCAL_HISTORY_BACKEND
            session_epoch = 0
            managed_prompt_hash_seen = None
            
            if stored_data:
                original_stored_data = dict(stored_data)
                stored_data = migrate_local_history_snapshot(
                    stored_data,
                    default_working_dir=default_working_dir,
                )
                should_persist_migration = (
                    original_stored_data.get("local_history_backend") != LOCAL_HISTORY_BACKEND
                )
                codex_session_id = stored_data.get("codex_session_id")
                claude_session_id = stored_data.get("claude_session_id")
                working_dir = stored_data.get("working_dir") or default_working_dir
                browse_dir = stored_data.get("browse_dir") or None
                try:
                    message_count = max(0, int(stored_data.get("message_count", 0) or 0))
                except (TypeError, ValueError):
                    message_count = 0
                last_activity = _parse_stored_datetime(stored_data.get("last_activity"))
                local_history_backend = stored_data.get("local_history_backend") or LOCAL_HISTORY_BACKEND
                try:
                    session_epoch = max(0, int(stored_data.get("session_epoch", 0) or 0))
                except (TypeError, ValueError):
                    session_epoch = 0
                managed_prompt_hash_seen = stored_data.get("managed_prompt_hash_seen") or None
                # 恢复时标记为已初始化（因为我们有 session_id）
                claude_session_initialized = bool(claude_session_id)
                if (
                    codex_session_id
                    or claude_session_id
                    or working_dir != default_working_dir
                ):
                    logger.info(f"已恢复会话: bot={bot_id}, user={user_id}, "
                              f"codex={codex_session_id is not None}, "
                              f"claude={claude_session_id is not None}, "
                              f"epoch={session_epoch}")
            
            sessions[key] = UserSession(
                bot_id=bot_id,
                bot_alias=bot_alias,
                user_id=user_id,
                working_dir=working_dir,
                browse_dir=browse_dir,
                history=[],
                codex_session_id=codex_session_id,
                claude_session_id=claude_session_id,
                claude_session_initialized=claude_session_initialized,
                web_turn_overlays=web_turn_overlays,
                running_user_text=running_user_text,
                running_preview_text=running_preview_text,
                running_started_at=running_started_at,
                running_updated_at=running_updated_at,
                last_activity=last_activity,
                message_count=message_count,
                local_history_backend=local_history_backend,
                session_epoch=session_epoch,
                managed_prompt_hash_seen=managed_prompt_hash_seen,
            )
            session = sessions[key]
        else:
            session = sessions[key]

    if should_persist_migration:
        _save_session_to_store(session)
    return session


# 保持向后兼容的别名
get_session = get_or_create_session


def _save_session_to_store(session: UserSession):
    """保存会话到持久化存储"""
    with session._lock:
        save_session(
            bot_id=session.bot_id,
            user_id=session.user_id,
            codex_session_id=session.codex_session_id,
            claude_session_id=session.claude_session_id,
            working_dir=session.working_dir,
            browse_dir=session.browse_dir,
            message_count=session.message_count,
            last_activity=session.last_activity.isoformat(),
            local_history_backend=session.local_history_backend,
            session_epoch=session.session_epoch,
            managed_prompt_hash_seen=session.managed_prompt_hash_seen,
        )


def reset_session(bot_id: int, user_id: int) -> bool:
    key = (bot_id, user_id)
    removed_in_memory = False
    with sessions_lock:
        session = sessions.pop(key, None)
        removed_in_memory = session is not None

    if session is not None:
        session.disable_persistence()
        try:
            session.terminate_process()
        except Exception as exc:
            logger.warning("终止会话进程失败 bot=%s user=%s error=%s", bot_id, user_id, exc)

    removed_from_store = remove_session(bot_id, user_id)
    return removed_in_memory or removed_from_store


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


def terminate_bot_processes(bot_alias: str) -> int:
    """终止指定 bot 的所有活动会话进程。"""
    targets: list[UserSession] = []
    with sessions_lock:
        for session in sessions.values():
            with session._lock:
                has_process = session.process is not None
                is_processing = session.is_processing
                alias_matches = session.bot_alias == bot_alias
            if alias_matches and (has_process or is_processing):
                targets.append(session)

    terminated = 0
    for session in targets:
        try:
            session.terminate_process()
            terminated += 1
        except Exception as exc:
            logger.warning("终止 bot 会话进程失败 alias=%s user=%s error=%s", bot_alias, session.user_id, exc)
    return terminated


def update_bot_working_dir(bot_alias: str, working_dir: str) -> int:
    """更新指定 bot 的所有会话的工作目录
    
    返回更新的会话数量
    """
    updated_count = 0
    with sessions_lock:
        for session in sessions.values():
            if session.bot_alias == bot_alias:
                session.working_dir = working_dir
                session.browse_dir = working_dir
                session.persist()
                updated_count += 1
    return updated_count


def align_session_paths(session: UserSession, default_working_dir: str, bot_mode: str) -> UserSession:
    """按 bot_mode 统一修正真实工作目录与文件浏览目录。"""
    changed = False
    with session._lock:
        current_browse_dir = (
            session.browse_dir
            if isinstance(session.browse_dir, str) and session.browse_dir
            else session.working_dir or default_working_dir
        )
        if session.browse_dir != current_browse_dir:
            session.browse_dir = current_browse_dir
            changed = True

        if bot_mode == "assistant" and default_working_dir and session.working_dir != default_working_dir:
            session.working_dir = default_working_dir
            changed = True

    if changed:
        session.persist()
    return session


def update_bot_alias(old_alias: str, new_alias: str) -> int:
    """更新指定 bot 的所有会话别名。"""
    updated_count = 0
    with sessions_lock:
        for session in sessions.values():
            if session.bot_alias == old_alias:
                session.bot_alias = new_alias
                session.persist()
                updated_count += 1
    return updated_count


def rekey_bot_sessions(old_bot_id: int, new_bot_id: int, *, old_alias: str, new_alias: str) -> int:
    """将内存中的 bot 会话迁移到新的 bot_id。"""
    if old_bot_id == new_bot_id:
        return update_bot_alias(old_alias, new_alias)

    moved = 0
    with sessions_lock:
        for key in [item for item in list(sessions.keys()) if item[0] == old_bot_id]:
            source = sessions.pop(key)
            target_key = (new_bot_id, source.user_id)
            target = sessions.pop(target_key, None)

            if target is None:
                source.bot_id = new_bot_id
                source.bot_alias = new_alias
                sessions[target_key] = source
                moved += 1
                continue

            preferred, fallback = (
                (source, target) if _session_rank(source) >= _session_rank(target) else (target, source)
            )
            merged = _merge_session_state(preferred, fallback, bot_id=new_bot_id, bot_alias=new_alias)
            sessions[target_key] = merged
            fallback.disable_persistence()
            moved += 1

    return moved


def save_all_sessions():
    """保存所有会话到持久化存储
    
    用于程序正常退出时保存状态
    """
    with sessions_lock:
        for session in sessions.values():
            session.persist()
    logger.info("已保存所有会话到持久化存储")
