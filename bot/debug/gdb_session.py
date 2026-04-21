from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

from .models import DebugBreakpoint, DebugFrame, DebugProfile, DebugVariable

_FRAME_ID_RE = re.compile(r"(\d+)$")


class GdbMiError(RuntimeError):
    def __init__(self, code: str, message: str, *, command: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.command = command


def _default_controller_factory(argv: list[str]):
    try:
        from pygdbmi.gdbcontroller import GdbController
    except ImportError as exc:
        raise GdbMiError("gdb_start_failed", "缺少 pygdbmi 依赖") from exc
    return GdbController(command=argv)


def _frame_id(level: object) -> str:
    candidate = str(level or "").strip()
    return f"frame-{candidate}" if candidate else ""


def _extract_frame_level(frame_id: str) -> str:
    match = _FRAME_ID_RE.search(str(frame_id or ""))
    return match.group(1) if match else str(frame_id or "").strip()


def _mi_quote(value: str) -> str:
    if not value:
        return '""'
    if any(char in value for char in (' ', '"', "\\")):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


class GdbMiSession:
    def __init__(
        self,
        profile: DebugProfile,
        *,
        controller_factory: Callable[[list[str]], object] | None = None,
    ):
        self._profile = profile
        self._controller_factory = controller_factory or _default_controller_factory
        self._custom_controller_factory = controller_factory is not None
        self._controller: object | None = None

    def _controller_instance(self):
        if self._controller is not None:
            return self._controller
        debugger_path = Path(self._profile.mi_debugger_path)
        if not self._custom_controller_factory and not debugger_path.exists():
            raise GdbMiError("mi_debugger_not_found", f"未找到 GDB: {self._profile.mi_debugger_path}")
        try:
            self._controller = self._controller_factory([self._profile.mi_debugger_path, "--interpreter=mi2"])
        except FileNotFoundError as exc:
            raise GdbMiError("mi_debugger_not_found", f"未找到 GDB: {self._profile.mi_debugger_path}") from exc
        except GdbMiError:
            raise
        except Exception as exc:
            raise GdbMiError("gdb_start_failed", str(exc)) from exc
        return self._controller

    def _raise_on_result_error(self, command: str, records: list[dict[str, Any]]) -> None:
        for record in records:
            if record.get("type") != "result" or record.get("message") != "error":
                continue
            payload = record.get("payload") or {}
            message = str(payload.get("msg") or payload.get("message") or "GDB 命令失败")
            if command.startswith("-target-select remote"):
                code = "gdb_connect_failed"
            elif command.startswith("-break"):
                code = "breakpoint_set_failed"
            elif command.startswith("-stack"):
                code = "stack_fetch_failed"
            else:
                code = "gdb_start_failed"
            raise GdbMiError(code, message, command=command)

    def _write(self, command: str) -> list[dict[str, Any]]:
        try:
            records = list(self._controller_instance().write(command))
        except GdbMiError:
            raise
        except Exception as exc:
            raise GdbMiError("gdb_start_failed", str(exc), command=command) from exc
        self._raise_on_result_error(command, records)
        return records

    def launch(self, host: str, port: int) -> list[dict[str, object]]:
        self._write("-gdb-set mi-async on")
        self._write(f"-file-exec-and-symbols {_mi_quote(self._profile.program)}")
        for index, command in enumerate(self._profile.setup_commands):
            ignore_failure = (
                index < len(self._profile.setup_command_ignore_failures)
                and self._profile.setup_command_ignore_failures[index]
            )
            try:
                if command.startswith("-"):
                    self._write(command)
                    continue
                escaped = command.replace("\\", "\\\\").replace('"', '\\"')
                self._write(f'-interpreter-exec console "{escaped}"')
            except GdbMiError:
                if ignore_failure:
                    continue
                raise
        return self._map_notify_events(self._write(f"-target-select remote {host}:{port}"))

    def replace_breakpoints(self, items: Iterable[tuple[str, int]]) -> list[DebugBreakpoint]:
        self._write("-break-delete")
        breakpoints: list[DebugBreakpoint] = []
        for source, line in items:
            self._write(f"-break-insert {source}:{line}")
            breakpoints.append(DebugBreakpoint(source=source, line=int(line), verified=True))
        return breakpoints

    def set_breakpoints(self, source: str, lines: list[int]) -> list[DebugBreakpoint]:
        normalized_lines = sorted({int(item) for item in lines if int(item) > 0})
        return self.replace_breakpoints((source, line) for line in normalized_lines)

    def continue_execution(self) -> list[dict[str, object]]:
        return self._map_notify_events(self._write("-exec-continue"))

    def run_to_entry(self, symbol: str = "main") -> list[dict[str, object]]:
        self._write(f"-break-insert -t {symbol}")
        return self.continue_execution()

    def pause_execution(self) -> list[dict[str, object]]:
        return self._map_notify_events(self._write("-exec-interrupt"))

    def next_instruction(self) -> list[dict[str, object]]:
        return self._map_notify_events(self._write("-exec-next"))

    def step_in(self) -> list[dict[str, object]]:
        return self._map_notify_events(self._write("-exec-step"))

    def step_out(self) -> list[dict[str, object]]:
        return self._map_notify_events(self._write("-exec-finish"))

    def select_frame(self, frame_id: str) -> None:
        level = _extract_frame_level(frame_id)
        self._write(f"-stack-select-frame {level}")

    def _map_stack_frames(self, records: list[dict[str, Any]]) -> list[DebugFrame]:
        for record in records:
            payload = record.get("payload") or {}
            stack = payload.get("stack") or []
            if not isinstance(stack, list):
                continue
            frames: list[DebugFrame] = []
            for item in stack:
                frame = item.get("frame") if isinstance(item, dict) and isinstance(item.get("frame"), dict) else item
                if not isinstance(frame, dict):
                    continue
                frames.append(
                    DebugFrame(
                        id=_frame_id(frame.get("level")),
                        name=str(frame.get("func") or frame.get("name") or ""),
                        source=str(frame.get("fullname") or frame.get("file") or ""),
                        line=int(frame.get("line") or 0),
                    )
                )
            return frames
        return []

    def stack_trace(self) -> list[DebugFrame]:
        return self._map_stack_frames(self._write("-stack-list-frames"))

    def list_locals(self, frame_id: str | None = None) -> list[DebugVariable]:
        if frame_id:
            self.select_frame(frame_id)
        records = self._write("-stack-list-variables --all-values")
        for record in records:
            payload = record.get("payload") or {}
            variables = payload.get("variables") or []
            if not isinstance(variables, list):
                continue
            return [
                DebugVariable(
                    name=str(item.get("name") or ""),
                    value=str(item.get("value") or ""),
                    type=str(item.get("type") or "") or None,
                )
                for item in variables
                if isinstance(item, dict)
            ]
        return []

    def list_variables(self, variables_reference: str, frame_id: str | None = None) -> list[DebugVariable]:
        if variables_reference.endswith(":locals"):
            return self.list_locals(frame_id)
        return []

    def _map_notify_events(self, records: list[dict[str, Any]]) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for record in records:
            if record.get("type") != "notify":
                continue
            message = str(record.get("message") or "")
            payload = record.get("payload") or {}
            if message == "running":
                events.append({"type": "running", "payload": {}})
                continue
            if message != "stopped":
                continue
            frame = payload.get("frame") or {}
            source = ""
            line = 0
            frame_id = ""
            if isinstance(frame, dict):
                source = str(frame.get("fullname") or frame.get("file") or "")
                line = int(frame.get("line") or 0)
                frame_id = _frame_id(frame.get("level"))
            events.append(
                {
                    "type": "stopped",
                    "payload": {
                        "reason": payload.get("reason", "unknown"),
                        "threadId": str(payload.get("thread-id") or ""),
                        "source": source,
                        "line": line,
                        "frameId": frame_id,
                    },
                }
            )
        return events

    def poll_events(self) -> list[dict[str, object]]:
        controller = self._controller_instance()
        try:
            records = controller.get_gdb_response(timeout_sec=0.1, raise_error_on_timeout=False)
        except Exception as exc:
            raise GdbMiError("gdb_connect_failed", str(exc)) from exc
        return self._map_notify_events(records)

    def close(self) -> None:
        if self._controller is None:
            return
        try:
            self._controller.exit()
        finally:
            self._controller = None
