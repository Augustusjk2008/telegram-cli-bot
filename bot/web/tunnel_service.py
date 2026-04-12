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
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from bot.platform.processes import build_subprocess_group_kwargs

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
        state_file: str = ".web_tunnel_state.json",
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
        self._state_file = Path(state_file).expanduser()
        self._local_url = self._build_local_url(host, port)
        self._state_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._expected_stop = False
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
        if tunnel_host in {"0.0.0.0", "::", "[::]"}:
            tunnel_host = "127.0.0.1"
        return f"http://{TunnelService._format_http_host(tunnel_host)}:{port}"

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
        self._refresh_external_process_state()
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

    def _persist_running_state(self) -> None:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            self._clear_state_file()
            return

        with self._state_lock:
            snapshot = copy.deepcopy(self._snapshot)

        pid = self._coerce_pid(snapshot.get("pid"))
        public_url = str(snapshot.get("public_url") or "").strip()
        if snapshot.get("status") != "running" or snapshot.get("source") != "quick_tunnel" or not public_url or pid <= 0:
            self._clear_state_file()
            return

        self._write_state_file(
            {
                "mode": "cloudflare_quick",
                "source": "quick_tunnel",
                "public_url": public_url,
                "local_url": self._local_url,
                "pid": pid,
            }
        )

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

    def _refresh_external_process_state(self) -> None:
        if self._manual_public_url:
            return

        with self._state_lock:
            process = self._process
            pid = self._coerce_pid(self._snapshot.get("pid"))
            status = str(self._snapshot.get("status") or "")

        if process is not None or pid <= 0 or status != "running":
            return
        if self._is_cloudflared_process(pid):
            return

        with self._state_lock:
            if self._process is None and self._coerce_pid(self._snapshot.get("pid")) == pid:
                self._snapshot.update(
                    {
                        "status": "error",
                        "last_error": "cloudflared 进程已退出",
                        "pid": None,
                        "public_url": "",
                    }
                )
        self._clear_state_file()

    def _try_restore_persisted_tunnel(self) -> bool:
        if self._manual_public_url or self._mode != "cloudflare_quick":
            return False

        data = self._read_state_file()
        if not data:
            return False
        if str(data.get("mode") or "").strip() != "cloudflare_quick":
            self._clear_state_file()
            return False
        if str(data.get("local_url") or "").strip() != self._local_url:
            self._clear_state_file()
            return False

        pid = self._coerce_pid(data.get("pid"))
        public_url = str(data.get("public_url") or "").strip()
        if pid <= 0 or not public_url or not self._is_cloudflared_process(pid):
            self._clear_state_file()
            return False

        with self._state_lock:
            self._process = None
            self._expected_stop = False
            self._snapshot.update(
                {
                    "mode": "cloudflare_quick",
                    "status": "running",
                    "source": "quick_tunnel",
                    "public_url": public_url,
                    "local_url": self._local_url,
                    "last_error": "",
                    "pid": pid,
                }
            )
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
                    logger.info("[cloudflared] %s", line)
                public_url = self._extract_public_url(line)
                if public_url:
                    self._set_snapshot(status="running", public_url=public_url, last_error="", pid=process.pid)
                    self._persist_running_state()
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
                self._clear_state_file()
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
                    "last_error": last_error,
                    "pid": None,
                }
            )
            if clear_public_url:
                self._snapshot["public_url"] = ""
        if clear_public_url:
            self._clear_state_file()
        else:
            self._persist_running_state()

    async def start(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        if self._mode != "cloudflare_quick":
            return self.snapshot()

        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return copy.deepcopy(self._snapshot)

        if self._try_restore_persisted_tunnel():
            return self.snapshot()

        with self._state_lock:
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
                **build_subprocess_group_kwargs(),
            )
        except FileNotFoundError:
            self._set_snapshot(status="error", last_error="未找到 cloudflared 可执行文件", pid=None, public_url="")
            self._clear_state_file()
            return self.snapshot()
        except Exception as exc:
            self._set_snapshot(status="error", last_error=str(exc), pid=None, public_url="")
            self._clear_state_file()
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
            pid = 0 if process is not None else self._coerce_pid(self._snapshot.get("pid"))

        await self._terminate_process(process, pid=pid, clear_public_url=True, status="stopped", last_error="")
        return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        if self._manual_public_url:
            return self.snapshot()
        await self.stop()
        return await self.start()

    def preserve_for_restart(self) -> dict[str, Any]:
        self._persist_running_state()
        return self.snapshot()
