"""Chat runtime Web service compatibility facade."""

from __future__ import annotations

from bot.web.api_service import (
    build_cluster_cli_params_override,
    execute_shell_command,
    kill_user_process,
    reset_user_session,
    run_chat,
    run_cli_chat,
    stream_chat,
)

__all__ = [
    "build_cluster_cli_params_override",
    "execute_shell_command",
    "kill_user_process",
    "reset_user_session",
    "run_chat",
    "run_cli_chat",
    "stream_chat",
]
