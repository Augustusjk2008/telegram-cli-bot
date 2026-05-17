from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class DapClient:
    def __init__(self, reader: asyncio.StreamReader, writer: Any):
        self._reader = reader
        self._writer = writer
        self._request_seq = 0
        self._pending: dict[int, asyncio.Future[dict[str, object]]] = {}
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop())

    async def request(self, command: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self._request_seq += 1
        seq = self._request_seq
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[seq] = future
        body = {
            "seq": seq,
            "type": "request",
            "command": command,
            "arguments": dict(arguments or {}),
        }
        payload = json.dumps(body).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        self._writer.write(header + payload)
        await self._writer.drain()
        return await future

    async def events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self._events.get()

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        close = getattr(self._writer, "close", None)
        if callable(close):
            close()
        wait_closed = getattr(self._writer, "wait_closed", None)
        if callable(wait_closed):
            await wait_closed()

    async def _read_loop(self) -> None:
        while True:
            headers = await self._read_headers()
            content_length = int(headers.get("content-length", "0") or "0")
            if content_length <= 0:
                continue
            payload = await self._reader.readexactly(content_length)
            message = json.loads(payload.decode("utf-8"))
            if not isinstance(message, dict):
                continue
            message_type = str(message.get("type") or "")
            if message_type == "response":
                request_seq = int(message.get("request_seq") or 0)
                future = self._pending.pop(request_seq, None)
                if future is None or future.done():
                    continue
                if not bool(message.get("success", True)):
                    future.set_exception(RuntimeError(str(message.get("message") or "DAP request failed")))
                    continue
                body = message.get("body")
                future.set_result(dict(body) if isinstance(body, dict) else {})
                continue
            if message_type == "event":
                await self._events.put(message)

    async def _read_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if not line:
                raise asyncio.CancelledError()
            decoded = line.decode("ascii", errors="ignore").strip()
            if not decoded:
                return headers
            key, _, value = decoded.partition(":")
            headers[key.strip().lower()] = value.strip()
