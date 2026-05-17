from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot.debug.models import DebugBreakpoint, DebugFrame, DebugProfileV3, DebugVariable
from bot.debug.providers.cpp_gdb import CppGdbProvider


def _profile(tmp_path: Path) -> DebugProfileV3:
    return DebugProfileV3(
        kind="cpp_remote_gdb",
        workspace=str(tmp_path),
        config_name="C++ Remote Debug",
        program=str(tmp_path / "build" / "app"),
        cwd=str(tmp_path),
        mi_mode="gdb",
        mi_debugger_path="D:/Toolchain/gdb.exe",
        compile_commands=None,
        prepare_command=r".\debug.bat",
        stop_at_entry=True,
        setup_commands=[],
        remote_host="192.168.1.29",
        remote_user="root",
        remote_dir="/home/sast8/tmp",
        remote_port=1234,
        spec_version=3,
        provider_id="cpp-gdb",
        provider_label="C++ GDB",
    )


class _FakeGdbSession:
    def __init__(self, profile):
        self.profile = profile
        self.closed = False
        self.breakpoints: list[DebugBreakpoint] = []

    def launch(self, host: str, port: int) -> list[dict[str, object]]:
        return [{"type": "stopped", "payload": {"reason": "entry", "threadId": "1", "source": "src/main.cpp", "line": 1, "frameId": "frame-0"}}]

    def continue_execution(self) -> list[dict[str, object]]:
        return [{"type": "running", "payload": {}}]

    def pause_execution(self) -> list[dict[str, object]]:
        return [{"type": "stopped", "payload": {"reason": "signal-received", "threadId": "1", "source": "src/main.cpp", "line": 2, "frameId": "frame-0"}}]

    def next_instruction(self) -> list[dict[str, object]]:
        return [{"type": "running", "payload": {}}]

    def step_in(self) -> list[dict[str, object]]:
        return [{"type": "running", "payload": {}}]

    def step_out(self) -> list[dict[str, object]]:
        return [{"type": "running", "payload": {}}]

    def run_to_entry(self, symbol: str = "main") -> list[dict[str, object]]:
        return [{"type": "running", "payload": {}}]

    def replace_breakpoints(self, items):
        self.breakpoints = [item if isinstance(item, DebugBreakpoint) else DebugBreakpoint(source=item[0], line=item[1]) for item in items]
        return self.breakpoints

    def stack_trace(self) -> list[DebugFrame]:
        return [DebugFrame(id="frame-0", name="main", source="src/main.cpp", line=2)]

    def list_locals(self, frame_id: str | None = None) -> list[DebugVariable]:
        return [DebugVariable(name="argc", value="1", type="int")]

    def list_variables(self, variables_reference: str, frame_id: str | None = None) -> list[DebugVariable]:
        if variables_reference.endswith(":locals"):
            return [DebugVariable(name="argc", value="1", type="int")]
        return [DebugVariable(name="child", value="2", type="int")]

    def evaluate_expression(self, expression: str, frame_id: str | None = None) -> dict[str, object]:
        return {"expression": expression, "value": "3"}

    def poll_events(self) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_cpp_gdb_provider_session_wraps_gdb_session(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    provider = CppGdbProvider(gdb_session_factory=_FakeGdbSession)
    session = provider.create_session(profile)

    await session.launch({"remote_host": "127.0.0.1", "remote_port": 4321})
    events = await asyncio.wait_for(session.events().__anext__(), timeout=1)
    stack = await session.stack_trace()
    scopes = await session.scopes("frame-0")
    variables = await session.variables("child-ref")
    result = await session.evaluate("argc + 2", "frame-0")
    breakpoints = await session.set_breakpoints("src/main.cpp", [{"line": 3}])
    await session.stop()

    assert events["type"] == "stopped"
    assert stack[0]["name"] == "main"
    assert scopes[0]["variablesReference"] == "frame-0:locals"
    assert variables[0]["name"] == "child"
    assert result["value"] == "3"
    assert breakpoints[0]["line"] == 3
