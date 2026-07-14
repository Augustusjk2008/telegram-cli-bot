"""Terminal process helpers shared by the Web runtime."""

from __future__ import annotations

import logging
import os
import base64
import select
import shlex
import shutil
import subprocess
import sys
import threading
from typing import Union

from bot.platform.processes import build_subprocess_group_kwargs, terminate_process_tree_sync
from bot.platform.subprocess_streams import close_process_streams

logger = logging.getLogger(__name__)


class TerminalLaunchError(RuntimeError):
    """终端 shell 启动失败。"""


def _format_launch_error(argv: list[str], exc: OSError) -> str:
    command = argv[0] if argv else ""
    if isinstance(exc, FileNotFoundError):
        return f"终端 shell 未找到: {command}"
    if isinstance(exc, PermissionError):
        return f"终端 shell 无执行权限: {command}"
    return f"终端 shell 启动失败: {command or exc}"

try:
    import fcntl
    import struct
    import termios
except ImportError:
    fcntl = None
    struct = None
    termios = None

try:
    from winpty import PtyProcess

    _WINPTY_AVAILABLE = True
except ImportError:
    PtyProcess = None
    _WINPTY_AVAILABLE = False


class PtyWrapper:
    """Unify winpty.PtyProcess and subprocess-backed terminal processes."""

    def __init__(
        self,
        process: Union[subprocess.Popen, "PtyProcess", "PosixPtyProcess"],
        is_pty: bool = False,
        *,
        read_timeout_supported: bool = False,
    ):
        self.process = process
        self.is_pty = is_pty
        self.read_timeout_supported = read_timeout_supported
        self._lock = threading.Lock()

    def read(self, timeout: int = 1000) -> bytes:
        if self.is_pty:
            try:
                if self.read_timeout_supported:
                    return self.process.read(timeout=timeout)
                return self.process.read(4096)
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

    def resize(self, cols: int, rows: int) -> bool:
        if not self.is_pty:
            return False

        try:
            resize = getattr(self.process, "resize", None)
            if callable(resize):
                resize(cols, rows)
                return True

            setwinsize = getattr(self.process, "setwinsize", None)
            if callable(setwinsize):
                setwinsize(rows, cols)
                return True
        except Exception:
            return False
        return False

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

        terminate_process_tree_sync(self.process)

    def close(self) -> None:
        with self._lock:
            if self.is_pty:
                try:
                    self.process.close()
                except Exception:
                    pass
                return
            close_process_streams(self.process)

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

    def resize(self, cols: int, rows: int) -> None:
        if not fcntl or not struct or not termios:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def isalive(self) -> bool:
        return self._process.poll() is None

    def terminate(self) -> None:
        terminate_process_tree_sync(self._process)

    def close(self) -> None:
        try:
            os.close(self._master_fd)
        except OSError:
            pass


def _normalize_terminal_size(cols: int | None, rows: int | None) -> tuple[int, int]:
    safe_cols = max(2, int(cols or 120))
    safe_rows = max(2, int(rows or 40))
    return safe_cols, safe_rows


def _build_windows_powershell_command(executable: str) -> str:
    setup = (
        "try { chcp.com 65001 > $null 2>&1 } catch {}; "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [Console]::OutputEncoding"
    )
    encoded_setup = base64.b64encode(setup.encode("utf-16-le")).decode("ascii")
    return f"{executable} -NoLogo -NoExit -EncodedCommand {encoded_setup}"


def _build_posix_shell_argv(shell_type: str) -> list[str]:
    if sys.platform == "darwin":
        argv = shlex.split(shell_type or os.environ.get("SHELL") or "/bin/zsh", posix=True)
        if not argv:
            argv = ["/bin/zsh"]
        if argv[0] in {"bash", "zsh", "sh"}:
            argv[0] = f"/bin/{argv[0]}"
        if not any(arg in {"-l", "--login"} for arg in argv[1:]):
            argv.append("-l")
        return argv
    argv = shlex.split(shell_type or "bash", posix=True)
    return argv or ["bash"]


def _validate_posix_shell_argv(argv: list[str]) -> None:
    command = argv[0] if argv else ""
    if not command:
        raise TerminalLaunchError("终端 shell 不能为空")
    if "\\" in command or (len(command) >= 2 and command[1] == ":"):
        raise TerminalLaunchError(f"终端 shell 不是当前 Linux/macOS 可执行路径: {command}")
    if os.path.isabs(command):
        if not os.path.exists(command):
            raise TerminalLaunchError(f"终端 shell 未找到: {command}")
        if not os.access(command, os.X_OK):
            raise TerminalLaunchError(f"终端 shell 无执行权限: {command}")
        return
    if shutil.which(command) is None:
        raise TerminalLaunchError(f"终端 shell 未找到: {command}")


def create_shell_process(
    shell_type: str,
    cwd: str,
    use_pty: bool = True,
    cols: int | None = None,
    rows: int | None = None,
) -> PtyWrapper:
    if shell_type == "powershell":
        cmdline = _build_windows_powershell_command("powershell.exe") if sys.platform == "win32" else "pwsh -NoLogo -NoExit"
    elif shell_type == "cmd":
        cmdline = "cmd.exe"
    elif shell_type == "bash":
        cmdline = "bash"
    else:
        cmdline = shell_type

    cols, rows = _normalize_terminal_size(cols, rows)

    if sys.platform == "win32" and use_pty and _WINPTY_AVAILABLE and PtyProcess is not None:
        try:
            process = PtyProcess.spawn(
                cmdline,
                cwd=cwd,
                dimensions=(rows, cols),
                env={
                    **os.environ,
                    "FORCE_COLOR": "1",
                    "TERM": "xterm-256color",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "PYTHONUNBUFFERED": "1",
                    "CHCP": "65001",
                },
            )
        except OSError as exc:
            raise TerminalLaunchError(_format_launch_error([cmdline], exc)) from exc
        return PtyWrapper(process, is_pty=True)

    if sys.platform == "win32":
        try:
            process = subprocess.Popen(
                cmdline,
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
        except OSError as exc:
            raise TerminalLaunchError(_format_launch_error([cmdline], exc)) from exc
        return PtyWrapper(process, is_pty=False)

    if use_pty:
        import pty

        argv = _build_posix_shell_argv(cmdline)
        _validate_posix_shell_argv(argv)
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
                **build_subprocess_group_kwargs(),
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            raise TerminalLaunchError(_format_launch_error(argv, exc)) from exc
        os.close(slave_fd)
        pty_process = PosixPtyProcess(process, master_fd)
        pty_process.resize(cols, rows)
        return PtyWrapper(pty_process, is_pty=True, read_timeout_supported=True)

    argv = _build_posix_shell_argv(cmdline)
    _validate_posix_shell_argv(argv)
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
            bufsize=0,
            **build_subprocess_group_kwargs(),
        )
    except OSError as exc:
        raise TerminalLaunchError(_format_launch_error(argv, exc)) from exc
    return PtyWrapper(process, is_pty=False)
