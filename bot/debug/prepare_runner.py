from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_PREPARE_COMMAND = r".\debug.bat"
_EXITED_STDOUT_DRAIN_TIMEOUT_SECONDS = 0.2


class PrepareRunError(RuntimeError):
    def __init__(self, code: str, message: str, *, logs: list[str] | None = None, command: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.logs = list(logs or [])
        self.command = command


def _prepare_value(request: dict[str, object], key: str) -> str:
    return str(request.get(key) or "")


def build_prepare_display_command(request: dict[str, object]) -> str:
    command = str(request.get("prepare_command") or _DEFAULT_PREPARE_COMMAND).strip() or _DEFAULT_PREPARE_COMMAND
    replacements = {
        "remoteHost": _prepare_value(request, "remote_host"),
        "remote_host": _prepare_value(request, "remote_host"),
        "remoteUser": _prepare_value(request, "remote_user"),
        "remote_user": _prepare_value(request, "remote_user"),
        "remoteDir": _prepare_value(request, "remote_dir"),
        "remote_dir": _prepare_value(request, "remote_dir"),
        "remotePort": _prepare_value(request, "remote_port"),
        "remote_port": _prepare_value(request, "remote_port"),
        "remoteGdbPort": _prepare_value(request, "remote_port"),
        "remote_gdb_port": _prepare_value(request, "remote_port"),
        "password": _prepare_value(request, "password"),
    }
    for key, value in replacements.items():
        command = command.replace("${" + key + "}", value)
    return command


def build_prepare_command(workspace: str | Path, request: dict[str, object]) -> list[str]:
    command = build_prepare_display_command(request)
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["sh", "-lc", command]


def redact_command(command: list[str]) -> list[str]:
    redacted = command[:]
    for index, part in enumerate(redacted[:-1]):
        if part == "-Password":
            redacted[index + 1] = "******"
    return redacted


def redact_output_line(line: str, password: str) -> str:
    if not password:
        return line
    return line.replace(password, "******")


async def _readline_after_process_exit(stdout: asyncio.StreamReader) -> bytes | None:
    try:
        return await asyncio.wait_for(stdout.readline(), timeout=_EXITED_STDOUT_DRAIN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_event(line: str, *, redacted: bool, phase: str = "prepare", event_type: str = "line") -> dict[str, object]:
    return {
        "type": event_type,
        "line": line,
        "redacted": redacted,
        "phase": phase,
        "timestamp": _now_iso(),
    }


def _timeout_seconds(request: dict[str, object]) -> float:
    raw = request.get("timeoutSeconds", request.get("timeout_seconds", 300))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 300
    return value if value > 0 else 300


def _cancel_requested(request: dict[str, object]) -> bool:
    token = request.get("cancelToken", request.get("cancel_token"))
    if token is None:
        return False
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return bool(token)


async def _kill_process(process: object) -> None:
    kill = getattr(process, "kill", None)
    terminate = getattr(process, "terminate", None)
    if callable(kill):
        with contextlib.suppress(Exception):
            kill()
    elif callable(terminate):
        with contextlib.suppress(Exception):
            terminate()
    wait = getattr(process, "wait", None)
    if callable(wait):
        with contextlib.suppress(Exception, asyncio.TimeoutError):
            await asyncio.wait_for(wait(), timeout=0.1)


async def stream_prepare_events(workspace: str | Path, request: dict[str, object]) -> AsyncIterator[dict[str, object]]:
    root = Path(workspace).resolve()
    command = build_prepare_command(root, request)
    password = str(request.get("password") or "")
    emitted_lines: list[str] = []
    display_command = build_prepare_display_command(request)
    command_line = redact_output_line(display_command, password)
    timeout_seconds = _timeout_seconds(request)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(root),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise PrepareRunError("prepare_spawn_failed", "无法启动调试准备命令", command=command_line) from exc

    assert process.stdout is not None
    emitted_lines.append(command_line)
    yield _prepare_event(command_line, redacted=bool(password and password in display_command), event_type="command")

    wait_task = asyncio.create_task(process.wait())
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        if _cancel_requested(request):
            await _kill_process(process)
            wait_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_task
            raise PrepareRunError("prepare_cancelled", "准备命令已取消", logs=emitted_lines, command=command_line)
        if asyncio.get_running_loop().time() >= deadline:
            await _kill_process(process)
            wait_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_task
            raise PrepareRunError("prepare_timeout", "准备命令超时", logs=emitted_lines, command=command_line)
        if wait_task.done():
            chunk = await _readline_after_process_exit(process.stdout)
            if not chunk:
                break
            line = redact_output_line(chunk.decode("utf-8", errors="replace").rstrip(), password)
            emitted_lines.append(line)
            yield _prepare_event(line, redacted=bool(password and password in line))
            continue

        read_task = asyncio.create_task(process.stdout.readline())
        timeout = max(0.001, min(0.1, deadline - asyncio.get_running_loop().time()))
        done, _pending = await asyncio.wait({read_task, wait_task}, return_when=asyncio.FIRST_COMPLETED, timeout=timeout)
        if not done:
            read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await read_task
            continue
        if read_task in done:
            chunk = read_task.result()
        else:
            try:
                chunk = await asyncio.wait_for(read_task, timeout=_EXITED_STDOUT_DRAIN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                read_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await read_task
                break

        if not chunk:
            if wait_task.done():
                break
            await asyncio.sleep(min(0.05, max(0.001, deadline - asyncio.get_running_loop().time())))
            continue
        line = redact_output_line(chunk.decode("utf-8", errors="replace").rstrip(), password)
        emitted_lines.append(line)
        yield _prepare_event(line, redacted=bool(password and password in line))

    return_code = await wait_task
    if return_code != 0:
        raise PrepareRunError(
            "prepare_failed",
            f"准备命令退出码 {return_code}",
            logs=emitted_lines,
            command=command_line,
        )


async def stream_prepare(workspace: str | Path, request: dict[str, object]) -> AsyncIterator[str]:
    async for event in stream_prepare_events(workspace, request):
        yield str(event.get("line") or "")
