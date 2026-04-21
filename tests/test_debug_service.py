from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from bot.debug.models import DebugFrame, DebugProfile, DebugVariable
from bot.debug.service import DebugService


def _write_workspace(root: Path) -> Path:
    vscode_dir = root / ".vscode"
    vscode_dir.mkdir(parents=True)
    (root / "debug.ps1").write_text(
        """
param(
    [string]$RemoteHost = "192.168.1.29",
    [string]$RemoteUser = "root",
    [string]$RemoteDir = "/home/sast8/tmp",
    [int]$RemoteGdbPort = 1234
)
""".strip(),
        encoding="utf-8",
    )
    (root / "debug.bat").write_text("@echo off\r\n", encoding="utf-8")
    program = root / "build" / "aarch64" / "Debug" / "MB_DDF"
    (vscode_dir / "launch.json").write_text(
        f"""
{{
  "version": "0.2.0",
  "configurations": [
    {{
      "name": "(gdb) Remote Debug",
      "type": "cppdbg",
      "request": "launch",
      "program": "{str(program).replace(chr(92), chr(92) + chr(92))}",
      "cwd": "${{workspaceFolder}}",
      "stopAtEntry": true,
      "MIMode": "gdb",
      "miDebuggerPath": "D:\\\\Toolchain\\\\aarch64-none-linux-gnu-gdb.exe",
      "miDebuggerServerAddress": "192.168.1.29:1234",
      "setupCommands": []
    }}
  ]
}}
""".strip(),
        encoding="utf-8",
    )
    return program


def test_resolve_source_path_maps_remote_dir_to_workspace(tmp_path: Path) -> None:
    service = DebugService(object())

    assert service._resolve_source_path(tmp_path, "/home/sast8/tmp/src/main.cpp", "/home/sast8/tmp") == str(
        (tmp_path / "src" / "main.cpp").resolve()
    )


