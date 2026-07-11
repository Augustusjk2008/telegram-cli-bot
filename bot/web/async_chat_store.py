from __future__ import annotations

import asyncio
import functools
import os
import threading
import weakref
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Any, TypeVar

from bot.web.chat_store import ChatStore


_ResultT = TypeVar("_ResultT")
_DEFAULT_MAX_WORKERS = max(1, int(os.environ.get("TCB_CHAT_STORE_MAX_WORKERS", "4")))
_DEFAULT_MAX_PENDING = max(
    _DEFAULT_MAX_WORKERS,
    int(os.environ.get("TCB_CHAT_STORE_MAX_PENDING", "32")),
)
_SHARED_EXECUTOR = ThreadPoolExecutor(
    max_workers=_DEFAULT_MAX_WORKERS,
    thread_name_prefix="chat-store",
)
_WRITE_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


class ChatStoreOverloadedError(RuntimeError):
    pass


def async_chat_store_enabled() -> bool:
    value = os.environ.get("TCB_ASYNC_CHAT_STORE", "true")
    return str(value or "").strip().lower() not in {"0", "false", "no", "off"}


def _workspace_write_lock(key: str) -> threading.Lock:
    normalized = str(key or "").strip()
    return _WRITE_LOCK_STRIPES[hash(normalized) % len(_WRITE_LOCK_STRIPES)]


class _BoundedExecutor:
    def __init__(
        self,
        *,
        executor: Executor | None = None,
        max_pending: int = _DEFAULT_MAX_PENDING,
    ) -> None:
        self._executor = executor or _SHARED_EXECUTOR
        self._max_pending = max(1, int(max_pending))
        self._loop_slots: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop,
            asyncio.Semaphore,
        ] = weakref.WeakKeyDictionary()
        self._loop_slots_lock = threading.Lock()
        self._diagnostics_lock = threading.Lock()
        self._pending_count = 0
        self._active_count = 0
        self._peak_pending_count = 0
        self._rejected_count = 0

    def _slots(self, loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
        with self._loop_slots_lock:
            slots = self._loop_slots.get(loop)
            if slots is None:
                slots = asyncio.Semaphore(self._max_pending)
                self._loop_slots[loop] = slots
            return slots

    async def run(
        self,
        function: Callable[..., _ResultT],
        *args: Any,
        write_key: str = "",
        **kwargs: Any,
    ) -> _ResultT:
        loop = asyncio.get_running_loop()
        slots = self._slots(loop)
        with self._diagnostics_lock:
            if self._pending_count >= self._max_pending:
                self._rejected_count += 1
                raise ChatStoreOverloadedError(
                    f"chat store pending budget exceeded ({self._max_pending})"
                )
            self._pending_count += 1
            self._peak_pending_count = max(self._peak_pending_count, self._pending_count)
        try:
            async with slots:
                with self._diagnostics_lock:
                    self._active_count += 1
                try:
                    call = functools.partial(function, *args, **kwargs)
                    if write_key:
                        lock = _workspace_write_lock(write_key)
                        call = functools.partial(self._run_locked, lock, call)
                    return await loop.run_in_executor(self._executor, call)
                finally:
                    with self._diagnostics_lock:
                        self._active_count -= 1
        finally:
            with self._diagnostics_lock:
                self._pending_count -= 1

    @staticmethod
    def _run_locked(lock: threading.Lock, call: Callable[[], _ResultT]) -> _ResultT:
        with lock:
            return call()

    def diagnostics(self) -> dict[str, int]:
        with self._diagnostics_lock:
            return {
                "max_workers": _DEFAULT_MAX_WORKERS,
                "max_pending": self._max_pending,
                "pending_count": self._pending_count,
                "active_count": self._active_count,
                "peak_pending_count": self._peak_pending_count,
                "rejected_count": self._rejected_count,
            }


_SHARED_DISPATCHER = _BoundedExecutor()


async def run_chat_store_io(
    function: Callable[..., _ResultT],
    *args: Any,
    write_key: str = "",
    **kwargs: Any,
) -> _ResultT:
    if not async_chat_store_enabled():
        return function(*args, **kwargs)
    return await _SHARED_DISPATCHER.run(
        function,
        *args,
        write_key=write_key,
        **kwargs,
    )


def chat_store_executor_diagnostics() -> dict[str, int | bool]:
    return {
        "enabled": async_chat_store_enabled(),
        **_SHARED_DISPATCHER.diagnostics(),
    }


class AsyncChatStore:
    def __init__(
        self,
        store: ChatStore,
        executor: Executor | None = None,
        *,
        max_pending: int = _DEFAULT_MAX_PENDING,
    ) -> None:
        self.store = store
        self._dispatcher = (
            _SHARED_DISPATCHER
            if executor is None and max_pending == _DEFAULT_MAX_PENDING
            else _BoundedExecutor(executor=executor, max_pending=max_pending)
        )
        self._write_key = str(store.db_path.resolve())

    async def run_read(
        self,
        function: Callable[..., _ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> _ResultT:
        return await self._dispatcher.run(function, *args, **kwargs)

    async def run_write(
        self,
        function: Callable[..., _ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> _ResultT:
        return await self._dispatcher.run(
            function,
            *args,
            write_key=self._write_key,
            **kwargs,
        )

    async def list_conversations(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self.run_read(self.store.list_conversations, **kwargs)

    async def list_active_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self.run_read(self.store.list_active_history, **kwargs)

    async def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self.run_read(
            self.store.list_messages,
            conversation_id,
            limit=limit,
        )

    async def count_history(self, **kwargs: Any) -> int:
        return await self.run_read(self.store.count_history, **kwargs)

    async def get_running_reply(self, **kwargs: Any) -> dict[str, Any] | None:
        return await self.run_read(self.store.get_running_reply, **kwargs)

    async def latest_active_workspace_histories(
        self,
        conversation_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        return await self.run_read(
            self.store.latest_active_workspace_histories,
            conversation_ids,
        )

    def diagnostics(self) -> dict[str, int | bool | str]:
        return {
            "enabled": async_chat_store_enabled(),
            "workspace_key": self.store.workspace_key,
            **self._dispatcher.diagnostics(),
        }
