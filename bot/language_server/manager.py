"""语言服务器实例隔离、懒启动与 Web 生命周期管理。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol

from bot import config
from bot.platform.processes import build_chat_cli_process_kwargs, terminate_async_process_tree
from bot.runtime_paths import get_language_servers_root

from .clangd import ClangdProvider
from .catalog import LanguageServerCatalog
from .document_store import (
    LanguageDocument,
    LanguageDocumentLimitError,
    LanguageDocumentStore,
    normalize_document_path,
)
from .external_source_registry import ExternalSourceRegistry
from .pyright import PyrightProvider
from .typescript import TypeScriptProvider
from .jsonrpc import (
    LspJsonRpcClosedError,
    LspJsonRpcProtocolError,
    LspJsonRpcTimeoutError,
)


_CANCEL_MARKER_TTL_SECONDS = 30.0
_MAX_CANCEL_MARKERS = 1024
_RESTART_BASE_DELAY_SECONDS = 0.25
_RESTART_MAX_DELAY_SECONDS = 8.0
_CRASH_WINDOW_SECONDS = 60.0
_CRASH_THRESHOLD = 3
_MAX_RECENT_ERRORS = 20
_MAINTENANCE_MAX_INTERVAL_SECONDS = 30.0


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

    async def sync_documents(self, documents: Sequence[LanguageDocument]) -> list[LanguageDocument]: ...

    async def close_documents(self, documents: Sequence[LanguageDocument | Mapping[str, Any] | str]) -> list[str]: ...

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
        managed_typescript_sdk_path: Path | str | None = None,
        runtime_cache_dir: Path | str | None = None,
        external_source_registry: ExternalSourceRegistry | None = None,
    ) -> None:
        self.key = key
        self.request_timeout = max(0.1, float(request_timeout))
        self.external_source_registry = external_source_registry
        if key.provider_id == "typescript":
            self.provider = TypeScriptProvider(
                key.workspace_root,
                managed_sdk_path=managed_typescript_sdk_path,
                external_source_registry=external_source_registry,
                bot_alias=key.bot_alias,
                user_id=key.user_id,
            )
        elif key.provider_id == "clangd":
            self.provider = ClangdProvider(
                key.workspace_root,
                runtime_cache_dir=runtime_cache_dir,
                external_source_registry=external_source_registry,
                bot_alias=key.bot_alias,
                user_id=key.user_id,
                trusted_compiler_commands=command[:1],
            )
        else:
            self.provider = PyrightProvider(
                key.workspace_root,
                external_source_registry=external_source_registry,
                bot_alias=key.bot_alias,
                user_id=key.user_id,
                pyright_command=command,
            )
        prepare_command = getattr(self.provider, "prepare_command", None)
        self.command = tuple(prepare_command(tuple(command))) if callable(prepare_command) else tuple(command)
        self.process: asyncio.subprocess.Process | None = None
        self.client: Any = None
        self.state = "stopped"
        self.generation = 0
        self.last_error = ""
        self.last_used_at = time.monotonic()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._recent_errors: deque[str] = deque(maxlen=_MAX_RECENT_ERRORS)
        self._stderr_task: asyncio.Task[None] | None = None
        self._process_wait_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        self._progress_tokens: set[str] = set()
        self._active_operation_count = 0
        self._failure_handler: Callable[["LanguageServerRuntime", BaseException], Any] | None = None
        self._failure_notified = False
        self._closing = False
        self.restart_count = 0
        self.restart_attempts = 0
        self.crash_count = 0
        self.last_crash_at = 0.0
        self.last_restart_at = 0.0

    @property
    def pending_count(self) -> int:
        return int(getattr(self.client, "pending_count", 0) or 0)

    @property
    def open_document_count(self) -> int:
        return self.provider.open_document_count

    @property
    def active_operation_count(self) -> int:
        return self._active_operation_count

    def set_failure_handler(
        self,
        handler: Callable[["LanguageServerRuntime", BaseException], Any] | None,
    ) -> None:
        self._failure_handler = handler

    def record_failure(self, error: BaseException, *, crash: bool = True) -> None:
        detail = str(error or "语言服务器传输失败").strip() or type(error).__name__
        detail = detail[:500]
        self.last_error = detail
        self._recent_errors.append(detail)
        if crash:
            self.crash_count += 1
            self.last_crash_at = time.time()

    async def _on_client_transport_failure(self, error: BaseException) -> None:
        if self._closing or self.state == "stopped":
            return
        if self._failure_notified:
            return
        self._failure_notified = True
        self.record_failure(error)
        self.state = "error"
        handler = self._failure_handler
        if handler is not None:
            result = handler(self, error)
            if hasattr(result, "__await__"):
                await result

    async def _watch_process(self, process: Any) -> None:
        wait = getattr(process, "wait", None)
        if not callable(wait):
            return
        try:
            result = wait()
            returncode = await result if hasattr(result, "__await__") else result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            returncode = None
            error: BaseException = LspJsonRpcClosedError(f"语言服务器进程监视失败: {exc}")
        else:
            error = LspJsonRpcClosedError(f"语言服务器进程已退出 (code={returncode})")
        if self._closing or process is not self.process:
            return
        client = self.client
        if client is not None:
            fail_transport = getattr(client, "fail_transport", None)
            if callable(fail_transport):
                fail_transport(error)
                return
        await self._on_client_transport_failure(error)

    async def start(self) -> None:
        if self.state in {"ready", "indexing"}:
            return
        if not self.command:
            raise LanguageServerUnavailableError("语言服务器命令为空")
        self._closing = False
        self._failure_notified = False
        self.state = "starting"
        try:
            process_kwargs = build_chat_cli_process_kwargs()
            process_environment = getattr(self.provider, "process_environment", None)
            if callable(process_environment):
                environment = process_environment()
                if environment is not None:
                    process_kwargs["env"] = environment
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.key.workspace_root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_kwargs,
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
                transport_failure_handler=self._on_client_transport_failure,
            )
            self._process_wait_task = asyncio.create_task(self._watch_process(self.process))
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
            self.record_failure(exc, crash=False)
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
            source_id = _document_source_id(document)
            if source_id:
                _reject_absolute_browser_path(source_id)
                target, content = self._read_external_navigation_document(document, source_id)
            else:
                path = str(document.get("path") or "").strip()
                _reject_absolute_browser_path(path)
                target = (self.key.workspace_root / path).resolve()
                try:
                    target.relative_to(self.key.workspace_root)
                except ValueError as exc:
                    raise ValueError("代码导航路径超出工作区") from exc
                content = str(document.get("content") or "")
            kind = str(request.get("kind") or "").strip().lower()
            request_id = str(request.get("requestId") or request.get("request_id") or "").strip()
            try:
                items = await self.provider.navigate(
                    self.client,
                    kind=kind,
                    path=target,
                    language_id=str(document.get("languageId") or document.get("language_id") or ""),
                    version=_int_value(document.get("version"), 0),
                    content=content,
                    line=max(1, _int_value(position.get("line"), 1)),
                    column=max(1, _int_value(position.get("column"), 1)),
                    source_id=source_id,
                )
            except asyncio.TimeoutError:
                return {"request_id": request_id, "items": [], "message": "仍在索引"}
            empty_message = "仍在索引" if self.state == "indexing" else (
                "未找到语义实现" if kind == "implementation" else "未找到语义定义"
            )
            return {
                "request_id": request_id,
                "items": items,
                "message": "" if items else empty_message,
            }
        finally:
            self._active_operation_count = max(0, self._active_operation_count - 1)
            self.last_used_at = time.monotonic()

    def _read_external_navigation_document(
        self,
        document: Mapping[str, Any],
        source_id: str,
    ) -> tuple[Path, str]:
        path = str(document.get("path") or "").strip()
        _reject_absolute_browser_path(path)
        registry = self.external_source_registry
        if registry is None:
            raise ValueError("外部依赖源码浏览未启用")
        record = registry.resolve(
            source_id,
            alias=self.key.bot_alias,
            user_id=self.key.user_id,
            workspace_root=self.key.workspace_root,
            provider_id=self.key.provider_id,
        )
        data = registry.read(
            source_id,
            alias=self.key.bot_alias,
            user_id=self.key.user_id,
            workspace_root=self.key.workspace_root,
            provider_id=self.key.provider_id,
            mode="cat",
        )
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError("外部源码内容不可读取")
        return record.path, content

    async def sync_documents(self, documents: Sequence[LanguageDocument]) -> list[LanguageDocument]:
        if self.state not in {"ready", "indexing"} or self.client is None:
            raise RuntimeError("语言服务器尚未就绪")
        sync = getattr(self.provider, "sync_documents", None)
        if not callable(sync):
            return []
        self._active_operation_count += 1
        try:
            return list(await sync(self.client, documents))
        finally:
            self._active_operation_count = max(0, self._active_operation_count - 1)
            self.last_used_at = time.monotonic()

    async def close_documents(
        self,
        documents: Sequence[LanguageDocument | Mapping[str, Any] | str],
    ) -> list[str]:
        if self.state not in {"ready", "indexing"} or self.client is None:
            return []
        close = getattr(self.provider, "close_documents", None)
        if not callable(close):
            return []
        self._active_operation_count += 1
        try:
            return list(await close(self.client, documents))
        finally:
            self._active_operation_count = max(0, self._active_operation_count - 1)
            self.last_used_at = time.monotonic()

    async def close_external_sources(self, source_ids: Sequence[str]) -> list[str]:
        if self.state not in {"ready", "indexing"} or self.client is None:
            return []
        close = getattr(self.provider, "close_external_sources", None)
        if not callable(close):
            return []
        self._active_operation_count += 1
        try:
            return list(await close(self.client, source_ids))
        finally:
            self._active_operation_count = max(0, self._active_operation_count - 1)
            self.last_used_at = time.monotonic()

    async def close(self) -> None:
        async with self._close_lock:
            if self.state == "stopped" and self.process is None:
                return
            self._closing = True
            client = self.client
            process = self.process
            self.client = None
            await self._finish_process_wait_task()
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
                if process is not None and process.returncode is None:
                    with contextlib.suppress(BaseException):
                        await asyncio.wait_for(process.wait(), timeout=0.5)
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
        self._closing = True
        client = self.client
        self.client = None
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(BaseException):
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
        await self._finish_process_wait_task()
        process = self.process
        if process is not None and process.returncode is None:
            with contextlib.suppress(BaseException):
                await terminate_async_process_tree(process)
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(process.wait(), timeout=0.5)
        await self._finish_stderr_task()
        self.process = None

    async def _finish_process_wait_task(self) -> None:
        task = self._process_wait_task
        self._process_wait_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task

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
        returncode = getattr(process, "returncode", None) if process is not None else None
        alive = bool(process is not None and returncode is None)
        return {
            "state": self.state,
            "generation": self.generation,
            "pid": process.pid if alive else None,
            "process": {
                "pid": process.pid if process is not None else None,
                "returncode": returncode,
                "alive": alive,
            },
            "pending_count": self.pending_count,
            "pending": {"count": self.pending_count},
            "active_operation_count": self.active_operation_count,
            "open_document_count": self.open_document_count,
            "document_count": self.open_document_count,
            "documents": {"open_count": self.open_document_count},
            "implementation_supported": bool(getattr(self.provider, "supports_implementation", False)),
            "idle_seconds": round(max(0.0, time.monotonic() - self.last_used_at), 3),
            "last_error": self.last_error,
            "stderr_tail": list(self._stderr_tail),
            "recent_errors": list(self._recent_errors),
            "restart_count": self.restart_count,
            "restart_attempts": self.restart_attempts,
            "restart": {
                "count": self.restart_count,
                "attempts": self.restart_attempts,
                "last_at": self.last_restart_at or None,
            },
            "crash_count": self.crash_count,
            "last_crash_at": self.last_crash_at or None,
            "crashes": {"count": self.crash_count, "last_at": self.last_crash_at or None},
            "last_restart_at": self.last_restart_at or None,
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
        restart_base_delay: float = _RESTART_BASE_DELAY_SECONDS,
        restart_max_delay: float = _RESTART_MAX_DELAY_SECONDS,
        crash_window_seconds: float = _CRASH_WINDOW_SECONDS,
        crash_threshold: int = _CRASH_THRESHOLD,
        external_source_registry: ExternalSourceRegistry | None = None,
    ) -> None:
        self.catalog = catalog
        self.request_timeout = float(
            config.TCB_LSP_REQUEST_TIMEOUT_SECONDS if request_timeout is None else request_timeout
        )
        self.idle_timeout = max(
            0.01,
            float(config.TCB_LSP_IDLE_TIMEOUT_SECONDS if idle_timeout is None else idle_timeout),
        )
        self.max_runtimes = max(
            1,
            int(config.TCB_LSP_MAX_RUNTIMES if max_runtimes is None else max_runtimes),
        )
        self.restart_base_delay = max(0.0, float(restart_base_delay))
        self.restart_max_delay = max(self.restart_base_delay, float(restart_max_delay))
        self.crash_window_seconds = max(0.1, float(crash_window_seconds))
        self.crash_threshold = max(1, int(crash_threshold))
        self.external_source_registry = external_source_registry
        installer = getattr(catalog, "installer", None)
        node_tools_dir = getattr(installer, "node_tools_dir", None)
        self._managed_typescript_sdk_path = (
            Path(node_tools_dir) / "node_modules" / "typescript" / "lib" / "tsserver.js"
            if node_tools_dir is not None
            else None
        )
        self._runtime_factory = runtime_factory or self._create_runtime
        self._runtimes: dict[LanguageServerRuntimeKey, RuntimeProtocol] = {}
        self._start_tasks: dict[LanguageServerRuntimeKey, asyncio.Task[RuntimeProtocol]] = {}
        # Candidates remain private until initialize plus document replay has
        # completed.  Transport failures need to find them before they become
        # generally usable runtimes.
        self._initializing_runtimes: dict[
            LanguageServerRuntimeKey,
            tuple[int, RuntimeProtocol],
        ] = {}
        # Replacement candidates retain their failed predecessor as the
        # publicly visible runtime until the recovery loop atomically accepts
        # the new generation.
        self._replacement_initializing_runtimes: dict[
            LanguageServerRuntimeKey,
            tuple[int, RuntimeProtocol],
        ] = {}
        self._replacement_initialization_failures: dict[
            LanguageServerRuntimeKey,
            tuple[RuntimeProtocol, BaseException],
        ] = {}
        self._restart_tasks: dict[LanguageServerRuntimeKey, asyncio.Task[None]] = {}
        self._generation_by_key: dict[LanguageServerRuntimeKey, int] = {}
        self._crash_history: dict[LanguageServerRuntimeKey, deque[float]] = {}
        self._restart_count = 0
        self._crash_count = 0
        self._recent_errors: deque[dict[str, object]] = deque(maxlen=_MAX_RECENT_ERRORS)
        self._active_requests: dict[
            tuple[LanguageServerRuntimeKey, str],
            set[asyncio.Task[Any]],
        ] = {}
        self._cancelled_requests: dict[tuple[str, int, Path, str], float] = {}
        self.document_store = LanguageDocumentStore()
        self._lock = asyncio.Lock()
        self._shutdown_started = False
        self._maintenance_task: asyncio.Task[None] | None = None

    def _create_runtime(self, key: LanguageServerRuntimeKey, command: tuple[str, ...]) -> LanguageServerRuntime:
        return LanguageServerRuntime(
            key,
            command,
            request_timeout=self.request_timeout,
            managed_typescript_sdk_path=self._managed_typescript_sdk_path,
            runtime_cache_dir=self._runtime_cache_dir(key),
            external_source_registry=self.external_source_registry,
        )

    @staticmethod
    def _runtime_cache_dir(key: LanguageServerRuntimeKey) -> Path:
        identity = "\x1f".join(
            (key.bot_alias, str(key.user_id), str(key.workspace_root), key.provider_id),
        ).encode("utf-8", errors="replace")
        digest = hashlib.sha256(identity).hexdigest()[:32]
        return get_language_servers_root() / "runtime-cache" / digest

    def _configure_runtime(self, runtime: RuntimeProtocol, generation: int) -> RuntimeProtocol:
        # RuntimeFactory is intentionally kept backward compatible with the
        # phase 1-7 two-argument contract.  Metadata and callbacks are attached
        # after construction so test doubles and integrations do not need to be
        # changed in lockstep.
        try:
            setattr(runtime, "generation", generation)
        except Exception:
            pass
        handler = getattr(runtime, "set_failure_handler", None)
        if callable(handler):
            handler(self._on_runtime_failure)
        else:
            try:
                setattr(runtime, "_failure_handler", self._on_runtime_failure)
            except Exception:
                pass
        return runtime

    def _next_generation_locked(self, key: LanguageServerRuntimeKey) -> int:
        generation = int(self._generation_by_key.get(key, 0) or 0) + 1
        self._generation_by_key[key] = generation
        return generation

    @staticmethod
    def _runtime_state(runtime: RuntimeProtocol) -> str:
        state = getattr(runtime, "state", None)
        if state:
            return str(state)
        try:
            return str(runtime.diagnostics().get("state") or "unknown")
        except Exception:
            return "unknown"

    @staticmethod
    def _runtime_generation(runtime: RuntimeProtocol) -> int:
        try:
            return int(getattr(runtime, "generation", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _runtime_diagnostics(cls, runtime: RuntimeProtocol) -> dict[str, object]:
        try:
            diagnostics = dict(runtime.diagnostics())
        except Exception as exc:
            diagnostics = {"last_error": str(exc)[:300]}
        diagnostics["state"] = cls._runtime_state(runtime)
        diagnostics.setdefault("generation", cls._runtime_generation(runtime))
        return diagnostics

    async def _ensure_maintenance_task(self) -> None:
        if self._shutdown_started:
            return
        task = self._maintenance_task
        if task is None or task.done():
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def _maintenance_loop(self) -> None:
        interval = min(
            _MAINTENANCE_MAX_INTERVAL_SECONDS,
            max(0.01, self.idle_timeout / 2.0),
        )
        try:
            while not self._shutdown_started:
                await asyncio.sleep(interval)
                if self._shutdown_started:
                    return
                await self.evict_idle()
        except asyncio.CancelledError:
            raise

    def _record_error_locked(
        self,
        key: LanguageServerRuntimeKey,
        runtime: RuntimeProtocol | None,
        error: BaseException,
        *,
        crash: bool = True,
        record_runtime: bool = True,
    ) -> None:
        detail = str(error or "语言服务器失败").strip() or type(error).__name__
        detail = detail[:500]
        self._recent_errors.append(
            {
                "provider_id": key.provider_id,
                "bot_alias": key.bot_alias,
                "user_id": key.user_id,
                "state": self._runtime_state(runtime) if runtime is not None else "starting",
                "error": detail,
                "at": time.time(),
            }
        )
        if runtime is not None and record_runtime:
            record = getattr(runtime, "record_failure", None)
            if callable(record):
                record(error, crash=crash)
            else:
                try:
                    setattr(runtime, "last_error", detail)
                except Exception:
                    pass
        if crash:
            self._crash_count += 1
            history = self._crash_history.setdefault(key, deque(maxlen=max(self.crash_threshold * 2, 8)))
            now = time.monotonic()
            history.append(now)
            while history and now - history[0] > self.crash_window_seconds:
                history.popleft()

    def _crashes_in_window_locked(self, key: LanguageServerRuntimeKey) -> int:
        history = self._crash_history.get(key)
        if not history:
            return 0
        now = time.monotonic()
        while history and now - history[0] > self.crash_window_seconds:
            history.popleft()
        return len(history)

    def _schedule_runtime_recovery_locked(
        self,
        key: LanguageServerRuntimeKey,
        runtime: RuntimeProtocol,
        error: BaseException,
    ) -> None:
        """Record one runtime failure and atomically begin its recovery.

        Transport callbacks can arrive more than once (for example a process
        exit followed by stdout EOF).  The first callback owns the recovery
        task; later callbacks for that same runtime must not inflate the crash
        window or schedule a competing restart.
        """

        existing = self._restart_tasks.get(key)
        if existing is not None and not existing.done():
            return
        if self._runtime_state(runtime) == "degraded":
            return
        self._record_error_locked(key, runtime, error, record_runtime=False)
        if self._crashes_in_window_locked(key) >= self.crash_threshold:
            try:
                setattr(runtime, "state", "degraded")
            except Exception:
                pass
            self._restart_tasks[key] = asyncio.create_task(self._close_degraded_runtime(runtime))
            return
        try:
            setattr(runtime, "state", "restarting")
        except Exception:
            pass
        self._restart_tasks[key] = asyncio.create_task(self._restart_runtime_loop(key, runtime))

    @staticmethod
    def _matches_initializing_candidate(
        candidate: tuple[int, RuntimeProtocol] | None,
        generation: int,
        runtime: RuntimeProtocol,
    ) -> bool:
        return candidate is not None and candidate[0] == generation and candidate[1] is runtime

    def _discard_replacement_initialization_locked(
        self,
        key: LanguageServerRuntimeKey,
        generation: int,
        runtime: RuntimeProtocol,
    ) -> BaseException | None:
        candidate = self._replacement_initializing_runtimes.get(key)
        if not self._matches_initializing_candidate(candidate, generation, runtime):
            return None
        self._replacement_initializing_runtimes.pop(key, None)
        failure = self._replacement_initialization_failures.pop(key, None)
        return failure[1] if failure is not None and failure[0] is runtime else None

    async def _on_runtime_failure(self, runtime: LanguageServerRuntime, error: BaseException) -> None:
        key = runtime.key
        async with self._lock:
            current = self._runtimes.get(key)
            generation = self._runtime_generation(runtime)
            if generation != int(self._generation_by_key.get(key, 0) or 0):
                return
            candidate = self._initializing_runtimes.get(key)
            if self._matches_initializing_candidate(candidate, generation, runtime):
                self._initializing_runtimes.pop(key, None)
                if current is not None and current is not runtime:
                    return
                self._runtimes[key] = runtime
                self._schedule_runtime_recovery_locked(key, runtime, error)
                return
            replacement = self._replacement_initializing_runtimes.get(key)
            if self._matches_initializing_candidate(replacement, generation, runtime):
                existing = self._replacement_initialization_failures.get(key)
                if existing is None or existing[0] is not runtime:
                    self._replacement_initialization_failures[key] = (runtime, error)
                return
            if current is not runtime:
                return
            self._schedule_runtime_recovery_locked(key, runtime, error)

    async def _recover_failed_start(
        self,
        key: LanguageServerRuntimeKey,
        runtime: RuntimeProtocol,
        generation: int,
        error: BaseException,
    ) -> None:
        """Move a failed initialize candidate into the normal recovery path.

        A JSON-RPC EOF/protocol failure may happen while ``start`` is awaiting
        ``initialize``.  At that point the runtime has intentionally not yet
        been exposed through ``_runtimes``.  Registering the closed candidate
        and scheduling recovery under the same lock keeps the failure visible
        to concurrent requests without ever returning a half-initialized
        runtime as ready.
        """

        async with self._lock:
            if self._shutdown_started or self._generation_by_key.get(key) != generation:
                return
            current = self._runtimes.get(key)
            if current is not None and current is not runtime:
                return
            candidate = self._initializing_runtimes.get(key)
            if self._matches_initializing_candidate(candidate, generation, runtime):
                self._initializing_runtimes.pop(key, None)
            self._runtimes[key] = runtime
            self._schedule_runtime_recovery_locked(key, runtime, error)

    async def _close_degraded_runtime(self, runtime: RuntimeProtocol) -> None:
        try:
            await runtime.close()
        finally:
            try:
                setattr(runtime, "state", "degraded")
            except Exception:
                pass
            async with self._lock:
                current = self._restart_tasks.get(runtime.key)
                if current is asyncio.current_task():
                    self._restart_tasks.pop(runtime.key, None)

    async def _restart_runtime_loop(
        self,
        key: LanguageServerRuntimeKey,
        failed_runtime: RuntimeProtocol,
    ) -> None:
        attempt = 0
        try:
            try:
                await failed_runtime.close()
            except asyncio.CancelledError:
                raise
            except BaseException:
                pass
            try:
                setattr(failed_runtime, "state", "restarting")
            except Exception:
                pass
            while True:
                delay = min(self.restart_max_delay, self.restart_base_delay * (2**attempt))
                if delay > 0:
                    await asyncio.sleep(delay)
                async with self._lock:
                    if self._shutdown_started or self._runtimes.get(key) is not failed_runtime:
                        return
                    if self._crashes_in_window_locked(key) >= self.crash_threshold:
                        try:
                            setattr(failed_runtime, "state", "degraded")
                        except Exception:
                            pass
                        return
                    generation = self._next_generation_locked(key)
                    try:
                        setattr(failed_runtime, "restart_attempts", attempt + 1)
                    except Exception:
                        pass
                command = tuple(getattr(failed_runtime, "command", ()) or ())
                try:
                    replacement = await self._start_replacement(key, command, generation)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    async with self._lock:
                        if self._runtimes.get(key) is not failed_runtime:
                            return
                        self._record_error_locked(key, failed_runtime, exc)
                        if self._crashes_in_window_locked(key) >= self.crash_threshold:
                            try:
                                setattr(failed_runtime, "state", "degraded")
                            except Exception:
                                pass
                            return
                    attempt += 1
                    continue
                replacement_failure: BaseException | None = None
                async with self._lock:
                    if self._shutdown_started or self._runtimes.get(key) is not failed_runtime:
                        self._discard_replacement_initialization_locked(key, generation, replacement)
                        stale = True
                    else:
                        replacement_failure = self._discard_replacement_initialization_locked(
                            key,
                            generation,
                            replacement,
                        )
                        if replacement_failure is not None:
                            stale = False
                        else:
                            self._runtimes[key] = replacement
                            self._restart_count += 1
                            stale = False
                            try:
                                setattr(replacement, "restart_count", self._restart_count)
                                setattr(replacement, "last_restart_at", time.time())
                            except Exception:
                                pass
                if stale:
                    with contextlib.suppress(BaseException):
                        await replacement.close()
                    return
                if replacement_failure is not None:
                    with contextlib.suppress(BaseException):
                        await replacement.close()
                    async with self._lock:
                        if self._runtimes.get(key) is not failed_runtime:
                            return
                        self._record_error_locked(key, failed_runtime, replacement_failure)
                        if self._crashes_in_window_locked(key) >= self.crash_threshold:
                            try:
                                setattr(failed_runtime, "state", "degraded")
                            except Exception:
                                pass
                            return
                    attempt += 1
                    continue
                return
        finally:
            async with self._lock:
                current = self._restart_tasks.get(key)
                if current is asyncio.current_task():
                    self._restart_tasks.pop(key, None)

    async def _start_replacement(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
        generation: int,
    ) -> RuntimeProtocol:
        if not command:
            raise LanguageServerUnavailableError("语言服务器命令为空")
        runtime = self._configure_runtime(self._runtime_factory(key, command), generation)
        try:
            async with self._lock:
                if self._shutdown_started or self._generation_by_key.get(key) != generation:
                    raise RuntimeError("语言服务器管理器正在关闭")
                self._replacement_initializing_runtimes[key] = (generation, runtime)
            await runtime.start()
            if self._runtime_state(runtime) in {"error", "stopped", "degraded"}:
                raise RuntimeError("语言服务器启动后不可用")
            snapshots = self.document_store.snapshot(key)
            replay = getattr(runtime, "replay_documents", None)
            sync = replay if callable(replay) else getattr(runtime, "sync_documents", None)
            if snapshots and callable(sync):
                await sync(snapshots)
            return runtime
        except BaseException:
            async with self._lock:
                self._discard_replacement_initialization_locked(key, generation, runtime)
            with contextlib.suppress(BaseException):
                await runtime.close()
            raise

    async def _wait_for_recovery(
        self,
        key: LanguageServerRuntimeKey,
        runtime: RuntimeProtocol,
        command: tuple[str, ...],
        error: BaseException | None = None,
    ) -> None:
        async with self._lock:
            task = self._restart_tasks.get(key)
            current = self._runtimes.get(key)
            if task is None and current is runtime and self._runtime_state(runtime) not in {"degraded"}:
                if error is not None:
                    self._record_error_locked(key, runtime, error, record_runtime=False)
                try:
                    setattr(runtime, "state", "restarting")
                except Exception:
                    pass
                task = asyncio.create_task(self._restart_runtime_loop(key, runtime))
                self._restart_tasks[key] = task
        if task is not None:
            await asyncio.shield(task)

    @staticmethod
    def _transport_failure_is_retryable(error: BaseException) -> bool:
        return isinstance(
            error,
            (
                LspJsonRpcClosedError,
                LspJsonRpcProtocolError,
                LspJsonRpcTimeoutError,
                ConnectionError,
                EOFError,
                asyncio.IncompleteReadError,
            ),
        )

    @staticmethod
    def _navigation_failure_is_retryable(runtime: RuntimeProtocol, error: BaseException) -> bool:
        return (
            LanguageServerRuntimeManager._transport_failure_is_retryable(error)
            or LanguageServerRuntimeManager._runtime_state(runtime) in {"error", "restarting"}
        )

    def _is_current_runtime(
        self,
        key: LanguageServerRuntimeKey,
        runtime: RuntimeProtocol,
        generation: int,
    ) -> bool:
        return (
            self._runtimes.get(key) is runtime
            and self._runtime_generation(runtime) == generation
            and int(self._generation_by_key.get(key, 0) or 0) == generation
            and self._runtime_state(runtime) in {"ready", "indexing"}
            and key not in self._restart_tasks
        )

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
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("工作区目录不存在")
        normalized_alias = str(bot_alias or "").strip().lower()
        normalized_user_id = int(user_id)
        document_value = request.get("document")
        if not isinstance(document_value, Mapping):
            raise ValueError("代码导航请求格式无效")
        source_id = _document_source_id(document_value)
        if source_id:
            _reject_absolute_browser_path(source_id)
            _reject_absolute_browser_path(str(document_value.get("path") or ""))
            registry = self.external_source_registry
            if registry is None:
                raise ValueError("外部依赖源码浏览未启用")
            record = registry.resolve(
                source_id,
                alias=normalized_alias,
                user_id=normalized_user_id,
                workspace_root=root,
            )
            provider_id = record.provider_id
            if provider_id not in {"pyright", "typescript", "clangd"}:
                raise ValueError("外部源码 provider 不受支持")
        else:
            provider_id = _provider_for_request(request)
            if provider_id is None:
                empty_message = "未找到语义实现" if kind == "implementation" else "未找到语义定义"
                return {"request_id": request_id, "items": [], "message": empty_message}
            if _workspace_path_requires_external_source_id(
                str(document_value.get("path") or ""),
                provider_id,
            ):
                raise ValueError("外部依赖源码必须使用 source_id")
        if not bool(getattr(self.catalog, "enabled", True)):
            raise LanguageServerUnavailableError("语言服务已关闭")

        key = LanguageServerRuntimeKey(
            bot_alias=normalized_alias,
            user_id=normalized_user_id,
            workspace_root=root,
            provider_id=provider_id,
        )
        runtime_request = dict(request)
        if not source_id:
            document = LanguageDocument.from_value(document_value)
            sync_result = self.document_store.sync_documents(key, [document])
            current_document = self.document_store.get(key, document.path)
            if current_document is not None and not sync_result.accepted:
                runtime_request["document"] = current_document.to_dict()

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
                raise LanguageServerUnavailableError("语言服务器未安装或命令不可用")
            command_tuple = tuple(command)
            for attempt in range(2):
                runtime: RuntimeProtocol | None = None
                try:
                    runtime = await self._get_or_start(key, command_tuple)
                    generation = self._runtime_generation(runtime)
                    result = await runtime.resolve_code_navigation(runtime_request)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    if attempt >= 1:
                        raise
                    if runtime is None:
                        if not self._transport_failure_is_retryable(exc):
                            raise
                        # _start_and_register has already made this failure
                        # visible to recovery.  The second (and final) pass
                        # waits for that task inside _get_or_start.
                        continue
                    if not self._navigation_failure_is_retryable(runtime, exc):
                        raise
                    await self._wait_for_recovery(key, runtime, command_tuple, exc)
                    continue
                if self._is_current_runtime(key, runtime, generation):
                    return result
                if attempt >= 1:
                    raise LspJsonRpcClosedError("语言服务器响应来自旧 runtime generation")
                await self._wait_for_recovery(key, runtime, command_tuple)
            raise LspJsonRpcClosedError("语言服务器导航重试失败")
        finally:
            async with self._lock:
                active_tasks = self._active_requests.get(active_key)
                if active_tasks is not None:
                    active_tasks.discard(current_task)
                    if not active_tasks:
                        self._active_requests.pop(active_key, None)

    async def sync_documents(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        documents: Sequence[LanguageDocument | Mapping[str, Any]],
    ) -> dict[str, object]:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("工作区目录不存在")
        if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
            raise ValueError("文档同步批次格式无效")
        parsed_documents = self.document_store.validate_documents(documents)

        normalized_alias = str(bot_alias or "").strip().lower()
        normalized_user_id = int(user_id)
        grouped: dict[str, list[LanguageDocument]] = {}
        for document in parsed_documents:
            if document.source_id:
                raise ValueError("外部源码为只读，不能同步浏览器文档内容")
            _reject_absolute_browser_path(document.path)
            provider_id = _provider_for_document(document.path, document.language_id)
            if provider_id is None:
                continue
            if _workspace_path_requires_external_source_id(document.path, provider_id):
                raise ValueError("外部依赖源码必须使用 source_id")
            target = (root / document.path).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError("文档同步路径超出工作区") from exc
            grouped.setdefault(provider_id, []).append(document)

        accepted: list[LanguageDocument] = []
        unchanged: list[LanguageDocument] = []
        rejected: list[dict[str, object]] = []
        sync_kinds: set[str] = set()
        for provider_id, provider_documents in grouped.items():
            key = LanguageServerRuntimeKey(normalized_alias, normalized_user_id, root, provider_id)
            result = self.document_store.sync_documents(key, provider_documents)
            accepted.extend(result.accepted)
            unchanged.extend(result.unchanged)
            rejected.extend(item.to_dict() for item in result.rejected)

            if not result.accepted and not result.unchanged:
                continue
            command = await asyncio.to_thread(self.catalog.command_for, provider_id)
            if not command:
                continue
            runtime = await self._get_or_start(key, tuple(command))
            if result.accepted:
                sync = getattr(runtime, "sync_documents", None)
                if callable(sync):
                    await sync(result.accepted)
            sync_kinds.add(_runtime_sync_kind(runtime))

        sync_kind = "incremental" if sync_kinds == {"incremental"} else "full"
        return {
            "accepted": len(accepted),
            "unchanged": len(unchanged),
            "rejected": len(rejected),
            "documents": [item.to_dict(include_content=False) for item in (*accepted, *unchanged)],
            "rejections": rejected,
            "sync_kind": sync_kind,
            "supports_incremental_changes": sync_kind == "incremental",
            "max_document_bytes": self.document_store.max_document_bytes,
            "max_batch_documents": self.document_store.max_batch_documents,
            "max_batch_bytes": self.document_store.max_batch_bytes,
        }

    async def close_documents(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        documents: Sequence[LanguageDocument | Mapping[str, Any] | str],
    ) -> dict[str, object]:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("工作区目录不存在")
        if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
            raise ValueError("文档关闭批次格式无效")
        if len(documents) > self.document_store.max_batch_documents:
            raise LanguageDocumentLimitError("文档关闭批次过大")
        normalized_alias = str(bot_alias or "").strip().lower()
        normalized_user_id = int(user_id)
        grouped: dict[str, list[LanguageDocument | Mapping[str, Any] | str]] = {}
        external_grouped: dict[str, list[str]] = {}
        for value in documents:
            if isinstance(value, str):
                path = normalize_document_path(value)
                language_id = ""
                source_id = ""
            elif isinstance(value, LanguageDocument):
                path = normalize_document_path(value.path)
                language_id = value.language_id
                source_id = str(value.source_id or "").strip()
            elif isinstance(value, Mapping):
                path = normalize_document_path(value.get("path"))
                language_id = str(value.get("languageId") or value.get("language_id") or "")
                source_id = _document_source_id(value)
            else:
                raise ValueError("文档关闭项格式无效")
            if source_id:
                _reject_absolute_browser_path(source_id)
                _reject_absolute_browser_path(path)
                registry = self.external_source_registry
                if registry is None:
                    raise ValueError("外部依赖源码浏览未启用")
                record = registry.resolve(
                    source_id,
                    alias=normalized_alias,
                    user_id=normalized_user_id,
                    workspace_root=root,
                )
                external_grouped.setdefault(record.provider_id, []).append(source_id)
                continue
            if not path:
                raise ValueError("文档关闭项缺少路径")
            _reject_absolute_browser_path(path)
            target = (root / path).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError("文档关闭路径超出工作区") from exc
            provider_id = _provider_for_document(path, language_id)
            if provider_id is not None:
                if _workspace_path_requires_external_source_id(path, provider_id):
                    raise ValueError("外部依赖源码必须使用 source_id")
                grouped.setdefault(provider_id, []).append(value)

        closed: list[LanguageDocument] = []
        missing: list[str] = []
        closed_external: list[str] = []
        for provider_id, provider_documents in grouped.items():
            key = LanguageServerRuntimeKey(normalized_alias, normalized_user_id, root, provider_id)
            result = self.document_store.close_documents(key, provider_documents)
            closed.extend(result.closed)
            missing.extend(result.missing)
            async with self._lock:
                runtime = self._runtimes.get(key)
            if runtime is not None:
                close = getattr(runtime, "close_documents", None)
                if callable(close):
                    await close(provider_documents)
        for provider_id, source_ids in external_grouped.items():
            key = LanguageServerRuntimeKey(normalized_alias, normalized_user_id, root, provider_id)
            async with self._lock:
                runtime = self._runtimes.get(key)
            if runtime is None:
                missing.extend(source_ids)
                continue
            close_external = getattr(runtime, "close_external_sources", None)
            if not callable(close_external):
                missing.extend(source_ids)
                continue
            closed_ids = list(await close_external(source_ids))
            closed_external.extend(closed_ids)
            missing.extend(source_id for source_id in source_ids if source_id not in closed_ids)
        return {
            "closed": len(closed) + len(closed_external),
            "documents": [
                *[item.to_dict(include_content=False) for item in closed],
                *[{"sourceId": source_id} for source_id in closed_external],
            ],
            "missing": missing,
        }

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
        if normalized_provider not in {"pyright", "typescript", "clangd"} or not bool(getattr(self.catalog, "enabled", True)):
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

    async def restart_runtime(
        self,
        *,
        bot_alias: str,
        user_id: int,
        workspace_root: Path | str,
        provider_id: str,
    ) -> dict[str, object]:
        """Restart exactly one isolated language-server runtime.

        The document store is intentionally retained.  The replacement goes
        through the same initialize/replay path as automatic recovery, while
        all other isolation keys remain untouched.
        """

        normalized_provider = str(provider_id or "").strip().lower()
        if normalized_provider not in {"pyright", "typescript", "clangd"}:
            raise ValueError("语言服务器 provider 无效")
        if not bool(getattr(self.catalog, "enabled", True)):
            raise LanguageServerUnavailableError("语言服务已关闭")
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("工作区目录不存在")
        command = await asyncio.to_thread(self.catalog.command_for, normalized_provider)
        if not command:
            raise LanguageServerUnavailableError("语言服务器未安装或命令不可用")
        key = LanguageServerRuntimeKey(
            bot_alias=str(bot_alias or "").strip().lower(),
            user_id=int(user_id),
            workspace_root=root,
            provider_id=normalized_provider,
        )
        async with self._lock:
            if self._shutdown_started:
                raise RuntimeError("语言服务器管理器正在关闭")
            old = self._runtimes.pop(key, None)
            start_task = self._start_tasks.pop(key, None)
            restart_task = self._restart_tasks.pop(key, None)
            generation = self._next_generation_locked(key) if old is not None else 0
            self._crash_history.pop(key, None)
            active_tasks = [
                task
                for (active_key, _request_id), tasks in self._active_requests.items()
                if active_key == key
                for task in tasks
                if task is not asyncio.current_task() and not task.done()
            ]
            for task in active_tasks:
                task.cancel()
            if old is not None:
                try:
                    setattr(old, "state", "restarting")
                except Exception:
                    pass
        for task in (restart_task, start_task):
            if task is not None and not task.done():
                task.cancel()
        if restart_task is not None:
            await asyncio.gather(restart_task, return_exceptions=True)
        if start_task is not None:
            await asyncio.gather(start_task, return_exceptions=True)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        if old is None:
            runtime = await self._get_or_start(key, tuple(command))
            return {"restarted": True, **runtime.diagnostics()}
        with contextlib.suppress(BaseException):
            await old.close()
        try:
            runtime = await self._start_replacement(key, tuple(command), generation)
        except BaseException as exc:
            try:
                setattr(old, "state", "degraded")
            except Exception:
                pass
            async with self._lock:
                if not self._shutdown_started and self._generation_by_key.get(key) == generation:
                    self._runtimes[key] = old
                    self._record_error_locked(key, old, exc, record_runtime=False)
            raise
        replacement_failure: BaseException | None = None
        async with self._lock:
            if self._shutdown_started or self._generation_by_key.get(key) != generation:
                self._discard_replacement_initialization_locked(key, generation, runtime)
                stale = True
            else:
                replacement_failure = self._discard_replacement_initialization_locked(
                    key,
                    generation,
                    runtime,
                )
                if replacement_failure is not None:
                    stale = False
                else:
                    self._runtimes[key] = runtime
                    self._restart_count += 1
                    stale = False
                    try:
                        setattr(runtime, "restart_count", self._restart_count)
                        setattr(runtime, "last_restart_at", time.time())
                    except Exception:
                        pass
        if stale:
            await runtime.close()
            raise RuntimeError("语言服务器重启已过期")
        if replacement_failure is not None:
            with contextlib.suppress(BaseException):
                await runtime.close()
            try:
                setattr(old, "state", "degraded")
            except Exception:
                pass
            async with self._lock:
                if not self._shutdown_started and self._generation_by_key.get(key) == generation:
                    self._runtimes[key] = old
                    self._record_error_locked(key, old, replacement_failure, record_runtime=False)
            raise replacement_failure
        await self._ensure_maintenance_task()
        return {"restarted": True, **runtime.diagnostics()}

    async def restart_language_server(self, **kwargs: object) -> dict[str, object]:
        """Compatibility alias for callers using the public language-server name."""

        return await self.restart_runtime(**kwargs)  # type: ignore[arg-type]

    async def _get_or_start(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
    ) -> RuntimeProtocol:
        while True:
            stale: list[RuntimeProtocol] = []
            wait_restart: asyncio.Task[None] | None = None
            async with self._lock:
                if self._shutdown_started:
                    raise RuntimeError("语言服务器管理器正在关闭")
                current = self._runtimes.get(key)
                if current is not None:
                    state = self._runtime_state(current)
                    if state in {"ready", "indexing", "starting"}:
                        return current
                    if state == "degraded":
                        raise LanguageServerUnavailableError("语言服务器已降级，请手动重启")
                    wait_restart = self._restart_tasks.get(key)
                    if wait_restart is None:
                        stale.append(current)
                        self._runtimes.pop(key, None)
                task = self._start_tasks.get(key) if wait_restart is None else None
                if wait_restart is None and task is None:
                    stale.extend(self._detach_for_capacity_locked())
                    generation = self._next_generation_locked(key)
                    task = asyncio.create_task(self._start_and_register(key, command, generation))
                    self._start_tasks[key] = task
            if stale:
                await asyncio.gather(*(runtime.close() for runtime in stale), return_exceptions=True)
            if wait_restart is not None:
                await asyncio.shield(wait_restart)
                continue
            if task is not None:
                runtime = await asyncio.shield(task)
                await self._ensure_maintenance_task()
                return runtime

    async def _start_and_register(
        self,
        key: LanguageServerRuntimeKey,
        command: tuple[str, ...],
        generation: int,
    ) -> RuntimeProtocol:
        runtime: RuntimeProtocol | None = None
        try:
            runtime = self._configure_runtime(self._runtime_factory(key, command), generation)
            async with self._lock:
                if self._shutdown_started or self._generation_by_key.get(key) != generation:
                    raise RuntimeError("语言服务器管理器正在关闭")
                self._initializing_runtimes[key] = (generation, runtime)
            await runtime.start()
            if self._runtime_state(runtime) in {"error", "stopped", "degraded"}:
                raise RuntimeError("语言服务器启动后不可用")
            snapshots = self.document_store.snapshot(key)
            replay = getattr(runtime, "replay_documents", None)
            sync = replay if callable(replay) else getattr(runtime, "sync_documents", None)
            if snapshots and callable(sync):
                await sync(snapshots)
            async with self._lock:
                current = self._runtimes.get(key)
                if self._shutdown_started or self._generation_by_key.get(key) != generation:
                    start_error: BaseException | None = RuntimeError("语言服务器管理器正在关闭")
                elif current is runtime and key in self._restart_tasks:
                    start_error = LspJsonRpcClosedError("语言服务器初始化期间传输已失效")
                elif current is not None and current is not runtime:
                    start_error = LspJsonRpcClosedError("语言服务器初始化已被新 generation 替换")
                else:
                    self._runtimes[key] = runtime
                    self._initializing_runtimes.pop(key, None)
                    start_error = None
            if start_error is not None:
                raise start_error
            return runtime
        except BaseException as exc:
            if runtime is not None:
                with contextlib.suppress(BaseException):
                    await runtime.close()
                if not isinstance(exc, asyncio.CancelledError):
                    await self._recover_failed_start(key, runtime, generation, exc)
            raise
        finally:
            async with self._lock:
                candidate = self._initializing_runtimes.get(key)
                if runtime is not None and candidate == (generation, runtime):
                    self._initializing_runtimes.pop(key, None)
                current = self._start_tasks.get(key)
                if current is asyncio.current_task():
                    self._start_tasks.pop(key, None)

    def _detach_for_capacity_locked(self) -> list[RuntimeProtocol]:
        if len(self._runtimes) + len(self._start_tasks) < self.max_runtimes:
            return []
        candidates = [
            runtime
            for runtime in self._runtimes.values()
            if self._runtime_state(runtime) in {"ready", "indexing", "error", "stopped", "degraded"}
            and _runtime_is_idle(runtime)
        ]
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
                if runtime.key not in self._restart_tasks
                and self._runtime_state(runtime) in {"ready", "indexing"}
                and _runtime_is_idle(runtime)
                and now - float(getattr(runtime, "last_used_at", now) or now) >= self.idle_timeout
            ]
            for runtime in stale:
                self._runtimes.pop(runtime.key, None)
        if stale:
            await asyncio.gather(*(runtime.close() for runtime in stale), return_exceptions=True)
        return len(stale)

    def diagnostics(self) -> dict[str, object]:
        runtimes = list(self._runtimes.values())
        runtime_details: list[dict[str, object]] = []
        for runtime in runtimes:
            try:
                runtime_details.append(
                    {
                        "key": {
                            "bot_alias": runtime.key.bot_alias,
                            "user_id": runtime.key.user_id,
                            "workspace_root": str(runtime.key.workspace_root),
                            "provider_id": runtime.key.provider_id,
                        },
                        **self._runtime_diagnostics(runtime),
                    }
                )
            except Exception as exc:
                runtime_details.append({"state": "error", "last_error": str(exc)[:300]})
        states = Counter(str(item.get("state") or "unknown") for item in runtime_details)
        process_count = sum(
            1
            for item in runtime_details
            if isinstance(item.get("process"), Mapping) and bool(item["process"].get("alive"))
        )
        return {
            "enabled": bool(getattr(self.catalog, "enabled", True)),
            "runtime_count": len(runtimes),
            "starting_count": len(self._start_tasks),
            "restarting_count": int(states.get("restarting", 0)),
            "degraded_count": int(states.get("degraded", 0)),
            "restart_pending_count": len(self._restart_tasks),
            "process_count": process_count,
            "active_request_count": sum(len(tasks) for tasks in self._active_requests.values()),
            "active_operation_count": sum(
                int(getattr(runtime, "active_operation_count", 0) or 0)
                for runtime in runtimes
            ),
            "pending_count": sum(int(getattr(runtime, "pending_count", 0) or 0) for runtime in runtimes),
            "open_document_count": sum(int(runtime.diagnostics().get("open_document_count") or 0) for runtime in runtimes),
            "provider_counts": dict(Counter(runtime.key.provider_id for runtime in runtimes)),
            "state_counts": dict(states),
            "restart_count": self._restart_count,
            "crash_count": self._crash_count,
            "restart": {
                "count": self._restart_count,
                "pending_count": len(self._restart_tasks),
                "base_delay_seconds": self.restart_base_delay,
                "max_delay_seconds": self.restart_max_delay,
            },
            "crashes": {
                "count": self._crash_count,
                "window_seconds": self.crash_window_seconds,
                "threshold": self.crash_threshold,
            },
            "recent_errors": list(self._recent_errors),
            "runtimes": runtime_details,
            "document_store": self.document_store.diagnostics(),
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
            return self._runtime_diagnostics(runtime)
        if key in self._restart_tasks:
            return {
                "state": "restarting",
                "generation": int(self._generation_by_key.get(key, 0) or 0),
                "pending_count": 0,
                "open_document_count": 0,
            }
        if key in self._start_tasks:
            return {"state": "starting", "pending_count": 0, "open_document_count": 0}
        return None

    async def shutdown(self) -> dict[str, int]:
        async with self._lock:
            if (
                self._shutdown_started
                and not self._runtimes
                and not self._start_tasks
                and not self._initializing_runtimes
                and not self._replacement_initializing_runtimes
                and not self._restart_tasks
            ):
                return {"requested": 0, "closed": 0, "failed": 0}
            self._shutdown_started = True
            runtimes = list(self._runtimes.values())
            start_tasks = list(self._start_tasks.values())
            restart_tasks = list(self._restart_tasks.values())
            maintenance_task = self._maintenance_task
            self._maintenance_task = None
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
            self._initializing_runtimes.clear()
            self._replacement_initializing_runtimes.clear()
            self._replacement_initialization_failures.clear()
            self._restart_tasks.clear()
            self._active_requests.clear()
            self._cancelled_requests.clear()
            self._generation_by_key.clear()
        for task in active_tasks:
            if not task.done():
                task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        for task in restart_tasks:
            if not task.done():
                task.cancel()
        if restart_tasks:
            await asyncio.gather(*restart_tasks, return_exceptions=True)
        if maintenance_task is not None and not maintenance_task.done():
            maintenance_task.cancel()
            await asyncio.gather(maintenance_task, return_exceptions=True)
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
        self.document_store.clear()
        return report


def _document_source_id(document: Mapping[str, Any]) -> str:
    return str(document.get("sourceId") or document.get("source_id") or "").strip()


def _is_absolute_browser_path(value: str) -> bool:
    path = str(value or "").strip()
    if not path:
        return False
    return Path(path).is_absolute() or PureWindowsPath(path).is_absolute() or path.lower().startswith("file:")


def _reject_absolute_browser_path(value: str) -> None:
    if _is_absolute_browser_path(value):
        raise ValueError("浏览器不能提交绝对路径")


def _provider_for_request(request: Mapping[str, Any]) -> str | None:
    document = request.get("document")
    if not isinstance(document, Mapping):
        raise ValueError("代码导航请求格式无效")
    path = str(document.get("path") or "").strip()
    _reject_absolute_browser_path(path)
    language_id = str(document.get("languageId") or document.get("language_id") or "").strip().lower()
    return _provider_for_document(path, language_id)


def _provider_for_document(path: str, language_id: str = "") -> str | None:
    language_id = str(language_id or "").strip().lower()
    suffix = Path(path).suffix.lower()
    if suffix in {".py", ".pyi"} and language_id in {"", "python", "py"}:
        return "pyright"
    if suffix in {".ts", ".tsx", ".mts", ".cts"} and language_id in {
        "",
        "typescript",
        "typescriptreact",
        "ts",
        "tsx",
    }:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"} and language_id in {
        "",
        "javascript",
        "javascriptreact",
        "js",
        "jsx",
    }:
        return "typescript"
    if suffix in {".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"} and language_id in {
        "",
        "c",
        "cpp",
        "c++",
    }:
        return "clangd"
    return None


def _workspace_path_requires_external_source_id(path: str, provider_id: str) -> bool:
    parts = [part.lower() for part in str(path or "").replace("\\", "/").split("/") if part and part != "."]
    if provider_id == "pyright":
        return bool(parts and parts[0] in {".venv", "venv"}) or any(
            part in {"site-packages", "dist-packages"} for part in parts
        )
    if provider_id == "typescript":
        return any(part in {"node_modules", ".yarn", ".pnp", ".pnpm"} for part in parts)
    return False


def _runtime_sync_kind(runtime: RuntimeProtocol) -> str:
    provider = getattr(runtime, "provider", None)
    return "incremental" if int(getattr(provider, "sync_change_kind", 1) or 0) == 2 else "full"


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
