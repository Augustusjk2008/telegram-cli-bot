from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gdb_session import GdbMiSession
from .models import DebugBreakpoint, DebugErrorInfo, DebugFrame, DebugProfile, DebugScope, DebugState
from .prepare_runner import PrepareRunError, stream_prepare
from .profile_loader import DebugProfileLoadError, load_debug_profile, require_debug_profile
from .providers.base import DebugProvider, DebugProviderError, DebugProviderSession
from .providers.registry import DebugProviderRegistry, build_default_provider_registry
from .source_resolver import resolve_source


class DebugServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, data: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def get_working_directory(manager, alias: str, user_id: int) -> dict[str, object]:
    from bot.web.api_service import get_working_directory as resolve_working_directory

    return resolve_working_directory(manager, alias, user_id)


@dataclass
class _Runtime:
    state: DebugState = field(default_factory=DebugState)
    workspace: Path | None = None
    profile: DebugProfile | None = None
    provider_id: str = ""
    session: DebugProviderSession | Any | None = None
    listeners: set[asyncio.Queue[dict[str, object]]] = field(default_factory=set)
    prepare_logs: list[str] = field(default_factory=list)
    saved_launch: dict[str, object] = field(default_factory=dict)
    command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    poll_task: asyncio.Task[None] | None = None
    event_task: asyncio.Task[None] | None = None


