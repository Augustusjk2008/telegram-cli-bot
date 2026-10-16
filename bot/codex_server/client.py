"""Bounded JSON-line app-server transport, including Windows Selector loops."""
from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import re
import subprocess
import threading
from typing import Any

from bot.cli_params import get_cli_output_limits
from bot.platform.processes import (
    attach_process_tree,
    build_chat_cli_process_kwargs,
    resume_suspended_process,
)
from bot.platform.subprocess_streams import close_process_streams


class CodexServerError(RuntimeError):
    """A protocol/transport failure; requests with unknown outcomes are not retried."""


class CodexServerUnknownOutcome(CodexServerError):
    """A realtime control request timed out; the shared runtime remains usable."""

APP_SERVER_VERSION = "0.160.0"  # Minimum supported CLI version and protocol baseline.
REALTIME_CONVERSATION_VERSION = "v3"


def noninteractive_response(method: str) -> dict[str, Any]:
    """Responses verified against the locally generated 0.160.0 JSON schemas."""
    if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
        return {"result": {"decision": "decline"}}
    if method in {"execCommandApproval", "applyPatchApproval"}:
        return {"result": {"decision": {"denied": {"rejection": "Non-interactive client cannot approve this request"}}}}
    if method == "item/permissions/requestApproval":
        return {"result": {"permissions": {}, "scope": "turn"}}
    if method == "item/tool/requestUserInput":
        return {"result": {"answers": {}}}
    if method == "mcpServer/elicitation/request":
        return {"result": {"action": "decline"}}
    if method == "item/tool/call":
        return {"result": {"success": False, "contentItems": [
            {"type": "inputText", "text": "Client-side dynamic tools are unavailable in this non-interactive client."}
        ]}}
    return {"error": {"code": -32601, "message": f"Non-interactive client does not support {method}"}}


