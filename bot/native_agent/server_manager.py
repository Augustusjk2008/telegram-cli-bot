from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.native_agent.client import NativeAgentClient, NativeAgentServerRef


@dataclass
class NativeAgentServerHandle:
    key: str
    base_url: str
    password: str
    username: str
    cwd: str
    process: asyncio.subprocess.Process | None = None

    def client(self) -> NativeAgentClient:
        return NativeAgentClient(NativeAgentServerRef(self.base_url, self.password, self.username))


class NativeAgentServerManager:
    def __init__(self) -> None:
        self._servers: dict[str, NativeAgentServerHandle] = {}
        self._lock = asyncio.Lock()

    def _config_hash(self, config: dict[str, Any]) -> str:
        material = "|".join(
            [
                str(config.get("command") or "opencode"),
                str(config.get("hostname") or "127.0.0.1"),
                str(config.get("port") or 0),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    def _server_key(self, *, bot_id: int, cwd: str, config: dict[str, Any]) -> str:
        real_cwd = str(Path(cwd).expanduser().resolve())
        return f"{bot_id}:{real_cwd}:{self._config_hash(config)}"

    def _pick_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def get_server(self, *, bot_id: int, cwd: str, config: dict[str, Any]) -> NativeAgentServerHandle:
        key = self._server_key(bot_id=bot_id, cwd=cwd, config=config)
        async with self._lock:
            existing = self._servers.get(key)
            if existing is not None and await self._is_healthy(existing):
                return existing
            if existing is not None:
                await self._stop_handle(existing)
                self._servers.pop(key, None)
            handle = await self._start_server(key=key, cwd=cwd, config=config)
            self._servers[key] = handle
            return handle

    async def get_existing(self, key: str | None) -> NativeAgentServerHandle | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        async with self._lock:
            return self._servers.get(normalized)

    async def _is_healthy(self, handle: NativeAgentServerHandle) -> bool:
        process = handle.process
        if process is not None and process.returncode is not None:
            return False
        try:
            await handle.client().health()
            return True
        except Exception:
            return False

    async def _start_server(self, *, key: str, cwd: str, config: dict[str, Any]) -> NativeAgentServerHandle:
        command = str(config.get("command") or "opencode").strip() or "opencode"
        hostname = str(config.get("hostname") or "127.0.0.1").strip() or "127.0.0.1"
        configured_port = int(config.get("port") or 0)
        port = configured_port if configured_port > 0 else self._pick_port()
        password = str(config.get("server_password") or "").strip() or secrets.token_urlsafe(24)
        username = "opencode"
        env = os.environ.copy()
        env["OPENCODE_SERVER_USERNAME"] = username
        env["OPENCODE_SERVER_PASSWORD"] = password
        process = await asyncio.create_subprocess_exec(
            command,
            "serve",
            "--hostname",
            hostname,
            "--port",
            str(port),
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        handle = NativeAgentServerHandle(
            key=key,
            base_url=f"http://{hostname}:{port}",
            password=password,
            username=username,
            cwd=str(Path(cwd).expanduser().resolve()),
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
            handles = list(self._servers.values())
            self._servers.clear()
        for handle in handles:
            await self._stop_handle(handle)


SERVER_MANAGER = NativeAgentServerManager()
