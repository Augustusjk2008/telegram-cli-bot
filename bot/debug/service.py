from __future__ import annotations

import asyncio
import contextlib
import ntpath
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .gdb_session import GdbMiError, GdbMiSession
from .models import DebugBreakpoint, DebugFrame, DebugProfile, DebugScope, DebugState, DebugVariable
from .prepare_runner import PrepareRunError, stream_prepare
from .profile_loader import DebugProfileLoadError, load_debug_profile, require_debug_profile


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
    gdb: GdbMiSession | None = None
    listeners: set[asyncio.Queue[dict[str, object]]] = field(default_factory=set)
    prepare_logs: list[str] = field(default_factory=list)
    saved_launch: dict[str, object] = field(default_factory=dict)
    command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    poll_task: asyncio.Task[None] | None = None


class DebugService:
    def __init__(
        self,
        manager,
        *,
        gdb_session_factory=GdbMiSession,
        poll_interval_seconds: float = 0.15,
    ):
        self._manager = manager
        self._runtimes: dict[tuple[str, int], _Runtime] = {}
        self._state_lock = asyncio.Lock()
        self._gdb_session_factory = gdb_session_factory
        self._poll_interval_seconds = poll_interval_seconds

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
        return profile.with_remote(
            remote_host=str(overrides.get("remote_host") or profile.remote_host),
            remote_user=str(overrides.get("remote_user") or profile.remote_user),
            remote_dir=str(overrides.get("remote_dir") or profile.remote_dir),
            remote_port=int(overrides.get("remote_port") or profile.remote_port),
            prepare_command=str(overrides.get("prepare_command") or profile.prepare_command),
            stop_at_entry=bool(overrides.get("stop_at_entry")) if "stop_at_entry" in overrides else profile.stop_at_entry,
        )

    def _resolve_source_path(self, workspace: Path | None, source: str, remote_dir: object = "") -> str:
        candidate = str(source or "").strip()
        if not candidate:
            return ""
        remote_root = str(remote_dir or "").rstrip("/")
        if workspace is not None and PurePosixPath(candidate).is_absolute() and remote_root:
            normalized = candidate.replace("\\", "/")
            if normalized == remote_root or normalized.startswith(f"{remote_root}/"):
                relative_source = normalized[len(remote_root):].lstrip("/")
                return str((workspace / relative_source).resolve())
            return candidate
        if ntpath.isabs(candidate) or Path(candidate).is_absolute():
            return str(Path(candidate))
        if workspace is None:
            return candidate
        return str((workspace / candidate).resolve())

    def _sort_breakpoints(self, breakpoints: list[DebugBreakpoint]) -> list[DebugBreakpoint]:
        deduped: dict[tuple[str, int], DebugBreakpoint] = {}
        for item in breakpoints:
            if item.line <= 0:
                continue
            deduped[(item.source, item.line)] = item
        return sorted(deduped.values(), key=lambda item: (item.source.lower(), item.line))

    def _locals_reference(self, frame_id: str) -> str:
        return f"{frame_id}:locals" if frame_id else ""

    def _is_workspace_source(self, workspace: Path | None, source: str) -> bool:
        if workspace is None or not source:
            return False
        try:
            workspace_path = workspace.resolve()
            source_path = Path(source).resolve()
        except Exception:
            return False
        return source_path == workspace_path or workspace_path in source_path.parents

    def _should_run_to_entry(self, runtime: _Runtime) -> bool:
        current_frame = runtime.state.frames[0] if runtime.state.frames else None
        if current_frame is None:
            return True
        if current_frame.name.strip() == "main":
            return False
        source = current_frame.source.strip()
        if current_frame.line > 0 and self._is_workspace_source(runtime.workspace, source):
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
        runtime.state.phase = "error"
        runtime.state.message = message
        runtime.state.reset_runtime_views()
        self._broadcast(
            runtime,
            {
                "type": "error",
                "payload": {
                    "code": code,
                    "message": message,
                    "data": data,
                },
            },
        )
        self._broadcast_state(runtime)

    def _coerce_port(self, value: object, default: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return resolved if resolved > 0 else default

    async def _stop_poll_task(self, runtime: _Runtime) -> None:
        if runtime.poll_task is None:
            return
        runtime.poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runtime.poll_task
        runtime.poll_task = None

    async def _cleanup_remote(self, runtime: _Runtime) -> None:
        host = str(runtime.saved_launch.get("remote_host") or "").strip()
        user = str(runtime.saved_launch.get("remote_user") or "").strip()
        port = self._coerce_port(runtime.saved_launch.get("remote_port"), 0)
        if not host or not user or port <= 0:
            return
        command = [
            "ssh",
            f"{user}@{host}",
            f"pkill -f 'gdbserver :{port}' || true",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
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

    def _build_scope_payload(self, runtime: _Runtime, frame_id: str, variables: list[DebugVariable]) -> None:
        if not frame_id:
            runtime.state.scopes = []
            runtime.state.variables = {}
            return
        reference = self._locals_reference(frame_id)
        runtime.state.scopes = [DebugScope(name="Locals", variables_reference=reference)]
        runtime.state.variables = {reference: variables}

    async def _refresh_paused_state(self, runtime: _Runtime, payload: dict[str, object] | None = None) -> None:
        if runtime.gdb is None:
            return
        try:
            frames = runtime.gdb.stack_trace()
        except GdbMiError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc
        resolved_frames = [
            DebugFrame(
                id=item.id,
                name=item.name,
                source=self._resolve_source_path(runtime.workspace, item.source, runtime.saved_launch.get("remote_dir")),
                line=item.line,
            )
            for item in frames
        ]
        runtime.state.frames = resolved_frames
        current_frame_id = resolved_frames[0].id if resolved_frames else ""
        runtime.state.current_frame_id = current_frame_id
        variables: list[DebugVariable] = []
        if current_frame_id and runtime.gdb is not None:
            try:
                variables = runtime.gdb.list_locals(current_frame_id)
            except GdbMiError as exc:
                raise DebugServiceError(exc.code, exc.message) from exc
        self._build_scope_payload(runtime, current_frame_id, variables)
        runtime.state.phase = "paused"
        reason = str((payload or {}).get("reason") or "")
        runtime.state.message = "命中断点" if reason == "breakpoint-hit" else "调试已暂停"
        current_frame = resolved_frames[0] if resolved_frames else None
        stopped_payload = {
            "reason": reason or "unknown",
            "threadId": str((payload or {}).get("threadId") or ""),
            "source": current_frame.source if current_frame else self._resolve_source_path(
                runtime.workspace,
                str((payload or {}).get("source") or ""),
                runtime.saved_launch.get("remote_dir"),
            ),
            "line": current_frame.line if current_frame else int((payload or {}).get("line") or 0),
            "frameId": current_frame.id if current_frame else str((payload or {}).get("frameId") or ""),
        }
        self._broadcast(runtime, {"type": "stopped", "payload": stopped_payload})
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
        reference = self._locals_reference(current_frame_id)
        if reference:
            self._broadcast(
                runtime,
                {
                    "type": "variables",
                    "payload": {
                        "variablesReference": reference,
                        "variables": [item.to_api() for item in runtime.state.variables.get(reference, [])],
                    },
                },
            )
        self._broadcast_state(runtime)

    async def _apply_debug_event(self, runtime: _Runtime, event: dict[str, object]) -> None:
        event_type = str(event.get("type") or "")
        payload = event.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        if event_type == "running":
            runtime.state.phase = "running"
            runtime.state.message = "程序运行中"
            self._broadcast_state(runtime)
            return
        if event_type == "stopped":
            await self._refresh_paused_state(runtime, payload_dict)

    async def _apply_debug_events(self, runtime: _Runtime, events: list[dict[str, object]]) -> None:
        for event in events:
            await self._apply_debug_event(runtime, event)

    async def _poll_loop(self, runtime: _Runtime) -> None:
        while runtime.gdb is not None:
            try:
                events = runtime.gdb.poll_events()
                if not events:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                for event in events:
                    await self._apply_debug_event(runtime, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_error(runtime, exc if isinstance(exc, DebugServiceError) else DebugServiceError("gdb_connect_failed", str(exc)))
                return

    async def _start_poll_task(self, runtime: _Runtime) -> None:
        await self._stop_poll_task(runtime)
        runtime.poll_task = asyncio.create_task(self._poll_loop(runtime))

    async def _terminate_runtime(self, runtime: _Runtime, *, keep_breakpoints: bool = True) -> None:
        preserved_breakpoints = runtime.state.breakpoints[:] if keep_breakpoints else []
        runtime.state.phase = "terminating"
        runtime.state.message = "停止调试中"
        runtime.state.reset_runtime_views()
        self._broadcast_state(runtime)
        await self._stop_poll_task(runtime)
        gdb = runtime.gdb
        runtime.gdb = None
        if gdb is not None:
            with contextlib.suppress(Exception):
                gdb.close()
        await self._cleanup_remote(runtime)
        runtime.state.phase = "idle"
        runtime.state.message = ""
        runtime.state.breakpoints = preserved_breakpoints
        runtime.state.reset_runtime_views()
        self._broadcast_state(runtime)

    async def _launch(self, runtime: _Runtime, alias: str, user_id: int, payload: dict[str, object]) -> None:
        workspace = self._workspace_path(alias, user_id)
        try:
            profile = require_debug_profile(workspace)
        except DebugProfileLoadError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc

        if runtime.gdb is not None:
            await self._terminate_runtime(runtime, keep_breakpoints=True)

        merged_launch = {
            "remote_host": str(payload.get("remoteHost") or runtime.saved_launch.get("remote_host") or profile.remote_host),
            "remote_user": str(payload.get("remoteUser") or runtime.saved_launch.get("remote_user") or profile.remote_user),
            "remote_dir": str(payload.get("remoteDir") or runtime.saved_launch.get("remote_dir") or profile.remote_dir),
            "remote_port": self._coerce_port(
                payload.get("remotePort") or runtime.saved_launch.get("remote_port"),
                profile.remote_port,
            ),
            "prepare_command": str(payload.get("prepareCommand") or runtime.saved_launch.get("prepare_command") or profile.prepare_command),
            "stop_at_entry": bool(payload["stopAtEntry"]) if "stopAtEntry" in payload else bool(runtime.saved_launch.get("stop_at_entry", profile.stop_at_entry)),
            "password": str(payload.get("password") or ""),
        }
        runtime.saved_launch = {
            "remote_host": merged_launch["remote_host"],
            "remote_user": merged_launch["remote_user"],
            "remote_dir": merged_launch["remote_dir"],
            "remote_port": merged_launch["remote_port"],
            "prepare_command": merged_launch["prepare_command"],
            "stop_at_entry": merged_launch["stop_at_entry"],
        }
        runtime.workspace = workspace
        runtime.profile = self._merge_profile(profile, runtime.saved_launch)
        runtime.prepare_logs = []
        runtime.state.phase = "preparing"
        runtime.state.message = "准备调试环境"
        runtime.state.reset_runtime_views()
        self._broadcast_state(runtime)

        try:
            async for line in stream_prepare(workspace, merged_launch):
                runtime.prepare_logs.append(line)
                self._broadcast(runtime, {"type": "prepareLog", "payload": {"line": line}})
        except PrepareRunError as exc:
            raise DebugServiceError(exc.code, exc.message, data={"logs": exc.logs}) from exc

        try:
            runtime.profile = self._merge_profile(require_debug_profile(workspace), runtime.saved_launch)
        except DebugProfileLoadError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc

        program_path = Path(runtime.profile.program)
        if not program_path.exists():
            raise DebugServiceError("program_not_found", f"未找到程序: {runtime.profile.program}")

        runtime.state.phase = "starting_gdb"
        runtime.state.message = "启动 GDB"
        self._broadcast_state(runtime)

        try:
            runtime.gdb = self._gdb_session_factory(runtime.profile)
            runtime.state.phase = "connecting_remote"
            runtime.state.message = "连接远端 gdbserver"
            self._broadcast_state(runtime)
            launch_events = runtime.gdb.launch(str(merged_launch["remote_host"]), int(merged_launch["remote_port"])) or []
            if runtime.state.breakpoints:
                runtime.state.breakpoints = self._sort_breakpoints(
                    runtime.gdb.replace_breakpoints((item.source, item.line) for item in runtime.state.breakpoints)
                )
                self._broadcast(
                    runtime,
                    {"type": "breakpoints", "payload": {"items": [item.to_api() for item in runtime.state.breakpoints]}},
                )
            stop_at_entry = bool(merged_launch["stop_at_entry"])
            await self._apply_debug_events(runtime, launch_events)
            if stop_at_entry:
                if runtime.state.phase == "connecting_remote":
                    await self._refresh_paused_state(runtime, {"reason": "entry"})
                if self._should_run_to_entry(runtime):
                    entry_events = runtime.gdb.run_to_entry() or []
                    runtime.state.reset_runtime_views()
                    runtime.state.phase = "running"
                    runtime.state.message = "运行到入口"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, entry_events)
            await self._start_poll_task(runtime)
            if not stop_at_entry:
                continue_events = runtime.gdb.continue_execution() or []
                runtime.state.reset_runtime_views()
                runtime.state.phase = "running"
                runtime.state.message = "程序运行中"
                self._broadcast_state(runtime)
                await self._apply_debug_events(runtime, continue_events)
        except GdbMiError as exc:
            if runtime.gdb is not None:
                with contextlib.suppress(Exception):
                    runtime.gdb.close()
            runtime.gdb = None
            raise DebugServiceError(exc.code, exc.message) from exc

    async def _set_breakpoints(self, runtime: _Runtime, payload: dict[str, object]) -> None:
        source = str(payload.get("source") or "").strip()
        lines_raw = payload.get("lines", [])
        lines = sorted({int(item) for item in lines_raw if isinstance(item, int) and int(item) > 0})
        runtime.state.breakpoints = self._sort_breakpoints(
            [
                item
                for item in runtime.state.breakpoints
                if item.source != source
            ] + [
                DebugBreakpoint(source=source, line=line, verified=True)
                for line in lines
            ]
        )
        if runtime.gdb is not None:
            try:
                runtime.state.breakpoints = self._sort_breakpoints(
                    runtime.gdb.replace_breakpoints((item.source, item.line) for item in runtime.state.breakpoints)
                )
            except GdbMiError as exc:
                raise DebugServiceError(exc.code, exc.message) from exc
        self._broadcast(
            runtime,
            {"type": "breakpoints", "payload": {"items": [item.to_api() for item in runtime.state.breakpoints]}},
        )
        self._broadcast_state(runtime)

    async def _select_frame(self, runtime: _Runtime, frame_id: str) -> None:
        if runtime.gdb is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        try:
            runtime.gdb.select_frame(frame_id)
            variables = runtime.gdb.list_locals(frame_id)
        except GdbMiError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc
        runtime.state.current_frame_id = frame_id
        self._build_scope_payload(runtime, frame_id, variables)
        self._broadcast_state(runtime)

    async def _emit_stack_trace(self, runtime: _Runtime) -> None:
        if runtime.gdb is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        await self._refresh_paused_state(runtime, {"reason": "manual"})

    async def _emit_scopes(self, runtime: _Runtime, frame_id: str) -> None:
        if runtime.gdb is None:
            raise DebugServiceError("session_not_started", "调试会话未启动")
        frame_reference = frame_id or runtime.state.current_frame_id
        try:
            variables = runtime.gdb.list_locals(frame_reference)
        except GdbMiError as exc:
            raise DebugServiceError(exc.code, exc.message) from exc
        self._build_scope_payload(runtime, frame_reference, variables)
        self._broadcast(
            runtime,
            {
                "type": "scopes",
                "payload": {
                    "frameId": frame_reference,
                    "scopes": [item.to_api() for item in runtime.state.scopes],
                },
            },
        )
        reference = self._locals_reference(frame_reference)
        if reference:
            self._broadcast(
                runtime,
                {
                    "type": "variables",
                    "payload": {
                        "variablesReference": reference,
                        "variables": [item.to_api() for item in runtime.state.variables.get(reference, [])],
                    },
                },
            )

    async def _emit_variables(self, runtime: _Runtime, variables_reference: str) -> None:
        items = runtime.state.variables.get(variables_reference, [])
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
                if runtime.gdb is None:
                    raise DebugServiceError("session_not_started", "调试会话未启动")
                if action == "continue":
                    events = runtime.gdb.continue_execution() or []
                    runtime.state.phase = "running"
                    runtime.state.message = "程序运行中"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, events)
                    return
                if action == "pause":
                    events = runtime.gdb.pause_execution() or []
                    runtime.state.message = "等待暂停"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, events)
                    return
                if action == "next":
                    events = runtime.gdb.next_instruction() or []
                    runtime.state.phase = "running"
                    runtime.state.message = "单步执行中"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, events)
                    return
                if action == "stepIn":
                    events = runtime.gdb.step_in() or []
                    runtime.state.phase = "running"
                    runtime.state.message = "进入函数"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, events)
                    return
                if action == "stepOut":
                    events = runtime.gdb.step_out() or []
                    runtime.state.phase = "running"
                    runtime.state.message = "跳出函数"
                    self._broadcast_state(runtime)
                    await self._apply_debug_events(runtime, events)
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
                if action == "selectFrame":
                    await self._select_frame(runtime, str(body.get("frameId") or ""))
                    return
                raise DebugServiceError("unknown_debug_command", f"未知调试指令: {action}")
            except Exception as exc:
                if isinstance(exc, DebugServiceError):
                    await self._publish_error(runtime, exc)
                    return
                await self._publish_error(runtime, DebugServiceError("internal_error", str(exc)))
