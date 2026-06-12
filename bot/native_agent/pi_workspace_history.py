from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from bot.native_agent.shadow_git_history import ShadowGitHistory

_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


@dataclass(frozen=True)
class WorkspaceHistoryStatus:
    head: str
    clean: bool
    manual_change_count: int
    degraded: bool = False
    message: str = ""
    locked_file_count: int = 0
    linear_index: int = 0


class PiWorkspaceHistory:
    def __init__(self, *, timeout_seconds: float = 10.0, shadow_history: ShadowGitHistory | None = None) -> None:
        self.timeout_seconds = max(0.1, float(timeout_seconds or 10.0))
        self._shadow_history = shadow_history or ShadowGitHistory(timeout_seconds=self.timeout_seconds)

    async def status(
        self,
        runtime: Any,
        *,
        cwd: str | Path | None = None,
        conversation_id: str = "",
    ) -> WorkspaceHistoryStatus:
        return await self._call_shadow(
            runtime,
            cwd,
            conversation_id,
            lambda resolved_cwd, resolved_conversation_id: self._shadow_history.status(
                cwd=resolved_cwd,
                conversation_id=resolved_conversation_id,
            ),
        )

    async def checkpoint(
        self,
        runtime: Any,
        *,
        label: str,
        cwd: str | Path | None = None,
        conversation_id: str = "",
    ) -> WorkspaceHistoryStatus:
        return await self._call_shadow(
            runtime,
            cwd,
            conversation_id,
            lambda resolved_cwd, resolved_conversation_id: self._shadow_history.snapshot(
                cwd=resolved_cwd,
                conversation_id=resolved_conversation_id,
                label=str(label or ""),
            ),
        )

    async def record_completed_turn(
        self,
        runtime: Any,
        *,
        turn_id: str,
        before_head: str,
        pi_session_id: str = "",
        cwd: str | Path | None = None,
        conversation_id: str = "",
    ) -> WorkspaceHistoryStatus:
        return await self._call_shadow(
            runtime,
            cwd,
            conversation_id,
            lambda resolved_cwd, resolved_conversation_id: self._shadow_history.record_completed_turn(
                cwd=resolved_cwd,
                conversation_id=resolved_conversation_id,
                turn_id=turn_id,
                before_head=before_head,
                pi_session_id=pi_session_id,
            ),
        )

    async def rollback(
        self,
        runtime: Any,
        *,
        target_head: str,
        cwd: str | Path | None = None,
        conversation_id: str = "",
    ) -> WorkspaceHistoryStatus:
        return await self._call_shadow(
            runtime,
            cwd,
            conversation_id,
            lambda resolved_cwd, resolved_conversation_id: self._shadow_history.rollback(
                cwd=resolved_cwd,
                conversation_id=resolved_conversation_id,
                target_head=str(target_head or ""),
            ),
        )

    async def _call_shadow(
        self,
        runtime: Any,
        cwd: str | Path | None,
        conversation_id: str,
        callback: Callable[[Path, str], Any],
    ) -> WorkspaceHistoryStatus:
        try:
            resolved_cwd = self._resolve_cwd(runtime, cwd)
            resolved_conversation_id = self._resolve_conversation_id(runtime, conversation_id)
        except Exception as exc:
            return WorkspaceHistoryStatus(
                head="",
                clean=False,
                manual_change_count=0,
                degraded=True,
                message=_safe_message(str(exc) or "", default="workspace history 不可用"),
            )
        lock = await _lock_for(resolved_cwd, resolved_conversation_id)
        await lock.acquire()
        task = asyncio.create_task(asyncio.to_thread(callback, resolved_cwd, resolved_conversation_id))
        release_in_finally = True
        try:
            status = await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError):
            release_in_finally = False
            task.add_done_callback(lambda done: _release_lock_after_done(done, lock))
            return WorkspaceHistoryStatus(
                head="",
                clean=False,
                manual_change_count=0,
                degraded=True,
                message="workspace history 响应超时",
            )
        except Exception as exc:
            return WorkspaceHistoryStatus(
                head="",
                clean=False,
                manual_change_count=0,
                degraded=True,
                message=_safe_message(str(exc) or "", default="workspace history 不可用"),
            )
        finally:
            if release_in_finally and lock.locked():
                lock.release()
        return WorkspaceHistoryStatus(
            head=str(getattr(status, "head", "") or ""),
            clean=bool(getattr(status, "clean", False)),
            manual_change_count=max(0, int(getattr(status, "manual_change_count", 0) or 0)),
            degraded=bool(getattr(status, "degraded", False)),
            message=_safe_message(str(getattr(status, "message", "") or ""), default=""),
            locked_file_count=max(0, int(getattr(status, "locked_file_count", 0) or 0)),
            linear_index=max(0, int(getattr(status, "linear_index", 0) or 0)),
        )

    def _resolve_cwd(self, runtime: Any, cwd: str | Path | None) -> Path:
        if cwd is not None and str(cwd or "").strip():
            return Path(cwd).expanduser().resolve()
        state = getattr(runtime, "state", None)
        for value in (
            getattr(state, "cwd", None),
            getattr(runtime, "cwd", None),
        ):
            if value:
                return Path(str(value)).expanduser().resolve()
        raise ValueError("workspace cwd is required")

    def _resolve_conversation_id(self, runtime: Any, conversation_id: str) -> str:
        if str(conversation_id or "").strip():
            return str(conversation_id or "").strip()
        state = getattr(runtime, "state", None)
        for value in (
            getattr(state, "conversation_id", None),
            getattr(runtime, "conversation_id", None),
        ):
            if str(value or "").strip():
                return str(value or "").strip()
        raise ValueError("conversation_id is required")


def _safe_message(message: str, *, default: str) -> str:
    text = str(message or "").strip()
    if not text:
        return default
    lowered = text.lower()
    if any(key in lowered for key in ("changed_files", "changed_paths", "manual_changes", "locked_files", "shadow_git_path")):
        return default
    if ":\\" in text or ":/" in text or "\\\\" in text:
        return default
    return text[:240]


async def _lock_for(cwd: Path, conversation_id: str) -> asyncio.Lock:
    key = (str(cwd), str(conversation_id or "").strip())
    async with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[key] = lock
        return lock


def _release_lock_after_done(task: asyncio.Task[Any], lock: asyncio.Lock) -> None:
    with suppress(BaseException):
        task.exception()
    if lock.locked():
        lock.release()
