from __future__ import annotations

from dataclasses import dataclass, field, replace


DebugPhase = str


@dataclass(frozen=True)
class DebugProfile:
    kind: str
    workspace: str
    config_name: str
    program: str
    cwd: str
    mi_mode: str
    mi_debugger_path: str
    compile_commands: str | None
    prepare_command: str
    stop_at_entry: bool
    setup_commands: list[str]
    remote_host: str
    remote_user: str
    remote_dir: str
    remote_port: int
    setup_command_ignore_failures: list[bool] = field(default_factory=list)

    def with_remote(
        self,
        *,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_dir: str | None = None,
        remote_port: int | None = None,
        prepare_command: str | None = None,
        stop_at_entry: bool | None = None,
    ) -> DebugProfile:
        return replace(
            self,
            remote_host=self.remote_host if remote_host is None else remote_host,
            remote_user=self.remote_user if remote_user is None else remote_user,
            remote_dir=self.remote_dir if remote_dir is None else remote_dir,
            remote_port=self.remote_port if remote_port is None else remote_port,
            prepare_command=self.prepare_command if prepare_command is None else prepare_command,
            stop_at_entry=self.stop_at_entry if stop_at_entry is None else stop_at_entry,
        )

    def to_api(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "workspace": self.workspace,
            "config_name": self.config_name,
            "program": self.program,
            "cwd": self.cwd,
            "mi_mode": self.mi_mode,
            "mi_debugger_path": self.mi_debugger_path,
            "compile_commands": self.compile_commands,
            "prepare_command": self.prepare_command,
            "stop_at_entry": self.stop_at_entry,
            "setup_commands": list(self.setup_commands),
            "setup_command_ignore_failures": list(self.setup_command_ignore_failures),
            "remote_host": self.remote_host,
            "remote_user": self.remote_user,
            "remote_dir": self.remote_dir,
            "remote_port": self.remote_port,
        }


@dataclass(frozen=True)
class DebugBreakpoint:
    source: str
    line: int
    verified: bool = True

    def to_api(self) -> dict[str, object]:
        return {
            "source": self.source,
            "line": self.line,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class DebugFrame:
    id: str
    name: str
    source: str
    line: int

    def to_api(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "line": self.line,
        }


@dataclass(frozen=True)
class DebugScope:
    name: str
    variables_reference: str

    def to_api(self) -> dict[str, object]:
        return {
            "name": self.name,
            "variablesReference": self.variables_reference,
        }


@dataclass(frozen=True)
class DebugVariable:
    name: str
    value: str
    type: str | None = None
    variables_reference: str | None = None

    def to_api(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "value": self.value,
        }
        if self.type:
            payload["type"] = self.type
        if self.variables_reference:
            payload["variablesReference"] = self.variables_reference
        return payload


@dataclass
class DebugState:
    phase: DebugPhase = "idle"
    message: str = ""
    breakpoints: list[DebugBreakpoint] = field(default_factory=list)
    frames: list[DebugFrame] = field(default_factory=list)
    current_frame_id: str = ""
    scopes: list[DebugScope] = field(default_factory=list)
    variables: dict[str, list[DebugVariable]] = field(default_factory=dict)

    def reset_runtime_views(self) -> None:
        self.frames = []
        self.current_frame_id = ""
        self.scopes = []
        self.variables = {}

    def to_api(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "message": self.message,
            "breakpoints": [item.to_api() for item in self.breakpoints],
            "frames": [item.to_api() for item in self.frames],
            "current_frame_id": self.current_frame_id,
            "scopes": [item.to_api() for item in self.scopes],
            "variables": {
                key: [item.to_api() for item in value]
                for key, value in self.variables.items()
            },
        }
