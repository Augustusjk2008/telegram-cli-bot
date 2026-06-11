from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceHistoryStatus:
    head: str
    clean: bool
    manual_change_count: int
    degraded: bool = False
    message: str = ""
    locked_file_count: int = 0


class PiWorkspaceHistory:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = max(0.1, float(timeout_seconds or 10.0))

    async def status(self, runtime: Any) -> WorkspaceHistoryStatus:
        return await self._request(runtime, {"action": "status"})

    async def checkpoint(self, runtime: Any, *, label: str) -> WorkspaceHistoryStatus:
        return await self._request(runtime, {"action": "checkpoint", "label": str(label or "")})

    async def rollback(self, runtime: Any, *, target_head: str) -> WorkspaceHistoryStatus:
        return await self._request(runtime, {"action": "rollback", "target_head": str(target_head or "")})

    async def _request(self, runtime: Any, fields: dict[str, Any]) -> WorkspaceHistoryStatus:
        request_id = f"wh_{uuid.uuid4().hex}"
        packet = {"type": "workspace_history", "id": request_id, **fields}
        try:
            await self._send(runtime, packet)
            payload = await asyncio.wait_for(self._wait_result(runtime, request_id), timeout=self.timeout_seconds)
        except TimeoutError:
            return WorkspaceHistoryStatus(head="", clean=False, manual_change_count=0, degraded=True, message="workspace history 响应超时")
        except Exception as exc:
            return WorkspaceHistoryStatus(
                head="",
                clean=False,
                manual_change_count=0,
                degraded=True,
                message=_safe_message(str(exc) or "", default="workspace history 不可用"),
            )
        return self._status_from_payload(payload)

    async def _send(self, runtime: Any, packet: dict[str, Any]) -> None:
        send = getattr(runtime, "send", None)
        if callable(send):
            await send(packet)
            return
        client = getattr(runtime, "client", None)
        client_send = getattr(client, "send", None)
        if callable(client_send):
            await client_send(packet)
            return
        raise RuntimeError("Pi workspace history 插件不可用")

    async def _wait_result(self, runtime: Any, request_id: str) -> dict[str, Any]:
        async for event in runtime.events():
            if not isinstance(event, dict):
                continue
            if str(event.get("type") or "") != "workspace_history_result":
                continue
            if str(event.get("id") or "") != request_id:
                continue
            return event
        raise RuntimeError("Pi workspace history 无响应")

    def _status_from_payload(self, payload: dict[str, Any]) -> WorkspaceHistoryStatus:
        if bool(payload.get("ok", True)) is False or payload.get("error"):
            error = payload.get("error")
            message = ""
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("code") or "")
            else:
                message = str(error or "")
            return WorkspaceHistoryStatus(
                head=str(payload.get("head") or payload.get("current_head") or ""),
                clean=False,
                manual_change_count=_count_value(payload, "manual_change_count", "changed_file_count", "changed_count", "changed_paths", "changed_files", "manual_changes"),
                degraded=True,
                message=_safe_message(message or str(payload.get("message") or ""), default="workspace history 执行失败"),
                locked_file_count=_count_value(payload, "locked_file_count", "locked_count", "locked_files"),
            )

        head = str(payload.get("head") or payload.get("current_head") or payload.get("target_head") or "")
        count = _count_value(payload, "manual_change_count", "changed_file_count", "changed_count", "changed_paths", "changed_files", "manual_changes")
        clean = bool(payload.get("clean", count == 0))
        return WorkspaceHistoryStatus(
            head=head,
            clean=clean,
            manual_change_count=count,
            degraded=bool(payload.get("degraded", False)),
            message=_safe_message(str(payload.get("message") or ""), default=""),
            locked_file_count=_count_value(payload, "locked_file_count", "locked_count", "locked_files"),
        )


def _count_value(payload: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, list):
            return len(value)
        try:
            if value is not None:
                return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _safe_message(message: str, *, default: str) -> str:
    text = str(message or "").strip()
    if not text:
        return default
    lowered = text.lower()
    if any(key in lowered for key in ("changed_files", "changed_paths", "manual_changes", "locked_files", "shadow_git_path")):
        return default
    if ":\\" in text or ":/" in text or "\\\\" in text:
        return default
    return text