class DebugService:
    def __init__(
        self,
        manager,
        *,
        gdb_session_factory=GdbMiSession,
        poll_interval_seconds: float = 0.15,
        providers: list[DebugProvider] | None = None,
        provider_registry: DebugProviderRegistry | None = None,
    ):
        self._manager = manager
        self._runtimes: dict[tuple[str, int], _Runtime] = {}
        self._state_lock = asyncio.Lock()
        self._gdb_session_factory = gdb_session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._provider_registry = provider_registry or (
            DebugProviderRegistry(providers)
            if providers is not None
            else build_default_provider_registry(gdb_session_factory=gdb_session_factory)
        )

    def _key(self, alias: str, user_id: int) -> tuple[str, int]:
        return alias, user_id

    async def _get_runtime(self, alias: str, user_id: int) -> _Runtime:
        key = self._key(alias, user_id)
        async with self._state_lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = _Runtime()
                self._runtimes[key] = runtime
            return runtime

    async def subscribe(self, alias: str, user_id: int) -> asyncio.Queue[dict[str, object]]:
        runtime = await self._get_runtime(alias, user_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        runtime.listeners.add(queue)
        return queue

    async def unsubscribe(self, alias: str, user_id: int, queue: asyncio.Queue[dict[str, object]]) -> None:
        runtime = await self._get_runtime(alias, user_id)
        runtime.listeners.discard(queue)

    def _broadcast(self, runtime: _Runtime, event: dict[str, object]) -> None:
        for queue in list(runtime.listeners):
            queue.put_nowait(event)

    def _broadcast_state(self, runtime: _Runtime) -> None:
        self._broadcast(runtime, {"type": "state", "payload": runtime.state.to_api()})

    def _workspace_path(self, alias: str, user_id: int) -> Path:
        working_dir = str(get_working_directory(self._manager, alias, user_id)["working_dir"] or "").strip()
        return Path(working_dir).resolve()

    def _merge_profile(self, profile: DebugProfile, overrides: dict[str, object]) -> DebugProfile:
        remote_host = str(overrides.get("remote_host") or profile.remote_host)
        remote_user = str(overrides.get("remote_user") or profile.remote_user)
        remote_dir = str(overrides.get("remote_dir") or profile.remote_dir)
        remote_port = int(overrides.get("remote_port") or profile.remote_port or 0)
        prepare_command = str(overrides.get("prepare_command") or profile.prepare_command)
        stop_at_entry = bool(overrides.get("stop_at_entry")) if "stop_at_entry" in overrides else profile.stop_at_entry
        updated = profile.with_remote(
            remote_host=remote_host,
            remote_user=remote_user,
            remote_dir=remote_dir,
            remote_port=remote_port,
            prepare_command=prepare_command,
            stop_at_entry=stop_at_entry,
        )
        launch_defaults = dict(updated.launch_defaults)
        for key in ("program", "cwd", "args", "env"):
            if key in overrides:
                launch_defaults[key] = overrides[key]
        return type(updated)(
            **{
                **updated.__dict__,
                "launch_defaults": launch_defaults,
            }
        )

    def _build_launch_payload(
        self,
        profile: DebugProfile,
        payload: dict[str, object],
        saved_launch: dict[str, object],
    ) -> dict[str, object]:
        merged_launch = {
            "remote_host": str(payload.get("remoteHost") or saved_launch.get("remote_host") or profile.remote_host),
            "remote_user": str(payload.get("remoteUser") or saved_launch.get("remote_user") or profile.remote_user),
            "remote_dir": str(payload.get("remoteDir") or saved_launch.get("remote_dir") or profile.remote_dir),
            "remote_port": self._coerce_port(payload.get("remotePort") or saved_launch.get("remote_port"), profile.remote_port),
            "prepare_command": str(payload.get("prepareCommand") or saved_launch.get("prepare_command") or profile.prepare_command),
            "stop_at_entry": bool(payload["stopAtEntry"]) if "stopAtEntry" in payload else bool(saved_launch.get("stop_at_entry", profile.stop_at_entry)),
            "timeout_seconds": self._coerce_port(
                payload.get("timeoutSeconds") or payload.get("timeout_seconds") or saved_launch.get("timeout_seconds"),
                int(profile.prepare.timeout_seconds if profile.prepare else 300),
            ),
            "password": str(payload.get("password") or ""),
            "program": str(payload.get("program") or profile.target.program),
            "cwd": str(payload.get("cwd") or profile.target.cwd),
            "args": payload.get("args") if isinstance(payload.get("args"), list) else list(profile.target.args),
            "env": payload.get("env") if isinstance(payload.get("env"), dict) else dict(profile.target.env),
        }
        reserved_keys = {
            "configName",
            "remoteHost",
            "remoteUser",
            "remoteDir",
            "remotePort",
            "prepareCommand",
            "stopAtEntry",
            "timeoutSeconds",
            "timeout_seconds",
            "password",
            "program",
            "cwd",
            "args",
            "env",
        }
        for key, value in payload.items():
            if key not in reserved_keys:
                merged_launch[str(key)] = value
        return merged_launch

    def _resolve_source_path(self, workspace: Path | None, source: str, remote_dir: object = "") -> str:
        if workspace is None:
            return str(source or "").strip()
        profile = DebugProfile(
            kind="compat_source_resolver",
            workspace=str(workspace),
            config_name="compat",
            program="",
            cwd=str(workspace),
            mi_mode="gdb",
            mi_debugger_path="",
            compile_commands=None,
            prepare_command=r".\debug.bat",
            stop_at_entry=True,
            setup_commands=[],
            remote_host="",
            remote_user="",
            remote_dir=str(remote_dir or ""),
            remote_port=0,
        )
        return str(resolve_source(workspace, profile, source, {"line": 1}).get("path") or "")

    def _resolve_frame_source(
        self,
        runtime: _Runtime,
        source: str,
        line: int,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if runtime.workspace is None or runtime.profile is None:
            return {"path": source, "line": line, "resolved": bool(source), "reason": "raw"}
        return resolve_source(runtime.workspace, runtime.profile, source, {"line": line, **(payload or {})})

    def _sort_breakpoints(self, breakpoints: list[DebugBreakpoint]) -> list[DebugBreakpoint]:
        deduped: dict[tuple[str, int], DebugBreakpoint] = {}
        for item in breakpoints:
            if item.line <= 0:
                continue
            deduped[(item.source, item.line)] = item
        return sorted(deduped.values(), key=lambda item: (item.source.lower(), item.line))

    def _locals_reference(self, frame_id: str) -> str:
        return f"{frame_id}:locals" if frame_id else ""

    def _phase(self, runtime: _Runtime, phase: str, message: str, detail_phase: str = "") -> None:
        runtime.state.phase = phase
        runtime.state.message = message
        runtime.state.detail_phase = detail_phase
        self._broadcast_state(runtime)

    def _should_run_to_entry(self, runtime: _Runtime) -> bool:
        current_frame = runtime.state.frames[0] if runtime.state.frames else None
        if current_frame is None:
            return True
        if current_frame.name.strip() == "main":
            return False
        if current_frame.line > 0 and current_frame.source_resolved:
            return False
        return True

    async def get_profile(self, alias: str, user_id: int) -> dict[str, object] | None:
        workspace = self._workspace_path(alias, user_id)
        profile = load_debug_profile(workspace)
        if profile is None:
            return None
        runtime = await self._get_runtime(alias, user_id)
        return self._merge_profile(profile, runtime.saved_launch).to_api()

    async def get_state(self, alias: str, user_id: int) -> dict[str, object]:
        runtime = await self._get_runtime(alias, user_id)
        return runtime.state.to_api()

    async def shutdown(self) -> None:
        async with self._state_lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            with contextlib.suppress(Exception):
                await self._terminate_runtime(runtime, keep_breakpoints=False)

    async def _publish_error(self, runtime: _Runtime, exc: DebugServiceError | Exception) -> None:
        if isinstance(exc, DebugServiceError):
            code = exc.code
            message = exc.message
            data = exc.data
        else:
            code = "internal_error"
            message = str(exc)
            data = {}
        logs = data.get("logs") if isinstance(data, dict) else None
        logs_tail = [str(item) for item in logs[-20:]] if isinstance(logs, list) else []
        error_info = DebugErrorInfo(
            code=code,
            message=message,
            detail=str(data.get("detail") or data.get("details") or "") if isinstance(data, dict) else "",
            phase=runtime.state.detail_phase or runtime.state.phase,
            command=str(data.get("command") or "") if isinstance(data, dict) else "",
            recoverable=bool(data.get("recoverable", True)) if isinstance(data, dict) else True,
            logs_tail=logs_tail,
        )
        runtime.state.phase = "error"
        runtime.state.message = message
        runtime.state.detail_phase = runtime.state.detail_phase or runtime.state.phase
        runtime.state.error_info = error_info
        runtime.state.reset_runtime_views()
        self._broadcast(runtime, {"type": "error", "payload": {**error_info.to_api(), "data": data}})
        self._broadcast_state(runtime)

    def _coerce_port(self, value: object, default: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return resolved if resolved > 0 else default

    async def _stop_task(self, task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _stop_poll_tasks(self, runtime: _Runtime) -> None:
        await self._stop_task(runtime.poll_task)
        runtime.poll_task = None
        await self._stop_task(runtime.event_task)
        runtime.event_task = None

    async def _cleanup_provider(self, runtime: _Runtime) -> None:
        if runtime.profile is None:
            return
        if runtime.provider_id != "cpp-gdb":
            return
        provider = self._provider_registry.require_provider(runtime.profile)
        cleanup_remote = getattr(provider, "cleanup_remote", None)
        if callable(cleanup_remote):
            ok = await cleanup_remote(runtime.saved_launch)
            if not ok:
                self._broadcast(
                    runtime,
                    {
                        "type": "warning",
                        "payload": {
                            "code": "remote_cleanup_failed",
                            "message": "远端 gdbserver 清理失败",
                        },
                    },
                )

    async def _refresh_paused_state(self, runtime: _Runtime, payload: dict[str, object] | None = None) -> None:
        if runtime.session is None:
            return
        frames_raw = await runtime.session.stack_trace()
        resolved_frames: list[DebugFrame] = []
        for item in frames_raw:
            frame_payload = dict(item) if isinstance(item, dict) else {}
            result = self._resolve_frame_source(
                runtime,
                str(frame_payload.get("source") or ""),
                int(frame_payload.get("line") or 0),
                frame_payload,
            )
            resolved_frames.append(
                DebugFrame(
                    id=str(frame_payload.get("id") or ""),
                    name=str(frame_payload.get("name") or ""),
                    source=str(result.get("path") or frame_payload.get("source") or "??"),
                    line=int(frame_payload.get("line") or 0),
                    source_resolved=bool(result.get("resolved")),
                    source_reason=str(result.get("reason") or ""),
                    original_source=str(
                        frame_payload.get("originalSource")
                        or frame_payload.get("original_source")
                        or frame_payload.get("source")
                        or ""
                    ),
                    source_reference=int(
                        result.get("sourceReference")
                        or frame_payload.get("sourceReference")
                        or frame_payload.get("source_reference")
                        or 0
                    ),
                )
            )
        runtime.state.frames = resolved_frames
        current_frame_id = resolved_frames[0].id if resolved_frames else ""
        runtime.state.current_frame_id = current_frame_id
        scopes_raw = await runtime.session.scopes(current_frame_id) if current_frame_id else []
        runtime.state.scopes = [
            DebugScope(
                name=str(item.get("name") or ""),
                variables_reference=str(item.get("variablesReference") or ""),
            )
            for item in scopes_raw
            if isinstance(item, dict)
        ]
        runtime.state.variables = {}
        for scope in runtime.state.scopes:
            variables_raw = await runtime.session.variables(scope.variables_reference)
            runtime.state.variables[scope.variables_reference] = [
                self._variable_from_api(item)
                for item in variables_raw
                if isinstance(item, dict)
            ]
        runtime.state.phase = "paused"
        runtime.state.detail_phase = "paused"
        reason = str((payload or {}).get("reason") or "")
        runtime.state.message = "命中断点" if reason == "breakpoint-hit" else "调试已暂停"
        current_frame = resolved_frames[0] if resolved_frames else None
        self._broadcast(
            runtime,
            {
                "type": "stopped",
                "payload": {
                    "reason": reason or "unknown",
                    "threadId": str((payload or {}).get("threadId") or ""),
                    "source": current_frame.source if current_frame else "",
                    "line": current_frame.line if current_frame else int((payload or {}).get("line") or 0),
                    "frameId": current_frame.id if current_frame else str((payload or {}).get("frameId") or ""),
                    "sourceResolved": bool(current_frame.source_resolved) if current_frame else False,
                },
            },
        )
        self._broadcast(runtime, {"type": "stackTrace", "payload": {"frames": [item.to_api() for item in runtime.state.frames]}})
        if runtime.state.scopes:
            self._broadcast(
                runtime,
                {
                    "type": "scopes",
                    "payload": {
                        "frameId": current_frame_id,
                        "scopes": [item.to_api() for item in runtime.state.scopes],
                    },
                },
            )
        for reference, variables in runtime.state.variables.items():
            self._broadcast(
                runtime,
                {
                    "type": "variables",
                    "payload": {
                        "variablesReference": reference,
                        "variables": [item.to_api() for item in variables],
                    },
                },
            )
        self._broadcast_state(runtime)

    def _variable_from_api(self, data: dict[str, object]):
        from .models import DebugVariable

        return DebugVariable(
            name=str(data.get("name") or ""),
            value=str(data.get("value") or ""),
            type=str(data.get("type") or "") or None,
            variables_reference=str(data.get("variablesReference") or "") or None,
        )

    async def _apply_debug_event(self, runtime: _Runtime, event: dict[str, object]) -> None:
        event_type = str(event.get("type") or "")
        payload = event.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        if event_type == "running":
            runtime.state.phase = "running"
            runtime.state.detail_phase = "running"
            runtime.state.message = "程序运行中"
            runtime.state.reset_runtime_views()
            self._broadcast_state(runtime)
            return
        if event_type == "stopped":
            await self._refresh_paused_state(runtime, payload_dict)
            return
        if event_type == "output":
            line = str(payload_dict.get("line") or payload_dict.get("output") or "")
            if line:
                runtime.prepare_logs.append(line)
                self._broadcast(runtime, {"type": "prepareLog", "payload": {"line": line, "type": str(payload_dict.get("category") or "output")}})
            return
        if event_type == "terminated":
            runtime.state.phase = "idle"
            runtime.state.detail_phase = ""
            runtime.state.message = "调试已结束"
            runtime.state.reset_runtime_views()
            self._broadcast_state(runtime)
            self._broadcast(runtime, event)
            return
        self._broadcast(runtime, event)

    async def _event_loop(self, runtime: _Runtime) -> None:
        assert runtime.session is not None
        async for event in runtime.session.events():
            await self._apply_debug_event(runtime, event)

    async def _poll_loop(self, runtime: _Runtime) -> None:
        while runtime.session is not None:
            try:
                poll_events = getattr(runtime.session, "poll_events", None)
                if not callable(poll_events):
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                events = poll_events() or []
                if not events:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                for event in events:
                    await self._apply_debug_event(runtime, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_error(runtime, exc if isinstance(exc, DebugServiceError) else DebugServiceError("provider_poll_failed", str(exc)))
                return

    async def _start_runtime_tasks(self, runtime: _Runtime) -> None:
        await self._stop_poll_tasks(runtime)
        if runtime.session is None:
            return
        runtime.event_task = asyncio.create_task(self._event_loop(runtime))
        if callable(getattr(runtime.session, "poll_events", None)):
            runtime.poll_task = asyncio.create_task(self._poll_loop(runtime))

    async def _terminate_runtime(self, runtime: _Runtime, *, keep_breakpoints: bool = True) -> None:
        preserved_breakpoints = runtime.state.breakpoints[:] if keep_breakpoints else []
        runtime.state.phase = "stopping"
        runtime.state.detail_phase = "stopping"
        runtime.state.message = "停止调试中"
        runtime.state.reset_runtime_views()
        self._broadcast_state(runtime)
        await self._stop_poll_tasks(runtime)
        session = runtime.session
        runtime.session = None
        if session is not None:
            with contextlib.suppress(Exception):
                await session.close()
        await self._cleanup_provider(runtime)
        runtime.state.phase = "idle"
        runtime.state.detail_phase = ""
        runtime.state.message = ""
        runtime.state.breakpoints = preserved_breakpoints
        runtime.state.error_info = None
        runtime.state.reset_runtime_views()
        self._broadcast_state(runtime)

    async def _launch(self, runtime: _Runtime, alias: str, user_id: int, payload: dict[str, object]) -> None:
        workspace = self._workspace_path(alias, user_id)
        try:
            profile = require_debug_profile(workspace)
        except DebugProfileLoadError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc

        if runtime.session is not None:
            await self._terminate_runtime(runtime, keep_breakpoints=True)

        merged_launch = self._build_launch_payload(profile, payload, runtime.saved_launch)
        runtime.saved_launch = {
            key: value
            for key, value in merged_launch.items()
            if key != "password"
        }
        runtime.workspace = workspace
        runtime.profile = self._merge_profile(profile, runtime.saved_launch)
        runtime.provider_id = runtime.profile.provider_id
        runtime.prepare_logs = []
        runtime.state.error_info = None
        runtime.state.reset_runtime_views()
        self._phase(runtime, "starting", "准备调试环境", "preparing")

        if runtime.profile.prepare_command:
            try:
                async for line in stream_prepare(workspace, merged_launch):
                    event_line = str(line)
                    runtime.prepare_logs.append(event_line)
                    self._broadcast(runtime, {"type": "prepareLog", "payload": {"line": event_line, "type": "line"}})
            except PrepareRunError as exc:
                raise DebugServiceError(exc.code, exc.message, data={"logs": exc.logs, "command": exc.command}) from exc

        self._phase(runtime, "starting", "准备结果校验", "deploying")
        try:
            runtime.profile = self._merge_profile(require_debug_profile(workspace), runtime.saved_launch)
        except DebugProfileLoadError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc

        program_path = runtime.profile.target.program or runtime.profile.program
        if program_path and runtime.profile.provider_id == "cpp-gdb" and not Path(program_path).exists():
            raise DebugServiceError("program_missing", f"未找到程序: {program_path}")

        provider = self._provider_registry.require_provider(runtime.profile)
        runtime.provider_id = provider.provider_id
        runtime.session = provider.create_session(runtime.profile)
        self._phase(runtime, "starting", f"启动 {provider.provider_label}", "provider_launch")
        try:
            await runtime.session.launch(runtime.saved_launch)
            if runtime.state.breakpoints:
                source_groups: dict[str, list[DebugBreakpoint]] = {}
                for item in runtime.state.breakpoints:
                    source_groups.setdefault(item.source, []).append(item)
                rebound: list[DebugBreakpoint] = []
                for source, items in source_groups.items():
                    results = await runtime.session.set_breakpoints(source, [item.to_api() for item in items])
                    rebound.extend(self._breakpoint_from_api(source, result) for result in results)
                runtime.state.breakpoints = self._sort_breakpoints(rebound)
                self._broadcast(runtime, {"type": "breakpoints", "payload": {"items": [item.to_api() for item in runtime.state.breakpoints]}})
            await self._start_runtime_tasks(runtime)
            if provider.provider_id == "cpp-gdb":
                run_to_entry = getattr(runtime.session, "run_to_entry", None)
                if runtime.profile.stop_at_entry:
                    await asyncio.sleep(0)
                    if runtime.state.phase == "starting":
                        await self._refresh_paused_state(runtime, {"reason": "entry"})
                    if callable(run_to_entry) and self._should_run_to_entry(runtime):
                        events = run_to_entry() or []
                        runtime.state.reset_runtime_views()
                        self._phase(runtime, "running", "运行到入口", "run_to_entry")
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                else:
                    await runtime.session.continue_execution()
                    runtime.state.reset_runtime_views()
                    self._phase(runtime, "running", "程序运行中", "running")
            elif runtime.state.phase == "starting":
                self._phase(runtime, "running", "程序运行中", "running")
        except DebugProviderError as exc:
            if runtime.session is not None:
                with contextlib.suppress(Exception):
                    await runtime.session.close()
            runtime.session = None
            raise DebugServiceError(exc.code, exc.message, data=exc.data) from exc

    def _breakpoint_from_api(self, source: str, data: dict[str, object]) -> DebugBreakpoint:
        return DebugBreakpoint(
            source=str(data.get("source") or source),
            line=int(data.get("line") or 0),
            verified=bool(data.get("verified", True)),
            status=str(data.get("status") or ""),
            type=str(data.get("type") or "line"),
            function=str(data.get("function") or ""),
            condition=str(data.get("condition") or ""),
            hit_condition=str(data.get("hitCondition") or data.get("hit_condition") or ""),
            log_message=str(data.get("logMessage") or data.get("log_message") or ""),
            message=str(data.get("message") or ""),
        )

    async def _set_breakpoints(self, runtime: _Runtime, payload: dict[str, object]) -> None:
        source = str(payload.get("source") or "").strip()
        raw_items = payload.get("breakpoints", payload.get("lines", []))
        items: list[dict[str, object]] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    line = int(item.get("line") or 0)
                    if line > 0:
                        items.append({"line": line, **item})
                    continue
                try:
                    line = int(item)
                except (TypeError, ValueError):
                    continue
                if line > 0:
                    items.append({"line": line})
        pending = [DebugBreakpoint(source=source, line=int(item.get("line") or 0), verified=False, status="pending") for item in items]
        runtime.state.breakpoints = self._sort_breakpoints(
            [item for item in runtime.state.breakpoints if item.source != source] + pending
        )
        if runtime.session is not None:
            try:
                results = await runtime.session.set_breakpoints(source, items)
            except DebugProviderError as exc:
                raise DebugServiceError(exc.code, exc.message, data=exc.data) from exc
            rebound = [item for item in runtime.state.breakpoints if item.source != source]
            rebound.extend(self._breakpoint_from_api(source, result) for result in results)
            runtime.state.breakpoints = self._sort_breakpoints(rebound)
        self._broadcast(runtime, {"type": "breakpoints", "payload": {"items": [item.to_api() for item in runtime.state.breakpoints]}})
        self._broadcast(runtime, {"type": "breakpoint", "payload": {"items": [item.to_api() for item in runtime.state.breakpoints]}})
        self._broadcast_state(runtime)

    async def _select_frame(self, runtime: _Runtime, frame_id: str) -> None:
        runtime.state.current_frame_id = frame_id
        await self._emit_scopes(runtime, frame_id)
        self._broadcast_state(runtime)

    async def _emit_stack_trace(self, runtime: _Runtime) -> None:
        if runtime.session is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        await self._refresh_paused_state(runtime, {"reason": "manual"})

    async def _emit_scopes(self, runtime: _Runtime, frame_id: str) -> None:
        if runtime.session is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        frame_reference = frame_id or runtime.state.current_frame_id
        scopes_raw = await runtime.session.scopes(frame_reference)
        runtime.state.scopes = [
            DebugScope(name=str(item.get("name") or ""), variables_reference=str(item.get("variablesReference") or ""))
            for item in scopes_raw
            if isinstance(item, dict)
        ]
        self._broadcast(runtime, {"type": "scopes", "payload": {"frameId": frame_reference, "scopes": [item.to_api() for item in runtime.state.scopes]}})
        for scope in runtime.state.scopes:
            await self._emit_variables(runtime, scope.variables_reference)

    async def _emit_variables(self, runtime: _Runtime, variables_reference: str) -> None:
        if runtime.session is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        items_raw = await runtime.session.variables(variables_reference)
        items = [self._variable_from_api(item) for item in items_raw if isinstance(item, dict)]
        runtime.state.variables[variables_reference] = items
        self._broadcast(
            runtime,
            {
                "type": "variables",
                "payload": {
                    "variablesReference": variables_reference,
                    "variables": [item.to_api() for item in items],
                },
            },
        )

    async def _evaluate(self, runtime: _Runtime, expression: str, frame_id: str = "") -> dict[str, object]:
        if runtime.session is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        try:
            result = await runtime.session.evaluate(expression, frame_id or runtime.state.current_frame_id)
        except DebugProviderError as exc:
            raise DebugServiceError(exc.code, exc.message, data=exc.data) from exc
        self._broadcast(runtime, {"type": "evaluate", "payload": result})
        return result

    async def patch_profile_overrides(self, alias: str, user_id: int, payload: dict[str, object]) -> dict[str, object] | None:
        runtime = await self._get_runtime(alias, user_id)
        profile = load_debug_profile(self._workspace_path(alias, user_id))
        if profile is None:
            return None
        runtime.saved_launch.update(
            {
                key: value
                for key, value in {
                    "remote_host": payload.get("remoteHost", payload.get("remote_host")),
                    "remote_user": payload.get("remoteUser", payload.get("remote_user")),
                    "remote_dir": payload.get("remoteDir", payload.get("remote_dir")),
                    "remote_port": payload.get("remotePort", payload.get("remote_port")),
                    "prepare_command": payload.get("prepareCommand", payload.get("prepare_command")),
                    "stop_at_entry": payload.get("stopAtEntry", payload.get("stop_at_entry")),
                    "timeout_seconds": payload.get("timeoutSeconds", payload.get("timeout_seconds")),
                    "program": payload.get("program"),
                    "cwd": payload.get("cwd"),
                    "args": payload.get("args"),
                    "env": payload.get("env"),
                }.items()
                if value is not None
            }
        )
        return self._merge_profile(profile, runtime.saved_launch).to_api()

    async def launch(self, alias: str, user_id: int, payload: dict[str, object]) -> dict[str, object]:
        await self.handle_ws_message(alias, user_id, {"type": "launch", "payload": payload})
        return await self.get_state(alias, user_id)

    async def stop(self, alias: str, user_id: int) -> dict[str, object]:
        await self.handle_ws_message(alias, user_id, {"type": "stop"})
        return await self.get_state(alias, user_id)

    async def command(self, alias: str, user_id: int, action: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        await self.handle_ws_message(alias, user_id, {"type": action, "payload": payload or {}})
        return await self.get_state(alias, user_id)

    async def set_breakpoints(self, alias: str, user_id: int, payload: dict[str, object]) -> dict[str, object]:
        await self.handle_ws_message(alias, user_id, {"type": "setBreakpoints", "payload": payload})
        return await self.get_state(alias, user_id)

    async def evaluate(self, alias: str, user_id: int, payload: dict[str, object]) -> dict[str, object]:
        runtime = await self._get_runtime(alias, user_id)
        async with runtime.command_lock:
            return await self._evaluate(
                runtime,
                str(payload.get("expression") or ""),
                str(payload.get("frameId") or payload.get("frame_id") or ""),
            )

    async def handle_ws_message(self, alias: str, user_id: int, message: dict[str, object]) -> None:
        runtime = await self._get_runtime(alias, user_id)
        action = str(message.get("type") or "").strip()
        payload = message.get("payload")
        body = payload if isinstance(payload, dict) else {}
        async with runtime.command_lock:
            try:
                if action == "launch":
                    await self._launch(runtime, alias, user_id, body)
                    return
                if action in {"terminate", "stop"}:
                    await self._terminate_runtime(runtime, keep_breakpoints=True)
                    return
                if action == "setBreakpoints":
                    await self._set_breakpoints(runtime, body)
                    return
                if runtime.session is None:
                    raise DebugServiceError("session_not_started", "调试会话未启动")
                if action == "continue":
                    events = await runtime.session.continue_execution()
                    runtime.state.reset_runtime_views()
                    self._phase(runtime, "running", "程序运行中", "running")
                    if isinstance(events, list):
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                    return
                if action == "pause":
                    events = await runtime.session.pause()
                    runtime.state.message = "等待暂停"
                    self._broadcast_state(runtime)
                    if isinstance(events, list):
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                    return
                if action == "next":
                    events = await runtime.session.next()
                    runtime.state.reset_runtime_views()
                    self._phase(runtime, "running", "单步执行中", "next")
                    if isinstance(events, list):
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                    return
                if action == "stepIn":
                    events = await runtime.session.step_in()
                    runtime.state.reset_runtime_views()
                    self._phase(runtime, "running", "进入函数", "step_in")
                    if isinstance(events, list):
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                    return
                if action == "stepOut":
                    events = await runtime.session.step_out()
                    runtime.state.reset_runtime_views()
                    self._phase(runtime, "running", "跳出函数", "step_out")
                    if isinstance(events, list):
                        for event in events:
                            await self._apply_debug_event(runtime, event)
                    return
                if action == "stackTrace":
                    await self._emit_stack_trace(runtime)
                    return
                if action == "scopes":
                    await self._emit_scopes(runtime, str(body.get("frameId") or runtime.state.current_frame_id))
                    return
                if action == "variables":
                    await self._emit_variables(runtime, str(body.get("variablesReference") or ""))
                    return
                if action == "evaluate":
                    await self._evaluate(runtime, str(body.get("expression") or ""), str(body.get("frameId") or ""))
                    return
                if action == "selectFrame":
                    await self._select_frame(runtime, str(body.get("frameId") or ""))
                    return
                raise DebugServiceError("unknown_debug_command", f"未知调试指令: {action}")
            except Exception as exc:
                if isinstance(exc, DebugServiceError):
                    await self._publish_error(runtime, exc)
                    return
                await self._publish_error(runtime, DebugServiceError("internal_error", str(exc)))
