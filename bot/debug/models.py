from __future__ import annotations

from dataclasses import dataclass, field, replace


DebugPhase = str


@dataclass(frozen=True)
class DebugSourceMap:
    remote: str
    local: str

    def to_api(self) -> dict[str, object]:
        return {"remote": self.remote, "local": self.local}


@dataclass(frozen=True)
class DebugTarget:
    type: str = "remote-gdbserver"
    architecture: str = "aarch64"
    program: str = ""
    cwd: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def to_api(self) -> dict[str, object]:
        return {
            "type": self.type,
            "architecture": self.architecture,
            "program": self.program,
            "cwd": self.cwd,
            "args": list(self.args),
            "env": dict(self.env),
        }


@dataclass(frozen=True)
class DebugPrepare:
    command: str = r".\debug.bat"
    timeout_seconds: float = 300
    problem_matchers: list[str] = field(default_factory=list)

    def to_api(self) -> dict[str, object]:
        return {
            "command": self.command,
            "timeoutSeconds": self.timeout_seconds,
            "timeout_seconds": self.timeout_seconds,
            "problemMatchers": list(self.problem_matchers),
            "problem_matchers": list(self.problem_matchers),
        }


@dataclass(frozen=True)
class DebugRemote:
    host: str = "192.168.1.29"
    user: str = "root"
    dir: str = "/home/sast8/tmp"
    gdbserver: str = "/home/sast8/tmp/gdbserver"
    port: int = 1234

    def to_api(self) -> dict[str, object]:
        return {
            "host": self.host,
            "user": self.user,
            "dir": self.dir,
            "gdbserver": self.gdbserver,
            "port": self.port,
        }


@dataclass(frozen=True)
class DebugGdbSetupCommand:
    text: str
    ignore_failures: bool = False

    def to_api(self) -> dict[str, object]:
        return {
            "text": self.text,
            "ignoreFailures": self.ignore_failures,
            "ignore_failures": self.ignore_failures,
        }


@dataclass(frozen=True)
class DebugGdb:
    path: str = ""
    sysroot: str = ""
    setup_commands: list[DebugGdbSetupCommand] = field(default_factory=list)

    def to_api(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sysroot": self.sysroot,
            "setupCommands": [item.to_api() for item in self.setup_commands],
            "setup_commands": [item.to_api() for item in self.setup_commands],
        }


@dataclass(frozen=True)
class DebugCapabilities:
    threads: bool = False
    variables: bool = True
    evaluate: bool = True
    memory: bool = False
    registers: bool = False
    disassembly: bool = False
    function_breakpoints: bool = True
    conditional_breakpoints: bool = True
    logpoints: bool = True

    def to_api(self) -> dict[str, object]:
        return {
            "threads": self.threads,
            "variables": self.variables,
            "evaluate": self.evaluate,
            "memory": self.memory,
            "registers": self.registers,
            "disassembly": self.disassembly,
            "functionBreakpoints": self.function_breakpoints,
            "function_breakpoints": self.function_breakpoints,
            "conditionalBreakpoints": self.conditional_breakpoints,
            "conditional_breakpoints": self.conditional_breakpoints,
            "logpoints": self.logpoints,
        }