class CodexServerClient:
    def __init__(self, process: subprocess.Popen, process_tree: Any, *, env: dict[str, str], timeout: float = 30):
        self.process = process
        self.process_tree = process_tree
        self.timeout = timeout
        self.limits = get_cli_output_limits(env)
        self._packets: queue.Queue = queue.Queue(maxsize=self.limits.queue_max_chunks)
        self._events: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._pending: dict[int, asyncio.Future] = {}
        self._sequence = 0
        self._write_lock = asyncio.Lock()
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._failure: CodexServerError | None = None
        self._stderr = b""
        self._events_claimed = False
        self._threads = [
            threading.Thread(target=self._read_stdout, name="codex-server-stdout", daemon=True),
            threading.Thread(target=self._read_stderr, name="codex-server-stderr", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._dispatcher = asyncio.create_task(self._dispatch(), name="codex-server-dispatch")

    @classmethod
    async def start(cls, argv: list[str], *, cwd: str, env: dict[str, str], timeout: float = 30,
                    experimental_api: bool = False):
        process = None
        tree = None
        try:
            # Launch suspended on Windows so children cannot escape before Job assignment.
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       **build_chat_cli_process_kwargs(suspended=True))
            tree = attach_process_tree(process)
            resume_suspended_process(process, tree)
        except Exception as exc:
            if tree is not None:
                tree.terminate()
                tree.close()
            if process is not None:
                close_process_streams(process)
            raise CodexServerError(f"codex app-server 启动失败: {exc}") from exc
        client = cls(process, tree, env=env, timeout=timeout)
        try:
            result = await client.request("initialize", {
                "clientInfo": {"name": "orbit_safe_claw", "title": "Orbit Safe Claw", "version": "1.0"},
                "capabilities": {"experimentalApi": experimental_api},
            })
            user_agent = result.get("userAgent")
            version = (
                re.match(r"[^/\s]+/(\d+)\.(\d+)\.(\d+)(?:\b|\s|$)", user_agent)
                if isinstance(user_agent, str) else None
            )
            if version is None or tuple(map(int, version.groups())) < tuple(map(int, APP_SERVER_VERSION.split("."))):
                raise CodexServerError(f"不兼容的 app-server initialize 响应（最低版本 {APP_SERVER_VERSION}）")
            await client.notify("initialized")
            return client
        except BaseException:
            await client.close()
            raise

    @property
    def alive(self) -> bool:
        return not self._closed and self._failure is None and self.process.poll() is None

    @property
    def stderr(self) -> str:
        return self._stderr.decode("utf-8", errors="replace")

    def _put_packet(self, packet: Any) -> None:
        while not self._stop.is_set():
            try:
                self._packets.put(packet, timeout=0.1)
                return
            except queue.Full:
                pass

    def _read_stdout(self) -> None:
        try:
            while not self._stop.is_set():
                raw = self.process.stdout.readline(self.limits.max_line_bytes + 1)
                if not raw:
                    raise CodexServerError("codex app-server stdout 已关闭")
                if len(raw) > self.limits.max_line_bytes:
                    raise CodexServerError("codex app-server 单行输出超过限制")
                if not raw.strip():
                    continue
                packet = json.loads(raw)
                if not isinstance(packet, dict):
                    raise ValueError("packet must be an object")
                self._put_packet(packet)
        except Exception as exc:
            self._put_packet(CodexServerError(f"codex app-server 协议读取失败: {exc}"))

    def _read_stderr(self) -> None:
        try:
            while not self._stop.is_set():
                raw = self.process.stderr.read1(4096)
                if not raw:
                    break
                self._stderr = (self._stderr + raw)[-self.limits.raw_tail_max_bytes:]
        except (OSError, ValueError):
            pass

    def _fail(self, exc: CodexServerError) -> None:
        if self._failure is not None:
            return
        self._failure = exc
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        with contextlib.suppress(asyncio.QueueFull):
            self._events.put_nowait(None)

    async def _dispatch(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    packet = await asyncio.to_thread(self._packets.get, True, 0.1)
                except queue.Empty:
                    continue
                if isinstance(packet, Exception):
                    raise packet
                method = packet.get("method")
                if method and "id" in packet:
                    await self._write({"id": packet["id"], **noninteractive_response(method)})
                elif method:
                    # Keep the notification queue bounded, but let the single
                    # events reader drain a burst before declaring the shared
                    # app-server runtime failed. A burst of realtime transcript
                    # and tool events is expected while the persistence layer is
                    # flushing each event.
                    await self._events.put(packet)
                elif "id" in packet:
                    future = self._pending.get(packet["id"])
                    if future is not None and not future.done():
                        if "error" in packet:
                            error = packet["error"]
                            future.set_exception(CodexServerError(
                                f"app-server 请求失败（协议基准 {APP_SERVER_VERSION}）: {error}"
                            ))
                        elif isinstance(packet.get("result"), dict):
                            future.set_result(packet["result"])
                        else:
                            future.set_exception(CodexServerError("app-server 响应缺少 result 对象"))
                else:
                    raise CodexServerError("不兼容的 app-server JSON packet")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc if isinstance(exc, CodexServerError) else CodexServerError(str(exc)))
            await asyncio.to_thread(self.close_sync)

    async def _write(self, packet: dict[str, Any]) -> None:
        if not self.alive:
            raise self._failure or CodexServerError("codex app-server 已关闭")
        data = (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > self.limits.max_line_bytes:
            raise CodexServerError("codex app-server 请求超过单行限制")
        def write():
            self.process.stdin.write(data)
            self.process.stdin.flush()
        try:
            async with self._write_lock:
                await asyncio.wait_for(asyncio.to_thread(write), self.timeout)
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            failure = CodexServerError(f"codex app-server 写入失败: {exc}")
            self._fail(failure)
            await asyncio.to_thread(self.close_sync)
            raise failure from exc

    async def request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> dict:
        if len(self._pending) >= 128:
            raise CodexServerError("codex app-server 未完成请求过多")
        self._sequence += 1
        request_id = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, self.timeout if timeout is None else timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if method in {"thread/realtime/start", "thread/realtime/stop"}:
                # Realtime control must never cancel an independent turn or kill
                # the shared process. A late response is discarded, never retried.
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise CodexServerUnknownOutcome("语音请求结果未知，不会重发") from exc
            # An accepted request may already have changed files. Never retry it.
            self._fail(CodexServerError(f"app-server {method} 超时或取消；请求结果未知，不会重发"))
            await self.close()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise self._failure from exc
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def notify(self, method: str) -> None:
        await self._write({"method": method})

    async def events(self):
        if self._events_claimed:
            raise CodexServerError("app-server events() 只能由一个 reader 消费")
        self._events_claimed = True
        while True:
            if self._events.empty() and self._failure is not None:
                raise self._failure
            packet = await self._events.get()
            if packet is None:
                raise self._failure or CodexServerError("codex app-server 已关闭")
            yield packet

    def close_sync(self) -> None:
        """Only touches the process tree created by this client; also works after loop exit."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            self.process_tree.terminate()
            self.process_tree.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=3)
            for thread in self._threads:
                thread.join(timeout=1)
            close_process_streams(self.process)

    async def close(self) -> None:
        self._fail(CodexServerError("codex app-server 已关闭"))
        await asyncio.to_thread(self.close_sync)
        if self._dispatcher is not asyncio.current_task():
            self._dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatcher
