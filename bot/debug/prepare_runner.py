from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

_DEFAULT_PREPARE_COMMAND = r".\debug.bat"
_EXITED_STDOUT_DRAIN_TIMEOUT_SECONDS = 0.2


class PrepareRunError(RuntimeError):
    def __init__(self, code: str, message: str, *, logs: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.logs = list(logs or [])


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
    return ["sh", "-c", command]


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


async def stream_prepare(workspace: str | Path, request: dict[str, object]) -> AsyncIterator[str]:
    root = Path(workspace).resolve()
    command = build_prepare_command(root, request)
    password = str(request.get("password") or "")
    emitted_lines: list[str] = []
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(root),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise PrepareRunError("prepare_failed", "无法启动调试准备命令") from exc

    assert process.stdout is not None
    command_line = redact_output_line(build_prepare_display_command(request), password)
    emitted_lines.append(command_line)
    yield command_line

    wait_task = asyncio.create_task(process.wait())
    while True:
        if wait_task.done():
            chunk = await _readline_after_process_exit(process.stdout)
            if not chunk:
                break
            line = redact_output_line(chunk.decode("utf-8", errors="replace").rstrip(), password)
            emitted_lines.append(line)
            yield line
            continue

        read_task = asyncio.create_task(process.stdout.readline())
        done, _pending = await asyncio.wait({read_task, wait_task}, return_when=asyncio.FIRST_COMPLETED)
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
            break
        line = redact_output_line(chunk.decode("utf-8", errors="replace").rstrip(), password)
        emitted_lines.append(line)
        yield line

    return_code = await wait_task
    if return_code != 0:
        raise PrepareRunError(
            "prepare_failed",
            f"准备命令退出码 {return_code}",
            logs=emitted_lines,
        )
