from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bot.config as config
from bot.cluster.setup import CLUSTER_MCP_SERVER_NAME, prepare_cluster_mcp_launcher
from bot.cli import resolve_cli_executable
from bot.models import BotProfile, build_native_agent_model_id, normalize_native_agent_config
from bot.native_agent.config_store import ensure_opencode_config
from bot.native_agent.client import NativeAgentClient, NativeAgentServerRef
from bot.native_agent.configuration import effective_native_agent_config, validate_native_agent_model_config
from bot.platform.executables import build_executable_invocation
from bot.runtime_paths import get_app_data_root

try:  # pragma: no cover - import fallback depends on optional runtime dependency
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _cluster_bridge_url() -> str:
    return f"http://127.0.0.1:{int(config.WEB_PORT)}"


def _cluster_mcp_launcher_signature() -> dict[str, str]:
    launcher_name = "tcb-cluster-mcp.cmd" if os.name == "nt" else "tcb-cluster-mcp.sh"
    return {
        "server_name": CLUSTER_MCP_SERVER_NAME,
        "launcher_path": str(Path.home() / ".tcb" / "bin" / launcher_name),
        "bridge_url": _cluster_bridge_url(),
    }


def _prepare_cluster_mcp_launcher_for_native() -> Path:
    launcher = prepare_cluster_mcp_launcher(
        home_dir=Path.home(),
        repo_root=_REPO_ROOT,
        bridge_url=_cluster_bridge_url(),
    )
    return launcher.launcher_path


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
                "native_agent": normalize_native_agent_config(server_config.get("native_agent")),
                "cluster_mcp": _cluster_mcp_launcher_signature(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    def _workspace_hash(self, server_config: dict[str, Any]) -> str:
        working_dir = self._normalize_working_dir(str(server_config.get("working_dir") or ""))
        return hashlib.sha256(working_dir.encode("utf-8")).hexdigest()[:12]

    def _server_key(self, server_config: dict[str, Any]) -> str:
        return f"workspace-{self._workspace_hash(server_config)}:{self._config_hash(server_config)}"

    def _current_config(self, profile: BotProfile | None = None) -> dict[str, Any]:
        command = str(config.NATIVE_AGENT_COMMAND or config.NATIVE_AGENT_PATH or "opencode").strip() or "opencode"
        hostname = str(config.NATIVE_AGENT_HOST or "127.0.0.1").strip() or "127.0.0.1"
        try:
            configured_port = min(65535, max(0, int(config.NATIVE_AGENT_PORT or 0)))
        except (TypeError, ValueError):
            configured_port = 0
        password = str(config.NATIVE_AGENT_SERVER_PASSWORD or "").strip()
        native_agent = effective_native_agent_config(getattr(profile, "native_agent", {}) if profile is not None else {})
        validate_native_agent_model_config(native_agent)
        working_dir = self._normalize_working_dir(str(getattr(profile, "working_dir", "") or config.WORKING_DIR or ""))
        return {
            "command": command,
            "hostname": hostname,
            "port": configured_port,
            "password": password,
            "working_dir": working_dir,
            "native_agent": native_agent,
        }

    def _normalize_working_dir(self, working_dir: str) -> str:
        candidate = str(working_dir or config.WORKING_DIR or ".").strip() or "."
        return str(Path(candidate).expanduser().resolve())

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
            workspace_prefix = key.split(":", 1)[0]
            stale_keys = [
                item_key
                for item_key in self._handles
                if item_key.split(":", 1)[0] == workspace_prefix
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
        _ = alias
        return await self.get_existing()

    async def _is_healthy(self, handle: NativeAgentServerHandle) -> bool:
        process = handle.process
        if process is not None and process.returncode is not None:
            return False
        try:
            await handle.client().health()
            return True
        except Exception:
            return False

    def _resolve_command(self, command: str, cwd: str) -> list[str]:
        resolved = resolve_cli_executable(command, cwd)
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

    def _write_opencode_config(self, key: str, native_agent: dict[str, Any]) -> Path:
        base_path = ensure_opencode_config(native_agent)
        try:
            payload = json.loads(base_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return base_path
        if not isinstance(payload, dict):
            return base_path
        runtime_payload = copy.deepcopy(payload)
        selected_model = build_native_agent_model_id(native_agent)
        if selected_model:
            runtime_payload["model"] = selected_model
            self._apply_model_options(runtime_payload, selected_model, _model_options(native_agent))
        opencode_agent = str(native_agent.get("opencode_agent") or "").strip()
        if opencode_agent:
            runtime_payload["agent"] = opencode_agent
        launcher_path = _prepare_cluster_mcp_launcher_for_native()
        mcp = runtime_payload.get("mcp")
        if not isinstance(mcp, dict):
            mcp = {}
            runtime_payload["mcp"] = mcp
        mcp[CLUSTER_MCP_SERVER_NAME] = {
            "type": "local",
            "command": [str(launcher_path)],
            "enabled": True,
        }
        path = self._runtime_config_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(runtime_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def _apply_model_options(self, payload: dict[str, Any], model_id: str, options: dict[str, Any]) -> None:
        if not options or "/" not in model_id:
            return
        provider_id, model_name = model_id.split("/", 1)
        provider_map = payload.get("provider")
        if not isinstance(provider_map, dict):
            return
        provider_config = provider_map.get(provider_id)
        if not isinstance(provider_config, dict):
            return
        models = provider_config.get("models")
        if not isinstance(models, dict):
            return
        model_config = models.get(model_name)
        if not isinstance(model_config, dict):
            return
        model_options = model_config.get("options")
        if not isinstance(model_options, dict):
            model_options = {}
            model_config["options"] = model_options
        model_options.update(options)

    async def _start_server(self, *, key: str, server_config: dict[str, Any]) -> NativeAgentServerHandle:
        command = str(server_config.get("command") or "opencode").strip() or "opencode"
        hostname = str(server_config.get("hostname") or "127.0.0.1").strip() or "127.0.0.1"
        configured_port = int(server_config.get("port") or 0)
        port = configured_port if configured_port > 0 else self._pick_port(hostname)
        password = str(server_config.get("password") or "").strip() or secrets.token_urlsafe(24)
        username = "opencode"
        working_dir = self._normalize_working_dir(str(server_config.get("working_dir") or ""))
        env = os.environ.copy()
        env["OPENCODE_SERVER_USERNAME"] = username
        env["OPENCODE_SERVER_PASSWORD"] = password
        opencode_config_path = self._write_opencode_config(key, normalize_native_agent_config(server_config.get("native_agent")))
        env["OPENCODE_CONFIG"] = str(opencode_config_path)
        env["TCB_NATIVE_AGENT_MANAGED"] = "1"
        env["TCB_NATIVE_AGENT_SERVER_KEY"] = key
        env["TCB_NATIVE_AGENT_CONFIG_PATH"] = str(opencode_config_path)
        invocation = self._resolve_command(command, working_dir)
        process = await asyncio.create_subprocess_exec(
            *invocation,
            "serve",
            "--hostname",
            hostname,
            "--port",
            str(port),
            cwd=working_dir,
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

    async def stop_all(self) -> None:
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            await self._stop_handle(handle)

    def terminate_stale_opencode_processes(self) -> list[int]:
        killed: list[int] = []
        if psutil is None:
            logger.warning("psutil 不可用，跳过旧 opencode serve 进程清理")
            return killed
        current_pid = os.getpid()
        candidates = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = int(process.info.get("pid") or 0)
                if pid <= 0 or pid == current_pid:
                    continue
                name = str(process.info.get("name") or "")
                cmdline = process.info.get("cmdline") or []
                if not _is_opencode_serve_process(name, cmdline):
                    continue
                environ = process.environ()
                if _is_tcb_managed_opencode_serve_process(name, cmdline, environ):
                    candidates.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        for process in candidates:
            try:
                pid = int(process.pid)
                children = process.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
                process.terminate()
                gone, alive = psutil.wait_procs([process, *children], timeout=3)
                _ = gone
                for alive_process in alive:
                    try:
                        alive_process.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
                killed.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        if killed:
            logger.info("已清理旧 opencode serve 进程: %s", killed)
        return killed


SERVER_MANAGER = NativeAgentServerManager()


def _model_options(native_agent: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    reasoning_effort = str(native_agent.get("reasoning_effort") or "").strip()
    if reasoning_effort:
        options["reasoningEffort"] = reasoning_effort
    raw_thinking_depth = str(native_agent.get("thinking_depth") or "").strip()
    if raw_thinking_depth:
        try:
            thinking_depth = int(float(raw_thinking_depth))
        except (TypeError, ValueError):
            thinking_depth = 0
        if thinking_depth > 0:
            options["thinking"] = {
                "type": "enabled",
                "budgetTokens": thinking_depth,
            }
    return options


def _is_opencode_serve_process(name: str, cmdline: Any) -> bool:
    parts = [str(item) for item in (cmdline or []) if str(item)]
    lowered_name = str(name or "").lower()
    lowered_parts = [item.lower() for item in parts]
    joined = " ".join(lowered_parts)
    has_opencode = "opencode" in lowered_name or "opencode" in joined
    has_serve = any(item == "serve" for item in lowered_parts)
    return has_opencode and has_serve


def _is_tcb_managed_opencode_serve_process(
    name: str,
    cmdline: Any,
    environ: dict[str, Any],
    app_data_root: Path | None = None,
) -> bool:
    if not _is_opencode_serve_process(name, cmdline):
        return False
    if str(environ.get("TCB_NATIVE_AGENT_MANAGED") or "") == "1":
        return True
    raw_config_path = str(environ.get("OPENCODE_CONFIG") or "").strip()
    if not raw_config_path:
        return False
    config_path = Path(raw_config_path)
    if not config_path.name.startswith("opencode-workspace-"):
        return False
    native_root = (app_data_root or get_app_data_root()) / "native-agent"
    try:
        return config_path.resolve().is_relative_to(native_root.resolve())
    except OSError:
        return False
