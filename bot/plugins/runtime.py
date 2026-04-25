from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .host_api import PluginHostApi, PluginHostPermissionError, PluginHostContext
from .models import PluginManifest
from .protocol import decode_message, encode_error, encode_request, encode_result, unwrap_result

logger = logging.getLogger(__name__)

PLUGIN_STDIO_STREAM_BUFFER_LIMIT = 1024 * 1024
PLUGIN_STDOUT_READ_CHUNK_BYTES = 64 * 1024
PLUGIN_CALL_TIMEOUT_SECONDS = 60.0
PLUGIN_PYTHON_BOOTSTRAP = (
    "import runpy, sys; "
    "entry=sys.argv[1]; "
    "entry_dir=sys.argv[2]; "
    "plugin_root=sys.argv[3]; "
    "sys.path.insert(0, entry_dir) if entry_dir not in sys.path else None; "
    "sys.path.insert(0, plugin_root) if plugin_root not in sys.path else None; "
    "sys.argv=[entry, *sys.argv[4:]]; "
    "runpy.run_path(entry, run_name='__main__')"
)


@dataclass
class _PluginProcess:
    process: asyncio.subprocess.Process
    request_id: int = 0
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    stderr_task: asyncio.Task[None] | None = None
    reader_task: asyncio.Task[None] | None = None
    last_used_at: float = field(default_factory=lambda: asyncio.get_running_loop().time())
    active_calls: int = 0


