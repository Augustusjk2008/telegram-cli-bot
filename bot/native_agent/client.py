from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, ClientTimeout


class NativeAgentClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeAgentServerRef:
    base_url: str
    password: str = ""


class NativeAgentClient:
    def __init__(self, server: NativeAgentServerRef, *, timeout_seconds: float = 120.0) -> None:
        self.server = server
        self.timeout = ClientTimeout(total=None, sock_connect=10, sock_read=timeout_seconds)

    def _url(self, path: str) -> str:
        return f"{self.server.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.server.password:
            token = base64.b64encode(f":{self.server.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with ClientSession(timeout=self.timeout) as session:
            async with session.request(
                method,
                self._url(path),
                headers=self._headers({"Content-Type": "application/json"} if json_body is not None else None),
                json=json_body,
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    raise NativeAgentClientError(text.strip() or f"HTTP {response.status}")
                if not text.strip():
                    return {}
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise NativeAgentClientError(f"原生 agent 返回了无效 JSON: {exc}") from exc
                return payload if isinstance(payload, dict) else {"data": payload}

    async def health(self) -> dict[str, Any]:
        return await self._request_json("GET", "/global/health")

    async def create_session(self, *, cwd: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if cwd:
            body["directory"] = cwd
            body["cwd"] = cwd
        return await self._request_json("POST", "/session", json_body=body)

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", f"/session/{session_id}/message")
        if isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, dict)]
        if isinstance(payload.get("messages"), list):
            return [item for item in payload["messages"] if isinstance(item, dict)]
        if isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
        return []

    async def prompt_async(self, session_id: str, text: str, *, message_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if message_id:
            body["messageID"] = message_id
            body["message_id"] = message_id
        return await self._request_json("POST", f"/session/{session_id}/prompt_async", json_body=body)

    async def abort(self, session_id: str) -> dict[str, Any]:
        return await self._request_json("POST", f"/session/{session_id}/abort", json_body={})

    async def reply_permission(
        self,
        session_id: str,
        permission_id: str,
        *,
        approved: bool,
        message: str = "",
    ) -> dict[str, Any]:
        body = {
            "permissionID": permission_id,
            "permission_id": permission_id,
            "response": "once" if approved else "reject",
            "approved": approved,
            "message": message,
        }
        return await self._request_json("POST", f"/session/{session_id}/permissions/{permission_id}", json_body=body)

    async def events(self, *, global_events: bool = True) -> AsyncIterator[dict[str, Any]]:
        path = "/global/event" if global_events else "/event"
        async with ClientSession(timeout=ClientTimeout(total=None, sock_connect=10, sock_read=None)) as session:
            async with session.get(self._url(path), headers=self._headers({"Accept": "text/event-stream"})) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise NativeAgentClientError(text.strip() or f"HTTP {response.status}")
                buffer = ""
                async for chunk in response.content.iter_chunked(4096):
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        event = parse_sse_block(block)
                        if event is not None:
                            yield event
                    await asyncio.sleep(0)


def parse_sse_block(block: str) -> dict[str, Any] | None:
    event_name = ""
    data_lines: list[str] = []
    for raw_line in str(block or "").splitlines():
        line = raw_line.rstrip("\r")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        payload = {"data": data}
    if isinstance(payload, dict):
        if event_name and "type" not in payload:
            payload["type"] = event_name
        return payload
    return {"type": event_name or "message", "data": payload}