@pytest.mark.asyncio
async def test_launch_runs_prepare_before_requiring_program(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    program = _write_workspace(tmp_path)
    prepare_requests: list[dict[str, object]] = []
    launched: list[tuple[DebugProfile, str, int]] = []

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    async def fake_stream_prepare(_workspace: Path, request: dict[str, object]) -> AsyncIterator[str]:
        prepare_requests.append(dict(request))
        program.parent.mkdir(parents=True)
        program.write_text("built", encoding="utf-8")
        yield "prepared"

    class FakeGdbSession:
        def __init__(self, profile: DebugProfile):
            self.profile = profile

        def launch(self, host: str, port: int) -> None:
            launched.append((self.profile, host, port))

        def stack_trace(self) -> list[DebugFrame]:
            return [DebugFrame(id="frame-0", name="main", source=str(tmp_path / "src" / "main.cpp"), line=1)]

        def list_locals(self, _frame_id: str | None = None) -> list[DebugVariable]:
            return []

        def poll_events(self) -> list[dict[str, object]]:
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr("bot.debug.service.stream_prepare", fake_stream_prepare)

    service = DebugService(object(), gdb_session_factory=FakeGdbSession, poll_interval_seconds=60)
    try:
        await service.handle_ws_message(
            "main",
            1001,
            {
                "type": "launch",
                "payload": {
                    "remoteHost": "192.168.1.77",
                    "remoteUser": "root",
                    "remoteDir": "/tmp/demo",
                    "remotePort": 2345,
                    "prepareCommand": r".\debug.bat",
                    "stopAtEntry": True,
                },
            },
        )
    finally:
        await service.shutdown()

    assert prepare_requests[0]["prepare_command"] == r".\debug.bat"
    assert launched[0][0].program == str(program)
    assert launched[0][1:] == ("192.168.1.77", 2345)


@pytest.mark.asyncio
async def test_launch_uses_stopped_event_from_target_select_to_enter_paused_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    program = _write_workspace(tmp_path)

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    async def fake_stream_prepare(_workspace: Path, _request: dict[str, object]) -> AsyncIterator[str]:
        program.parent.mkdir(parents=True)
        program.write_text("built", encoding="utf-8")
        yield "prepared"

    class FakeGdbSession:
        def __init__(self, _profile: DebugProfile):
            return None

        def launch(self, _host: str, _port: int) -> list[dict[str, object]]:
            return [
                {
                    "type": "stopped",
                    "payload": {
                        "reason": "entry",
                        "threadId": "1",
                        "source": str(tmp_path / "src" / "main.cpp"),
                        "line": 1,
                        "frameId": "frame-0",
                    },
                }
            ]

        def stack_trace(self) -> list[DebugFrame]:
            return [
                DebugFrame(
                    id="frame-0",
                    name="main",
                    source=str(tmp_path / "src" / "main.cpp"),
                    line=1,
                )
            ]

        def list_locals(self, _frame_id: str | None = None) -> list[DebugVariable]:
            return [DebugVariable(name="argc", value="1", type="int")]

        def poll_events(self) -> list[dict[str, object]]:
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr("bot.debug.service.stream_prepare", fake_stream_prepare)

    service = DebugService(object(), gdb_session_factory=FakeGdbSession, poll_interval_seconds=60)
    try:
        await service.handle_ws_message(
            "main",
            1001,
            {
                "type": "launch",
                "payload": {
                    "prepareCommand": r".\debug.bat",
                    "stopAtEntry": True,
                },
            },
        )
        state = await service.get_state("main", 1001)
    finally:
        await service.shutdown()

    assert state["phase"] == "paused"
    assert state["frames"][0]["name"] == "main"
    assert state["variables"]["frame-0:locals"][0]["name"] == "argc"


@pytest.mark.asyncio
async def test_launch_runs_to_main_when_initial_stop_has_no_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    program = _write_workspace(tmp_path)
    run_to_entry_calls: list[str] = []

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    async def fake_stream_prepare(_workspace: Path, _request: dict[str, object]) -> AsyncIterator[str]:
        program.parent.mkdir(parents=True)
        program.write_text("built", encoding="utf-8")
        yield "prepared"

    class FakeGdbSession:
        def __init__(self, _profile: DebugProfile):
            return None

        def launch(self, _host: str, _port: int) -> list[dict[str, object]]:
            return [{"type": "stopped", "payload": {"reason": "entry", "source": "", "line": 0}}]

        def stack_trace(self) -> list[DebugFrame]:
            return [DebugFrame(id="frame-0", name="??", source="", line=0)]

        def list_locals(self, _frame_id: str | None = None) -> list[DebugVariable]:
            return []

        def run_to_entry(self, symbol: str = "main") -> None:
            run_to_entry_calls.append(symbol)

        def poll_events(self) -> list[dict[str, object]]:
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr("bot.debug.service.stream_prepare", fake_stream_prepare)

    service = DebugService(object(), gdb_session_factory=FakeGdbSession, poll_interval_seconds=60)
    try:
        await service.handle_ws_message(
            "main",
            1001,
            {"type": "launch", "payload": {"prepareCommand": r".\debug.bat", "stopAtEntry": True}},
        )
        state = await service.get_state("main", 1001)
    finally:
        await service.shutdown()

    assert run_to_entry_calls == ["main"]
    assert state["phase"] == "running"
    assert state["message"] == "运行到入口"
    assert state["frames"] == []


@pytest.mark.asyncio
async def test_pause_uses_stopped_event_returned_by_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    program = _write_workspace(tmp_path)

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    async def fake_stream_prepare(_workspace: Path, _request: dict[str, object]) -> AsyncIterator[str]:
        program.parent.mkdir(parents=True)
        program.write_text("built", encoding="utf-8")
        yield "prepared"

    class FakeGdbSession:
        def __init__(self, _profile: DebugProfile):
            return None

        def launch(self, _host: str, _port: int) -> list[dict[str, object]]:
            return []

        def continue_execution(self) -> list[dict[str, object]]:
            return []

        def pause_execution(self) -> list[dict[str, object]]:
            return [{"type": "stopped", "payload": {"reason": "signal-received", "source": "src/main.cpp", "line": 2}}]

        def stack_trace(self) -> list[DebugFrame]:
            return [DebugFrame(id="frame-0", name="main", source="src/main.cpp", line=2)]

        def list_locals(self, _frame_id: str | None = None) -> list[DebugVariable]:
            return []

        def poll_events(self) -> list[dict[str, object]]:
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr("bot.debug.service.stream_prepare", fake_stream_prepare)

    service = DebugService(object(), gdb_session_factory=FakeGdbSession, poll_interval_seconds=60)
    try:
        await service.handle_ws_message(
            "main",
            1001,
            {"type": "launch", "payload": {"prepareCommand": r".\debug.bat", "stopAtEntry": False}},
        )
        await service.handle_ws_message("main", 1001, {"type": "pause"})
        state = await service.get_state("main", 1001)
    finally:
        await service.shutdown()

    assert state["phase"] == "paused"
    assert state["frames"][0]["line"] == 2
