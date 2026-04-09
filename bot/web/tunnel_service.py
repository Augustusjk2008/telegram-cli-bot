"""Cloudflare Tunnel 生命周期管理。"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import subprocess
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


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
        startup_timeout: float = 10.0,
    ):
        normalized_mode = (mode or "disabled").strip().lower()
        if public_url.strip():
            normalized_mode = "manual"
        elif normalized_mode not in {"disabled", "cloudflare_quick"}:
            normalized_mode = "disabled"

        self._mode = normalized_mode
        self._autostart = bool(autostart)
        self._manual_public_url = public_url.strip()
        self._cloudflared_path = cloudflared_path.strip()
        self._startup_timeout = startup_timeout
        self._local_url = self._build_local_url(host, port)
        self._state_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._expected_stop = False
        self._snapshot = self._build_initial_snapshot()

    @staticmethod
    def _build_local_url(host: str, port: int) -> str:
        tunnel_host = host.strip() or "127.0.0.1"
        if tunnel_host in {"0.0.0.0", "::"}:
            tunnel_host = "127.0.0.1"
        return f"http://{tunnel_host}:{port}"

    def _build_initial_snapshot(self) -> dict[str, Any]:
        if self._manual_public_url:
            return {
                "mode": "manual",
                "status": "running",
                "source": "manual_config",
                "public_url": self._manual_public_url,
                "local_url": self._local_url,
                "last_error": "",
                "pid": None,
            }
        if self._mode == "cloudflare_quick":
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": self._local_url,
                "last_error": "",
                "pid": None,
            }
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": self._local_url,
            "last_error": "",
            "pid": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._snapshot)

    def should_autostart(self) -> bool:
        return self._mode == "cloudflare_quick" and self._autostart and not self._manual_public_url

    def _set_snapshot(self, **changes: Any) -> None:
        with self._state_lock:
            self._snapshot.update(changes)

    @staticmethod
    def _extract_public_url(line: str) -> Optional[str]:
        match = _CLOUDFLARE_URL_RE.search(line)
        if match:
            return match.group(0)
        return None

    def _cloudflared_command(self) -> list[str]:
        executable = self._cloudflared_path or "cloudflared"
        return [executable, "tunnel", "--url", self._local_url]

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
                    logger.info("[cloudflared] %s", line)
                public_url = self._extract_public_url(line)
                if public_url:
                    self._set_snapshot(status="running", public_url=public_url, last_error="", pid=process.pid)
                    ready_event.set()

            returncode = process.poll()
            with self._state_lock:
                is_current = self._process is process
                expected_stop = self._expected_stop
                public_url = self._snapshot.get("public_url", "")

            if not ready_event.is_set():
                ready_event.set()

            if is_current and not expected_stop:
                error_message = f"cloudflared 已退出 (exit={returncode})"
                with self._state_lock:
                    self._process = None
                    self._snapshot.update(
                        {
                            "status": "error",
                            "last_error": error_message,
                            "pid": None,
                        }
                    )
                    if not public_url:
                        self._snapshot["public_url"] = ""
        except Exception as exc:
            logger.warning("读取 cloudflared 输出失败: %s", exc)
            with self._state_lock:
                if self._process is process and not self._expected_stop:
                    self._process = None
                    self._snapshot.update(
                        {
                            "status": "error",
                            "last_error": str(exc),
                            "pid": None,
                            "public_url": "",
                        }
                    )
            ready_event.set()

    async def _terminate_process(self, process: Optional[subprocess.Popen], *, clear_public_url: bool, status: str, last_error: str) -> None:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
            except TypeError:
                process.wait(timeout=3)

        with self._state_lock:
            if self._process is process:
                self._process = None
            self._snapshot.update(
                {
                    "status": status,
                    "last_error": last_error,
                    "pid": None,
                }
            )
            if clear_public_url:
                self._snapshot["public_url"] = ""

    async def start(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        if self._mode != "cloudflare_quick":
            return self.snapshot()

        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return copy.deepcopy(self._snapshot)
            self._expected_stop = False
            self._snapshot.update({"status": "starting", "last_error": "", "public_url": "", "pid": None})

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
            )
        except FileNotFoundError:
            self._set_snapshot(status="error", last_error="未找到 cloudflared 可执行文件", pid=None, public_url="")
            return self.snapshot()
        except Exception as exc:
            self._set_snapshot(status="error", last_error=str(exc), pid=None, public_url="")
            return self.snapshot()

        ready_event = threading.Event()
        with self._state_lock:
            self._process = process
            self._snapshot["pid"] = process.pid

        threading.Thread(target=self._consume_output, args=(process, ready_event), daemon=True).start()

        received = await asyncio.to_thread(ready_event.wait, self._startup_timeout)
        if not received or not self.snapshot().get("public_url"):
            with self._state_lock:
                self._expected_stop = True
            await self._terminate_process(process, clear_public_url=True, status="error", last_error="cloudflared 启动超时，未获取到公网地址")
            return self.snapshot()

        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()

        with self._state_lock:
            process = self._process
            self._expected_stop = True

        await self._terminate_process(process, clear_public_url=True, status="stopped", last_error="")
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        await self.stop()
        return await self.start()
