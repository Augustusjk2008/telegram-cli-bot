from __future__ import annotations

import asyncio
import contextlib
import shlex
import sys
from collections.abc import AsyncIterator
from typing import Any

from bot.debug.models import DebugProfile

from .base import DebugProvider, DebugProviderError, DebugProviderSession
from .dap_client import DapClient


def _config_dict(profile: DebugProfile) -> dict[str, object]:
    raw = profile.provider_config.get("godot")
    return dict(raw) if isinstance(raw, dict) else {}


def _first_string(*values: object, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_value(value: object, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _split_options(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    return shlex.split(value, posix=sys.platform != "win32")


async def _default_process_launcher(command: list[str], *, cwd: str, env: dict[str, str]):
    return await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or None,
        env=env or None,
    )


async def _default_dap_client_factory(_profile: DebugProfile, host: str, port: int) -> DapClient:
    reader, writer = await asyncio.open_connection(host, port)
    return DapClient(reader, writer)


class _GodotSession(DebugProviderSession):
    def __init__(
        self,
        profile: DebugProfile,
        *,
        process_launcher=None,
        dap_client_factory=None,
    ):
        self._profile = profile
        self._process_launcher = process_launcher or _default_process_launcher
        self._dap_client_factory = dap_client_factory or _default_dap_client_factory
        self._process: Any | None = None
        self._client: Any | None = None
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._pending_events: list[dict[str, object]] = []

    async def launch(self, payload: dict[str, object]) -> None:
        config = _config_dict(self._profile)
        connect_dap = _bool_value(payload.get("connectDap", config.get("connectDap")), False)
        launch_process = _bool_value(payload.get("launchProcess", config.get("launchProcess")), not connect_dap)
        if launch_process:
            await self._launch_process(payload, config)
        if connect_dap:
            await self._connect_dap(payload, config)

    async def stop(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.request("disconnect", {"terminateDebuggee": True})
        await self.close()

    async def continue_execution(self) -> None:
        await self._require_client().request("continue", {"threadId": 1})

    async def pause(self) -> None:
        await self._require_client().request("pause", {"threadId": 1})

    async def next(self) -> None:
        await self._require_client().request("next", {"threadId": 1})

    async def step_in(self) -> None:
        await self._require_client().request("stepIn", {"threadId": 1})

    async def step_out(self) -> None:
        await self._require_client().request("stepOut", {"threadId": 1})

    async def set_breakpoints(self, source: str, breakpoints: list[dict[str, object]]) -> list[dict[str, object]]:
        client = self._client
        if client is None:
            return [
                {
                    "source": source,
                    "line": int(item.get("line") or 0),
                    "verified": False,
                    "status": "rejected",
                    "message": "Godot DAP 未连接",
                }
                for item in breakpoints
                if int(item.get("line") or 0) > 0
            ]
        result = await client.request(
            "setBreakpoints",
            {
                "source": {"path": source},
                "breakpoints": [{"line": int(item.get("line") or 0)} for item in breakpoints if int(item.get("line") or 0) > 0],
            },
        )
        return [dict(item) for item in result.get("breakpoints", []) if isinstance(item, dict)]

    async def stack_trace(self) -> list[dict[str, object]]:
        result = await self._require_client().request("stackTrace", {"threadId": 1})
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
        result = await self._require_client().request("scopes", {"frameId": int(frame_id or 0)})
        items: list[dict[str, object]] = []
        for item in result.get("scopes", []):
            if isinstance(item, dict):
                items.append({"name": str(item.get("name") or ""), "variablesReference": str(item.get("variablesReference") or "")})
        return items

    async def variables(self, variables_reference: str) -> list[dict[str, object]]:
        result = await self._require_client().request("variables", {"variablesReference": int(variables_reference or 0)})
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
        result = await self._require_client().request(
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
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                await close()
            self._client = None
        process = self._process
        self._process = None
        if process is not None and getattr(process, "returncode", None) is None:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=3)
            if getattr(process, "returncode", None) is None:
                kill = getattr(process, "kill", None)
                if callable(kill):
                    kill()
                with contextlib.suppress(Exception):
                    await process.wait()

    async def _launch_process(self, payload: dict[str, object], config: dict[str, object]) -> None:
        command = self._build_command(payload, config)
        cwd = _first_string(payload.get("cwd"), self._profile.target.cwd, self._profile.cwd, self._profile.workspace)
        env = dict(self._profile.target.env)
        if isinstance(payload.get("env"), dict):
            env.update({str(key): str(value) for key, value in dict(payload.get("env")).items()})
        try:
            self._process = await self._process_launcher(command, cwd=cwd, env=env)
        except FileNotFoundError as exc:
            raise DebugProviderError("godot_not_found", f"未找到 Godot 可执行文件: {command[0]}") from exc
        except Exception as exc:
            raise DebugProviderError("godot_launch_failed", str(exc)) from exc
        stdout = getattr(self._process, "stdout", None)
        stderr = getattr(self._process, "stderr", None)
        if stdout is not None:
            self._tasks.append(asyncio.create_task(self._forward_stream(stdout, "stdout")))
        if stderr is not None:
            self._tasks.append(asyncio.create_task(self._forward_stream(stderr, "stderr")))
        self._tasks.append(asyncio.create_task(self._wait_process()))

    async def _connect_dap(self, payload: dict[str, object], config: dict[str, object]) -> None:
        host = _first_string(payload.get("dapHost"), payload.get("address"), config.get("dapHost"), config.get("address"), default="127.0.0.1")
        port = _int_value(payload.get("dapPort", payload.get("debugServer", config.get("dapPort", config.get("debugServer")))), 6006)
        game_port = _int_value(payload.get("gamePort", payload.get("port", config.get("gamePort", config.get("port")))), 6007)
        try:
            client = self._dap_client_factory(self._profile, host, port)
            if asyncio.iscoroutine(client):
                client = await client
            start = getattr(client, "start", None)
            if callable(start):
                await start()
            self._client = client
        except Exception as exc:
            raise DebugProviderError(
                "godot_dap_connect_failed",
                f"无法连接 Godot DAP: {host}:{port}",
                data={"detail": str(exc)},
            ) from exc
        await self._client.request("initialize", {"clientID": "tcb-debug", "adapterID": "godot"})
        arguments = {
            "name": self._profile.config_name,
            "type": "godot",
            "request": "launch",
            "project": _first_string(payload.get("project"), config.get("project"), default=self._profile.workspace),
            "address": _first_string(payload.get("address"), config.get("address"), default="127.0.0.1"),
            "port": game_port,
        }
        scene = _first_string(payload.get("scene"), config.get("scene"))
        if scene:
            arguments["scene"] = scene
        launch_task = asyncio.create_task(self._client.request("launch", arguments))
        try:
            await asyncio.sleep(0)
            await self._wait_for_initialized()
            await self._client.request("configurationDone", {})
            await launch_task
        except Exception:
            launch_task.cancel()
            raise
        self._tasks.append(asyncio.create_task(self._forward_dap_events()))

    def _build_command(self, payload: dict[str, object], config: dict[str, object]) -> list[str]:
        program = _first_string(payload.get("program"), self._profile.target.program, self._profile.program, default="godot")
        project = _first_string(payload.get("project"), config.get("project"), default=self._profile.workspace)
        command = [program, "--path", project, "-d"]
        remote_debug = _first_string(payload.get("remoteDebug"), config.get("remoteDebug"))
        if remote_debug:
            command.extend(["--remote-debug", remote_debug])
        flag_map = [
            ("headless", "--headless"),
            ("singleThreadedScene", "--single-threaded-scene"),
            ("debugCollisions", "--debug-collisions"),
            ("debugPaths", "--debug-paths"),
            ("debugNavigation", "--debug-navigation"),
            ("debugAvoidance", "--debug-avoidance"),
            ("debugStringNames", "--debug-stringnames"),
            ("disableVsync", "--disable-vsync"),
        ]
        for key, flag in flag_map:
            if _bool_value(payload.get(key, config.get(key)), False):
                command.append(flag)
        value_flags = [
            ("frameDelay", "--frame-delay"),
            ("timeScale", "--time-scale"),
            ("fixedFps", "--fixed-fps"),
            ("maxFps", "--max-fps"),
            ("logFile", "--log-file"),
        ]
        for key, flag in value_flags:
            value = payload.get(key, config.get(key))
            if value not in (None, ""):
                command.extend([flag, str(value)])
        command.extend(_split_options(payload.get("additionalOptions", config.get("additionalOptions"))))
        scene = _first_string(payload.get("scene"), config.get("scene"))
        if scene:
            command.append(scene)
        return command

    async def _forward_stream(self, stream, category: str) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                await self._events.put({"type": "output", "payload": {"category": category, "output": text, "line": text}})

    async def _wait_process(self) -> None:
        process = self._process
        if process is None:
            return
        exit_code = await process.wait()
        await self._events.put({"type": "terminated", "payload": {"exitCode": int(exit_code or 0)}})

    async def _forward_dap_events(self) -> None:
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
        if event_name == "output":
            return {"type": "output", "payload": payload}
        if event_name == "terminated":
            return {"type": "terminated", "payload": payload}
        return {"type": event_name, "payload": payload}

    def _require_client(self):
        if self._client is None:
            raise DebugProviderError("godot_dap_not_connected", "Godot DAP 未连接")
        return self._client


class GodotProvider(DebugProvider):
    provider_id = "godot"
    provider_label = "Godot"

    def __init__(self, *, process_launcher=None, dap_client_factory=None):
        self._process_launcher = process_launcher
        self._dap_client_factory = dap_client_factory

    def can_handle(self, profile: DebugProfile) -> bool:
        if profile.provider_id == self.provider_id:
            return True
        return profile.language in {"gdscript", "godot"} or profile.kind == "godot"

    def create_session(self, profile: DebugProfile) -> _GodotSession:
        return _GodotSession(
            profile,
            process_launcher=self._process_launcher,
            dap_client_factory=self._dap_client_factory,
        )
