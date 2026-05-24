from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from bot.debug.models import DebugProfile

from .base import DebugProvider, DebugProviderError, DebugProviderSession
from .dap_client import DapClient


async def _default_adapter_launcher(profile: DebugProfile):
    module = str(
        (
            profile.provider_config.get("dap", {})
            if isinstance(profile.provider_config.get("dap", {}), dict)
            else {}
        ).get("module")
        or "debugpy.adapter"
    )
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=profile.cwd or profile.workspace,
    )


async def _default_dap_client_factory(profile: DebugProfile) -> DapClient:
    process = await _default_adapter_launcher(profile)
    assert process.stdout is not None
    assert process.stdin is not None
    client = DapClient(process.stdout, process.stdin)
    await client.start()
    return client


class _PythonDebugpySession(DebugProviderSession):
    def __init__(
        self,
        profile: DebugProfile,
        *,
        dap_client_factory,
        adapter_launcher,
    ):
        self._profile = profile
        self._dap_client_factory = dap_client_factory
        self._adapter_launcher = adapter_launcher
        self._client: Any | None = None
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._event_task: asyncio.Task[None] | None = None
        self._pending_events: list[dict[str, object]] = []

    def _dap_source_path(self, source: str) -> str:
        candidate = str(source or "").strip()
        if not candidate:
            return candidate
        path = Path(candidate).expanduser()
        if path.is_absolute():
            return str(path.resolve())
        root = Path(self._profile.cwd or self._profile.workspace or ".")
        return str((root / candidate).resolve())

    async def launch(self, payload: dict[str, object]) -> None:
        self._client = await self._create_client()
        await self._client.request("initialize", {"clientID": "tcb-debug", "adapterID": "python"})
        target = self._profile.target
        arguments = {
            "name": self._profile.config_name,
            "type": "python",
            "request": "launch",
            "program": str(payload.get("program") or target.program),
            "cwd": str(payload.get("cwd") or target.cwd),
            "args": list(payload.get("args") or target.args),
            "env": dict(payload.get("env") or target.env),
            "stopOnEntry": bool(payload.get("stopAtEntry", payload.get("stop_at_entry", self._profile.stop_at_entry))),
        }
        launch_task = asyncio.create_task(self._client.request("launch", arguments))
        try:
            await asyncio.sleep(0)
            await self._wait_for_initialized()
            await self._client.request("configurationDone", {})
            await launch_task
        except Exception:
            launch_task.cancel()
            raise
        self._event_task = asyncio.create_task(self._forward_events())

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.request("disconnect", {"terminateDebuggee": True})
            except Exception:
                pass
        await self.close()

    async def continue_execution(self) -> None:
        await self._client.request("continue", {"threadId": 1})

    async def pause(self) -> None:
        await self._client.request("pause", {"threadId": 1})

    async def next(self) -> None:
        await self._client.request("next", {"threadId": 1})

    async def step_in(self) -> None:
        await self._client.request("stepIn", {"threadId": 1})

    async def step_out(self) -> None:
        await self._client.request("stepOut", {"threadId": 1})

    async def set_breakpoints(self, source: str, breakpoints: list[dict[str, object]]) -> list[dict[str, object]]:
        result = await self._client.request(
            "setBreakpoints",
            {
                "source": {"path": self._dap_source_path(source)},
                "breakpoints": [{"line": int(item.get("line") or 0)} for item in breakpoints if int(item.get("line") or 0) > 0],
            },
        )
        return [dict(item) for item in result.get("breakpoints", []) if isinstance(item, dict)]

    async def stack_trace(self) -> list[dict[str, object]]:
        result = await self._client.request("stackTrace", {"threadId": 1})
        frames: list[dict[str, object]] = []
        for item in result.get("stackFrames", []):
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            source_path = str(source.get("path") or "") if isinstance(source, dict) else ""
            source_reference = int(source.get("sourceReference") or 0) if isinstance(source, dict) else 0
            frames.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "source": source_path,
                    "line": int(item.get("line") or 0),
                    "sourceResolved": bool(source_path),
                    "sourceReason": "dap",
                    "originalSource": source_path,
                    "sourceReference": source_reference,
                }
            )
        return frames

    async def scopes(self, frame_id: str) -> list[dict[str, object]]:
        result = await self._client.request("scopes", {"frameId": int(frame_id or 0)})
        items: list[dict[str, object]] = []
        for item in result.get("scopes", []):
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": str(item.get("name") or ""),
                    "variablesReference": str(item.get("variablesReference") or ""),
                }
            )
        return items

    async def variables(self, variables_reference: str) -> list[dict[str, object]]:
        result = await self._client.request("variables", {"variablesReference": int(variables_reference or 0)})
        items: list[dict[str, object]] = []
        for item in result.get("variables", []):
            if not isinstance(item, dict):
                continue
            payload: dict[str, object] = {
                "name": str(item.get("name") or ""),
                "value": str(item.get("value") or ""),
            }
            if item.get("type"):
                payload["type"] = str(item.get("type") or "")
            if item.get("variablesReference"):
                payload["variablesReference"] = str(item.get("variablesReference") or "")
            items.append(payload)
        return items

    async def evaluate(self, expression: str, frame_id: str = "") -> dict[str, object]:
        result = await self._client.request(
            "evaluate",
            {"expression": expression, "frameId": int(frame_id or 0), "context": "repl"},
        )
        return {
            "expression": expression,
            "value": str(result.get("result") or ""),
            "variablesReference": str(result.get("variablesReference") or ""),
        }

    async def events(self) -> AsyncIterator[dict[str, object]]:
        while self._pending_events:
            yield self._pending_events.pop(0)
        while True:
            yield await self._events.get()

    async def close(self) -> None:
        if self._event_task is not None:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
            self._event_task = None
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close is not None:
                await close()
            self._client = None

    async def _create_client(self):
        if self._dap_client_factory is not None:
            client = self._dap_client_factory(self._profile)
            if asyncio.iscoroutine(client):
                client = await client
            start = getattr(client, "start", None)
            if callable(start):
                await start()
            return client
        return await _default_dap_client_factory(self._profile)

    async def _forward_events(self) -> None:
        client = self._client
        if client is None:
            return
        if hasattr(client, "events"):
            async for raw in client.events():
                await self._events.put(self._normalize_event(raw))
            return
        if hasattr(client, "next_event"):
            while True:
                raw = await client.next_event()
                await self._events.put(self._normalize_event(raw))

    async def _wait_for_initialized(self) -> None:
        client = self._client
        if client is None:
            return
        while True:
            if hasattr(client, "next_event"):
                raw = await asyncio.wait_for(client.next_event(), timeout=10)
            else:
                raw = await asyncio.wait_for(client.events().__anext__(), timeout=10)
            event = self._normalize_event(raw)
            if event["type"] == "initialized":
                return
            self._pending_events.append(event)

    def _normalize_event(self, event: dict[str, object]) -> dict[str, object]:
        event_name = str(event.get("event") or event.get("type") or "")
        body = event.get("body") if isinstance(event.get("body"), dict) else {}
        payload = dict(body) if isinstance(body, dict) else {}
        if event_name == "stopped":
            return {
                "type": "stopped",
                "payload": {
                    "reason": str(payload.get("reason") or "unknown"),
                    "threadId": str(payload.get("threadId") or ""),
                    "source": "",
                    "line": 0,
                    "frameId": "",
                },
            }
        if event_name == "continued":
            return {"type": "running", "payload": {}}
        return {"type": event_name, "payload": payload}


class PythonDebugpyProvider(DebugProvider):
    provider_id = "python-debugpy"
    provider_label = "Python debugpy"

    def __init__(self, *, dap_client_factory=None, adapter_launcher=None):
        self._dap_client_factory = dap_client_factory
        self._adapter_launcher = adapter_launcher

    def can_handle(self, profile: DebugProfile) -> bool:
        if profile.provider_id == self.provider_id:
            return True
        return profile.language == "python" and profile.spec_version >= 3

    def create_session(self, profile: DebugProfile) -> _PythonDebugpySession:
        return _PythonDebugpySession(
            profile,
            dap_client_factory=self._dap_client_factory,
            adapter_launcher=self._adapter_launcher,
        )
