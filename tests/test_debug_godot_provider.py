from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot.debug.models import DebugProfileV3
from bot.debug.providers.godot import GodotProvider


def _profile(tmp_path: Path, provider_config: dict[str, object] | None = None) -> DebugProfileV3:
    (tmp_path / "project.godot").write_text("[application]\n", encoding="utf-8")
    return DebugProfileV3(
        kind="godot",
        workspace=str(tmp_path),
        config_name="Godot",
        program="godot",
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
        language="gdscript",
        provider_id="godot",
        provider_label="Godot",
        provider_config=provider_config or {"godot": {"launchProcess": True}},
    )


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = None
        self.stderr = None
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return int(self.returncode or 0)

    def finish(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self._done.set()

    def terminate(self) -> None:
        self.terminated = True
        self.finish(0)

    def kill(self) -> None:
        self.killed = True
        self.finish(1)


class _ConfigurationGateDapClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.configuration_done = asyncio.Event()
        self.initialized_sent = False
        self.closed = False

    async def start(self) -> None:
        return None

    async def request(self, command: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        payload = dict(arguments or {})
        self.requests.append((command, payload))
        if command == "launch":
            await self.configuration_done.wait()
        if command == "configurationDone":
            self.configuration_done.set()
        return {}

    async def next_event(self) -> dict[str, object]:
        if not self.initialized_sent:
            self.initialized_sent = True
            return {"event": "initialized"}
        return await asyncio.Future()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_godot_provider_launches_process_with_project_scene_and_remote_debug(tmp_path: Path) -> None:
    process = _FakeProcess()
    launched: list[tuple[list[str], str, dict[str, str]]] = []

    async def launcher(command: list[str], *, cwd: str, env: dict[str, str]):
        launched.append((command, cwd, env))
        return process

    provider = GodotProvider(process_launcher=launcher)
    session = provider.create_session(
        _profile(tmp_path, {"godot": {"remoteDebug": "tcp://127.0.0.1:6007"}})
    )

    await session.launch({"scene": "res://main.tscn", "debugCollisions": True})
    process.finish(7)
    event = await asyncio.wait_for(session.events().__anext__(), timeout=1)
    await session.close()

    command, cwd, _env = launched[0]
    assert command == [
        "godot",
        "--path",
        str(tmp_path),
        "-d",
        "--remote-debug",
        "tcp://127.0.0.1:6007",
        "--debug-collisions",
        "res://main.tscn",
    ]
    assert cwd == str(tmp_path)
    assert event["type"] == "terminated"
    assert event["payload"]["exitCode"] == 7


@pytest.mark.asyncio
async def test_godot_provider_sends_configuration_done_while_dap_launch_is_pending(tmp_path: Path) -> None:
    fake_client = _ConfigurationGateDapClient()
    provider = GodotProvider(dap_client_factory=lambda _profile, _host, _port: fake_client)
    session = provider.create_session(
        _profile(
            tmp_path,
            {
                "godot": {
                    "connectDap": True,
                    "launchProcess": False,
                    "dapHost": "127.0.0.1",
                    "dapPort": 6006,
                    "gamePort": 6007,
                }
            },
        )
    )

    await asyncio.wait_for(session.launch({"scene": "res://main.tscn"}), timeout=1)
    await session.close()

    assert [item[0] for item in fake_client.requests[:3]] == ["initialize", "launch", "configurationDone"]
    assert fake_client.requests[1][1]["project"] == str(tmp_path)
    assert fake_client.requests[1][1]["port"] == 6007
    assert fake_client.requests[1][1]["scene"] == "res://main.tscn"
    assert fake_client.closed is True
