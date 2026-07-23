"""LSP stdio JSON-RPC transport.

Language servers use JSON-RPC 2.0 messages framed as ``Content-Length``
headers followed by UTF-8 JSON.  This module deliberately owns stdout through
one reader task so concurrent callers can safely share one language-server
process.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

JSON_RPC_VERSION = "2.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_MESSAGE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HEADER_BYTES = 16 * 1024
MAX_PENDING_NOTIFICATIONS = 256
DEFAULT_MAX_NOTIFICATION_HANDLER_TASKS = 32

_MISSING = object()

NotificationHandler = Callable[[str, Any], Awaitable[None] | None]
ServerRequestHandler = Callable[[str, Any], Awaitable[Any] | Any]


class LspJsonRpcError(RuntimeError):
    """Base exception raised by the LSP JSON-RPC transport."""


class LspJsonRpcClosedError(LspJsonRpcError):
    """The language-server transport is no longer usable."""


class LspJsonRpcProtocolError(LspJsonRpcError):
    """The peer emitted an invalid or unsafe JSON-RPC frame."""


class LspJsonRpcTimeoutError(TimeoutError):
    """A request did not receive a response before its deadline."""


class LspJsonRpcResponseError(LspJsonRpcError):
    """The server answered a JSON-RPC request with an error object."""

    def __init__(
        self,
        method: str,
        *,
        code: int | None,
        message: str,
        data: Any = None,
    ) -> None:
        self.method = method
        self.code = code
        self.data = data
        self.message = message
        detail = f"LSP 请求 {method} 失败"
        if code is not None:
            detail += f" ({code})"
        if message:
            detail += f": {message}"
        super().__init__(detail)


class LspJsonRpcServerRequestError(LspJsonRpcError):
    """Lets a server-request callback return a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = int(code)
        self.message = str(message)
        self.data = data
        super().__init__(self.message)


@dataclass
class _PendingRequest:
    method: str
    future: asyncio.Future[Any]


