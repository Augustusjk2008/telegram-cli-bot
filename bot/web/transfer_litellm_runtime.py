"""LiteLLM proxy sidecar runtime."""

from __future__ import annotations

import asyncio
import os
import secrets
import shlex
import socket
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from bot.web.transfer_litellm_config import LiteLLMTransferConfig, write_litellm_proxy_config


def _choose_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _split_command(command: str) -> list[str]:
    normalized = str(command or "").strip() or "litellm"
    return shlex.split(normalized, posix=os.name != "nt")


class LiteLLMProxyRuntime:
    def __init__(
        self,
        *,
        config_path: Path,
        log_path: Path,
        command: str = "litellm",
        host: str = "127.0.0.1",
        ready_timeout_seconds: float = 30,
    ) -> None:
        self.config_path = config_path
        self.log_path = log_path
        self.command = command
        self.host = host
        self.ready_timeout_seconds = ready_timeout_seconds
        self.master_key = f"sk-tcb-{secrets.token_urlsafe(32)}"
        self.port: int | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._log_handle: Any | None = None
        self._fingerprint = ""

    @property
    def is_running(self) -> bool:
        return bool(self.process is not None and self.process.returncode is None)

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    @property
    def api_base_url(self) -> str:
        if self.port is None:
            return ""
        return f"http://{self.host}:{self.port}/v1"

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        if not config.enabled:
            await self.close()
            return
        fingerprint = config.runtime_fingerprint()
        if self.is_running and self._fingerprint == fingerprint:
            return

        await self.close()
        self.port = _choose_local_port()
        write_litellm_proxy_config(self.config_path, config, self.master_key)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        command = _split_command(self.command)
        args = [
            *command,
            "--config",
            str(self.config_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdout=self._log_handle,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            self._close_log_handle()
            raise RuntimeError(f"LiteLLM 命令不可用: {command[0]}") from exc
        except Exception:
            self._close_log_handle()
            raise
        self._fingerprint = fingerprint
        await self._wait_until_ready()

    async def close(self) -> None:
        process = self.process
        self.process = None
        self._fingerprint = ""
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._close_log_handle()

    async def _wait_until_ready(self) -> None:
        assert self.port is not None
        deadline = asyncio.get_running_loop().time() + self.ready_timeout_seconds
        last_error = ""
        while asyncio.get_running_loop().time() < deadline:
            if self.process is not None and self.process.returncode is not None:
                raise RuntimeError(f"LiteLLM 进程已退出，退出码 {self.process.returncode}: {self.log_tail(20)}")
            try:
                timeout = ClientTimeout(total=2)
                async with ClientSession(timeout=timeout) as session:
                    headers = {"Authorization": f"Bearer {self.master_key}"}
                    async with session.get(f"http://{self.host}:{self.port}/v1/models", headers=headers) as response:
                        if response.status < 500:
                            return
                        last_error = await response.text()
            except Exception as exc:  # pragma: no cover - timing dependent
                last_error = str(exc)
            await asyncio.sleep(0.25)
        raise RuntimeError(f"LiteLLM 启动超时: {last_error or self.log_tail(20)}")

    def log_tail(self, max_lines: int = 80) -> list[str]:
        if not self.log_path.exists():
            return []
        try:
            data = self.log_path.read_bytes()[-65536:]
        except OSError:
            return []
        text = data.decode("utf-8", errors="replace")
        return text.splitlines()[-max_lines:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "pid": self.pid,
            "host": self.host,
            "port": self.port,
            "api_base_url": self.api_base_url,
            "config_path": str(self.config_path),
            "log_path": str(self.log_path),
            "log_tail": self.log_tail(),
        }

    def _close_log_handle(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None
