from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.models import (
    PluginHostLimits,
    PluginManifest,
    PluginPermissions,
    PluginRuntimeSpec,
    PluginViewSpec,
)
from bot.plugins.protocol import decode_message
from bot.plugins.runtime import PLUGIN_MAX_FRAME_BYTES, PluginRuntime, _PluginProcess


def _manifest(root: Path) -> PluginManifest:
    return PluginManifest(
        root=root,
        plugin_id="test-plugin",
        schema_version=2,
        name="Test",
        version="1.0.0",
        description="",
        enabled=True,
        config={},
        runtime=PluginRuntimeSpec(
            runtime_type="python",
            entry="main.py",
            protocol="jsonrpc-stdio",
            permissions=PluginPermissions(workspace_read=True),
            limits=PluginHostLimits(),
        ),
        views=(PluginViewSpec(id="main", title="Main", renderer="document"),),
        file_handlers=(),
    )


class _FakeStdin:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def write(self, payload: bytes) -> None:
        self.payloads.append(payload)

    async def drain(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, stdout: asyncio.StreamReader | None = None) -> None:
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self.stdout = stdout
        self.stderr = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


@pytest.mark.asyncio
async def test_host_api_concurrency_rejects_excess_and_tracks_active_tasks(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowHostApi(PluginHostApi):
        async def dispatch(self, *args, **kwargs):
            started.set()
            await release.wait()
            return {"ok": True}

    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: tmp_path,
        host_api=SlowHostApi(ArtifactStore(tmp_path)),
        host_api_concurrency=1,
    )
    process = _FakeProcess()
    wrapped = _PluginProcess(process=process, host_api_semaphore=asyncio.Semaphore(1))
    key = ("main", "test-plugin")
    runtime._manifests[key] = _manifest(tmp_path)

    await runtime._handle_incoming_message(key, wrapped, {"id": 1, "method": "host.workspace.stat", "params": {}})
    await started.wait()
    await runtime._handle_incoming_message(key, wrapped, {"id": 2, "method": "host.workspace.stat", "params": {}})
    await asyncio.sleep(0)

    assert wrapped.host_api_active == 1
    assert len(wrapped.host_api_tasks) == 1
    assert decode_message(process.stdin.payloads[-1])["error"]["message"] == "插件 Host API 并发请求超限，请稍后重试"

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert wrapped.host_api_active == 0
    assert not wrapped.host_api_tasks


@pytest.mark.asyncio
async def test_oversized_unterminated_stdout_frame_stops_plugin_and_fails_pending(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.plugins.runtime.PLUGIN_MAX_FRAME_BYTES", 16)
    reader = asyncio.StreamReader()
    process = _FakeProcess(reader)
    runtime = PluginRuntime(workspace_root_for=lambda _alias: tmp_path)
    wrapped = _PluginProcess(process=process, host_api_semaphore=asyncio.Semaphore(1))
    pending = asyncio.get_running_loop().create_future()
    wrapped.pending[1] = pending
    key = ("main", "test-plugin")
    runtime._processes[key] = wrapped
    runtime._manifests[key] = _manifest(tmp_path)

    task = asyncio.create_task(runtime._reader_loop(key, wrapped))
    reader.feed_data(b"x" * 17)
    await task

    with pytest.raises(RuntimeError, match="协议帧超过"):
        await pending
    assert process.terminated is True
    assert key not in runtime._processes


@pytest.mark.asyncio
async def test_stop_process_cancels_inflight_host_api_tasks(tmp_path: Path) -> None:
    runtime = PluginRuntime(workspace_root_for=lambda _alias: tmp_path)
    process = _FakeProcess()
    wrapped = _PluginProcess(process=process, host_api_semaphore=asyncio.Semaphore(1))
    blocked = asyncio.create_task(asyncio.Event().wait())
    wrapped.host_api_tasks.add(blocked)

    await runtime._stop_process(("main", "test-plugin"), wrapped, send_shutdown=False)

    assert blocked.cancelled()
    assert not wrapped.host_api_tasks
