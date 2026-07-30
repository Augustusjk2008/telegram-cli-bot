"""Cross-platform process group helpers."""

import asyncio
import contextlib
import os
import signal
import subprocess
from typing import Any


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _kernel32 = None


class ProcessTreeJob:
    """Windows Job Object handle used to contain subprocess descendants."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def terminate(self) -> None:
        handle = self._handle
        if handle is None or _kernel32 is None:
            return
        _kernel32.TerminateJobObject(handle, 1)

    def close(self) -> None:
        handle = self._handle
        if handle is None or _kernel32 is None:
            return
        self._handle = None
        _kernel32.CloseHandle(handle)


def attach_process_tree_job(process: subprocess.Popen) -> ProcessTreeJob | None:
    """Attach a Windows process to a kill-on-close Job Object when possible."""

    if os.name != "nt" or _kernel32 is None:
        return None
    process_handle = getattr(process, "_handle", None)
    if process_handle is None:
        return None
    job_handle = _kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        return None
    info = _JobObjectExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(
        job_handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        _kernel32.CloseHandle(job_handle)
        return None
    if not _kernel32.AssignProcessToJobObject(job_handle, wintypes.HANDLE(int(process_handle))):
        _kernel32.CloseHandle(job_handle)
        return None
    return ProcessTreeJob(job_handle)


def build_subprocess_group_kwargs() -> dict:
    if os.name == "nt":
        return {}
    return {"start_new_session": True}


def build_chat_cli_process_kwargs() -> dict:
    if os.name != "nt":
        return {"start_new_session": True}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0,
    )
    if not creationflags:
        return {}
    return {"creationflags": creationflags}


def build_hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not creationflags:
        return {}
    return {"creationflags": creationflags}


def terminate_process_tree_sync(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    process_pid = getattr(process, "pid", None)
    if os.name == "nt" and process_pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process_pid)],
                capture_output=True,
                timeout=5,
                check=False,
            )
            process.wait(timeout=2)
            return
        except Exception:
            pass

    if os.name != "nt" and process_pid:
        try:
            os.killpg(process_pid, signal.SIGTERM)
            process.wait(timeout=3)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process_pid, signal.SIGKILL)
                process.wait(timeout=2)
                return
            except ProcessLookupError:
                return
            except Exception:
                pass
        except Exception:
            pass

    process.terminate()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass

    process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


async def _wait_async_process(process: object, timeout: float) -> None:
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return
    result = wait()
    if hasattr(result, "__await__"):
        await asyncio.wait_for(result, timeout=timeout)


async def terminate_async_process_tree(process: asyncio.subprocess.Process) -> None:
    if getattr(process, "returncode", None) is not None:
        return

    process_pid = getattr(process, "pid", None)
    if os.name == "nt" and process_pid:
        try:
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(process_pid),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            with contextlib.suppress(Exception, asyncio.TimeoutError):
                await asyncio.wait_for(taskkill.wait(), timeout=5)
            with contextlib.suppress(Exception, asyncio.TimeoutError):
                await _wait_async_process(process, 2)
            if getattr(process, "returncode", None) is not None:
                return
        except Exception:
            pass

    if os.name != "nt" and process_pid:
        try:
            os.killpg(process_pid, signal.SIGTERM)
            with contextlib.suppress(asyncio.TimeoutError):
                await _wait_async_process(process, 3)
            if getattr(process, "returncode", None) is not None:
                return
            os.killpg(process_pid, signal.SIGKILL)
            with contextlib.suppress(asyncio.TimeoutError):
                await _wait_async_process(process, 2)
            return
        except ProcessLookupError:
            return
        except Exception:
            pass

    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        with contextlib.suppress(Exception):
            terminate()
        with contextlib.suppress(Exception, asyncio.TimeoutError):
            await _wait_async_process(process, 3)
        if getattr(process, "returncode", None) is not None:
            return

    kill = getattr(process, "kill", None)
    if callable(kill):
        with contextlib.suppress(Exception):
            kill()
        with contextlib.suppress(Exception, asyncio.TimeoutError):
            await _wait_async_process(process, 2)
