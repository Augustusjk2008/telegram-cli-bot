from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from bot.debug.prepare_runner import PrepareRunError, build_prepare_command, build_prepare_display_command, stream_prepare


class _FakeStdout:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class _FakeProcess:
    def __init__(self, lines: list[bytes], return_code: int = 0):
        self.stdout = _FakeStdout(lines)
        self._return_code = return_code

    async def wait(self) -> int:
        return self._return_code


class _InheritedPipeStdout:
    async def readline(self) -> bytes:
        await asyncio.Event().wait()
        return b""


class _ExitedProcessWithInheritedStdout:
    def __init__(self):
        self.stdout = _InheritedPipeStdout()

    async def wait(self) -> int:
        return 0


def test_build_prepare_command_uses_user_prepare_command_template(tmp_path: Path) -> None:
    request = {
        "remote_host": "192.168.1.77",
        "remote_user": "root",
        "remote_dir": "/tmp/demo",
        "remote_port": 2345,
        "password": "secret",
        "prepare_command": r".\debug.bat -RemoteHost ${remoteHost} -RemoteGdbPort ${remotePort}",
    }

    command = build_prepare_command(tmp_path, request)

    assert command[-1] == r".\debug.bat -RemoteHost 192.168.1.77 -RemoteGdbPort 2345"
    assert command[0] == ("cmd.exe" if os.name == "nt" else "sh")
    assert build_prepare_display_command(request) == r".\debug.bat -RemoteHost 192.168.1.77 -RemoteGdbPort 2345"


@pytest.mark.asyncio
async def test_stream_prepare_emits_redacted_command_and_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = {
        "remote_host": "192.168.1.77",
        "remote_user": "root",
        "remote_dir": "/tmp/demo",
        "remote_port": 2345,
        "password": "secret",
        "prepare_command": r".\debug.bat -Password ${password}",
    }
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        captured["cwd"] = kwargs.get("cwd")
        captured["stdin"] = kwargs.get("stdin")
        return _FakeProcess([b"Password: secret\r\n", b"ready\r\n"])

    monkeypatch.setattr("bot.debug.prepare_runner.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    lines = [line async for line in stream_prepare(tmp_path, request)]

    assert lines == [
        r".\debug.bat -Password ******",
        "Password: ******",
        "ready",
    ]
    assert captured["command"] == build_prepare_command(tmp_path, request)
    assert captured["cwd"] == str(tmp_path)
    assert captured["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_stream_prepare_raises_prepare_failed_with_redacted_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = {
        "remote_host": "192.168.1.77",
        "remote_user": "root",
        "remote_dir": "/tmp/demo",
        "remote_port": 2345,
        "password": "secret",
        "prepare_command": r".\debug.bat -Password ${password}",
    }

    async def fake_create_subprocess_exec(*_command, **_kwargs):
        return _FakeProcess([b"upload secret failed\r\n"], return_code=3)

    monkeypatch.setattr("bot.debug.prepare_runner.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(PrepareRunError) as exc_info:
        [line async for line in stream_prepare(tmp_path, request)]

    assert exc_info.value.code == "prepare_failed"
    assert exc_info.value.logs[0].endswith("-Password ******")
    assert exc_info.value.logs[1] == "upload ****** failed"


@pytest.mark.asyncio
async def test_stream_prepare_does_not_wait_forever_for_inherited_stdout_pipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = {"prepare_command": r".\debug.bat"}

    async def fake_create_subprocess_exec(*_command, **_kwargs):
        return _ExitedProcessWithInheritedStdout()

    monkeypatch.setattr("bot.debug.prepare_runner.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("bot.debug.prepare_runner._EXITED_STDOUT_DRAIN_TIMEOUT_SECONDS", 0.001)

    async def collect_lines() -> list[str]:
        return [line async for line in stream_prepare(tmp_path, request)]

    assert await asyncio.wait_for(collect_lines(), timeout=1) == [r".\debug.bat"]
