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


@pytest.mark.asyncio
async def test_paused_state_preserves_dap_source_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "debug.json").write_text(
        """
{
  "specVersion": 3,
  "providerId": "python-debugpy",
  "language": "python",
  "configName": "Python",
  "target": {
    "program": "${workspaceFolder}/main.py",
    "cwd": "${workspaceFolder}"
  }
}
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    class FakeSession:
        async def launch(self, _payload: dict[str, object]) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def stack_trace(self) -> list[dict[str, object]]:
            return [
                {
                    "id": "1",
                    "name": "main",
                    "source": "",
                    "line": 5,
                    "sourceReference": 99,
                }
            ]

        async def scopes(self, _frame_id: str) -> list[dict[str, object]]:
            return []

        async def variables(self, _variables_reference: str) -> list[dict[str, object]]:
            return []

        def events(self):  # type: ignore[no-untyped-def]
            async def _iter():
                if False:
                    yield {}

            return _iter()

        async def close(self) -> None:
            return None

    class FakeProvider:
        provider_id = "python-debugpy"

        def can_handle(self, profile: DebugProfile) -> bool:
            return profile.provider_id == self.provider_id

        def create_session(self, _profile: DebugProfile) -> FakeSession:
            return FakeSession()

    service = DebugService(object(), providers=[FakeProvider()], poll_interval_seconds=60)
    try:
        await service.handle_ws_message("main", 1001, {"type": "launch", "payload": {}})
        runtime = await service._get_runtime("main", 1001)
        assert runtime.session is not None
        await service._refresh_paused_state(runtime)
        state = await service.get_state("main", 1001)
    finally:
        await service.shutdown()

    assert state["frames"][0]["sourceResolved"] is False
    assert state["frames"][0]["sourceReason"] == "source_reference"
    assert state["frames"][0]["sourceReference"] == 99


@pytest.mark.asyncio
async def test_non_gdb_provider_launch_returns_running_when_no_stop_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "debug.json").write_text(
        """
{
  "specVersion": 3,
  "providerId": "python-debugpy",
  "language": "python",
  "configName": "Python",
  "target": {
    "program": "${workspaceFolder}/main.py",
    "cwd": "${workspaceFolder}"
  }
}
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    class FakeSession:
        async def launch(self, _payload: dict[str, object]) -> None:
            return None

        async def stop(self) -> None:
            return None

        def events(self):  # type: ignore[no-untyped-def]
            async def _iter():
                if False:
                    yield {}

            return _iter()

        async def close(self) -> None:
            return None

    class FakeProvider:
        provider_id = "python-debugpy"
        provider_label = "Python debugpy"

        def can_handle(self, profile: DebugProfile) -> bool:
            return profile.provider_id == self.provider_id

        def create_session(self, _profile: DebugProfile) -> FakeSession:
            return FakeSession()

    service = DebugService(object(), providers=[FakeProvider()], poll_interval_seconds=60)
    try:
        await service.handle_ws_message("main", 1001, {"type": "launch", "payload": {}})
        state = await service.get_state("main", 1001)
    finally:
        await service.shutdown()

    assert state["phase"] == "running"
    assert state["detailPhase"] == "running"


@pytest.mark.asyncio
async def test_launch_passes_dynamic_provider_fields_to_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "debug.json").write_text(
        """
{
  "specVersion": 3,
  "providerId": "godot",
  "language": "gdscript",
  "configName": "Godot",
  "target": {
    "program": "godot",
    "cwd": "${workspaceFolder}"
  },
  "launchDefaults": {
    "scene": "res://main.tscn",
    "debugCollisions": false
  }
}
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    seen_payloads: list[dict[str, object]] = []

    monkeypatch.setattr(
        "bot.debug.service.get_working_directory",
        lambda _manager, _alias, _user_id: {"working_dir": str(tmp_path)},
    )

    class FakeSession:
        async def launch(self, payload: dict[str, object]) -> None:
            seen_payloads.append(dict(payload))

        async def stop(self) -> None:
            return None

        def events(self):  # type: ignore[no-untyped-def]
            async def _iter():
                if False:
                    yield {}

            return _iter()

        async def close(self) -> None:
            return None

    class FakeProvider:
        provider_id = "godot"
        provider_label = "Godot"

        def can_handle(self, profile: DebugProfile) -> bool:
            return profile.provider_id == self.provider_id

        def create_session(self, _profile: DebugProfile) -> FakeSession:
            return FakeSession()

    service = DebugService(object(), providers=[FakeProvider()], poll_interval_seconds=60)
    try:
        await service.handle_ws_message(
            "main",
            1001,
            {
                "type": "launch",
                "payload": {
                    "scene": "res://test_scene.tscn",
                    "debugCollisions": True,
                    "customGodotFlag": "value",
                },
            },
        )
    finally:
        await service.shutdown()

    assert seen_payloads[0]["scene"] == "res://test_scene.tscn"
    assert seen_payloads[0]["debugCollisions"] is True
    assert seen_payloads[0]["customGodotFlag"] == "value"


@pytest.mark.asyncio
async def test_provider_output_events_are_appended_to_prepare_logs() -> None:
    service = DebugService(object(), providers=[], poll_interval_seconds=60)
    runtime = await service._get_runtime("main", 1001)

    await service._apply_debug_event(
        runtime,
        {"type": "output", "payload": {"category": "stdout", "output": "Godot started"}},
    )

    assert runtime.prepare_logs == ["Godot started"]


@pytest.mark.asyncio
async def test_terminated_event_moves_runtime_back_to_idle() -> None:
    service = DebugService(object(), providers=[], poll_interval_seconds=60)
    runtime = await service._get_runtime("main", 1001)
    runtime.state.phase = "running"

    await service._apply_debug_event(runtime, {"type": "terminated", "payload": {"exitCode": 0}})

    assert runtime.state.phase == "idle"
    assert runtime.state.message == "调试已结束"
