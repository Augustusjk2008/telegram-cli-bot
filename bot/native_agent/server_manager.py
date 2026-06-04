from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bot.config as config
from bot.cli import resolve_cli_executable
from bot.native_agent.client import NativeAgentClient, NativeAgentServerRef
from bot.platform.executables import build_executable_invocation


@dataclass
class NativeAgentServerHandle:
    key: str
    base_url: str
    password: str
    username: str
    process: asyncio.subprocess.Process | None = None

    def client(self) -> NativeAgentClient:
        return NativeAgentClient(NativeAgentServerRef(self.base_url, self.password, self.username))


class NativeAgentServerManager:
    def __init__(self) -> None:
        self._handle: NativeAgentServerHandle | None = None
        self._lock = asyncio.Lock()

    def _config_hash(self, server_config: dict[str, Any]) -> str:
        material = "|".join(
            [
                str(server_config.get("command") or "opencode"),
                str(server_config.get("hostname") or "127.0.0.1"),
                str(server_config.get("port") or 0),
                str(server_config.get("password") or ""),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    def _server_key(self, server_config: dict[str, Any]) -> str:
        return f"global:{self._config_hash(server_config)}"

    def _current_config(self) -> dict[str, Any]:
        command = str(config.NATIVE_AGENT_COMMAND or config.NATIVE_AGENT_PATH or "opencode").strip() or "opencode"
        hostname = str(config.NATIVE_AGENT_HOST or "127.0.0.1").strip() or "127.0.0.1"
        try:
            configured_port = min(65535, max(0, int(config.NATIVE_AGENT_PORT or 0)))
        except (TypeError, ValueError):
            configured_port = 0
        password = str(config.NATIVE_AGENT_SERVER_PASSWORD or "").strip()
        return {
            "command": command,
            "hostname": hostname,
            "port": configured_port,
            "password": password,
        }

    def _pick_port(self, hostname: str) -> int:
        bind_host = str(hostname or "127.0.0.1").strip() or "127.0.0.1"
        bind_host = bind_host.strip("[]")
        family = socket.AF_INET6 if ":" in bind_host and bind_host != "0.0.0.0" else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((bind_host, 0))
                return int(sock.getsockname()[1])
        except OSError:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return int(sock.getsockname()[1])

    async def ensure_started(self) -> NativeAgentServerHandle:
        if not config.NATIVE_AGENT_ENABLED:
            raise RuntimeError("原生 agent 服务未启用")
        server_config = self._current_config()
        key = self._server_key(server_config)
        async with self._lock:
            existing = self._handle
            if existing is not None and existing.key == key and await self._is_healthy(existing):
                return existing
            if existing is not None:
                await self._stop_handle(existing)
                self._handle = None
            handle = await self._start_server(key=key, server_config=server_config)
            self._handle = handle
            return handle

    async def get_existing(self) -> NativeAgentServerHandle | None:
        async with self._lock:
            existing = self._handle
            if existing is None:
                return None
            if await self._is_healthy(existing):
                return existing
            await self._stop_handle(existing)
            self._handle = None
            return None

    async def _is_healthy(self, handle: NativeAgentServerHandle) -> bool:
        process = handle.process
        if process is not None and process.returncode is not None:
            return False
        try:
            await handle.client().health()
            return True
        except Exception:
            return False

    def _resolve_command(self, command: str) -> list[str]:
        resolved = resolve_cli_executable(command, config.WORKING_DIR)
        if resolved:
            return build_executable_invocation(resolved)
        return [command]

    def _format_base_url(self, hostname: str, port: int) -> str:
        normalized = str(hostname or "127.0.0.1").strip() or "127.0.0.1"
        if ":" in normalized and not normalized.startswith("["):
            normalized = f"[{normalized}]"
        return f"http://{normalized}:{port}"

    async def _start_server(self, *, key: str, server_config: dict[str, Any]) -> NativeAgentServerHandle:
        command = str(server_config.get("command") or "opencode").strip() or "opencode"
        hostname = str(server_config.get("hostname") or "127.0.0.1").strip() or "127.0.0.1"
        configured_port = int(server_config.get("port") or 0)
        port = configured_port if configured_port > 0 else self._pick_port(hostname)
        password = str(server_config.get("password") or "").strip() or secrets.token_urlsafe(24)
        username = "opencode"
        env = os.environ.copy()
        env["OPENCODE_SERVER_USERNAME"] = username
        env["OPENCODE_SERVER_PASSWORD"] = password
        invocation = self._resolve_command(command)
        process = await asyncio.create_subprocess_exec(
            *invocation,
            "serve",
            "--hostname",
            hostname,
            "--port",
            str(port),
            cwd=str(Path(config.WORKING_DIR).expanduser().resolve()),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        handle = NativeAgentServerHandle(
            key=key,
            base_url=self._format_base_url(hostname, port),
            password=password,
            username=username,
            process=process,
        )
        last_error: Exception | None = None
        for _ in range(50):
            if process.returncode is not None:
                break
            try:
                await handle.client().health()
                return handle
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        await self._stop_handle(handle)
        raise RuntimeError(f"原生 agent 服务启动失败: {last_error or '进程已退出'}")

    async def _stop_handle(self, handle: NativeAgentServerHandle) -> None:
        process = handle.process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def stop_all(self) -> None:
        async with self._lock:
            handle = self._handle
            self._handle = None
        if handle is not None:
            await self._stop_handle(handle)


SERVER_MANAGER = NativeAgentServerManager()
