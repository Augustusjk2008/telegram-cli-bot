from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_kill_process_uses_async_process_tree_terminator(monkeypatch) -> None:
    import bot.debug.prepare_runner as prepare_runner

    calls: list[object] = []

    async def fake_terminate(process: object) -> None:
        calls.append(process)

    process = object()
    monkeypatch.setattr(prepare_runner, "terminate_async_process_tree", fake_terminate, raising=False)

    await prepare_runner._kill_process(process)

    assert calls == [process]


@pytest.mark.asyncio
async def test_stream_prepare_events_creates_process_group(monkeypatch, tmp_path) -> None:
    import bot.debug.prepare_runner as prepare_runner

    captured_kwargs: dict[str, object] = {}

    class _FakeStdout:
        async def readline(self) -> bytes:
            await asyncio.sleep(0)
            return b""

    class _FakeProcess:
        stdout = _FakeStdout()
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(prepare_runner, "build_subprocess_group_kwargs", lambda: {"start_new_session": True}, raising=False)
    monkeypatch.setattr(prepare_runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    events = [
        event
        async for event in prepare_runner.stream_prepare_events(
            tmp_path,
            {"prepare_command": "echo ok", "timeoutSeconds": 1},
        )
    ]

    assert events[0]["type"] == "command"
    assert captured_kwargs["start_new_session"] is True
