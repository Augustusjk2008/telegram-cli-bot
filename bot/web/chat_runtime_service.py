"""Chat runtime Web service compatibility facade."""

from __future__ import annotations

from bot.web.api_service import (
    build_assistant_run_request,
    build_cluster_cli_params_override,
    execute_assistant_run_request,
    execute_shell_command,
    kill_user_process,
    reset_user_session,
    run_chat,
    run_cli_chat,
    stream_assistant_run_request,
    stream_chat,
)

__all__ = [
    "build_assistant_run_request",
    "build_cluster_cli_params_override",
    "execute_assistant_run_request",
    "execute_shell_command",
    "kill_user_process",
    "reset_user_session",
    "run_chat",
    "run_cli_chat",
    "stream_assistant_run_request",
    "stream_chat",
]
