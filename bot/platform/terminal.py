"""Terminal process helpers shared by the Web runtime."""

from __future__ import annotations

import logging
import os
import select
import subprocess
import sys
import threading
from typing import Union

from bot.platform.processes import build_subprocess_group_kwargs

logger = logging.getLogger(__name__)

try:
    from winpty import PtyProcess

    _WINPTY_AVAILABLE = True
except ImportError:
    PtyProcess = None
    _WINPTY_AVAILABLE = False


class PtyWrapper:
    """Unify winpty.PtyProcess and subprocess-backed terminal processes."""

    def __init__(self, process: Union[subprocess.Popen, "PtyProcess", "PosixPtyProcess"], is_pty: bool = False):
        self.process = process
        self.is_pty = is_pty
        self._lock = threading.Lock()

    def read(self, timeout: int = 1000) -> bytes:
        if self.is_pty:
            try:
                return self.process.read(timeout=timeout)
            except TypeError:
                try:
                    return self.process.read(4096)
                except Exception:
                    return b""
            except Exception:
                return b""

        if hasattr(self.process.stdout, "read1"):
            data = self.process.stdout.read1(4096)
        else:
            data = self.process.stdout.read(4096)
        return data if data else b""

    def write(self, data: bytes) -> None:
        with self._lock:
            if self.is_pty:
                self.process.write(data.decode("utf-8", errors="replace"))
            else:
                self.process.stdin.write(data)
                self.process.stdin.flush()

    def isalive(self) -> bool:
        if self.is_pty:
            return self.process.isalive()
        return self.process.poll() is None

    def terminate(self) -> None:
        if self.is_pty:
            try:
                self.process.terminate()
            except Exception:
                pass
            return

        try:
            self.process.terminate()
            self.process.wait(timeout=3)
        except Exception:
            self.process.kill()

    def close(self) -> None:
        if self.is_pty:
            try:
                self.process.close()
            except Exception:
                pass

    @property
    def pid(self) -> int:
        return self.process.pid


class PosixPtyProcess:
    """POSIX PTY process wrapper with a winpty-like interface."""

    def __init__(self, process: subprocess.Popen, master_fd: int):
        self._process = process
        self._master_fd = master_fd
        self.pid = process.pid

    def read(self, timeout: int = 1000) -> bytes:
        wait_seconds = max(timeout, 0) / 1000
        readable, _, _ = select.select([self._master_fd], [], [], wait_seconds)
        if not readable:
            return b""
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    def write(self, data: str) -> None:
        os.write(self._master_fd, data.encode("utf-8", errors="replace"))

    def isalive(self) -> bool:
        return self._process.poll() is None

    def terminate(self) -> None:
        self._process.terminate()

    def close(self) -> None:
        try:
            os.close(self._master_fd)
        except OSError:
            pass


def create_shell_process(shell_type: str, cwd: str, use_pty: bool = True) -> PtyWrapper:
    if shell_type == "powershell":
        cmdline = "powershell.exe -NoLogo -NoExit" if sys.platform == "win32" else "pwsh -NoLogo -NoExit"
    elif shell_type == "cmd":
        cmdline = "cmd.exe"
    elif shell_type == "bash":
        cmdline = "bash"
    else:
        cmdline = shell_type

    if sys.platform == "win32" and use_pty and _WINPTY_AVAILABLE and PtyProcess is not None:
        process = PtyProcess.spawn(
            cmdline,
            cwd=cwd,
            dimensions=(40, 120),
            env={
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            },
        )
        return PtyWrapper(process, is_pty=True)

    if sys.platform == "win32":
        process = subprocess.Popen(
            cmdline.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "CHCP": "65001",
            },
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            bufsize=0,
        )
        return PtyWrapper(process, is_pty=False)

    if use_pty:
        import pty

        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            cmdline.split(),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
            **build_subprocess_group_kwargs(),
        )
        os.close(slave_fd)
        return PtyWrapper(PosixPtyProcess(process, master_fd), is_pty=True)

    process = subprocess.Popen(
        cmdline.split(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
        bufsize=0,
        **build_subprocess_group_kwargs(),
    )
    return PtyWrapper(process, is_pty=False)