class LspJsonRpcClient:
    """Concurrent JSON-RPC client for one already-started LSP subprocess.

    The caller owns the subprocess lifecycle.  ``shutdown()`` performs the
    LSP protocol handshake (``shutdown`` followed by ``exit``), while
    ``close()`` only releases transport resources unless ``shutdown=True`` is
    explicitly requested.
    """

    def __init__(
        self,
        process: Any,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
        notification_handler: NotificationHandler | None = None,
        server_request_handler: ServerRequestHandler | None = None,
        max_notification_handler_tasks: int = DEFAULT_MAX_NOTIFICATION_HANDLER_TASKS,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必须大于 0")
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes 必须大于 0")
        if max_header_bytes <= 0:
            raise ValueError("max_header_bytes 必须大于 0")
        if max_notification_handler_tasks <= 0:
            raise ValueError("max_notification_handler_tasks 必须大于 0")

        self.process = process
        self._reader = getattr(process, "stdout", None)
        self._writer = getattr(process, "stdin", None)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.max_message_bytes = int(max_message_bytes)
        self.max_header_bytes = int(max_header_bytes)
        self._notification_handler = notification_handler
        self._server_request_handler = server_request_handler
        self._max_notification_handler_tasks = int(max_notification_handler_tasks)

        self._next_request_id = 0
        self._pending: dict[int, _PendingRequest] = {}
        self._writer_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._notification_handler_tasks: set[asyncio.Task[None]] = set()
        self._notification_drop_reported = False
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=MAX_PENDING_NOTIFICATIONS
        )
        self._reader_error: BaseException | None = None
        self._closed = False
        self._closed_event = asyncio.Event()
        self._shutdown_started = False
        self._shutdown_sent = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def start(self, *, _allow_shutdown: bool = False) -> None:
        """Start the sole stdout reader task if it has not started yet."""

        self._ensure_usable(allow_shutdown=_allow_shutdown)
        if self._reader_task is None:
            if self._reader is None:
                raise LspJsonRpcClosedError("语言服务器 stdout 不可用")
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def request(
        self,
        method: str,
        params: Any = _MISSING,
        *,
        timeout_seconds: float | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC request and wait for its matching response.

        On timeout the pending request is removed and a standard
        ``$/cancelRequest`` notification is sent before a timeout exception is
        raised.  ``timeout`` is retained as a concise alias for callers that
        already use that spelling.
        """

        normalized_method = _normalize_method(method)
        effective_timeout = self._resolve_timeout(timeout_seconds, timeout)
        is_shutdown_request = normalized_method == "shutdown"
        await self.start(_allow_shutdown=is_shutdown_request)
        if is_shutdown_request:
            self._begin_shutdown()
        else:
            self._ensure_usable()

        self._next_request_id += 1
        request_id = self._next_request_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(method=normalized_method, future=future)
        message: dict[str, Any] = {
            "jsonrpc": JSON_RPC_VERSION,
            "id": request_id,
            "method": normalized_method,
        }
        if params is not _MISSING:
            message["params"] = params

        try:
            await self._send_message(message, allow_shutdown=is_shutdown_request)
        except asyncio.CancelledError:
            self._discard_pending(request_id, future)
            self._schedule_cancel_request(request_id)
            self._consume_done_future_exception(future)
            raise
        except BaseException:
            self._discard_pending(request_id, future)
            self._consume_done_future_exception(future)
            raise

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            self._discard_pending(request_id, future)
            self._schedule_cancel_request(request_id)
            raise LspJsonRpcTimeoutError(f"LSP 请求 {normalized_method} 响应超时") from exc
        except asyncio.CancelledError:
            self._discard_pending(request_id, future)
            self._schedule_cancel_request(request_id)
            raise
        finally:
            self._discard_pending(request_id, future, cancel=False)

    async def call(
        self,
        method: str,
        params: Any = _MISSING,
        *,
        timeout_seconds: float | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Alias for :meth:`request`."""

        return await self.request(
            method,
            params,
            timeout_seconds=timeout_seconds,
            timeout=timeout,
        )

    async def notify(self, method: str, params: Any = _MISSING) -> None:
        """Send a JSON-RPC notification without allocating a request id."""

        normalized_method = _normalize_method(method)
        is_exit_notification = normalized_method == "exit"
        await self.start(_allow_shutdown=is_exit_notification)
        message: dict[str, Any] = {"jsonrpc": JSON_RPC_VERSION, "method": normalized_method}
        if params is not _MISSING:
            message["params"] = params
        await self._send_message(message, allow_shutdown=is_exit_notification)
        if is_exit_notification:
            self._shutdown_sent = True
            self._closed_event.set()

    async def send_notification(self, method: str, params: Any = _MISSING) -> None:
        """Alias for :meth:`notify`."""

        await self.notify(method, params)

    async def next_notification(self) -> dict[str, Any]:
        """Return the next server notification when no callback is sufficient."""

        if self._closed_event.is_set():
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 连接已关闭")
        notification_task = asyncio.create_task(self._notifications.get())
        close_task = asyncio.create_task(self._closed_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {notification_task, close_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if notification_task in done:
                return notification_task.result()
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 连接已关闭")
        finally:
            for task in (notification_task, close_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(notification_task, close_task, return_exceptions=True)

    async def shutdown(self, *, timeout_seconds: float | None = None) -> None:
        """Perform the normal LSP ``shutdown`` then ``exit`` sequence.

        The ``exit`` notification is attempted even if the shutdown request
        fails or times out, so a well-behaved server still receives its normal
        termination signal.
        """

        if self._closed or self._shutdown_sent:
            return
        async with self._shutdown_lock:
            if self._closed or self._shutdown_sent:
                return
            request_error: BaseException | None = None
            if not self._shutdown_started:
                try:
                    await self.request("shutdown", timeout_seconds=timeout_seconds)
                except Exception as exc:
                    request_error = exc
            try:
                if not self._closed:
                    await self.notify("exit")
            except asyncio.CancelledError:
                raise
            except Exception:
                if request_error is None:
                    raise
            finally:
                self._shutdown_sent = True
                self._closed_event.set()
            if request_error is not None:
                raise request_error

    async def close(
        self,
        *,
        shutdown: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        """Release reader/writer resources and fail outstanding requests.

        The subprocess is intentionally not terminated here: its owning runtime
        decides whether a graceful exit, timeout, or process-tree termination
        is appropriate.  Pass ``shutdown=True`` to send the normal LSP
        handshake before releasing the transport.
        """

        if shutdown and not self._closed:
            try:
                await self.shutdown(timeout_seconds=timeout_seconds)
            finally:
                await self._close_transport(timeout_seconds=timeout_seconds)
            return
        await self._close_transport(timeout_seconds=timeout_seconds)

    async def _close_transport(self, *, timeout_seconds: float | None = None) -> None:
        close_timeout = self._resolve_timeout(timeout_seconds, None)
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._closed_event.set()
            self._fail_pending(LspJsonRpcClosedError("语言服务器 JSON-RPC 连接已关闭"))

            current_task = asyncio.current_task()
            tasks: list[asyncio.Task[Any]] = []
            if self._reader_task is not None and self._reader_task is not current_task:
                self._reader_task.cancel()
                tasks.append(self._reader_task)
            for task in list(self._background_tasks):
                if task is current_task:
                    continue
                task.cancel()
                tasks.append(task)
            self._background_tasks.clear()
            self._notification_handler_tasks.clear()

            close = getattr(self._writer, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
            wait_closed = getattr(self._writer, "wait_closed", None)
            if callable(wait_closed):
                with contextlib.suppress(Exception):
                    result = wait_closed()
                    if inspect.isawaitable(result):
                        await asyncio.wait_for(result, timeout=close_timeout)
            if tasks:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=close_timeout,
                    )

    def _schedule_cancel_request(self, request_id: int) -> None:
        if self._closed or self._reader_error is not None:
            return
        self._track_background_task(self._send_cancel_request(request_id))

    async def _send_cancel_request(self, request_id: int) -> None:
        if self._closed or self._reader_error is not None:
            return
        with contextlib.suppress(Exception):
            await self.start(_allow_shutdown=True)
            await self._send_message(
                {
                    "jsonrpc": JSON_RPC_VERSION,
                    "method": "$/cancelRequest",
                    "params": {"id": request_id},
                },
                allow_shutdown=True,
            )

    async def _send_message(self, message: Mapping[str, Any], *, allow_shutdown: bool = False) -> None:
        self._ensure_usable(allow_shutdown=allow_shutdown)
        if self._writer is None:
            error = LspJsonRpcClosedError("语言服务器 stdin 不可用")
            self._mark_transport_failed(error)
            raise error
        try:
            payload = json.dumps(
                dict(message),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise LspJsonRpcProtocolError(f"LSP JSON-RPC 消息无法编码: {exc}") from exc
        if len(payload) > self.max_message_bytes:
            raise LspJsonRpcProtocolError(
                f"LSP JSON-RPC 消息超过 {self.max_message_bytes} 字节限制"
            )
        frame = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        async with self._writer_lock:
            self._ensure_usable(allow_shutdown=allow_shutdown)
            if getattr(self.process, "returncode", None) is not None:
                error = LspJsonRpcClosedError("语言服务器进程已退出，无法写入")
                self._mark_transport_failed(error)
                raise error
            try:
                self._writer.write(frame)
                result = self._writer.drain()
                if inspect.isawaitable(result):
                    try:
                        await asyncio.wait_for(
                            self._await_drain_or_close(result),
                            timeout=self.request_timeout_seconds,
                        )
                    except asyncio.TimeoutError as exc:
                        raise LspJsonRpcTimeoutError("LSP JSON-RPC 写入超时") from exc
            except LspJsonRpcTimeoutError:
                raise
            except (BrokenPipeError, ConnectionError, OSError, ValueError) as exc:
                error = LspJsonRpcClosedError("语言服务器 stdin 写入失败")
                self._mark_transport_failed(error)
                raise error from exc

    async def _await_drain_or_close(self, result: Awaitable[Any]) -> None:
        drain_task = asyncio.ensure_future(result)
        close_task = asyncio.create_task(self._closed_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {drain_task, close_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if drain_task in done:
                await drain_task
                return
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 连接已关闭")
        finally:
            for task in (drain_task, close_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(drain_task, close_task, return_exceptions=True)

    async def _reader_loop(self) -> None:
        try:
            while not self._closed:
                message = await self._read_message()
                if message is None:
                    raise LspJsonRpcClosedError("语言服务器 stdout 已关闭")
                self._handle_message(message)
        except asyncio.CancelledError:
            if not self._closed:
                error = LspJsonRpcClosedError("语言服务器 JSON-RPC reader 已取消")
                self._mark_transport_failed(error)
            raise
        except Exception as exc:
            self._mark_transport_failed(exc)

    async def _read_message(self) -> dict[str, Any] | None:
        headers = await self._read_headers()
        if headers is None:
            return None
        content_length_text = headers.get("content-length")
        if content_length_text is None:
            raise LspJsonRpcProtocolError("LSP JSON-RPC 帧缺少 Content-Length")
        if not content_length_text.isdecimal():
            raise LspJsonRpcProtocolError("LSP JSON-RPC Content-Length 非法")
        content_length = int(content_length_text)
        if content_length <= 0:
            raise LspJsonRpcProtocolError("LSP JSON-RPC Content-Length 必须大于 0")
        if content_length > self.max_message_bytes:
            raise LspJsonRpcProtocolError(
                f"LSP JSON-RPC 消息超过 {self.max_message_bytes} 字节限制"
            )
        try:
            payload = await self._reader.readexactly(content_length)
        except asyncio.IncompleteReadError as exc:
            raise LspJsonRpcProtocolError("LSP JSON-RPC 消息体不完整") from exc
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LspJsonRpcProtocolError(f"LSP JSON-RPC 消息不是有效 UTF-8 JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise LspJsonRpcProtocolError("LSP JSON-RPC 消息必须是对象")
        if message.get("jsonrpc") != JSON_RPC_VERSION:
            raise LspJsonRpcProtocolError("LSP JSON-RPC 版本必须为 2.0")
        return message

    async def _read_headers(self) -> dict[str, str] | None:
        if self._reader is None:
            raise LspJsonRpcClosedError("语言服务器 stdout 不可用")
        headers: dict[str, str] = {}
        header_bytes = 0
        saw_any = False
        while True:
            line = await self._read_header_line(self.max_header_bytes - header_bytes)
            if line is None:
                if not saw_any:
                    return None
                raise LspJsonRpcProtocolError("LSP JSON-RPC 头部不完整")
            header_bytes += len(line)
            if line in (b"\r\n", b"\n"):
                if not saw_any:
                    raise LspJsonRpcProtocolError("LSP JSON-RPC 帧头为空")
                return headers
            saw_any = True
            try:
                decoded = line.rstrip(b"\r\n").decode("ascii")
            except UnicodeDecodeError as exc:
                raise LspJsonRpcProtocolError("LSP JSON-RPC 头部必须为 ASCII") from exc
            key, separator, value = decoded.partition(":")
            normalized_key = key.strip().lower()
            if not separator or not normalized_key:
                raise LspJsonRpcProtocolError("LSP JSON-RPC 头部格式非法")
            if normalized_key in headers:
                raise LspJsonRpcProtocolError(f"LSP JSON-RPC 头部重复: {normalized_key}")
            headers[normalized_key] = value.strip()

    async def _read_header_line(self, remaining: int) -> bytes | None:
        if remaining <= 0:
            raise LspJsonRpcProtocolError(
                f"LSP JSON-RPC 头部超过 {self.max_header_bytes} 字节限制"
            )
        line = bytearray()
        while True:
            chunk = await self._reader.read(1)
            if not chunk:
                return None if not line else bytes(line)
            line.extend(chunk)
            if len(line) > remaining:
                raise LspJsonRpcProtocolError(
                    f"LSP JSON-RPC 头部超过 {self.max_header_bytes} 字节限制"
                )
            if chunk == b"\n":
                return bytes(line)

    def _handle_message(self, message: dict[str, Any]) -> None:
        if "method" in message:
            method = message["method"]
            if not isinstance(method, str) or not method:
                raise LspJsonRpcProtocolError("LSP JSON-RPC method 必须是非空字符串")
            if "id" in message and message.get("id") is not None:
                request_id = message["id"]
                if not _is_valid_server_request_id(request_id):
                    raise LspJsonRpcProtocolError("LSP 服务端请求 id 非法")
                self._track_background_task(
                    self._handle_server_request(request_id, method, message.get("params"))
                )
                return
            notification = {"method": method}
            if "params" in message:
                notification["params"] = message["params"]
            if self._notification_handler is None:
                try:
                    self._notifications.put_nowait(notification)
                except asyncio.QueueFull:
                    logger.warning("语言服务器通知队列已满，已丢弃通知: %s", method)
            else:
                if len(self._notification_handler_tasks) >= self._max_notification_handler_tasks:
                    if not self._notification_drop_reported:
                        logger.warning("语言服务器通知处理任务已满，已丢弃后续通知")
                        self._notification_drop_reported = True
                else:
                    self._notification_drop_reported = False
                    task = self._track_background_task(
                        self._call_notification_handler(method, message.get("params"))
                    )
                    self._notification_handler_tasks.add(task)
                    task.add_done_callback(self._notification_handler_tasks.discard)
            return

        if "id" not in message:
            raise LspJsonRpcProtocolError("LSP JSON-RPC 消息既非请求也非响应")
        response_id = message.get("id")
        if not isinstance(response_id, int) or isinstance(response_id, bool):
            return
        pending = self._pending.get(response_id)
        if pending is None or pending.future.done():
            return
        if "error" in message:
            error = message["error"]
            if not isinstance(error, Mapping):
                pending.future.set_exception(LspJsonRpcProtocolError("LSP JSON-RPC error 必须是对象"))
                return
            raw_code = error.get("code")
            code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
            pending.future.set_exception(
                LspJsonRpcResponseError(
                    pending.method,
                    code=code,
                    message=str(error.get("message") or "语言服务器返回错误"),
                    data=error.get("data"),
                )
            )
            return
        if "result" not in message:
            pending.future.set_exception(LspJsonRpcProtocolError("LSP JSON-RPC 响应缺少 result 或 error"))
            return
        pending.future.set_result(message["result"])

    async def _call_notification_handler(self, method: str, params: Any) -> None:
        try:
            result = self._notification_handler(method, params)  # type: ignore[misc]
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("语言服务器通知处理失败: %s", method)

    async def _handle_server_request(self, request_id: Any, method: str, params: Any) -> None:
        try:
            if self._server_request_handler is not None:
                result = self._server_request_handler(method, params)
                if inspect.isawaitable(result):
                    result = await result
            else:
                result = _default_server_request_result(method, params)
        except asyncio.CancelledError:
            raise
        except LspJsonRpcServerRequestError as exc:
            await self._send_server_error(request_id, exc.code, exc.message, exc.data)
            return
        except Exception:
            logger.exception("语言服务器请求处理失败: %s", method)
            await self._send_server_error(request_id, -32603, "客户端处理服务端请求失败")
            return
        try:
            await self._send_message({"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": result})
        except LspJsonRpcClosedError:
            return

    async def _send_server_error(self, request_id: Any, code: int, message: str, data: Any = _MISSING) -> None:
        error: dict[str, Any] = {"code": int(code), "message": str(message)}
        if data is not _MISSING:
            error["data"] = data
        try:
            await self._send_message({"jsonrpc": JSON_RPC_VERSION, "id": request_id, "error": error})
        except LspJsonRpcClosedError:
            return

    def _track_background_task(self, coroutine: Awaitable[None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._finish_background_task)
        return task

    def _finish_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("语言服务器后台 JSON-RPC 任务失败")

    def _discard_pending(self, request_id: int, future: asyncio.Future[Any], *, cancel: bool = True) -> None:
        pending = self._pending.get(request_id)
        if pending is not None and pending.future is future:
            self._pending.pop(request_id, None)
        if cancel and not future.done():
            future.cancel()

    @staticmethod
    def _consume_done_future_exception(future: asyncio.Future[Any]) -> None:
        if future.done() and not future.cancelled():
            with contextlib.suppress(Exception):
                future.exception()

    def _fail_pending(self, error: BaseException) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_exception(error)

    def _mark_transport_failed(self, error: BaseException) -> None:
        if self._reader_error is None:
            self._reader_error = error
        self._closed_event.set()
        self._fail_pending(error)

    def _ensure_usable(self, *, allow_shutdown: bool = False) -> None:
        if self._closed:
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 连接已关闭")
        if self._reader_error is not None:
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC reader 已停止") from self._reader_error
        if self._shutdown_sent or (self._shutdown_started and not allow_shutdown):
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 正在或已经关闭")

    def _begin_shutdown(self) -> None:
        if self._shutdown_started or self._shutdown_sent:
            raise LspJsonRpcClosedError("语言服务器 JSON-RPC 已开始关闭")
        self._shutdown_started = True

    def _resolve_timeout(self, timeout_seconds: float | None, timeout: float | None) -> float:
        if timeout_seconds is not None and timeout is not None:
            raise ValueError("timeout_seconds 与 timeout 不能同时指定")
        value = self.request_timeout_seconds if timeout_seconds is None and timeout is None else (
            timeout_seconds if timeout_seconds is not None else timeout
        )
        if value is None or value <= 0:
            raise ValueError("请求超时必须大于 0")
        return float(value)


def _normalize_method(method: str) -> str:
    if not isinstance(method, str):
        raise ValueError("LSP JSON-RPC method 必须是字符串")
    normalized = method.strip()
    if not normalized:
        raise ValueError("LSP JSON-RPC method 不能为空")
    return normalized


def _is_valid_server_request_id(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _default_server_request_result(method: str, params: Any) -> Any:
    if method == "workspace/configuration":
        items = params.get("items") if isinstance(params, Mapping) else None
        return [None for _item in items] if isinstance(items, list) else []
    if method == "workspace/workspaceFolders":
        return []
    if method == "workspace/applyEdit":
        return {"applied": False}
    if method == "window/showDocument":
        return {"success": False}
    if method in {
        "client/registerCapability",
        "client/unregisterCapability",
        "window/workDoneProgress/create",
        "window/showMessageRequest",
    }:
        return None
    raise LspJsonRpcServerRequestError(-32601, f"客户端不支持服务端请求: {method}")


__all__ = [
    "DEFAULT_MAX_HEADER_BYTES",
    "DEFAULT_MAX_MESSAGE_BYTES",
    "DEFAULT_MAX_NOTIFICATION_HANDLER_TASKS",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "LspJsonRpcClient",
    "LspJsonRpcClosedError",
    "LspJsonRpcError",
    "LspJsonRpcProtocolError",
    "LspJsonRpcResponseError",
    "LspJsonRpcServerRequestError",
    "LspJsonRpcTimeoutError",
]
