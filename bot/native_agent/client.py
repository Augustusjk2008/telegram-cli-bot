from __future__ import annotations

import asyncio
import base64
import json
import uuid
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
    username: str = "opencode"


class NativeAgentClient:
    def __init__(self, server: NativeAgentServerRef, *, timeout_seconds: float = 120.0) -> None:
        self.server = server
        self.timeout = ClientTimeout(total=None, sock_connect=10, sock_read=timeout_seconds)

    def _url(self, path: str) -> str:
        return f"{self.server.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.server.password:
            username = str(self.server.username or "opencode").strip() or "opencode"
            token = base64.b64encode(f"{username}:{self.server.password}".encode("utf-8")).decode("ascii")
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

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._request_json("GET", f"/session/{session_id}")

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", f"/session/{session_id}/message")
        raw_items: list[Any]
        if isinstance(payload.get("data"), list):
            raw_items = payload["data"]
        elif isinstance(payload.get("messages"), list):
            raw_items = payload["messages"]
        elif isinstance(payload.get("items"), list):
            raw_items = payload["items"]
        else:
            raw_items = []
        return [_flatten_message(item) for item in raw_items if isinstance(item, dict)]

    async def prompt_async(
        self,
        session_id: str,
        text: str,
        *,
        message_id: str | None = None,
        model: str | None = None,
        agent: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messageID": str(message_id or f"msg_{uuid.uuid4().hex}"),
            "parts": [{"type": "text", "text": text}],
        }
        if str(model or "").strip():
            body["model"] = str(model).strip()
        if str(agent or "").strip():
            body["agent"] = str(agent).strip()
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

    async def events(
        self,
        *,
        global_events: bool = True,
        ready_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        path = "/global/event" if global_events else "/event"
        async with ClientSession(timeout=ClientTimeout(total=None, sock_connect=10, sock_read=None)) as session:
            async with session.get(self._url(path), headers=self._headers({"Accept": "text/event-stream"})) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise NativeAgentClientError(text.strip() or f"HTTP {response.status}")
                if ready_event is not None:
                    ready_event.set()
                buffer = ""
                async for chunk in response.content.iter_chunked(4096):
                    buffer += chunk.decode("utf-8", errors="replace")
                    buffer = _normalize_sse_newlines(buffer)
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        event = parse_sse_block(block)
                        if event is not None:
                            yield event
                    await asyncio.sleep(0)


def parse_sse_block(block: str) -> dict[str, Any] | None:
    event_name = ""
    data_lines: list[str] = []
    for raw_line in _normalize_sse_newlines(str(block or "")).split("\n"):
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


def _normalize_sse_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _part_text(part: Any) -> str:
    if part is None:
        return ""
    if isinstance(part, str):
        return part
    if isinstance(part, (int, float, bool)):
        return str(part)
    if isinstance(part, list):
        return "".join(_part_text(item) for item in part)
    if not isinstance(part, dict):
        return ""
    for key in ("text", "content", "value", "message", "summary", "delta"):
        value = part.get(key)
        if value is not None:
            text = _part_text(value)
            if text:
                return text
    nested = part.get("part")
    if isinstance(nested, dict):
        return _part_text(nested)
    return ""


def _parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            kind = str(part.get("type") or part.get("kind") or "").strip().lower()
            if kind and kind not in {"text", "assistant_text", "message"}:
                continue
        text = _part_text(part)
        if text:
            texts.append(text)
    return "".join(texts)


def _flatten_message(message: dict[str, Any]) -> dict[str, Any]:
    info = message.get("info") if isinstance(message.get("info"), dict) else {}
    parts = message.get("parts") if isinstance(message.get("parts"), list) else []
    flattened = dict(info)
    flattened.update({key: value for key, value in message.items() if key != "info"})
    if info:
        flattened.setdefault("info", dict(info))
    message_id = (
        flattened.get("id")
        or flattened.get("messageID")
        or flattened.get("message_id")
        or flattened.get("messageId")
        or info.get("id")
        or info.get("messageID")
        or info.get("message_id")
        or info.get("messageId")
    )
    role = flattened.get("role") or info.get("role")
    content = flattened.get("content") or flattened.get("text") or _parts_text(parts)
    if message_id:
        flattened["id"] = str(message_id)
    if role:
        flattened["role"] = str(role)
    flattened["content"] = str(content or "")
    flattened["parts"] = parts
    return flattened
