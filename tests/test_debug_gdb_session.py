from __future__ import annotations

from pathlib import Path

import pytest

from bot.debug.gdb_session import GdbMiError, GdbMiSession
from bot.debug.models import DebugProfile


class _FakeController:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.responses: dict[str, list[dict[str, object]]] = {}
        self.poll_batches: list[list[dict[str, object]]] = []
        self.exited = False

    def write(self, command: str):
        self.commands.append(command)
        return self.responses.get(command, [{"type": "result", "message": "done", "payload": {}}])

    def get_gdb_response(self, timeout_sec: float = 0.1, raise_error_on_timeout: bool = False):
        assert timeout_sec == 0.1
        assert raise_error_on_timeout is False
        return self.poll_batches.pop(0) if self.poll_batches else []

    def exit(self) -> None:
        self.exited = True


def _make_profile(
    mi_debugger_path: str = "D:/Toolchain/aarch64-none-linux-gnu-gdb.exe",
    program: str = "C:/demo/build/aarch64/Debug/MB_DDF",
    setup_commands: list[str] | None = None,
    setup_command_ignore_failures: list[bool] | None = None,
) -> DebugProfile:
    return DebugProfile(
        kind="mbddf_remote_gdb",
        workspace="C:/demo",
        config_name="(gdb) Remote Debug",
        program=program,
        cwd="C:/demo",
        mi_mode="gdb",
        mi_debugger_path=mi_debugger_path,
        compile_commands="C:/demo/.vscode/compile_commands.json",
        prepare_command=r".\debug.bat",
        stop_at_entry=True,
        setup_commands=setup_commands if setup_commands is not None else ["-enable-pretty-printing", "set pagination off"],
        setup_command_ignore_failures=setup_command_ignore_failures or [],
        remote_host="192.168.1.29",
        remote_user="root",
        remote_dir="/home/sast8/tmp",
        remote_port=1234,
    )


def test_launch_writes_expected_mi_commands_in_order() -> None:
    controller = _FakeController()
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    events = session.launch("192.168.1.29", 1234)

    assert controller.commands == [
        "-gdb-set mi-async on",
        "-file-exec-and-symbols C:/demo/build/aarch64/Debug/MB_DDF",
        "-enable-pretty-printing",
        '-interpreter-exec console "set pagination off"',
        "-target-select remote 192.168.1.29:1234",
    ]
    assert events == []


def test_launch_maps_stopped_event_returned_by_target_select() -> None:
    controller = _FakeController()
    controller.responses["-target-select remote 192.168.1.29:1234"] = [
        {
            "type": "notify",
            "message": "stopped",
            "payload": {
                "reason": "breakpoint-hit",
                "thread-id": "1",
                "frame": {"level": "0", "fullname": "C:/demo/src/main.cpp", "line": "42"},
            },
        }
    ]
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    events = session.launch("192.168.1.29", 1234)

    assert events == [
        {
            "type": "stopped",
            "payload": {
                "reason": "breakpoint-hit",
                "threadId": "1",
                "source": "C:/demo/src/main.cpp",
                "line": 42,
                "frameId": "frame-0",
            },
        }
    ]


def test_launch_quotes_windows_program_path_for_gdb_mi() -> None:
    controller = _FakeController()
    session = GdbMiSession(
        _make_profile(program=r"H:\Resources\RTLinux\Demos\MB_DDF\build\aarch64\Debug\MB_DDF"),
        controller_factory=lambda _argv: controller,
    )

    session.launch("192.168.1.29", 1234)

    assert controller.commands[1] == (
        r'-file-exec-and-symbols "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\build\\aarch64\\Debug\\MB_DDF"'
    )


def test_launch_ignores_setup_command_error_when_ignore_failures_is_true() -> None:
    controller = _FakeController()
    setup_command = r'-interpreter-exec console "handle SIGRTMIN nostop noprint pass"'
    controller.responses[setup_command] = [
        {
            "type": "result",
            "message": "error",
            "payload": {"msg": 'Unrecognized or ambiguous flag word: "SIGRTMIN".'},
        }
    ]
    session = GdbMiSession(
        _make_profile(
            program="C:/demo/app",
            setup_commands=["handle SIGRTMIN nostop noprint pass"],
            setup_command_ignore_failures=[True],
        ),
        controller_factory=lambda _argv: controller,
    )

    session.launch("192.168.1.29", 1234)

    assert controller.commands[-1] == "-target-select remote 192.168.1.29:1234"


def test_launch_still_raises_other_setup_command_errors() -> None:
    controller = _FakeController()
    setup_command = r'-interpreter-exec console "set sysroot Z:\\missing"'
    controller.responses[setup_command] = [
        {
            "type": "result",
            "message": "error",
            "payload": {"msg": "No such file or directory."},
        }
    ]
    session = GdbMiSession(
        _make_profile(program="C:/demo/app", setup_commands=[r"set sysroot Z:\missing"]),
        controller_factory=lambda _argv: controller,
    )

    with pytest.raises(GdbMiError) as exc_info:
        session.launch("192.168.1.29", 1234)

    assert exc_info.value.message == "No such file or directory."