@dataclass(frozen=True)
class DebugErrorInfo:
    code: str
    message: str
    detail: str = ""
    phase: str = ""
    command: str = ""
    recoverable: bool = True
    logs_tail: list[str] = field(default_factory=list)

    def to_api(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "details": self.detail,
            "phase": self.phase,
            "command": self.command,
            "recoverable": self.recoverable,
            "logsTail": list(self.logs_tail),
            "logs_tail": list(self.logs_tail),
        }


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
    spec_version: int = 2
    language: str = "cpp"
    target: DebugTarget | None = None
    prepare: DebugPrepare | None = None
    remote: DebugRemote | None = None
    gdb: DebugGdb | None = None
    source_maps: list[DebugSourceMap] = field(default_factory=list)
    capabilities: DebugCapabilities = field(default_factory=DebugCapabilities)
    open_source_on_pause: bool = True
    default_panels: list[str] = field(default_factory=lambda: ["source", "stack", "variables", "console"])

    def __post_init__(self) -> None:
        if self.target is None:
            object.__setattr__(
                self,
                "target",
                DebugTarget(program=self.program, cwd=self.cwd),
            )
        if self.prepare is None:
            object.__setattr__(self, "prepare", DebugPrepare(command=self.prepare_command))
        if self.remote is None:
            object.__setattr__(
                self,
                "remote",
                DebugRemote(host=self.remote_host, user=self.remote_user, dir=self.remote_dir, port=self.remote_port),
            )
        if self.gdb is None:
            setup_commands = [
                DebugGdbSetupCommand(
                    text=command,
                    ignore_failures=index < len(self.setup_command_ignore_failures)
                    and self.setup_command_ignore_failures[index],
                )
                for index, command in enumerate(self.setup_commands)
            ]
            object.__setattr__(self, "gdb", DebugGdb(path=self.mi_debugger_path, setup_commands=setup_commands))

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
        next_prepare_command = self.prepare_command if prepare_command is None else prepare_command
        next_remote_host = self.remote_host if remote_host is None else remote_host
        next_remote_user = self.remote_user if remote_user is None else remote_user
        next_remote_dir = self.remote_dir if remote_dir is None else remote_dir
        next_remote_port = self.remote_port if remote_port is None else remote_port
        current_prepare = self.prepare or DebugPrepare(command=self.prepare_command)
        current_remote = self.remote or DebugRemote(
            host=self.remote_host,
            user=self.remote_user,
            dir=self.remote_dir,
            port=self.remote_port,
        )
        return replace(
            self,
            remote_host=next_remote_host,
            remote_user=next_remote_user,
            remote_dir=next_remote_dir,
            remote_port=next_remote_port,
            prepare_command=next_prepare_command,
            stop_at_entry=self.stop_at_entry if stop_at_entry is None else stop_at_entry,
            prepare=replace(current_prepare, command=next_prepare_command),
            remote=replace(
                current_remote,
                host=next_remote_host,
                user=next_remote_user,
                dir=next_remote_dir,
                port=next_remote_port,
            ),
        )

    def with_source_maps(self, source_maps: list[DebugSourceMap]) -> DebugProfile:
        return replace(self, source_maps=list(source_maps))

    def to_api(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "specVersion": self.spec_version,
            "spec_version": self.spec_version,
            "language": self.language,
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
            "target": self.target.to_api() if self.target else {},
            "prepare": self.prepare.to_api() if self.prepare else {},
            "remote": self.remote.to_api() if self.remote else {},
            "gdb": self.gdb.to_api() if self.gdb else {},
            "sourceMaps": [item.to_api() for item in self.source_maps],
            "source_maps": [item.to_api() for item in self.source_maps],
            "capabilities": self.capabilities.to_api(),
            "ui": {
                "stopAtEntry": self.stop_at_entry,
                "stop_at_entry": self.stop_at_entry,
                "openSourceOnPause": self.open_source_on_pause,
                "open_source_on_pause": self.open_source_on_pause,
                "defaultPanels": list(self.default_panels),
                "default_panels": list(self.default_panels),
            },
        }


@dataclass(frozen=True)
class DebugProfileV2(DebugProfile):
    pass


@dataclass(frozen=True)
class DebugBreakpoint:
    source: str
    line: int
    verified: bool = True
    status: str = ""
    type: str = "line"
    function: str = ""
    condition: str = ""
    hit_condition: str = ""
    log_message: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        status = self.status or ("verified" if self.verified else "pending")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "verified", status == "verified")

    def to_api(self) -> dict[str, object]:
        return {
            "source": self.source,
            "line": self.line,
            "verified": self.verified,
            "status": self.status,
            "type": self.type,
            "function": self.function,
            "condition": self.condition,
            "hitCondition": self.hit_condition,
            "hit_condition": self.hit_condition,
            "logMessage": self.log_message,
            "log_message": self.log_message,
            "message": self.message,
        }


@dataclass(frozen=True)
class DebugFrame:
    id: str
    name: str
    source: str
    line: int
    source_resolved: bool = True
    source_reason: str = ""
    original_source: str = ""

    def to_api(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "line": self.line,
            "sourceResolved": self.source_resolved,
            "source_resolved": self.source_resolved,
            "sourceReason": self.source_reason,
            "source_reason": self.source_reason,
            "originalSource": self.original_source,
            "original_source": self.original_source,
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
    error_info: DebugErrorInfo | None = None

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
            "currentFrameId": self.current_frame_id,
            "scopes": [item.to_api() for item in self.scopes],
            "variables": {
                key: [item.to_api() for item in value]
                for key, value in self.variables.items()
            },
            "error": self.error_info.to_api() if self.error_info else None,
        }
