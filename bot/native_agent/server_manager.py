from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bot.config as config
from bot.cli import resolve_cli_executable
from bot.models import BotProfile, normalize_native_agent_config
from bot.native_agent.client import NativeAgentClient, NativeAgentServerRef
from bot.platform.executables import build_executable_invocation
from bot.runtime_paths import get_app_data_root


@dataclass
class NativeAgentServerHandle:
    key: str
    base_url: str
    password: str
    username: str
    config_path: Path | None = None
    process: asyncio.subprocess.Process | None = None

    def client(self) -> NativeAgentClient:
        return NativeAgentClient(NativeAgentServerRef(self.base_url, self.password, self.username))


class NativeAgentServerManager:
    BUILTIN_PROVIDER_IDS = {"anthropic", "openai"}

    def __init__(self) -> None:
        self._handles: dict[str, NativeAgentServerHandle] = {}
        self._lock = asyncio.Lock()

    def _config_hash(self, server_config: dict[str, Any]) -> str:
        material = json.dumps(
            {
                "command": str(server_config.get("command") or "opencode"),
                "hostname": str(server_config.get("hostname") or "127.0.0.1"),
                "port": int(server_config.get("port") or 0),
                "password": str(server_config.get("password") or ""),
                "bot_alias": str(server_config.get("bot_alias") or "global"),
                "native_agent": normalize_native_agent_config(server_config.get("native_agent")),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    def _server_key(self, server_config: dict[str, Any]) -> str:
        alias = str(server_config.get("bot_alias") or "global").strip().lower() or "global"
        return f"{alias}:{self._config_hash(server_config)}"

    def _current_config(self, profile: BotProfile | None = None) -> dict[str, Any]:
        command = str(config.NATIVE_AGENT_COMMAND or config.NATIVE_AGENT_PATH or "opencode").strip() or "opencode"
        hostname = str(config.NATIVE_AGENT_HOST or "127.0.0.1").strip() or "127.0.0.1"
        try:
            configured_port = min(65535, max(0, int(config.NATIVE_AGENT_PORT or 0)))
        except (TypeError, ValueError):
            configured_port = 0
        password = str(config.NATIVE_AGENT_SERVER_PASSWORD or "").strip()
        native_agent = normalize_native_agent_config(getattr(profile, "native_agent", {}) if profile is not None else {})
        return {
            "command": command,
            "hostname": hostname,
            "port": configured_port,
            "password": password,
            "bot_alias": str(getattr(profile, "alias", "") or "global").strip().lower() or "global",
            "native_agent": native_agent,
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

    async def ensure_started(self, profile: BotProfile | None = None) -> NativeAgentServerHandle:
        if not config.NATIVE_AGENT_ENABLED:
            raise RuntimeError("原生 agent 服务未启用")
        server_config = self._current_config(profile)
        key = self._server_key(server_config)
        async with self._lock:
            existing = self._handles.get(key)
            if existing is not None and existing.key == key and await self._is_healthy(existing):
                return existing
            stale_keys = [
                item_key
                for item_key, handle in self._handles.items()
                if item_key.split(":", 1)[0] == key.split(":", 1)[0]
            ]
            for item_key in stale_keys:
                stale = self._handles.pop(item_key, None)
                if stale is not None:
                    await self._stop_handle(stale)
            handle = await self._start_server(key=key, server_config=server_config)
            self._handles[key] = handle
            return handle

    async def get_existing(self) -> NativeAgentServerHandle | None:
        async with self._lock:
            for key, existing in list(self._handles.items()):
                if await self._is_healthy(existing):
                    return existing
                await self._stop_handle(existing)
                self._handles.pop(key, None)
        return None

    async def get_existing_by_key(self, key: str) -> NativeAgentServerHandle | None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return None
        async with self._lock:
            existing = self._handles.get(normalized_key)
            if existing is None:
                return None
            if await self._is_healthy(existing):
                return existing
            await self._stop_handle(existing)
            self._handles.pop(normalized_key, None)
            return None

    async def get_existing_for(self, profile: BotProfile) -> NativeAgentServerHandle | None:
        server_config = self._current_config(profile)
        key = self._server_key(server_config)
        async with self._lock:
            existing = self._handles.get(key)
            if existing is None:
                return None
            if await self._is_healthy(existing):
                return existing
            await self._stop_handle(existing)
            self._handles.pop(key, None)
            return None

    async def get_existing_for_alias(self, alias: str) -> NativeAgentServerHandle | None:
        normalized_alias = str(alias or "").strip().lower()
        if not normalized_alias:
            return None
        async with self._lock:
            healthy: list[NativeAgentServerHandle] = []
            for key, existing in list(self._handles.items()):
                if key.split(":", 1)[0] != normalized_alias:
                    continue
                if await self._is_healthy(existing):
                    healthy.append(existing)
                    continue
                await self._stop_handle(existing)
                self._handles.pop(key, None)
            return healthy[0] if len(healthy) == 1 else None

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

    def _runtime_config_path(self, key: str) -> Path:
        return get_app_data_root() / "native-agent" / f"opencode-{key.replace(':', '-')}.json"

    def _provider_name(self, provider: str) -> str:
        return provider[:1].upper() + provider[1:] if provider else "Provider"

    def _is_builtin_provider(self, provider: str) -> bool:
        return provider in self.BUILTIN_PROVIDER_IDS

    def _write_opencode_config(self, key: str, native_agent: dict[str, Any]) -> Path | None:
        provider = str(native_agent.get("provider") or "").strip().lower()
        model = str(native_agent.get("model") or "").strip()
        base_url = str(native_agent.get("base_url") or "").strip()
        api_key = str(native_agent.get("api_key") or "").strip()
        if not (provider and model and (base_url or api_key)):
            return None
        model_name = model.split("/", 1)[1] if "/" in model else model
        provider_config: dict[str, Any] = {
            "options": {},
            "models": {
                model_name: {
                    "name": model_name,
                },
            },
        }
        if not self._is_builtin_provider(provider):
            provider_config["npm"] = "@ai-sdk/openai-compatible"
            provider_config["name"] = self._provider_name(provider)
        if base_url:
            provider_config["options"]["baseURL"] = base_url
        if api_key:
            provider_config["options"]["apiKey"] = api_key
        payload = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                provider: provider_config,
            },
        }
        path = self._runtime_config_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

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
        opencode_config_path = self._write_opencode_config(key, normalize_native_agent_config(server_config.get("native_agent")))
        if opencode_config_path is not None:
            env["OPENCODE_CONFIG"] = str(opencode_config_path)
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
            config_path=opencode_config_path,
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
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if handle.config_path is not None:
            try:
                handle.config_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def stop_all(self) -> None:
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            await self._stop_handle(handle)


SERVER_MANAGER = NativeAgentServerManager()