def test_stack_trace_locals_and_poll_events_are_mapped() -> None:
    controller = _FakeController()
    controller.responses["-stack-list-frames"] = [
        {
            "type": "result",
            "message": "done",
            "payload": {
                "stack": [
                    {"level": "0", "func": "main", "fullname": "C:/demo/src/main.cpp", "line": "42"},
                    {"level": "1", "func": "worker", "fullname": "C:/demo/src/worker.cpp", "line": "17"},
                ]
            },
        }
    ]
    controller.responses["-stack-select-frame 0"] = [{"type": "result", "message": "done", "payload": {}}]
    controller.responses["-stack-list-variables --all-values"] = [
        {
            "type": "result",
            "message": "done",
            "payload": {
                "variables": [
                    {"name": "argc", "value": "1", "type": "int"},
                    {"name": "argv", "value": "0x1000", "type": "char **"},
                ]
            },
        }
    ]
    controller.poll_batches.append(
        [
            {"type": "notify", "message": "running", "payload": {}},
            {
                "type": "notify",
                "message": "stopped",
                "payload": {
                    "reason": "breakpoint-hit",
                    "thread-id": "1",
                    "frame": {"level": "0", "fullname": "C:/demo/src/main.cpp", "line": "42"},
                },
            },
        ]
    )
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    frames = session.stack_trace()
    locals_list = session.list_locals("frame-0")
    events = session.poll_events()

    assert [frame.id for frame in frames] == ["frame-0", "frame-1"]
    assert frames[0].source == "C:/demo/src/main.cpp"
    assert locals_list[0].name == "argc"
    assert locals_list[0].type == "int"
    assert events == [
        {"type": "running", "payload": {}},
        {
            "type": "stopped",
            "payload": {
                "reason": "breakpoint-hit",
                "threadId": "1",
                "source": "C:/demo/src/main.cpp",
                "line": 42,
                "frameId": "frame-0",
            },
        },
    ]


def test_run_to_entry_sets_temporary_main_breakpoint_then_continues() -> None:
    controller = _FakeController()
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    events = session.run_to_entry()

    assert controller.commands == ["-break-insert -t main", "-exec-continue"]
    assert events == []


def test_execution_commands_map_notify_events_returned_by_write() -> None:
    controller = _FakeController()
    controller.responses["-exec-interrupt"] = [
        {
            "type": "notify",
            "message": "stopped",
            "payload": {
                "reason": "signal-received",
                "thread-id": "1",
                "frame": {"level": "0", "fullname": "C:/demo/src/main.cpp", "line": "42"},
            },
        }
    ]
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    assert session.pause_execution() == [
        {
            "type": "stopped",
            "payload": {
                "reason": "signal-received",
                "threadId": "1",
                "source": "C:/demo/src/main.cpp",
                "line": 42,
                "frameId": "frame-0",
            },
        }
    ]


def test_missing_local_gdb_path_raises_mi_debugger_not_found(tmp_path: Path) -> None:
    session = GdbMiSession(_make_profile(mi_debugger_path=str(tmp_path / "missing-gdb.exe")))

    with pytest.raises(GdbMiError) as exc_info:
        session.launch("192.168.1.29", 1234)

    assert exc_info.value.code == "mi_debugger_not_found"


def test_custom_controller_factory_skips_local_path_check() -> None:
    controller = _FakeController()
    session = GdbMiSession(_make_profile(mi_debugger_path="Z:/missing-gdb.exe"), controller_factory=lambda _argv: controller)

    session.launch("192.168.1.29", 1234)
    session.close()

    assert controller.exited is True


def test_breakpoint_pending_and_rejected_states() -> None:
    controller = _FakeController()
    controller.responses["-break-insert C:/demo/src/main.cpp:42"] = [
        {"type": "result", "message": "error", "payload": {"msg": "No source file named main.cpp."}}
    ]
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    breakpoints = session.replace_breakpoints([("C:/demo/src/main.cpp", 42)])

    assert breakpoints[0].status == "rejected"
    assert breakpoints[0].verified is False
    assert breakpoints[0].message == "No source file named main.cpp."


def test_evaluate_expression_returns_value() -> None:
    controller = _FakeController()
    controller.responses["-stack-select-frame 0"] = [{"type": "result", "message": "done", "payload": {}}]
    controller.responses['-data-evaluate-expression "argc + 1"'] = [
        {"type": "result", "message": "done", "payload": {"value": "2"}}
    ]
    session = GdbMiSession(_make_profile(), controller_factory=lambda _argv: controller)

    result = session.evaluate_expression("argc + 1", "frame-0")

    assert result == {"expression": "argc + 1", "value": "2"}
