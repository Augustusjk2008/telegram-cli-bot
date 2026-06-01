"""Cloudflare Tunnel 生命周期管理。"""

from __future__ import annotations

import asyncio
import copy
import csv
import json
import logging
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bot.platform.processes import build_subprocess_group_kwargs

logger = logging.getLogger(__name__)

_CLOUDFLARE_URL_RE = re.compile(r"https?://[a-z0-9-]+\.trycloudflare\.com")
_HEALTH_PATH = "/api/health"
_BENIGN_TUNNEL_WARNINGS = (
    "Failed to initialize DNS local resolver",
    "cloudflared does not support loading the system root certificate pool on Windows",
)
_ACTIVE_TUNNEL_STATUSES = {"waiting_local", "waiting_url", "connected", "verifying_public", "starting", "running"}
_PUBLIC_PROBE_INTERVAL_SECONDS = 1.0
_PUBLIC_PROBE_INITIAL_DELAY_SECONDS = 0.25
_LOG_TAIL_LIMIT = 40


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_quick_public_url(value: str) -> str:
    parsed = urlsplit((value or "").strip())
    host = parsed.hostname or ""
    if host.endswith(".trycloudflare.com"):
        return f"https://{host}"
    if parsed.scheme == "https" and host:
        return value.strip()
    return ""