class PluginRuntime:
    def __init__(
        self,
        *,
        workspace_root_for: Callable[[str], Path] | None = None,
        host_api: PluginHostApi | None = None,
        audit_hook: Callable[[dict[str, Any]], None] | None = None,
        call_timeout_seconds: float = PLUGIN_CALL_TIMEOUT_SECONDS,
        idle_timeout_seconds: float = 10 * 60,
    ) -> None:
        self._workspace_root_for = workspace_root_for or (lambda _alias: Path.cwd())
        self._host_api = host_api or PluginHostApi(ArtifactStore(Path.cwd()))
        self._audit_hook = audit_hook
        self._call_timeout_seconds = call_timeout_seconds
        self._idle_timeout_seconds = idle_timeout_seconds
        self._processes: dict[tuple[str, str], _PluginProcess] = {}
        self._manifests: dict[tuple[str, str], PluginManifest] = {}

    def active_process_count(self) -> int:
        return sum(1 for wrapped in self._processes.values() if wrapped.process.returncode is None)

    def _context_payload(self, bot_alias: str, manifest: PluginManifest) -> dict[str, Any]:
        workspace_root = self._workspace_root_for(bot_alias).expanduser().resolve()
        return {
            "plugin": {
                "id": manifest.plugin_id,
                "version": manifest.version,
                "config": dict(manifest.config),
            },
            "host": {
                "apiVersion": 1,
                "botAlias": bot_alias,
                "workspaceRoot": str(workspace_root),
                "permissions": {
                    "workspaceRead": manifest.runtime.permissions.workspace_read,
                    "workspaceList": manifest.runtime.permissions.workspace_list,
                    "tempArtifacts": manifest.runtime.permissions.temp_artifacts,
                },
            },
        }

    async def _read_stderr(
        self,
        key: tuple[str, str],
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.stderr is None:
            return
        bot_alias, plugin_id = key
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("plugin[%s:%s] stderr: %s", bot_alias, plugin_id, text)
        except asyncio.CancelledError:
            return

    async def _write_message(self, wrapped: _PluginProcess, payload: bytes) -> None:
        process = wrapped.process
        if process.returncode is not None:
            raise RuntimeError(f"插件进程已退出: {process.returncode}")
        if process.stdin is None:
            raise RuntimeError("插件进程 stdin 不可用")
        async with wrapped.write_lock:
            process.stdin.write(payload)
            await process.stdin.drain()

    def _fail_pending(self, wrapped: _PluginProcess, message: str) -> None:
        for future in list(wrapped.pending.values()):
            if not future.done():
                future.set_exception(RuntimeError(message))
        wrapped.pending.clear()

    def _handle_incoming_message(
        self,
        key: tuple[str, str],
        wrapped: _PluginProcess,
        message: dict[str, Any],
    ) -> None:
        if "method" in message:
            asyncio.create_task(self._dispatch_plugin_request(key, wrapped, message))
            return
        try:
            response_id = int(message.get("id"))
        except Exception:
            return
        future = wrapped.pending.pop(response_id, None)
        if future is not None and not future.done():
            future.set_result(message)

    async def _reader_loop(self, key: tuple[str, str], wrapped: _PluginProcess) -> None:
        process = wrapped.process
        if process.stdout is None:
            self._fail_pending(wrapped, "插件进程 stdout 不可用")
            return
        pending = bytearray()
        try:
            while True:
                chunk = await process.stdout.read(PLUGIN_STDOUT_READ_CHUNK_BYTES)
                if not chunk:
                    if pending.strip():
                        self._handle_incoming_message(key, wrapped, decode_message(bytes(pending)))
                    self._fail_pending(wrapped, "插件未返回结果")
                    return
                pending.extend(chunk)
                while True:
                    line_end = pending.find(b"\n")
                    if line_end < 0:
                        break
                    line = bytes(pending[:line_end + 1])
                    del pending[:line_end + 1]
                    if not line.strip():
                        continue
                    self._handle_incoming_message(key, wrapped, decode_message(line))
        except asyncio.CancelledError:
            self._fail_pending(wrapped, "插件 reader 已取消")
            raise
        except Exception as exc:
            self._fail_pending(wrapped, str(exc))

    async def _dispatch_plugin_request(
        self,
        key: tuple[str, str],
        wrapped: _PluginProcess,
        message: dict[str, Any],
    ) -> None:
        bot_alias, plugin_id = key
        manifest = self._manifests.get(key)
        request_id = int(message.get("id") or 0)
        method = str(message.get("method") or "")
        params = dict(message.get("params") or {})
        if manifest is None:
            await self._write_message(wrapped, encode_error(request_id, f"unknown plugin runtime: {plugin_id}"))
            return

        permission_denied = False
        artifact_id = ""
        artifact_bytes = 0
        try:
            result = await self._host_api.dispatch(
                PluginHostContext(
                    bot_alias=bot_alias,
                    plugin_id=plugin_id,
                    workspace_root=self._workspace_root_for(bot_alias).expanduser().resolve(),
                ),
                manifest,
                method,
                params,
            )
            artifact_id = str(result.get("artifactId") or "")
            artifact_bytes = int(result.get("sizeBytes") or 0)
            await self._write_message(wrapped, encode_result(request_id, result))
        except PluginHostPermissionError as exc:
            permission_denied = True
            await self._write_message(wrapped, encode_error(request_id, str(exc)))
        except Exception as exc:
            await self._write_message(wrapped, encode_error(request_id, str(exc)))
        finally:
            if self._audit_hook is not None:
                self._audit_hook(
                    {
                        "event": "host_api",
                        "plugin_id": plugin_id,
                        "bot_alias": bot_alias,
                        "host_api_method": method,
                        "permission_denied": permission_denied,
                        "artifact_id": artifact_id,
                        "artifact_bytes": artifact_bytes,
                    }
                )

    async def _invoke(self, wrapped: _PluginProcess, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = wrapped.process
        if process.returncode is not None:
            raise RuntimeError(f"插件进程已退出: {process.returncode}")
        wrapped.request_id += 1
        request_id = wrapped.request_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        wrapped.pending[request_id] = future
        try:
            await self._write_message(wrapped, encode_request(request_id, method, params))
            message = await future
        finally:
            wrapped.pending.pop(request_id, None)
        return unwrap_result(message)

    async def _spawn_process(self, bot_alias: str, manifest: PluginManifest) -> _PluginProcess:
        if manifest.runtime.runtime_type != "python":
            raise ValueError(f"unsupported runtime: {manifest.runtime.runtime_type}")
        if manifest.runtime.protocol != "jsonrpc-stdio":
            raise ValueError(f"unsupported protocol: {manifest.runtime.protocol}")

        entry_path = (manifest.root / manifest.runtime.entry).resolve()
        entry = str(entry_path)
        env = dict(os.environ)
        # Plugins speak JSON-RPC over stdio and the protocol decoder is UTF-8-only.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            PLUGIN_PYTHON_BOOTSTRAP,
            entry,
            str(entry_path.parent),
            str(manifest.root),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(manifest.root),
            env=env,
            limit=PLUGIN_STDIO_STREAM_BUFFER_LIMIT,
        )
        key = (bot_alias, manifest.plugin_id)
        wrapped = _PluginProcess(process=process)
        self._processes[key] = wrapped
        self._manifests[key] = manifest
        wrapped.stderr_task = asyncio.create_task(self._read_stderr(key, process))
        wrapped.reader_task = asyncio.create_task(self._reader_loop(key, wrapped))
        await self._invoke(
            wrapped,
            "plugin.initialize",
            {
                "context": self._context_payload(bot_alias, manifest),
            },
        )
        return wrapped

    async def _ensure_process(self, bot_alias: str, manifest: PluginManifest) -> _PluginProcess:
        key = (bot_alias, manifest.plugin_id)
        existing = self._processes.get(key)
        if existing is not None and existing.process.returncode is None:
            return existing
        return await self._spawn_process(bot_alias, manifest)

    async def _call(self, bot_alias: str, manifest: PluginManifest, method: str, params: dict[str, Any]) -> dict[str, Any]:
        wrapped = await self._ensure_process(bot_alias, manifest)
        wrapped.active_calls += 1
        try:
            return await asyncio.wait_for(self._invoke(wrapped, method, params), timeout=self._call_timeout_seconds)
        except asyncio.TimeoutError as exc:
            await self.stop_plugin(bot_alias, manifest.plugin_id)
            raise RuntimeError(f"插件响应超时: {manifest.plugin_id}") from exc
        finally:
            wrapped.active_calls = max(0, wrapped.active_calls - 1)
            wrapped.last_used_at = asyncio.get_running_loop().time()

    async def render_view(self, bot_alias: str, manifest: PluginManifest, view_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            bot_alias,
            manifest,
            "plugin.render_view",
            {
                "viewId": view_id,
                "input": input_payload,
                "context": self._context_payload(bot_alias, manifest),
            },
        )

    async def open_view(self, bot_alias: str, manifest: PluginManifest, view_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(
            bot_alias,
            manifest,
            "plugin.open_view",
            {
                "viewId": view_id,
                "input": input_payload,
                "context": self._context_payload(bot_alias, manifest),
            },
        )

    async def get_view_window(
        self,
        bot_alias: str,
        manifest: PluginManifest,
        session_id: str,
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._call(
            bot_alias,
            manifest,
            "plugin.get_view_window",
            {
                "sessionId": session_id,
                **request_payload,
                "context": self._context_payload(bot_alias, manifest),
            },
        )

    async def invoke_action(
        self,
        bot_alias: str,
        manifest: PluginManifest,
        *,
        view_id: str,
        session_id: str | None,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._call(
            bot_alias,
            manifest,
            "plugin.invoke_action",
            {
                "viewId": view_id,
                "sessionId": session_id or "",
                "actionId": action_id,
                "payload": payload,
                "context": self._context_payload(bot_alias, manifest),
            },
        )

    async def dispose_view(self, bot_alias: str, manifest: PluginManifest, session_id: str) -> dict[str, Any]:
        return await self._call(
            bot_alias,
            manifest,
            "plugin.dispose_view",
            {
                "sessionId": session_id,
                "context": self._context_payload(bot_alias, manifest),
            },
        )

    async def _stop_process(self, key: tuple[str, str], wrapped: _PluginProcess) -> None:
        process = wrapped.process
        manifest = self._manifests.get(key)
        if process.returncode is None and manifest is not None:
            try:
                await asyncio.wait_for(
                    self._invoke(wrapped, "plugin.shutdown", {"context": self._context_payload(key[0], manifest)}),
                    timeout=3,
                )
            except Exception:
                pass
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._fail_pending(wrapped, "插件进程已停止")
        tasks = [task for task in (wrapped.reader_task, wrapped.stderr_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_plugin(self, bot_alias: str, plugin_id: str) -> None:
        key = (bot_alias, plugin_id)
        wrapped = self._processes.pop(key, None)
        self._manifests.pop(key, None)
        if wrapped is not None:
            await self._stop_process(key, wrapped)

    async def stop_plugin_instances(self, plugin_id: str) -> None:
        keys = [key for key in self._processes.keys() if key[1] == plugin_id]
        for key in keys:
            wrapped = self._processes.pop(key, None)
            self._manifests.pop(key, None)
            if wrapped is not None:
                await self._stop_process(key, wrapped)

    async def evict_idle_processes(self) -> int:
        now = asyncio.get_running_loop().time()
        stopped = 0
        for key, wrapped in list(self._processes.items()):
            if wrapped.process.returncode is not None:
                self._processes.pop(key, None)
                self._manifests.pop(key, None)
                continue
            if wrapped.active_calls > 0:
                continue
            if now - wrapped.last_used_at < self._idle_timeout_seconds:
                continue
            await self._stop_process(key, wrapped)
            self._processes.pop(key, None)
            self._manifests.pop(key, None)
            stopped += 1
        return stopped

    async def shutdown(self) -> None:
        processes = list(self._processes.items())
        self._processes = {}
        self._manifests = {}
        for key, wrapped in processes:
            await self._stop_process(key, wrapped)
