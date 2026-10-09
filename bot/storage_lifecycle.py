"""Runtime quiescing helpers used before moving TCB-managed storage."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def stop_all_agent_processes(server: Any | None = None) -> dict[str, Any]:
    """Stop every locally owned agent/runtime before storage is copied.

    The Web server remains alive long enough to report the migration state.  All
    process-owning services are quiesced here; the normal server shutdown still
    runs afterwards and each operation is intentionally idempotent.
    """

    from bot.codex_server.runtime import get_codex_server_registry
    from bot.models import flush_pending_session_persistence
    from bot.native_agent.service import get_native_agent_service
    from bot.session_store import close_session_store
    from bot.sessions import sessions, sessions_lock

    with sessions_lock:
        sessions_to_stop = list(sessions.values())

    async def stop_session(session: Any) -> None:
        try:
            with session._lock:
                active = session.process is not None or bool(session.is_processing)
                if active:
                    session.stop_requested = True
            if active:
                await asyncio.to_thread(session.terminate_process)
            else:
                session.persist()
        except Exception:
            logger.exception("停止会话进程失败: %s", getattr(session, "bot_alias", ""))
            raise

    errors: list[str] = []
    results = await asyncio.gather(
        *(stop_session(session) for session in sessions_to_stop),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            errors.append(str(result))

    # Cluster child tasks can own separate CLI/native runtimes.  Cancel the
    # in-memory runs before closing the shared runtime registries.
    try:
        from bot.web import api_service

        cancel_run = getattr(api_service, "_cancel_cluster_run", None)
        runtime = getattr(api_service, "_CLUSTER_RUNTIME", None)
        runs = list(getattr(runtime, "_runs", {}).keys()) if runtime is not None else []
        if callable(cancel_run):
            for run_id in runs:
                try:
                    await cancel_run(run_id, "存储迁移已停止全部智能体")
                except Exception as exc:
                    errors.append(str(exc))
    except Exception as exc:
        errors.append(str(exc))

    try:
        await get_native_agent_service().shutdown()
    except Exception as exc:
        errors.append(str(exc))
    try:
        await get_codex_server_registry().aclose()
    except Exception as exc:
        errors.append(str(exc))

    if server is not None:
        for owner, method_name in (
            (getattr(server, "manager", None), "plugin_service"),
            (server, "_terminal_manager"),
            (server, "_debug_service"),
            (server, "language_server_manager"),
        ):
            target = getattr(owner, method_name, None) if owner is not None else None
            shutdown = getattr(target, "shutdown", None)
            if not callable(shutdown):
                continue
            try:
                value = shutdown()
                if hasattr(value, "__await__"):
                    await value
            except Exception as exc:
                errors.append(str(exc))

    try:
        flush_pending_session_persistence()
        close_session_store()
    except Exception as exc:
        errors.append(str(exc))

    return {
        "ready": not errors,
        "stopped": not errors,
        "sessions": len(sessions_to_stop),
        "errors": errors,
    }
