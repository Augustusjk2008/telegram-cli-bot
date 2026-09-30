from __future__ import annotations

from typing import TYPE_CHECKING

from bot.platform.processes import terminate_process_tree_sync
from bot.platform.subprocess_streams import close_process_streams

if TYPE_CHECKING:
    from bot.models import UserSession


def terminate_session_process(session: "UserSession") -> None:
    from bot.codex_server.runtime import get_codex_server_registry
    from bot.chat_identity import chat_session_user_id
    get_codex_server_registry().release_owner((session.bot_id, chat_session_user_id(session.user_id), session.agent_id))
    with session._lock:
        process = session.process
    if process is not None and process.poll() is None:
        terminate_process_tree_sync(process)
    close_process_streams(process)
