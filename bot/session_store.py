"""会话快照持久化存储。

按 (bot_id, user_id) 将会话相关状态保存到 JSON 文件，程序重启后可以恢复：
- 各 CLI 的 session_id
- 用户工作目录
- 文件浏览目录
- Web 端最小 overlay 快照
- 运行中回复的最近快照
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from bot.config import MANAGED_BOTS_FILE

logger = logging.getLogger(__name__)
LOCAL_HISTORY_BACKEND = "local_v1"

# 存储文件路径（与托管bots文件同级目录）
STORE_FILE = Path(MANAGED_BOTS_FILE).parent / ".session_store.json"

_store_lock = threading.Lock()


def load_session_ids() -> Dict[str, dict]:
    """加载所有持久化的会话ID

    Returns:
        Dict[str, dict]: 键为 "bot_id:user_id"，值为 session 信息字典
    """
    if not STORE_FILE.exists():
        return {}

    try:
        with _store_lock:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"加载会话存储文件失败: {e}")
        return {}


def save_session_ids(data: Dict[str, dict]):
    """保存所有会话ID到文件"""
    try:
        with _store_lock:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"保存会话存储文件失败: {e}")


def _make_key(bot_id: int, user_id: int) -> str:
    """生成存储键"""
    return f"{bot_id}:{user_id}"


def _parse_key(key: str) -> Tuple[int, int] | None:
    try:
        bot_text, user_text = str(key or "").split(":", 1)
        return int(bot_text), int(user_text)
    except (TypeError, ValueError):
        return None


def _snapshot_rank(data: dict[str, Any] | None) -> tuple[int, int, int, str]:
    snapshot = dict(data or {})
    message_count = max(0, int(snapshot.get("message_count", 0) or 0))
    session_count = int(bool(snapshot.get("codex_session_id"))) + int(bool(snapshot.get("claude_session_id")))
    session_epoch = max(0, int(snapshot.get("session_epoch", 0) or 0))
    last_activity = str(snapshot.get("last_activity") or "")
    return (message_count, session_count, session_epoch, last_activity)


def _merge_session_snapshots(source: dict[str, Any] | None, target: dict[str, Any] | None) -> dict[str, Any]:
    source_data = dict(source or {})
    target_data = dict(target or {})
    preferred = source_data if _snapshot_rank(source_data) >= _snapshot_rank(target_data) else target_data
    fallback = target_data if preferred is source_data else source_data
    merged = dict(preferred)

    for key, value in fallback.items():
        if key not in merged or merged.get(key) in (None, "", [], {}):
            merged[key] = value

    merged["working_dir"] = str(
        merged.get("working_dir") or fallback.get("working_dir") or source_data.get("working_dir") or ""
    )
    browse_dir = merged.get("browse_dir") or fallback.get("browse_dir") or merged["working_dir"]
    if browse_dir:
        merged["browse_dir"] = str(browse_dir)
    elif "browse_dir" in merged:
        merged.pop("browse_dir", None)

    merged["message_count"] = max(
        0,
        int(source_data.get("message_count", 0) or 0),
        int(target_data.get("message_count", 0) or 0),
    )
    merged["session_epoch"] = max(
        0,
        int(source_data.get("session_epoch", 0) or 0),
        int(target_data.get("session_epoch", 0) or 0),
    )
    last_activity = max(str(source_data.get("last_activity") or ""), str(target_data.get("last_activity") or ""))
    if last_activity:
        merged["last_activity"] = last_activity
    elif "last_activity" in merged:
        merged.pop("last_activity", None)

    local_history_backend = (
        str(target_data.get("local_history_backend") or "")
        or str(source_data.get("local_history_backend") or "")
        or LOCAL_HISTORY_BACKEND
    )
    merged["local_history_backend"] = local_history_backend

    if not merged.get("codex_session_id"):
        merged.pop("codex_session_id", None)
    if not merged.get("claude_session_id"):
        merged.pop("claude_session_id", None)
    if not merged.get("managed_prompt_hash_seen"):
        merged.pop("managed_prompt_hash_seen", None)
    return merged


def _flush_live_session_if_available(bot_id: int, user_id: int):
    """在直接读取持久化快照前，尽量刷新同一会话的待写状态。

    `get_session()` 在持有 `sessions_lock` 时也会调用 `load_session()`，这里必须避免阻塞式重入。
    因此只在能立即拿到锁时刷新；拿不到锁就直接读取磁盘快照。
    """
    try:
        from bot.sessions import sessions, sessions_lock
    except ImportError:
        return

    if not sessions_lock.acquire(blocking=False):
        return

    try:
        session = sessions.get((bot_id, user_id))
    finally:
        sessions_lock.release()

    if session is not None:
        session.flush_persistence()


def load_session(bot_id: int, user_id: int) -> Optional[dict]:
    """加载指定会话的 session 信息
    
    Returns:
        dict: 包含 codex_session_id, claude_session_id
        None: 如果没有找到
    """
    _flush_live_session_if_available(bot_id, user_id)
    data = load_session_ids()
    key = _make_key(bot_id, user_id)
    return data.get(key)


def migrate_local_history_snapshot(data: dict[str, Any] | None, *, default_working_dir: str) -> dict[str, Any]:
    next_data = dict(data or {})
    if next_data.get("local_history_backend") == LOCAL_HISTORY_BACKEND:
        next_data["session_epoch"] = max(0, int(next_data.get("session_epoch", 0) or 0))
        if default_working_dir:
            next_data["working_dir"] = next_data.get("working_dir") or default_working_dir
            next_data["browse_dir"] = next_data.get("browse_dir") or next_data["working_dir"]
        return next_data

    next_data["local_history_backend"] = LOCAL_HISTORY_BACKEND
    next_data["session_epoch"] = max(1, int(next_data.get("session_epoch", 0) or 0) + 1)
    next_data["working_dir"] = next_data.get("working_dir") or default_working_dir
    next_data["browse_dir"] = next_data.get("browse_dir") or next_data["working_dir"]
    next_data["codex_session_id"] = None
    next_data["claude_session_id"] = None
    next_data["claude_session_initialized"] = False
    next_data.pop("running_user_text", None)
    next_data.pop("running_preview_text", None)
    next_data.pop("running_started_at", None)
    next_data.pop("running_updated_at", None)
    next_data.pop("web_turn_overlays", None)
    return next_data


def save_session(
    bot_id: int,
    user_id: int,
    codex_session_id: Optional[str] = None,
    claude_session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    browse_dir: Optional[str] = None,
    history: Optional[list[dict]] = None,
    web_turn_overlays: Optional[list[dict]] = None,
    message_count: Optional[int] = None,
    last_activity: Optional[str] = None,
    local_history_backend: Optional[str] = None,
    session_epoch: Optional[int] = None,
    managed_prompt_hash_seen: Optional[str] = None,
    running_user_text: Optional[str] = None,
    running_preview_text: Optional[str] = None,
    running_started_at: Optional[str] = None,
    running_updated_at: Optional[str] = None,
):
    """保存会话信息到持久化存储（原子读-改-写）"""
    key = _make_key(bot_id, user_id)

    session_data: dict = {}
    if codex_session_id:
        session_data["codex_session_id"] = codex_session_id
    if claude_session_id:
        session_data["claude_session_id"] = claude_session_id
    if isinstance(working_dir, str) and working_dir:
        session_data["working_dir"] = working_dir
    if isinstance(browse_dir, str) and browse_dir:
        session_data["browse_dir"] = browse_dir
    if isinstance(message_count, int):
        session_data["message_count"] = max(0, message_count)
    if last_activity:
        session_data["last_activity"] = last_activity
    if local_history_backend:
        session_data["local_history_backend"] = local_history_backend
    if isinstance(session_epoch, int):
        session_data["session_epoch"] = max(0, session_epoch)
    if managed_prompt_hash_seen:
        session_data["managed_prompt_hash_seen"] = managed_prompt_hash_seen
    # legacy history is intentionally no longer persisted
    # legacy running_* and web_turn_overlays are intentionally dropped on local_v1

    with _store_lock:
        try:
            if STORE_FILE.exists():
                with open(STORE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            else:
                data = {}
        except (json.JSONDecodeError, IOError):
            data = {}

        if not session_data:
            data.pop(key, None)
        else:
            data[key] = session_data

        try:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存会话存储文件失败: {e}")
            return

    logger.debug(f"已保存会话: bot={bot_id}, user={user_id}")


def remove_session(bot_id: int, user_id: int) -> bool:
    """删除指定会话的持久化存储（原子读-改-写）"""
    key = _make_key(bot_id, user_id)

    with _store_lock:
        if not STORE_FILE.exists():
            return False
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or key not in data:
                return False
        except (json.JSONDecodeError, IOError):
            return False

        del data[key]
        try:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存会话存储文件失败: {e}")
            return False

    logger.debug(f"已删除会话: bot={bot_id}, user={user_id}")
    return True


def remove_all_sessions_for_bot(bot_id: int):
    """删除指定bot的所有会话（原子读-改-写）"""
    prefix = f"{bot_id}:"

    with _store_lock:
        if not STORE_FILE.exists():
            return
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (json.JSONDecodeError, IOError):
            return

        keys_to_remove = [k for k in data if k.startswith(prefix)]
        if not keys_to_remove:
            return
        for key in keys_to_remove:
            del data[key]
        try:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存会话存储文件失败: {e}")
            return

    logger.debug(f"已删除bot={bot_id}的所有会话，共{len(keys_to_remove)}个")


def rename_bot_sessions(old_bot_id: int, new_bot_id: int) -> int:
    """将指定 bot_id 的持久化会话快照迁移到新的 bot_id。"""
    if old_bot_id == new_bot_id:
        return 0

    moved = 0
    with _store_lock:
        if not STORE_FILE.exists():
            return 0
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return 0
        except (json.JSONDecodeError, IOError):
            return 0

        next_data = dict(data)
        for key, value in list(data.items()):
            parsed = _parse_key(key)
            if parsed is None:
                continue
            bot_id, user_id = parsed
            if bot_id != old_bot_id:
                continue
            new_key = _make_key(new_bot_id, user_id)
            next_data[new_key] = _merge_session_snapshots(value if isinstance(value, dict) else {}, next_data.get(new_key))
            next_data.pop(key, None)
            moved += 1

        if moved == 0:
            return 0

        try:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(next_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"保存会话存储文件失败: {e}")
            return 0

    logger.debug("已迁移 bot 会话快照: old_bot=%s new_bot=%s moved=%s", old_bot_id, new_bot_id, moved)
    return moved
