from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from .models import PluginManifest
from .protocol import decode_message, encode_request

logger = logging.getLogger(__name__)

PLUGIN_STDIO_LIMIT = 64 * 1024 * 1024


@dataclass
class _PluginProcess:
    process: asyncio.subprocess.Process
    request_id: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stderr_task: asyncio.Task[None] | None = None


class PluginRuntime:
    def __init__(self) -> None:
        self._processes: dict[str, _PluginProcess] = {}
        self._manifests: dict[str, PluginManifest] = {}

    async def _read_stderr(self, plugin_id: str, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("plugin[%s] stderr: %s", plugin_id, text)
        except asyncio.CancelledError:
            return

    async def _invoke(self, wrapped: _PluginProcess, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = wrapped.process
        if process.returncode is not None:
            raise RuntimeError(f"插件进程已退出: {process.returncode}")
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("插件进程 stdio 不可用")
        wrapped.request_id += 1
        request_id = wrapped.request_id
        process.stdin.write(encode_request(request_id, method, params))
        await process.stdin.drain()
        line = await process.stdout.readline()
        if not line:
            raise RuntimeError("插件未返回结果")
        message = decode_message(line)
        if message.get("id") != request_id:
            raise RuntimeError("插件响应 id 不匹配")
        if message.get("error"):
            error = message["error"]
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or "插件执行失败")
            else:
                detail = str(error)
            raise RuntimeError(detail)
        result = message.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("插件 result 不是对象")
        return dict(result)

    async def _spawn_process(self, manifest: PluginManifest) -> _PluginProcess:
        if manifest.runtime.runtime_type != "python":
            raise ValueError(f"unsupported runtime: {manifest.runtime.runtime_type}")
        if manifest.runtime.protocol != "jsonrpc-stdio":
            raise ValueError(f"unsupported protocol: {manifest.runtime.protocol}")

        entry = str((manifest.root / manifest.runtime.entry).resolve())
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            entry,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(manifest.root),
            limit=PLUGIN_STDIO_LIMIT,
        )
        wrapped = _PluginProcess(process=process)
        wrapped.stderr_task = asyncio.create_task(self._read_stderr(manifest.plugin_id, process))
        self._processes[manifest.plugin_id] = wrapped
        self._manifests[manifest.plugin_id] = manifest
        async with wrapped.lock:
            await self._invoke(wrapped, "plugin.initialize", {})
        return wrapped

    async def _ensure_process(self, manifest: PluginManifest) -> _PluginProcess:
        existing = self._processes.get(manifest.plugin_id)
        if existing is not None and existing.process.returncode is None:
            return existing
        return await self._spawn_process(manifest)

    async def _call(self, manifest: PluginManifest, method: str, params: dict[str, Any]) -> dict[str, Any]:
        wrapped = await self._ensure_process(manifest)
        async with wrapped.lock:
            return await self._invoke(wrapped, method, params)

    async def render_view(self, manifest: PluginManifest, view_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            manifest,
            "plugin.render_view",
            {
                "viewId": view_id,
                "input": input_payload,
            },
        )

    async def open_view(self, manifest: PluginManifest, view_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            manifest,
            "plugin.open_view",
            {
                "viewId": view_id,
                "input": input_payload,
            },
        )

    async def get_view_window(self, manifest: PluginManifest, session_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            manifest,
            "plugin.get_view_window",
            {
                "sessionId": session_id,
                **request_payload,
            },
        )

    async def dispose_view(self, manifest: PluginManifest, session_id: str) -> dict[str, Any]:
        return await self._call(
            manifest,
            "plugin.dispose_view",
            {
                "sessionId": session_id,
            },
        )

    async def _stop_process(self, plugin_id: str, wrapped: _PluginProcess) -> None:
        process = wrapped.process
        if process.returncode is None:
            manifest = self._manifests.get(plugin_id)
            if manifest is not None:
                try:
                    async with wrapped.lock:
                        await self._invoke(wrapped, "plugin.shutdown", {})
                except Exception:
                    pass
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if wrapped.stderr_task is not None:
            wrapped.stderr_task.cancel()
            await asyncio.gather(wrapped.stderr_task, return_exceptions=True)

    async def shutdown(self) -> None:
        processes = list(self._processes.items())
        self._processes = {}
        self._manifests = {}
        for plugin_id, wrapped in processes:
            await self._stop_process(plugin_id, wrapped)
