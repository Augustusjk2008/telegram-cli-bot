"""会话快照持久化存储。

按 (bot_id, user_id) 将会话相关状态保存到 JSON 文件，程序重启后可以恢复：
- 各 CLI 的 session_id
- 用户工作目录
- 文件浏览目录
- 有限聊天历史
- 运行中回复的最近快照
"""

import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from bot.config import MANAGED_BOTS_FILE

logger = logging.getLogger(__name__)

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


def load_session(bot_id: int, user_id: int) -> Optional[dict]:
    """加载指定会话的 session 信息
    
    Returns:
        dict: 包含 codex_session_id, kimi_session_id, claude_session_id
        None: 如果没有找到
    """
    data = load_session_ids()
    key = _make_key(bot_id, user_id)
    return data.get(key)


def save_session(
    bot_id: int,
    user_id: int,
    codex_session_id: Optional[str] = None,
    kimi_session_id: Optional[str] = None,
    claude_session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    browse_dir: Optional[str] = None,
    history: Optional[list[dict]] = None,
    message_count: Optional[int] = None,
    last_activity: Optional[str] = None,
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
    if kimi_session_id:
        session_data["kimi_session_id"] = kimi_session_id
    if claude_session_id:
        session_data["claude_session_id"] = claude_session_id
    if isinstance(working_dir, str) and working_dir:
        session_data["working_dir"] = working_dir
    if isinstance(browse_dir, str) and browse_dir:
        session_data["browse_dir"] = browse_dir
    if history:
        session_data["history"] = history
    if isinstance(message_count, int):
        session_data["message_count"] = max(0, message_count)
    if last_activity:
        session_data["last_activity"] = last_activity
    if running_user_text:
        session_data["running_user_text"] = running_user_text
    if running_preview_text:
        session_data["running_preview_text"] = running_preview_text
    if running_started_at:
        session_data["running_started_at"] = running_started_at
    if running_updated_at:
        session_data["running_updated_at"] = running_updated_at

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