class TunnelService:
    """管理当前 Web 服务的公网 tunnel 状态。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        mode: str = "disabled",
        autostart: bool = True,
        public_url: str = "",
        cloudflared_path: str = "",
        state_file: str = ".web_tunnel_state.json",
        startup_timeout: float = 10.0,
        local_health_timeout: float = 5.0,
        public_health_timeout: float = 60.0,
        fixed_public_forward_enabled: bool = False,
    ):
        normalized_mode = (mode or "disabled").strip().lower()
        if public_url.strip() and not fixed_public_forward_enabled:
            normalized_mode = "manual"
        elif normalized_mode not in {"disabled", "cloudflare_quick"}:
            normalized_mode = "disabled"

        self._mode = normalized_mode
        self._autostart = bool(autostart)
        self._fixed_public_forward_enabled = bool(fixed_public_forward_enabled)
        self._manual_public_url = public_url.strip()
        self._cloudflared_path = cloudflared_path.strip()
        self._startup_timeout = startup_timeout
        self._local_health_timeout = local_health_timeout
        self._public_health_timeout = public_health_timeout
        self._state_file = Path(state_file).expanduser()
        self._local_url = self._build_local_url(host, port)
        normalized_host = host.strip()
        self._restore_local_urls = {self._local_url}
        if normalized_host in {"::", "[::]"}:
            self._restore_local_urls.add(f"http://127.0.0.1:{port}")
        self._state_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._expected_stop = False
        self._public_probe_task: asyncio.Task[None] | None = None
        self._snapshot = self._build_initial_snapshot()

    @staticmethod
    def _format_http_host(host: str) -> str:
        normalized = host.strip()
        if normalized.startswith("[") and normalized.endswith("]"):
            return normalized
        if ":" in normalized:
            return f"[{normalized}]"
        return normalized

    @staticmethod
    def _build_local_url(host: str, port: int) -> str:
        tunnel_host = host.strip() or "127.0.0.1"
        if tunnel_host in {"0.0.0.0"}:
            tunnel_host = "127.0.0.1"
        elif tunnel_host in {"::", "[::]"}:
            tunnel_host = "::1"
        return f"http://{TunnelService._format_http_host(tunnel_host)}:{port}"

    @staticmethod
    def _can_connect_local_url(local_url: str, timeout: float = 0.5) -> bool:
        parsed = urlsplit(local_url)
        host = parsed.hostname
        port = parsed.port
        if not host or port is None:
            return False
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def _can_resolve_public_url(public_url: str) -> bool:
        parsed = urlsplit(public_url)
        host = parsed.hostname
        if not host:
            return False
        try:
            return bool(socket.getaddrinfo(host, None))
        except OSError:
            return False

    @staticmethod
    def _default_probe_error() -> dict[str, Any]:
        return {
            "ok": False,
            "status_code": None,
            "error_class": "",
            "error_text": "",
            "elapsed_ms": 0,
        }

    @staticmethod
    def _build_health_url(base_url: str) -> str:
        parsed = urlsplit((base_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return ""
        base_path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{base_path}{_HEALTH_PATH}"

    @staticmethod
    def _can_fetch_health(base_url: str, timeout: float = 1.0) -> dict[str, Any]:
        started_at = time.perf_counter()
        health_url = TunnelService._build_health_url(base_url)
        if not health_url:
            return {
                "ok": False,
                "status_code": None,
                "error_class": "invalid_url",
                "error_text": "公网地址无效",
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        try:
            request = Request(health_url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                status_code = int(status)
                return {
                    "ok": 200 <= status_code < 300,
                    "status_code": status_code,
                    "error_class": "" if 200 <= status_code < 300 else "http_status",
                    "error_text": "" if 200 <= status_code < 300 else f"HTTP {status_code}",
                    "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
                }
        except HTTPError as exc:
            return {
                "ok": False,
                "status_code": int(getattr(exc, "code", 0) or 0) or None,
                "error_class": "http_status",
                "error_text": f"HTTP {getattr(exc, 'code', '')}".strip(),
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        except TimeoutError as exc:
            return {
                "ok": False,
                "status_code": None,
                "error_class": "timeout",
                "error_text": str(exc) or "公网健康检查超时",
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        except ssl.SSLError as exc:
            return {
                "ok": False,
                "status_code": None,
                "error_class": "ssl",
                "error_text": str(exc),
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            error_class = "url_error"
            if isinstance(reason, TimeoutError):
                error_class = "timeout"
            elif isinstance(reason, ssl.SSLError):
                error_class = "ssl"
            elif isinstance(reason, socket.gaierror):
                error_class = "dns"
            return {
                "ok": False,
                "status_code": None,
                "error_class": error_class,
                "error_text": str(reason),
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        except OSError as exc:
            error_class = "dns" if isinstance(exc, socket.gaierror) else "os_error"
            return {
                "ok": False,
                "status_code": None,
                "error_class": error_class,
                "error_text": str(exc),
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "error_class": type(exc).__name__,
                "error_text": str(exc),
                "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            }

    def _wait_for_health(self, base_url: str, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self._can_fetch_health(base_url).get("ok"):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.25, remaining))

    def _build_initial_snapshot(self) -> dict[str, Any]:
        if self._manual_public_url:
            return {
                "mode": "manual",
                "status": "running",
                "phase": "running",
                "source": "manual_config",
                "public_url": self._manual_public_url,
                "local_url": self._local_url,
                "last_error": "",
                "verified": True,
                "last_probe_at": "",
                "last_probe_elapsed_ms": 0,
                "last_probe_error": {},
                "registered_at": "",
                "log_tail": [],
                "pid": None,
            }
        if self._mode == "cloudflare_quick":
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "phase": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": self._local_url,
                "last_error": "",
                "verified": False,
                "last_probe_at": "",
                "last_probe_elapsed_ms": 0,
                "last_probe_error": {},
                "registered_at": "",
                "log_tail": [],
                "pid": None,
            }
        return {
            "mode": "disabled",
            "status": "stopped",
            "phase": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": self._local_url,
            "last_error": "",
            "verified": False,
            "last_probe_at": "",
            "last_probe_elapsed_ms": 0,
            "last_probe_error": {},
            "registered_at": "",
            "log_tail": [],
            "pid": None,
        }

    def snapshot(self) -> dict[str, Any]:
        self._refresh_external_process_state()
        with self._state_lock:
            return copy.deepcopy(self._snapshot)

    def should_autostart(self) -> bool:
        return (
            self._mode == "cloudflare_quick"
            and self._autostart
            and not self._manual_public_url
            and not self._fixed_public_forward_enabled
        )

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

    def _set_probe_result(self, result: dict[str, Any], *, status_on_failure: str = "verifying_public") -> dict[str, Any]:
        normalized = result if isinstance(result, dict) else self._default_probe_error()
        ok = bool(normalized.get("ok"))
        elapsed_ms = int(normalized.get("elapsed_ms") or 0)
        now = _utc_timestamp()
        with self._state_lock:
            public_url = str(self._snapshot.get("public_url") or "")
            pid = self._coerce_pid(self._snapshot.get("pid")) or None
            if ok:
                self._snapshot.update(
                    {
                        "status": "running",
                        "phase": "running",
                        "public_url": public_url,
                        "last_error": "",
                        "verified": True,
                        "last_probe_at": now,
                        "last_probe_elapsed_ms": elapsed_ms,
                        "last_probe_error": {},
                        "pid": pid,
                    }
                )
            else:
                error = {
                    "error_class": str(normalized.get("error_class") or ""),
                    "error_text": str(normalized.get("error_text") or ""),
                    "status_code": normalized.get("status_code"),
                }
                message = self._format_probe_error(error, public_url)
                self._snapshot.update(
                    {
                        "status": status_on_failure,
                        "phase": status_on_failure,
                        "last_error": message,
                        "verified": False,
                        "last_probe_at": now,
                        "last_probe_elapsed_ms": elapsed_ms,
                        "last_probe_error": error,
                        "pid": pid,
                    }
                )
            snapshot = copy.deepcopy(self._snapshot)
        if ok:
            self._persist_running_state()
        else:
            self._persist_starting_state()
        return snapshot

    @staticmethod
    def _format_probe_error(error: dict[str, Any], public_url: str) -> str:
        error_class = str(error.get("error_class") or "").strip().lower()
        error_text = str(error.get("error_text") or "").strip()
        if error_class == "timeout":
            return "公网健康检查超时"
        if error_class == "dns":
            return f"公网地址 DNS 解析失败: {error_text}" if error_text else "公网地址 DNS 解析失败"
        if error_class == "ssl":
            return f"公网地址 SSL 校验失败: {error_text}" if error_text else "公网地址 SSL 校验失败"
        if error_class == "http_status":
            return error_text or "公网健康检查返回异常状态"
        if error_text:
            return f"公网健康检查失败: {error_text}"
        return f"公网地址已创建，正在验证: {public_url}" if public_url else "公网地址已创建，正在验证"

    @staticmethod
    def _extract_public_url(line: str) -> Optional[str]:
        match = _CLOUDFLARE_URL_RE.search(line)
        if match:
            normalized = _normalize_quick_public_url(match.group(0))
            return normalized or None
        return None

    def _cloudflared_command(self) -> list[str]:
        executable = self._cloudflared_path or "cloudflared"
        return [executable, "tunnel", "--url", self._local_url]

    @staticmethod
    def _log_cloudflared_line(line: str) -> None:
        if any(pattern in line for pattern in _BENIGN_TUNNEL_WARNINGS):
            logger.warning("[cloudflared] %s", line)
            return
        logger.info("[cloudflared] %s", line)

    @staticmethod
    def _coerce_pid(value: Any) -> int:
        try:
            pid = int(value)
        except (TypeError, ValueError):
            return 0
        return pid if pid > 0 else 0

    def _read_state_file(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            logger.warning("读取 tunnel 状态文件失败: JSON 非法 %s", self._state_file)
            self._clear_state_file()
            return None
        except Exception as exc:
            logger.warning("读取 tunnel 状态文件失败 %s: %s", self._state_file, exc)
            return None
        if not isinstance(data, dict):
            self._clear_state_file()
            return None
        return data

    def _load_persisted_quick_tunnel_candidate(self) -> dict[str, Any] | None:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return None
        return self._read_state_file()

    def _write_state_file(self, data: dict[str, Any]) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("写入 tunnel 状态文件失败 %s: %s", self._state_file, exc)

    def _clear_state_file(self) -> None:
        try:
            self._state_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("删除 tunnel 状态文件失败 %s: %s", self._state_file, exc)

    def _persist_active_tunnel_state(self, *, allowed_statuses: set[str]) -> None:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            self._clear_state_file()
            return

        with self._state_lock:
            snapshot = copy.deepcopy(self._snapshot)

        pid = self._coerce_pid(snapshot.get("pid"))
        public_url = _normalize_quick_public_url(str(snapshot.get("public_url") or ""))
        status = str(snapshot.get("status") or "")
        if status not in allowed_statuses or snapshot.get("source") != "quick_tunnel" or not public_url or pid <= 0:
            self._clear_state_file()
            return

        self._write_state_file(
            {
                "mode": "cloudflare_quick",
                "status": status,
                "source": "quick_tunnel",
                "public_url": public_url,
                "local_url": self._local_url,
                "pid": pid,
                "phase": status,
                "verified": bool(snapshot.get("verified")),
                "last_probe_at": str(snapshot.get("last_probe_at") or ""),
                "last_probe_elapsed_ms": int(snapshot.get("last_probe_elapsed_ms") or 0),
                "last_probe_error": snapshot.get("last_probe_error") if isinstance(snapshot.get("last_probe_error"), dict) else {},
                "registered_at": str(snapshot.get("registered_at") or ""),
            }
        )

    def _persist_running_state(self) -> None:
        self._persist_active_tunnel_state(allowed_statuses={"running"})

    def _persist_starting_state(self) -> None:
        self._persist_active_tunnel_state(allowed_statuses={"starting", "connected", "verifying_public", "running"})

    def _query_process_name(self, pid: int) -> str:
        if pid <= 0:
            return ""

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    creationflags=creationflags,
                )
                line = result.stdout.strip()
                if not line or line.startswith("INFO:"):
                    return ""
                row = next(csv.reader([line]), [])
                if not row:
                    return ""
                return Path(row[0].strip()).name.lower()

            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            line = result.stdout.strip().splitlines()
            if not line:
                return ""
            return Path(line[0].strip()).name.lower()
        except Exception as exc:
            logger.debug("查询 cloudflared 进程名失败 pid=%s: %s", pid, exc)
            return ""

    def _is_cloudflared_process(self, pid: int) -> bool:
        name = self._query_process_name(pid)
        return bool(name) and name.startswith("cloudflared")

    def _is_current_quick_tunnel_state(self, data: dict[str, Any] | None) -> bool:
        if not isinstance(data, dict):
            return False
        if str(data.get("mode") or "").strip() != "cloudflare_quick":
            return False
        if str(data.get("source") or "").strip() != "quick_tunnel":
            return False
        persisted_local_url = str(data.get("local_url") or "").strip()
        return persisted_local_url in self._restore_local_urls

    def _cleanup_stale_persisted_tunnel(self, data: dict[str, Any] | None) -> None:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return
        if not self._is_current_quick_tunnel_state(data):
            return

        pid = self._coerce_pid(data.get("pid"))
        if pid <= 0 or not self._is_cloudflared_process(pid):
            return

        logger.info("清理无法复用的旧 cloudflared 进程 pid=%s", pid)
        self._terminate_pid(pid)

    def _refresh_external_process_state(self) -> None:
        if self._manual_public_url:
            return

        with self._state_lock:
            process = self._process
            pid = self._coerce_pid(self._snapshot.get("pid"))
            if process is not None and pid <= 0:
                pid = self._coerce_pid(getattr(process, "pid", 0))
            status = str(self._snapshot.get("status") or "")

        if process is not None or pid <= 0 or status not in _ACTIVE_TUNNEL_STATUSES:
            return
        if self._is_cloudflared_process(pid):
            return

        with self._state_lock:
            current_status = str(self._snapshot.get("status") or "")
            if self._process is None and self._coerce_pid(self._snapshot.get("pid")) == pid:
                self._snapshot.update(
                    {
                        "status": "error",
                        "phase": "error",
                        "last_error": "cloudflared 进程已退出",
                        "pid": None,
                        "verified": False,
                    }
                )
                if current_status == "running":
                    self._snapshot["public_url"] = ""
        self._clear_state_file()

    def _try_restore_persisted_tunnel(self, data: dict[str, Any] | None = None) -> bool:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return False

        if data is None:
            data = self._load_persisted_quick_tunnel_candidate()
        if not data:
            return False
        if str(data.get("mode") or "").strip() != "cloudflare_quick":
            self._clear_state_file()
            return False
        persisted_local_url = str(data.get("local_url") or "").strip()
        if persisted_local_url not in self._restore_local_urls:
            self._clear_state_file()
            return False
        if persisted_local_url != self._local_url and not self._can_connect_local_url(persisted_local_url):
            self._clear_state_file()
            return False

        pid = self._coerce_pid(data.get("pid"))
        public_url = _normalize_quick_public_url(str(data.get("public_url") or ""))
        if (
            pid <= 0
            or not public_url
            or not self._is_cloudflared_process(pid)
            or not self._can_resolve_public_url(public_url)
        ):
            self._clear_state_file()
            return False

        persisted_status = str(data.get("status") or "running").strip()
        if persisted_status in {"starting", "connected", "verifying_public"}:
            restored_status = "verifying_public"
        else:
            restored_status = "running"
        restored_error = "公网地址已创建，正在验证" if restored_status == "verifying_public" else ""

        with self._state_lock:
            self._process = None
            self._expected_stop = False
            self._snapshot.update(
                {
                    "mode": "cloudflare_quick",
                    "status": restored_status,
                    "phase": restored_status,
                    "source": "quick_tunnel",
                    "public_url": public_url,
                    "local_url": self._local_url,
                    "last_error": restored_error,
                    "verified": restored_status == "running",
                    "last_probe_at": str(data.get("last_probe_at") or ""),
                    "last_probe_elapsed_ms": int(data.get("last_probe_elapsed_ms") or 0),
                    "last_probe_error": data.get("last_probe_error") if isinstance(data.get("last_probe_error"), dict) else {},
                    "registered_at": str(data.get("registered_at") or ""),
                    "pid": pid,
                }
            )
        if restored_status == "verifying_public":
            self._ensure_public_probe_task()
        return True

    def _consume_output(self, process: subprocess.Popen, ready_event: threading.Event) -> None:
        try:
            if process.stdout is None:
                self._set_snapshot(status="error", last_error="cloudflared 没有可读取的输出", pid=None)
                ready_event.set()
                return

            for raw_line in iter(process.stdout.readline, ""):
                if not raw_line:
                    break
                line = raw_line.rstrip()
                if line:
                    self._append_log_tail(line)
                    self._log_cloudflared_line(line)
                public_url = self._extract_public_url(line)
                if public_url:
                    self._set_snapshot(
                        status="connected",
                        phase="connected",
                        public_url=public_url,
                        last_error="",
                        pid=process.pid,
                        registered_at=_utc_timestamp(),
                    )
                    ready_event.set()

            returncode = process.poll()
            with self._state_lock:
                is_current = self._process is process
                expected_stop = self._expected_stop
                public_url = self._snapshot.get("public_url", "")

            if not ready_event.is_set():
                ready_event.set()

            if is_current and not expected_stop and returncode is not None:
                error_message = f"cloudflared 已退出 (exit={returncode})"
                with self._state_lock:
                    self._process = None
                    self._snapshot.update(
                        {
                            "status": "error",
                            "phase": "error",
                            "last_error": error_message,
                            "pid": None,
                            "verified": False,
                        }
                    )
                    if not public_url:
                        self._snapshot["public_url"] = ""
                self._clear_state_file()
        except Exception as exc:
            logger.warning("读取 cloudflared 输出失败: %s", exc)
            with self._state_lock:
                if self._process is process and not self._expected_stop:
                    self._process = None
                    self._snapshot.update(
                        {
                            "status": "error",
                            "phase": "error",
                            "last_error": str(exc),
                            "pid": None,
                            "public_url": "",
                            "verified": False,
                        }
                    )
            self._clear_state_file()
            ready_event.set()

    def _terminate_pid(self, pid: int) -> None:
        if pid <= 0:
            return

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    creationflags=creationflags,
                )
            except Exception as exc:
                logger.warning("终止 cloudflared 进程失败 pid=%s: %s", pid, exc)
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:
            logger.warning("终止 cloudflared 进程失败 pid=%s: %s", pid, exc)
            return

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not self._is_cloudflared_process(pid):
                return
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except Exception as exc:
            logger.warning("强制终止 cloudflared 进程失败 pid=%s: %s", pid, exc)

    async def _terminate_process(
        self,
        process: Optional[subprocess.Popen],
        *,
        pid: int | None = None,
        clear_public_url: bool,
        status: str,
        last_error: str,
    ) -> None:
        target_pid = pid or (process.pid if process is not None else 0)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
            except TypeError:
                process.wait(timeout=3)
        elif target_pid > 0:
            await asyncio.to_thread(self._terminate_pid, target_pid)

        with self._state_lock:
            if self._process is process:
                self._process = None
            self._snapshot.update(
                {
                    "status": status,
                    "phase": status,
                    "last_error": last_error,
                    "pid": None,
                    "verified": False,
                }
            )
            if clear_public_url:
                self._snapshot["public_url"] = ""
        if clear_public_url:
            self._clear_state_file()
        else:
            self._persist_running_state()

    def _ensure_public_probe_task(self) -> None:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._public_probe_task is not None and not self._public_probe_task.done():
            return
        self._public_probe_task = loop.create_task(self._public_probe_loop(), name="web-tunnel-public-probe")

    async def _public_probe_loop(self) -> None:
        await asyncio.sleep(_PUBLIC_PROBE_INITIAL_DELAY_SECONDS)
        while True:
            snapshot = self.snapshot()
            status = str(snapshot.get("status") or "")
            public_url = str(snapshot.get("public_url") or "").strip()
            if status == "running" or not public_url:
                return
            if status not in {"connected", "verifying_public", "starting"}:
                return
            ready = await self.wait_until_public_ready(timeout=min(5.0, max(0.1, self._public_health_timeout)))
            if ready.get("status") == "running":
                return
            await asyncio.sleep(_PUBLIC_PROBE_INTERVAL_SECONDS)

    async def start(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        if self._mode != "cloudflare_quick":
            return self.snapshot()

        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return copy.deepcopy(self._snapshot)

        persisted_data = self._load_persisted_quick_tunnel_candidate()
        if persisted_data and self._try_restore_persisted_tunnel(persisted_data):
            return self.snapshot()

        local_ready = await asyncio.to_thread(self._wait_for_health, self._local_url, timeout=self._local_health_timeout)
        if not local_ready:
            self._set_snapshot(
                status="error",
                last_error="本地 Web 未就绪，未启动 cloudflared",
                pid=None,
                public_url="",
                verified=False,
            )
            self._clear_state_file()
            return self.snapshot()

        await asyncio.to_thread(self._cleanup_stale_persisted_tunnel, persisted_data)

        with self._state_lock:
            self._expected_stop = False
            self._snapshot.update(
                {
                    "status": "waiting_url",
                    "phase": "waiting_url",
                    "last_error": "",
                    "public_url": "",
                    "pid": None,
                    "verified": False,
                    "last_probe_at": "",
                    "last_probe_elapsed_ms": 0,
                    "last_probe_error": {},
                    "registered_at": "",
                    "log_tail": [],
                }
            )

        try:
            process = subprocess.Popen(
                self._cloudflared_command(),
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
            self._set_snapshot(status="error", last_error="未找到 cloudflared 可执行文件", pid=None, public_url="", verified=False)
            self._clear_state_file()
            return self.snapshot()
        except Exception as exc:
            self._set_snapshot(status="error", last_error=str(exc), pid=None, public_url="", verified=False)
            self._clear_state_file()
            return self.snapshot()

        ready_event = threading.Event()
        with self._state_lock:
            self._process = process
            self._snapshot["pid"] = process.pid

        threading.Thread(target=self._consume_output, args=(process, ready_event), daemon=True).start()

        received = await asyncio.to_thread(ready_event.wait, self._startup_timeout)
        snapshot = self.snapshot()
        public_url = str(snapshot.get("public_url") or "").strip()
        if not received or not public_url:
            with self._state_lock:
                self._expected_stop = True
            last_error = str(snapshot.get("last_error") or "") or "cloudflared 启动超时，未获取到公网地址"
            await self._terminate_process(process, clear_public_url=True, status="error", last_error=last_error)
            return self.snapshot()

        self._set_snapshot(
            status="verifying_public",
            public_url=public_url,
            last_error="公网地址已创建，正在验证",
            pid=process.pid,
            verified=False,
        )
        self._persist_starting_state()
        self._ensure_public_probe_task()
        return self.snapshot()

    async def wait_until_public_ready(self, *, timeout: float = 90.0) -> dict[str, Any]:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return self.snapshot()

        snapshot = self.snapshot()
        if snapshot.get("status") == "running":
            return snapshot

        public_url = str(snapshot.get("public_url") or "").strip()
        if not public_url:
            return snapshot

        with self._state_lock:
            process = self._process
            pid = self._coerce_pid(self._snapshot.get("pid"))

        if process is not None and process.poll() is not None:
            self._set_snapshot(status="error", last_error="cloudflared 进程已退出", pid=None, verified=False)
            self._clear_state_file()
            return self.snapshot()
        if process is None and pid > 0 and not self._is_cloudflared_process(pid):
            self._set_snapshot(status="error", last_error="cloudflared 进程已退出", pid=None, verified=False)
            self._clear_state_file()
            return self.snapshot()

        result = await asyncio.to_thread(self._can_fetch_health, public_url, timeout=timeout)
        return self._set_probe_result(result, status_on_failure="verifying_public")

    async def stop(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()

        with self._state_lock:
            process = self._process
            self._expected_stop = True
            pid = 0 if process is not None else self._coerce_pid(self._snapshot.get("pid"))

        await self._terminate_process(process, pid=pid, clear_public_url=True, status="stopped", last_error="")
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        await self.stop()
        return await self.start()

    def preserve_for_restart(self) -> dict[str, Any]:
        self._persist_starting_state()
        return self.snapshot()
