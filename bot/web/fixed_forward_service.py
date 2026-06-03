"""Fixed Hub public forward frpc lifecycle service."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import platform
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bot.platform.processes import build_subprocess_group_kwargs, terminate_process_tree_sync
from bot.version import APP_VERSION

logger = logging.getLogger(__name__)

_LOG_TAIL_LIMIT = 80
_DEFAULT_HEARTBEAT_INTERVAL = 30.0
_DEFAULT_STARTUP_TIMEOUT = 2.0
_DEFAULT_CONNECT_TIMEOUT = 5.0
_DEFAULT_HEARTBEAT_TIMEOUT = 5.0
_ACTIVE_STATUSES = {"starting", "running"}


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _format_http_host(host: str) -> str:
    normalized = str(host or "").strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        return normalized
    if ":" in normalized:
        return f"[{normalized}]"
    return normalized


def _build_local_url(host: str, port: int) -> str:
    tunnel_host = str(host or "").strip() or "127.0.0.1"
    if tunnel_host == "0.0.0.0":
        tunnel_host = "127.0.0.1"
    elif tunnel_host in {"::", "[::]"}:
        tunnel_host = "::1"
    return f"http://{_format_http_host(tunnel_host)}:{int(port)}"


def _heartbeat_url(public_url: str) -> str:
    parsed = urlsplit(str(public_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/api/nodes/heartbeat"


def _public_hostname(public_url: str) -> str:
    parsed = urlsplit(str(public_url or "").strip())
    return parsed.hostname or ""


def _normalize_base_path(value: str) -> str:
    text = str(value or "").strip()
    if not text or text == "/":
        return ""
    return text.rstrip("/")


def _is_frpc_auth_error(line: str) -> bool:
    text = line.lower()
    return (
        "authorization failed" in text
        or "authentication failed" in text
        or "auth failed" in text
        or ("login to server failed" in text and "token" in text)
    )


def _is_frps_timeout_error(line: str) -> bool:
    text = line.lower()
    return (
        "i/o timeout" in text
        or "timed out" in text
        or "timeout" in text
        or "deadline exceeded" in text
    )


class FixedForwardService:
    """Manages frpc for Hub fixed public forwarding."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        enabled: bool = False,
        autostart: bool = True,
        public_url: str = "",
        node_id: str = "",
        base_path: str = "",
        frps_port: int = 0,
        node_token: str = "",
        frps_token: str = "",
        frpc_path: str = "",
        runtime_dir: str | Path | None = None,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL,
        startup_timeout: float = _DEFAULT_STARTUP_TIMEOUT,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        heartbeat_timeout: float = _DEFAULT_HEARTBEAT_TIMEOUT,
    ) -> None:
        self._host = str(host or "").strip() or "0.0.0.0"
        self._port = int(port)
        self._enabled = bool(enabled)
        self._autostart = bool(autostart)
        self._public_url = str(public_url or "").strip()
        self._node_id = str(node_id or "").strip()
        self._base_path = _normalize_base_path(base_path)
        self._frps_port = int(frps_port or 0)
        self._node_token = str(node_token or "").strip()
        self._frps_token = str(frps_token or "").strip()
        self._frpc_path = str(frpc_path or "").strip() or "frpc"
        self._runtime_dir = Path(runtime_dir or Path.cwd() / ".tcb" / "fixed-forward").expanduser()
        self._heartbeat_interval = max(0.1, float(heartbeat_interval))
        self._startup_timeout = max(0.0, float(startup_timeout))
        self._connect_timeout = max(0.1, float(connect_timeout))
        self._heartbeat_timeout = max(0.1, float(heartbeat_timeout))
        self._local_url = _build_local_url(self._host, self._port)

        self._state_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._expected_stop = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._snapshot = self._build_initial_snapshot()

    def should_autostart(self) -> bool:
        return self._enabled and self._autostart

    def snapshot(self) -> dict[str, Any]:
        self._refresh_process_state()
        with self._state_lock:
            snapshot = copy.deepcopy(self._snapshot)
        return self._with_public_fields(snapshot)

    def write_frpc_config(self) -> Path:
        error = self._validate_config()
        if error:
            raise ValueError(error)
        path = self._frpc_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._build_frpc_config_text(), encoding="utf-8")
        return path

    def check_frps_connectivity(self) -> dict[str, Any]:
        started_at = time.perf_counter()
        host = _public_hostname(self._public_url)
        if not host or self._frps_port <= 0:
            return self._probe_result(False, "invalid_config", "frps 地址或端口未配置", started_at)
        try:
            with socket.create_connection((host, self._frps_port), timeout=self._connect_timeout):
                return self._probe_result(True, "", "", started_at)
        except (TimeoutError, socket.timeout):
            return self._probe_result(False, "frps_timeout", "frps 端口不通/安全组未放通", started_at)
        except OSError as exc:
            return self._probe_result(False, "frps_connect_error", f"frps 端口连接失败: {exc}", started_at)

    def send_heartbeat_once(self) -> dict[str, Any]:
        started_at = time.perf_counter()
        url = _heartbeat_url(self._public_url)
        if not url:
            result = self._probe_result(False, "invalid_url", "固定公网入口 URL 无效", started_at)
            self._set_heartbeat(result)
            return result

        payload = {
            "node_id": self._node_id,
            "token": self._node_token,
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "bridge_version": APP_VERSION,
            "local_url": self._local_url,
        }
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._heartbeat_timeout) as response:
                status_code = int(getattr(response, "status", response.getcode()) or 0)
                result = {
                    **self._probe_result(200 <= status_code < 300, "", "", started_at),
                    "status_code": status_code,
                }
                if not result["ok"]:
                    result["error_class"] = "http_status"
                    result["error_text"] = f"HTTP {status_code}"
        except HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            if status_code == 403:
                result = {
                    **self._probe_result(False, "node_token", "节点 token 错", started_at),
                    "status_code": status_code,
                }
            else:
                result = {
                    **self._probe_result(False, "http_status", f"HTTP {status_code}", started_at),
                    "status_code": status_code,
                }
        except (TimeoutError, socket.timeout):
            result = self._probe_result(False, "heartbeat_timeout", "Hub 心跳超时", started_at)
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                result = self._probe_result(False, "heartbeat_timeout", "Hub 心跳超时", started_at)
            else:
                result = self._probe_result(False, "heartbeat_error", f"Hub 心跳失败: {reason}", started_at)
        except Exception as exc:
            result = self._probe_result(False, type(exc).__name__, f"Hub 心跳失败: {exc}", started_at)

        self._set_heartbeat(result)
        if not result.get("ok") and result.get("error_class") == "node_token":
            self._set_snapshot(last_error="节点 token 错", verified=False)
        return result

    async def start(self) -> dict[str, Any]:
        if not self._enabled:
            self._set_snapshot(status="stopped", last_error="", verified=False, pid=None)
            return self.snapshot()

        error = self._validate_config()
        if error:
            self._set_snapshot(status="error", last_error=error, verified=False, pid=None)
            return self.snapshot()

        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return self.snapshot()

        connectivity = await asyncio.to_thread(self.check_frps_connectivity)
        if not connectivity.get("ok"):
            self._set_snapshot(
                status="error",
                last_error=str(connectivity.get("error_text") or "frps 端口连接失败"),
                verified=False,
                pid=None,
            )
            return self.snapshot()

        try:
            config_path = await asyncio.to_thread(self.write_frpc_config)
        except Exception as exc:
            self._set_snapshot(status="error", last_error=str(exc), verified=False, pid=None)
            return self.snapshot()

        self._set_snapshot(
            status="starting",
            last_error="",
            verified=False,
            pid=None,
            registered_at="",
            log_tail=[],
            frpc_config_path=str(config_path),
        )

        try:
            process = subprocess.Popen(
                [self._frpc_path, "-c", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                **build_subprocess_group_kwargs(),
            )
        except FileNotFoundError:
            self._set_snapshot(status="error", last_error="未找到 frpc 可执行文件", verified=False, pid=None)
            return self.snapshot()
        except Exception as exc:
            self._set_snapshot(status="error", last_error=str(exc), verified=False, pid=None)
            return self.snapshot()

        ready_event = threading.Event()
        with self._state_lock:
            self._process = process
            self._expected_stop = False
            self._snapshot["pid"] = process.pid

        threading.Thread(target=self._consume_output, args=(process, ready_event), daemon=True).start()
        await asyncio.to_thread(ready_event.wait, self._startup_timeout)

        snapshot = self.snapshot()
        if snapshot.get("status") == "error":
            await asyncio.to_thread(terminate_process_tree_sync, process)
            with self._state_lock:
                if self._process is process:
                    self._process = None
                self._snapshot["pid"] = None
            return snapshot

        if process.poll() is not None:
            with self._state_lock:
                if self._process is process:
                    self._process = None
            self._set_snapshot(
                status="error",
                last_error=f"frpc 已退出 (exit={process.returncode})",
                verified=False,
                pid=None,
            )
            return self.snapshot()

        self._set_snapshot(
            status="running",
            last_error="",
            verified=True,
            pid=process.pid,
            registered_at=_utc_timestamp(),
        )
        self._ensure_heartbeat_task()
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        await self._stop_heartbeat_task()
        with self._state_lock:
            process = self._process
            self._expected_stop = True
        if process is not None:
            await asyncio.to_thread(terminate_process_tree_sync, process)
        with self._state_lock:
            if self._process is process:
                self._process = None
            self._snapshot.update(
                {
                    "status": "stopped",
                    "phase": "stopped",
                    "last_error": "",
                    "verified": False,
                    "pid": None,
                }
            )
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        return await self.start()

    def preserve_for_restart(self) -> dict[str, Any]:
        return self.snapshot()

    @staticmethod
    def _with_public_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
        heartbeat = snapshot.get("heartbeat") if isinstance(snapshot.get("heartbeat"), dict) else {}
        heartbeat_error = str(heartbeat.get("error_text") or "")
        if heartbeat.get("ok"):
            heartbeat_status = "online"
        elif heartbeat_error:
            heartbeat_status = "error"
        else:
            heartbeat_status = ""
        return {
            **snapshot,
            "frpc_status": str(snapshot.get("status") or ""),
            "frpc_pid": snapshot.get("pid"),
            "frpc_last_error": str(snapshot.get("last_error") or ""),
            "heartbeat_status": heartbeat_status,
            "heartbeat_last_at": str(heartbeat.get("last_at") or ""),
            "heartbeat_last_error": heartbeat_error,
        }

    def _build_initial_snapshot(self) -> dict[str, Any]:
        mode = "fixed_public_forward" if self._enabled else "disabled"
        status = "stopped"
        return {
            "mode": mode,
            "status": status,
            "phase": status,
            "source": "fixed_public_forward" if self._enabled else "disabled",
            "public_url": self._public_url,
            "local_url": self._local_url,
            "last_error": "",
            "verified": False,
            "last_probe_at": "",
            "last_probe_elapsed_ms": 0,
            "last_probe_error": {},
            "registered_at": "",
            "log_tail": [],
            "pid": None,
            "fixed_public_forward_enabled": self._enabled,
            "node_id": self._node_id,
            "base_path": self._base_path,
            "frpc_config_path": str(self._frpc_config_path()),
            "heartbeat": self._default_heartbeat(),
        }

    @staticmethod
    def _default_heartbeat() -> dict[str, Any]:
        return {
            "ok": False,
            "status_code": None,
            "error_class": "",
            "error_text": "",
            "last_at": "",
            "elapsed_ms": 0,
        }

    @staticmethod
    def _probe_result(ok: bool, error_class: str, error_text: str, started_at: float) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "status_code": None,
            "error_class": str(error_class or ""),
            "error_text": str(error_text or ""),
            "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
        }

    def _frpc_config_path(self) -> Path:
        return self._runtime_dir / "frpc.toml"

    def _build_frpc_config_text(self) -> str:
        server_addr = _public_hostname(self._public_url)
        return "\n".join(
            [
                f"serverAddr = {_toml_string(server_addr)}",
                f"serverPort = {self._frps_port}",
                'auth.method = "token"',
                f"auth.token = {_toml_string(self._frps_token)}",
                "transport.tls.enable = true",
                "",
                "[[proxies]]",
                f"name = {_toml_string(self._node_id)}",
                'type = "http"',
                'localIP = "127.0.0.1"',
                f"localPort = {self._port}",
                f"customDomains = [{_toml_string(server_addr)}]",
                f"locations = [{_toml_string(self._base_path)}]",
                "",
                "[proxies.requestHeaders.set]",
                f"X-Forwarded-Prefix = {_toml_string(self._base_path)}",
                f"X-TCB-Node-ID = {_toml_string(self._node_id)}",
                "",
            ]
        )

    def _validate_config(self) -> str:
        if not self._node_id:
            return "TCB_NODE_ID 未配置"
        expected_base_path = f"/node/{self._node_id}"
        if self._base_path != expected_base_path:
            return "WEB_BASE_PATH 必须等于 /node/<TCB_NODE_ID>"
        if not self._public_url:
            return "WEB_FIXED_PUBLIC_FORWARD_URL 未配置"
        parsed = urlsplit(self._public_url)
        if not parsed.scheme or not parsed.netloc or not parsed.hostname:
            return "WEB_FIXED_PUBLIC_FORWARD_URL 无效"
        if _normalize_base_path(parsed.path) != self._base_path:
            return "WEB_FIXED_PUBLIC_FORWARD_URL 必须包含 WEB_BASE_PATH"
        if self._frps_port <= 0:
            return "TCB_HUB_FRPS_PORT 未配置"
        if not self._node_token:
            return "TCB_HUB_NODE_TOKEN 未配置"
        if not self._frps_token:
            return "TCB_HUB_FRPS_TOKEN 未配置"
        return ""

    def _set_snapshot(self, **changes: Any) -> None:
        if "status" in changes and "phase" not in changes:
            changes["phase"] = changes["status"]
        with self._state_lock:
            self._snapshot.update(changes)

    def _append_log_tail(self, line: str) -> None:
        text = str(line or "").strip()
        if not text:
            return
        with self._state_lock:
            tail = [str(item) for item in self._snapshot.get("log_tail") or []]
            tail.append(text)
            self._snapshot["log_tail"] = tail[-_LOG_TAIL_LIMIT:]

    def _set_heartbeat(self, result: dict[str, Any]) -> None:
        heartbeat = {
            "ok": bool(result.get("ok")),
            "status_code": result.get("status_code"),
            "error_class": str(result.get("error_class") or ""),
            "error_text": str(result.get("error_text") or ""),
            "last_at": _utc_timestamp(),
            "elapsed_ms": int(result.get("elapsed_ms") or 0),
        }
        with self._state_lock:
            self._snapshot["heartbeat"] = heartbeat

    def _map_frpc_output_error(self, line: str) -> str:
        if _is_frpc_auth_error(line):
            return "frps token 错"
        if _is_frps_timeout_error(line):
            return "frps 端口不通/安全组未放通"
        return ""

    def _consume_output(self, process: subprocess.Popen, ready_event: threading.Event) -> None:
        try:
            if process.stdout is None:
                self._set_snapshot(status="error", last_error="frpc 没有可读取的输出", verified=False, pid=None)
                ready_event.set()
                return

            for raw_line in iter(process.stdout.readline, ""):
                if not raw_line:
                    break
                line = raw_line.rstrip()
                self._append_log_tail(line)
                logger.info("[frpc] %s", line)
                mapped_error = self._map_frpc_output_error(line)
                if mapped_error:
                    self._set_snapshot(status="error", last_error=mapped_error, verified=False, pid=None)
                    ready_event.set()
                    return

            ready_event.set()
            returncode = process.poll()
            with self._state_lock:
                is_current = self._process is process
                expected_stop = self._expected_stop
                current_status = str(self._snapshot.get("status") or "")
            if is_current and not expected_stop and returncode is not None and current_status != "error":
                self._set_snapshot(
                    status="error",
                    last_error=f"frpc 已退出 (exit={returncode})",
                    verified=False,
                    pid=None,
                )
        except Exception as exc:
            logger.warning("读取 frpc 输出失败: %s", exc)
            with self._state_lock:
                if self._process is process and not self._expected_stop:
                    self._snapshot.update(
                        {
                            "status": "error",
                            "phase": "error",
                            "last_error": str(exc),
                            "verified": False,
                            "pid": None,
                        }
                    )
            ready_event.set()

    def _refresh_process_state(self) -> None:
        with self._state_lock:
            process = self._process
            expected_stop = self._expected_stop
            status = str(self._snapshot.get("status") or "")
        if process is None or expected_stop or status not in _ACTIVE_STATUSES:
            return
        returncode = process.poll()
        if returncode is None:
            return
        self._set_snapshot(
            status="error",
            last_error=f"frpc 已退出 (exit={returncode})",
            verified=False,
            pid=None,
        )
        with self._state_lock:
            if self._process is process:
                self._process = None

    def _ensure_heartbeat_task(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = loop.create_task(self._heartbeat_loop(), name="fixed-forward-heartbeat")

    async def _heartbeat_loop(self) -> None:
        while True:
            snapshot = self.snapshot()
            if snapshot.get("status") != "running":
                return
            await asyncio.to_thread(self.send_heartbeat_once)
            await asyncio.sleep(self._heartbeat_interval)

    async def _stop_heartbeat_task(self) -> None:
        task = self._heartbeat_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._heartbeat_task = None
