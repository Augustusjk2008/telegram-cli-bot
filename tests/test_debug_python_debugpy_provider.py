from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from bot.debug.models import DebugProfileV3
from bot.debug.providers.python_debugpy import PythonDebugpyProvider
from bot.debug.providers import python_debugpy


def _profile(tmp_path: Path) -> DebugProfileV3:
    main_file = tmp_path / "main.py"
    main_file.write_text("print('ok')\n", encoding="utf-8")
    return DebugProfileV3(
        kind="python",
        workspace=str(tmp_path),
        config_name="Python: Current File",
        program=str(main_file),
        cwd=str(tmp_path),
        mi_mode="",
        mi_debugger_path="",
        compile_commands=None,
        prepare_command="",
        stop_at_entry=False,
        setup_commands=[],
        remote_host="",
        remote_user="",
        remote_dir="",
        remote_port=0,
        spec_version=3,
        language="python",
        provider_id="python-debugpy",
        provider_label="Python debugpy",
        provider_config={"dap": {"module": "debugpy.adapter", "request": "launch"}},
    )


class _FakeDapClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.closed = False

    async def start(self) -> None:
        return None

    async def request(self, command: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        payload = dict(arguments or {})
        self.requests.append((command, payload))
        if command == "stackTrace":
            return {"stackFrames": [{"id": 1, "name": "main", "source": {"path": payload.get("path", "main.py"), "sourceReference": 99}, "line": 3}]}
        if command == "scopes":
            return {"scopes": [{"name": "Locals", "variablesReference": 10}]}
        if command == "variables":
            return {"variables": [{"name": "argc", "value": "1", "type": "int"}]}
        if command == "evaluate":
            return {"result": "2", "variablesReference": 0}
        if command == "setBreakpoints":
            return {"breakpoints": [{"verified": True, "line": 3}]}
        return {}

    async def close(self) -> None:
        self.closed = True

    async def emit(self, event: dict[str, object]) -> None:
        await self._events.put(event)

    async def next_event(self) -> dict[str, object]:
        return await self._events.get()


class _ConfigurationGateDapClient:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.configuration_done = asyncio.Event()
        self.initialized_sent = False

    async def start(self) -> None:
        return None

    async def request(self, command: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append(command)
        if command == "launch":
            await self.configuration_done.wait()
        if command == "configurationDone":
            self.configuration_done.set()
        return {}

    async def close(self) -> None:
        return None

    async def next_event(self) -> dict[str, object]:
        if not self.initialized_sent:
            self.initialized_sent = True
            return {"event": "initialized"}
        return await asyncio.Future()


@pytest.mark.asyncio
async def test_python_debugpy_provider_session_sends_dap_requests(tmp_path: Path) -> None:
    fake_client = _FakeDapClient()
    provider = PythonDebugpyProvider(
        dap_client_factory=lambda _profile: fake_client,
        adapter_launcher=lambda _profile: None,
    )
    session = provider.create_session(_profile(tmp_path))

    await fake_client.emit({"event": "initialized"})
    await fake_client.emit({"event": "stopped", "body": {"reason": "breakpoint", "threadId": 1}})
    await session.launch({})
    event = await asyncio.wait_for(session.events().__anext__(), timeout=1)
    stack = await session.stack_trace()
    scopes = await session.scopes("1")
    variables = await session.variables("10")
    evaluation = await session.evaluate("1+1", "1")
    breakpoints = await session.set_breakpoints(str(tmp_path / "main.py"), [{"line": 3}])
    await session.close()

    assert event["type"] == "stopped"
    assert stack[0]["name"] == "main"
    assert stack[0]["sourceReference"] == 99
    assert scopes[0]["variablesReference"] == "10"
    assert variables[0]["name"] == "argc"
    assert evaluation["value"] == "2"
    assert breakpoints[0]["verified"] is True
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_python_debugpy_provider_sends_workspace_absolute_breakpoint_path(tmp_path: Path) -> None:
    fake_client = _FakeDapClient()
    provider = PythonDebugpyProvider(
        dap_client_factory=lambda _profile: fake_client,
        adapter_launcher=lambda _profile: None,
    )
    session = provider.create_session(_profile(tmp_path))

    await fake_client.emit({"event": "initialized"})
    await session.launch({})
    await session.set_breakpoints("main.py", [{"line": 3}])
    await session.close()

    breakpoint_request = next(payload for command, payload in fake_client.requests if command == "setBreakpoints")
    source = breakpoint_request["source"]
    assert isinstance(source, dict)
    assert source["path"] == str((tmp_path / "main.py").resolve())


@pytest.mark.asyncio
async def test_python_debugpy_provider_sends_configuration_done_while_launch_is_pending(tmp_path: Path) -> None:
    fake_client = _ConfigurationGateDapClient()
    provider = PythonDebugpyProvider(dap_client_factory=lambda _profile: fake_client)
    session = provider.create_session(_profile(tmp_path))

    await asyncio.wait_for(session.launch({}), timeout=1)
    await session.close()

    assert fake_client.requests[:3] == ["initialize", "launch", "configurationDone"]


@pytest.mark.asyncio
async def test_default_debugpy_adapter_uses_current_python_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(python_debugpy.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    process = await python_debugpy._default_adapter_launcher(_profile(tmp_path))

    assert process is not None
    assert captured["args"][:3] == (sys.executable, "-m", "debugpy.adapter")
