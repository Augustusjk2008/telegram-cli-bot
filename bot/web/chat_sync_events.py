"""Hints that a chat session changed, so Web clients can sync instead of polling.

Sessions are shared by ``(bot_id, shared_user_id, agent_id)`` across Web, Telegram,
Weixin and scheduled tasks, so a change made on one channel has to reach every open
Web page. Publishers call :func:`publish_chat_sync` from any thread; the Web server
installs the delivery callback and forwards the hint over the notifications
WebSocket. A hint carries no chat content: clients answer it with their normal,
authorized history requests, and they keep a slow poll as the fallback.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

ChatSyncPublisher = Callable[[str, str, str], None]

# Lifecycle hints are delivered promptly; progress hints are rate limited.
CHAT_SYNC_REASON_TURN_STARTED = "turn_started"
CHAT_SYNC_REASON_TURN_FINISHED = "turn_finished"
CHAT_SYNC_REASON_PROGRESS = "progress"
CHAT_SYNC_REASON_CONVERSATION = "conversation"
CHAT_SYNC_REASON_CLUSTER = "cluster"

_publisher: ChatSyncPublisher | None = None


def set_chat_sync_publisher(publisher: ChatSyncPublisher | None) -> ChatSyncPublisher | None:
    """Install the delivery callback and return the one it replaces."""
    global _publisher
    previous = _publisher
    _publisher = publisher
    return previous


def clear_chat_sync_publisher(publisher: ChatSyncPublisher) -> None:
    """Remove ``publisher`` unless another one was installed in the meantime."""
    global _publisher
    # Bound methods are recreated on each attribute access, so compare by equality.
    if _publisher == publisher:
        _publisher = None


def publish_chat_sync(alias: str, agent_id: str = "main", reason: str = "") -> None:
    """Report that the session of ``alias``/``agent_id`` changed. Never raises or blocks."""
    publisher = _publisher
    if publisher is None:
        return
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return
    try:
        publisher(normalized_alias, str(agent_id or "main").strip().lower() or "main", str(reason or ""))
    except Exception:  # pragma: no cover - a hint must never fail the chat path
        logger.debug("发布聊天同步提示失败 alias=%s agent=%s", normalized_alias, agent_id, exc_info=True)
