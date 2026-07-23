"""语言服务器实例隔离、懒启动与 Web 生命周期管理。"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from bot import config
from bot.platform.processes import build_chat_cli_process_kwargs, terminate_async_process_tree

from .catalog import LanguageServerCatalog
from .pyright import PyrightProvider


_CANCEL_MARKER_TTL_SECONDS = 30.0
_MAX_CANCEL_MARKERS = 1024


class LanguageServerUnavailableError(RuntimeError):
    """语言服务被关闭或当前 provider 没有可运行命令。"""


@dataclass(frozen=True)
class LanguageServerRuntimeKey:
    bot_alias: str
    user_id: int
    workspace_root: Path
    provider_id: str


class RuntimeProtocol(Protocol):
    key: LanguageServerRuntimeKey
    pending_count: int
    active_operation_count: int

    async def start(self) -> None: ...

    async def resolve_code_navigation(self, request: dict[str, Any]) -> dict[str, object]: ...

    async def close(self) -> None: ...

    def diagnostics(self) -> dict[str, object]: ...


RuntimeFactory = Callable[[LanguageServerRuntimeKey, tuple[str, ...]], RuntimeProtocol]


class LanguageServerRuntime:
    """单个工作区/provider 的持久 LSP 子进程。"""

    def __init__(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
        *,
        request_timeout: float,
    ) -> None:
        self.key = key
        self.command = tuple(command)
        self.request_timeout = max(0.1, float(request_timeout))
        self.provider = PyrightProvider(key.workspace_root)
        self.process: asyncio.subprocess.Process | None = None
        self.client: Any = None
        self.state = "stopped"
        self.last_error = ""
        self.last_used_at = time.monotonic()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._stderr_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        self._progress_tokens: set[str] = set()
        self._active_operation_count = 0

    @property
    def pending_count(self) -> int:
        return int(getattr(self.client, "pending_count", 0) or 0)

    @property
    def open_document_count(self) -> int:
        return self.provider.open_document_count

    @property
    def active_operation_count(self) -> int:
        return self._active_operation_count

    async def start(self) -> None:
        if self.state in {"ready", "indexing"}:
            return
        if not self.command:
            raise LanguageServerUnavailableError("语言服务器命令为空")
        self.state = "starting"
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.key.workspace_root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **build_chat_cli_process_kwargs(),
            )
            if self.process.stdin is None or self.process.stdout is None:
                raise RuntimeError("语言服务器标准输入输出不可用")
            if self.process.stderr is not None:
                self._stderr_task = asyncio.create_task(self._drain_stderr(self.process.stderr))

            # 延迟导入允许目录/安装器在 JSON-RPC 子模块不可用时仍可独立工作。
            from .jsonrpc import LspJsonRpcClient

            self.client = LspJsonRpcClient(
                self.process,
                request_timeout_seconds=self.request_timeout,
                notification_handler=self.handle_notification,
                server_request_handler=self.provider.handle_server_request,
            )
            start_reader = getattr(self.client, "start", None)
            if callable(start_reader):
                started = start_reader()
                if hasattr(started, "__await__"):
                    await started
            await self.provider.initialize(self.client)
            self.state = "indexing" if self._progress_tokens else "ready"
            self.last_error = ""
            self.last_used_at = time.monotonic()
        except BaseException as exc:
            self.state = "error"
            self.last_error = str(exc)[:300]
            await self._force_stop_process()
            raise

    async def handle_notification(self, method: str, params: Any) -> None:
        """Track LSP work-done progress without retaining source or log payloads."""

        if method != "$/progress" or not isinstance(params, Mapping):
            return
        value = params.get("value")
        if not isinstance(value, Mapping):
            return
        token = str(params.get("token") or "").strip()
        if not token:
            return
        kind = str(value.get("kind") or "").strip().lower()
        if kind == "begin":
            self._progress_tokens.add(token)
            if self.state not in {"error", "stopped"}:
                self.state = "indexing"
        elif kind == "end":
            self._progress_tokens.discard(token)
            if not self._progress_tokens and self.state == "indexing":
                self.state = "ready"

    async def resolve_code_navigation(self, request: dict[str, Any]) -> dict[str, object]:
        if self.state not in {"ready", "indexing"} or self.client is None:
            raise RuntimeError("语言服务器尚未就绪")
        self._active_operation_count += 1
        try:
            document = request.get("document")
            position = request.get("position")
            if not isinstance(document, Mapping) or not isinstance(position, Mapping):
                raise ValueError("代码导航请求格式无效")
            path = str(document.get("path") or "").strip()
            target = (self.key.workspace_root / path).resolve()
            try:
                target.relative_to(self.key.workspace_root)
            except ValueError as exc:
                raise ValueError("代码导航路径超出工作区") from exc
            kind = str(request.get("kind") or "").strip().lower()
            request_id = str(request.get("requestId") or request.get("request_id") or "").strip()
            items = await self.provider.navigate(
                self.client,
                kind=kind,
                path=target,
                language_id=str(document.get("languageId") or document.get("language_id") or ""),
                version=_int_value(document.get("version"), 0),
                content=str(document.get("content") or ""),
                line=max(1, _int_value(position.get("line"), 1)),
                column=max(1, _int_value(position.get("column"), 1)),
            )
            empty_message = "未找到语义实现" if kind == "implementation" else "未找到语义定义"
            return {
                "request_id": request_id,
                "items": items,
                "message": "" if items else empty_message,
            }
        finally:
            self._active_operation_count = max(0, self._active_operation_count - 1)
            self.last_used_at = time.monotonic()

    async def close(self) -> None:
        async with self._close_lock:
            if self.state == "stopped" and self.process is None:
                return
            client = self.client
            process = self.process
            self.client = None
            graceful_timeout = min(3.0, self.request_timeout)
            cancelled: asyncio.CancelledError | None = None
            graceful_task = asyncio.create_task(self._graceful_shutdown(client, process))
            try:
                done, _pending = await asyncio.wait(
                    {graceful_task},
                    timeout=graceful_timeout,
                )
                if graceful_task in done:
                    with contextlib.suppress(BaseException):
                        graceful_task.result()
            except asyncio.CancelledError as exc:
                cancelled = exc
            finally:
                if not graceful_task.done():
                    graceful_task.cancel()
                if process is not None and process.returncode is None:
                    with contextlib.suppress(BaseException):
                        await terminate_async_process_tree(process)
                if not graceful_task.done():
                    graceful_task.cancel()
                    done, _pending = await asyncio.wait({graceful_task}, timeout=0.1)
                    if graceful_task in done:
                        with contextlib.suppress(BaseException):
                            graceful_task.result()
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(self._finish_stderr_task(), timeout=1.0)
                self.process = None
                self.state = "stopped"
            if cancelled is not None:
                raise cancelled

    async def _graceful_shutdown(self, client: Any, process: Any) -> None:
        if client is None:
            if process is not None and process.returncode is None:
                await process.wait()
            return

        if process is not None and process.returncode is None:
            try:
                shutdown = getattr(client, "shutdown", None)
                if callable(shutdown):
                    result = shutdown(timeout_seconds=self.request_timeout)
                    if hasattr(result, "__await__"):
                        await result
                else:
                    try:
                        await client.request("shutdown", {})
                    except Exception:
                        pass
                    await client.notify("exit", {})
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
        if process is not None and process.returncode is None:
            await process.wait()

    async def _force_stop_process(self) -> None:
        process = self.process
        if process is not None and process.returncode is None:
            with contextlib.suppress(BaseException):
                await terminate_async_process_tree(process)
        await self._finish_stderr_task()
        self.process = None

    async def _finish_stderr_task(self) -> None:
        task = self._stderr_task
        self._stderr_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip()[:500])

    def diagnostics(self) -> dict[str, object]:
        process = self.process
        return {
            "state": self.state,
            "pid": process.pid if process is not None and process.returncode is None else None,
            "pending_count": self.pending_count,
            "active_operation_count": self.active_operation_count,
            "open_document_count": self.open_document_count,
            "implementation_supported": bool(self.provider.supports_implementation),
            "idle_seconds": round(max(0.0, time.monotonic() - self.last_used_at), 3),
            "last_error": self.last_error,
            "stderr_tail": list(self._stderr_tail),
        }


class LanguageServerRuntimeManager:
    def __init__(
        self,
        catalog: LanguageServerCatalog,
        *,
        runtime_factory: RuntimeFactory | None = None,
        request_timeout: float | None = None,
        idle_timeout: float | None = None,
        max_runtimes: int | None = None,
    ) -> None:
        self.catalog = catalog
        self.request_timeout = float(request_timeout or config.TCB_LSP_REQUEST_TIMEOUT_SECONDS)
        self.idle_timeout = float(idle_timeout or config.TCB_LSP_IDLE_TIMEOUT_SECONDS)
        self.max_runtimes = max(1, int(max_runtimes or config.TCB_LSP_MAX_RUNTIMES))
        self._runtime_factory = runtime_factory or self._create_runtime
        self._runtimes: dict[LanguageServerRuntimeKey, RuntimeProtocol] = {}
        self._start_tasks: dict[LanguageServerRuntimeKey, asyncio.Task[RuntimeProtocol]] = {}
        self._active_requests: dict[
            tuple[LanguageServerRuntimeKey, str],
            set[asyncio.Task[Any]],
        ] = {}
        self._cancelled_requests: dict[tuple[str, int, Path, str], float] = {}
        self._lock = asyncio.Lock()
        self._shutdown_started = False

    def _create_runtime(self, key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> LanguageServerRuntime:
        return LanguageServerRuntime(key, command, request_timeout=self.request_timeout)

    async def resolve_code_navigation(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        request: dict[str, Any],
    ) -> dict[str, object]:
        kind = str(request.get("kind") or "").strip().lower()
        if kind not in {"definition", "implementation"}:
            raise ValueError("代码导航类型无效")
        request_id = str(request.get("requestId") or request.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("缺少代码导航请求 ID")
        provider_id = _provider_for_request(request)
        if provider_id is None:
            empty_message = "未找到语义实现" if kind == "implementation" else "未找到语义定义"
            return {"request_id": request_id, "items": [], "message": empty_message}
        if not bool(getattr(self.catalog, "enabled", True)):
            raise LanguageServerUnavailableError("语言服务已关闭")

        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("工作区目录不存在")
        normalized_alias = str(bot_alias or "").strip().lower()
        normalized_user_id = int(user_id)
        key = LanguageServerRuntimeKey(
            bot_alias=normalized_alias,
            user_id=normalized_user_id,
            workspace_root=root,
            provider_id=provider_id,
        )
        cancellation_key = (normalized_alias, normalized_user_id, root, request_id)
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("无法登记代码导航任务")
        active_key = (key, request_id)
        async with self._lock:
            if self._shutdown_started:
                raise RuntimeError("语言服务器管理器正在关闭")
            self._prune_cancelled_requests_locked()
            if cancellation_key in self._cancelled_requests:
                raise asyncio.CancelledError
            self._active_requests.setdefault(active_key, set()).add(current_task)
        try:
            command = await asyncio.to_thread(self.catalog.command_for, provider_id)
            if not command:
                raise LanguageServerUnavailableError("Pyright 未安装或命令不可用")
            runtime = await self._get_or_start(key, tuple(command))
            return await runtime.resolve_code_navigation(request)
        finally:
            async with self._lock:
                active_tasks = self._active_requests.get(active_key)
                if active_tasks is not None:
                    active_tasks.discard(current_task)
                    if not active_tasks:
                        self._active_requests.pop(active_key, None)

    async def cancel_code_navigation(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        request_id: str,
    ) -> bool:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            raise ValueError("缺少代码导航请求 ID")
        normalized_alias = str(bot_alias or "").strip().lower()
        normalized_user_id = int(user_id)
        root = Path(workspace_root).expanduser().resolve()
        cancellation_key = (normalized_alias, normalized_user_id, root, normalized_request_id)
        async with self._lock:
            self._prune_cancelled_requests_locked()
            self._cancelled_requests[cancellation_key] = time.monotonic() + _CANCEL_MARKER_TTL_SECONDS
            if len(self._cancelled_requests) > _MAX_CANCEL_MARKERS:
                oldest = min(self._cancelled_requests, key=self._cancelled_requests.__getitem__)
                self._cancelled_requests.pop(oldest, None)
            tasks: list[asyncio.Task[Any]] = []
            for (key, active_request_id), active_tasks in self._active_requests.items():
                if (
                    active_request_id == normalized_request_id
                    and key.bot_alias == normalized_alias
                    and key.user_id == normalized_user_id
                    and key.workspace_root == root
                ):
                    tasks.extend(task for task in active_tasks if not task.done())
            for task in tasks:
                task.cancel()
        return bool(tasks)

    def _prune_cancelled_requests_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, deadline in self._cancelled_requests.items() if deadline <= now]
        for key in expired:
            self._cancelled_requests.pop(key, None)

    async def prewarm(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        provider_id: str,
    ) -> bool:
        """Start an already-discovered provider without issuing navigation or installing tools."""

        normalized_provider = str(provider_id or "").strip().lower()
        if normalized_provider != "pyright" or not bool(getattr(self.catalog, "enabled", True)):
            return False
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            return False
        command = await asyncio.to_thread(self.catalog.command_for, normalized_provider)
        if not command:
            return False
        key = LanguageServerRuntimeKey(
            bot_alias=str(bot_alias or "").strip().lower(),
            user_id=int(user_id),
            workspace_root=root,
            provider_id=normalized_provider,
        )
        await self._get_or_start(key, tuple(command))
        return True

    async def _get_or_start(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> RuntimeProtocol:
        stale: list[RuntimeProtocol] = []
        async with self._lock:
            if self._shutdown_started:
                raise RuntimeError("语言服务器管理器正在关闭")
            current = self._runtimes.get(key)
            if current is not None:
                return current
            task = self._start_tasks.get(key)
            if task is None:
                stale = self._detach_for_capacity_locked()
                task = asyncio.create_task(self._start_and_register(key, command))
                self._start_tasks[key] = task
        if stale:
            await asyncio.gather(*(runtime.close() for runtime in stale), return_exceptions=True)
        return await asyncio.shield(task)

    async def _start_and_register(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> RuntimeProtocol:
        runtime = self._runtime_factory(key, command)
        try:
            await runtime.start()
            async with self._lock:
                if self._shutdown_started:
                    rejected = True
                else:
                    self._runtimes[key] = runtime
                    rejected = False
            if rejected:
                await runtime.close()
                raise RuntimeError("语言服务器管理器正在关闭")
            return runtime
        except BaseException:
            with contextlib.suppress(BaseException):
                await runtime.close()
            raise
        finally:
            async with self._lock:
                current = self._start_tasks.get(key)
                if current is asyncio.current_task():
                    self._start_tasks.pop(key, None)

    def _detach_for_capacity_locked(self) -> list[RuntimeProtocol]:
        if len(self._runtimes) + len(self._start_tasks) < self.max_runtimes:
            return []
        candidates = [runtime for runtime in self._runtimes.values() if _runtime_is_idle(runtime)]
        candidates.sort(key=lambda item: float(getattr(item, "last_used_at", 0.0) or 0.0))
        needed = len(self._runtimes) + len(self._start_tasks) - self.max_runtimes + 1
        evicted = candidates[:needed]
        for runtime in evicted:
            self._runtimes.pop(runtime.key, None)
        if len(evicted) < needed:
            raise RuntimeError("语言服务器实例数量已达上限，请稍后重试")
        return evicted

    async def evict_idle(self) -> int:
        now = time.monotonic()
        async with self._lock:
            stale = [
                runtime
                for runtime in self._runtimes.values()
                if _runtime_is_idle(runtime)
                and now - float(getattr(runtime, "last_used_at", now) or now) >= self.idle_timeout
            ]
            for runtime in stale:
                self._runtimes.pop(runtime.key, None)
        if stale:
            await asyncio.gather(*(runtime.close() for runtime in stale), return_exceptions=True)
        return len(stale)

    def diagnostics(self) -> dict[str, object]:
        runtimes = list(self._runtimes.values())
        states = Counter(str(runtime.diagnostics().get("state") or "unknown") for runtime in runtimes)
        return {
            "enabled": bool(getattr(self.catalog, "enabled", True)),
            "runtime_count": len(runtimes),
            "starting_count": len(self._start_tasks),
            "active_request_count": sum(len(tasks) for tasks in self._active_requests.values()),
            "active_operation_count": sum(
                int(getattr(runtime, "active_operation_count", 0) or 0)
                for runtime in runtimes
            ),
            "pending_count": sum(int(getattr(runtime, "pending_count", 0) or 0) for runtime in runtimes),
            "open_document_count": sum(int(runtime.diagnostics().get("open_document_count") or 0) for runtime in runtimes),
            "provider_counts": dict(Counter(runtime.key.provider_id for runtime in runtimes)),
            "state_counts": dict(states),
        }

    def runtime_status(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        provider_id: str,
    ) -> dict[str, object] | None:
        key = LanguageServerRuntimeKey(
            bot_alias=str(bot_alias or "").strip().lower(),
            user_id=int(user_id),
            workspace_root=Path(workspace_root).expanduser().resolve(),
            provider_id=str(provider_id or "").strip().lower(),
        )
        runtime = self._runtimes.get(key)
        if runtime is not None:
            return runtime.diagnostics()
        if key in self._start_tasks:
            return {"state": "starting", "pending_count": 0, "open_document_count": 0}
        return None

    async def shutdown(self) -> dict[str, int]:
        async with self._lock:
            if self._shutdown_started and not self._runtimes and not self._start_tasks:
                return {"requested": 0, "closed": 0, "failed": 0}
            self._shutdown_started = True
            runtimes = list(self._runtimes.values())
            start_tasks = list(self._start_tasks.values())
            active_tasks = [
                task
                for task in {
                    task
                    for tasks in self._active_requests.values()
                    for task in tasks
                }
                if task is not asyncio.current_task()
            ]
            self._runtimes.clear()
            self._start_tasks.clear()
            self._active_requests.clear()
            self._cancelled_requests.clear()
        for task in active_tasks:
            if not task.done():
                task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        for task in start_tasks:
            if not task.done():
                task.cancel()
        if start_tasks:
            started = await asyncio.gather(*start_tasks, return_exceptions=True)
            for value in started:
                if not isinstance(value, BaseException) and hasattr(value, "close"):
                    runtimes.append(value)
        unique = {id(runtime): runtime for runtime in runtimes}
        report = {"requested": len(unique), "closed": 0, "failed": 0}
        for runtime in unique.values():
            try:
                await runtime.close()
                report["closed"] += 1
            except BaseException:
                report["failed"] += 1
        return report


def _provider_for_request(request: Mapping[str, Any]) -> str | None:
    document = request.get("document")
    if not isinstance(document, Mapping):
        raise ValueError("代码导航请求格式无效")
    path = str(document.get("path") or "").strip()
    language_id = str(document.get("languageId") or document.get("language_id") or "").strip().lower()
    suffix = Path(path).suffix.lower()
    if suffix in {".py", ".pyi"} and language_id in {"", "python", "py"}:
        return "pyright"
    return None


def _runtime_is_idle(runtime: RuntimeProtocol) -> bool:
    return (
        int(getattr(runtime, "pending_count", 0) or 0) == 0
        and int(getattr(runtime, "active_operation_count", 0) or 0) == 0
    )


def _int_value(value: object, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default
