from __future__ import annotations

from typing import TYPE_CHECKING

from bot.platform.processes import terminate_process_tree_sync

if TYPE_CHECKING:
    from bot.models import UserSession


def terminate_session_process(session: "UserSession") -> None:
    with session._lock:
        process = session.process
    if process is not None and process.poll() is None:
        terminate_process_tree_sync(process)

