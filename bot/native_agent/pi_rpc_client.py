from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.cli import resolve_cli_executable
from bot.platform.executables import build_executable_invocation
from bot.platform.processes import build_chat_cli_process_kwargs, terminate_process_tree_sync


DEFAULT_PI_COMMAND = "pi"
DEFAULT_TIMEOUT_SECONDS = 5.0
TAIL_LIMIT = 1600


class PiRpcRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        stdout: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@dataclass(frozen=True)
class PiRpcStartRequest:
    command: str | None
    cwd: Path
    env: dict[str, str] | None = None
    model: str | None = None
    timeout_seconds: float | None = None


class _TailBuffer:
    def __init__(self, limit: int = TAIL_LIMIT) -> None:
        self._limit = max(1, int(limit))
        self._items: list[str] = []
        self._size = 0
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._items.append(text)
            self._size += len(text)
            while self._items and self._size > self._limit:
                overflow = self._size - self._limit
                first = self._items[0]
                if len(first) <= overflow:
                    self._size -= len(first)
                    self._items.pop(0)
                else:
                    self._items[0] = first[overflow:]
                    self._size -= overflow
                    break

    def text(self) -> str:
        with self._lock:
            return "".join(self._items)


class PiRpcClient:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        timeout_seconds: float | None,
    ) -> None:
        self.process = process
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        self._lock = asyncio.Lock()
        self._closed = False
        self._killed = False
        self._stderr_tail = _TailBuffer()
        self._stdout_tail = _TailBuffer()
        self._stderr_thread = threading.Thread(
            target=_drain_stream_to_tail,
            args=(process.stderr, self._stderr_tail),
            daemon=True,
        )
        self._stderr_thread.start()

    @classmethod
    async def start(cls, request: PiRpcStartRequest) -> PiRpcClient:
        cwd = Path(request.cwd or ".").expanduser().resolve()
        args = _build_rpc_command(request.command, str(cwd), model=request.model)
        env = _base_env(request.env)
        try:
            process = subprocess.Popen(
                args,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **build_chat_cli_process_kwargs(),
            )
        except FileNotFoundError as exc:
            raise PiRpcRunError(f"未找到 Pi RPC 命令: {args[0]}") from exc
        except OSError as exc:
            raise PiRpcRunError(f"Pi RPC 启动失败: {exc}") from exc
        return cls(process, timeout_seconds=request.timeout_seconds)

    async def send(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            raise TypeError("Pi RPC message 必须是 dict")
        await self._write_packet(message)

    async def prompt(
        self,
        text: str,
        *,
        conversation_id: str | None = None,
        agent_id: str = "",
        reasoning_effort: str = "",
    ) -> None:
        normalized_reasoning = str(reasoning_effort or "").strip()
        if normalized_reasoning:
            await self.send({"type": "set_thinking_level", "level": normalized_reasoning})
        normalized_agent = str(agent_id or "").strip().lstrip("/")
        prompt_text = str(text or "")
        if normalized_agent and not prompt_text.lstrip().startswith("/"):
            prompt_text = f"/{normalized_agent} {prompt_text}".strip()
        message: dict[str, Any] = {"type": "prompt", "message": prompt_text}
        if conversation_id:
            message["conversation_id"] = str(conversation_id)
        await self.send(message)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        stdout = self.process.stdout
        if stdout is None:
            await self._raise_if_failed(await self._wait_no_timeout())
            return
        while True:
            try:
                line = await asyncio.to_thread(stdout.readline)
            except (OSError, ValueError):
                break
            if line == "":
                break
            raw_line = line.rstrip("\r\n")
            if not raw_line:
                continue
            self._stdout_tail.append(raw_line + "\n")
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                yield {
                    "type": "diagnostic",
                    "source": "pi_rpc_transport",
                    "level": "warning",
                    "message": f"Pi RPC 输出不是有效 JSON: {exc.msg}",
                    "raw": raw_line,
                }
                continue
            if isinstance(payload, dict):
                yield payload
            else:
                yield {
                    "type": "diagnostic",
                    "source": "pi_rpc_transport",
                    "level": "warning",
                    "message": "Pi RPC 输出不是 JSON 对象",
                    "raw": raw_line,
                }
        returncode = await self._wait_no_timeout()
        await self._raise_if_failed(returncode)

    async def abort(self) -> None:
        if self.process.poll() is not None:
            return
        async with self._lock:
            if self.process.poll() is None:
                await self._write_packet_unlocked({"type": "abort"}, ignore_errors=True)
        try:
            await self._wait_for_exit(self.timeout_seconds)
        except subprocess.TimeoutExpired:
            await self.kill()
            return
        self._close_streams()
        await asyncio.to_thread(self._stderr_thread.join, 0.5)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            _safe_close(self.process.stdin)
        if self.process.poll() is None:
            try:
                await self._wait_for_exit(self.timeout_seconds)
            except subprocess.TimeoutExpired:
                await self.kill()
        self._close_streams()
        await asyncio.to_thread(self._stderr_thread.join, 0.5)

    async def kill(self) -> None:
        async with self._lock:
            if self._killed:
                return
            self._killed = True
            process = self.process
        if process.poll() is None:
            await asyncio.to_thread(terminate_process_tree_sync, process)
        self._close_streams()
        await asyncio.to_thread(self._stderr_thread.join, 0.5)

    async def _write_packet(self, message: dict[str, Any]) -> None:
        async with self._lock:
            await self._write_packet_unlocked(message, ignore_errors=False)

    async def _write_packet_unlocked(self, message: dict[str, Any], *, ignore_errors: bool) -> None:
        stdin = self.process.stdin
        if self.process.poll() is not None or stdin is None or stdin.closed:
            if ignore_errors:
                return
            raise PiRpcRunError("Pi RPC 进程未运行，无法写入")
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            await asyncio.to_thread(stdin.write, line)
            await asyncio.to_thread(stdin.flush)
        except (BrokenPipeError, OSError, ValueError):
            if not ignore_errors:
                raise PiRpcRunError("Pi RPC stdin 写入失败")

    async def _wait_for_exit(self, timeout: float | None) -> int:
        try:
            return await asyncio.to_thread(self.process.wait, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise

    async def _wait_no_timeout(self) -> int:
        return await asyncio.to_thread(self.process.wait)

    async def _raise_if_failed(self, returncode: int) -> None:
        await asyncio.to_thread(self._stderr_thread.join, 0.5)
        if returncode == 0:
            return
        stderr = self._stderr_tail.text()
        stdout = self._stdout_tail.text()
        detail = _format_failure_detail(stderr, stdout)
        raise PiRpcRunError(
            f"Pi RPC 退出码 {returncode}{detail}",
            returncode=returncode,
            stderr=stderr,
            stdout=stdout,
        )

    def _close_streams(self) -> None:
        _safe_close(self.process.stdin)
        _safe_close(self.process.stdout)
        _safe_close(self.process.stderr)


def _build_rpc_command(command: str | None, cwd: str, *, model: str | None = None) -> list[str]:
    command_text = str(command or DEFAULT_PI_COMMAND).strip() or DEFAULT_PI_COMMAND
    resolved = resolve_cli_executable(command_text, cwd)
    invocation = build_executable_invocation(resolved) if resolved else [command_text]
    args = [*invocation, "--mode", "rpc"]
    normalized_model = str(model or "").strip()
    if normalized_model:
        args.extend(["--model", normalized_model])
    return args


def _base_env(extra_env: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if os.name == "nt":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    for key, value in (extra_env or {}).items():
        env[str(key)] = str(value)
    return env


def _drain_stream_to_tail(stream: Any, tail: _TailBuffer) -> None:
    if stream is None:
        return
    try:
        for line in stream:
            tail.append(str(line))
    except Exception:
        return


def _safe_close(stream: Any) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        return


def _format_failure_detail(stderr: str, stdout: str) -> str:
    combined = "\n".join(item.strip() for item in (stderr, stdout) if item.strip())
    if not combined:
        return ""
    if len(combined) > 2000:
        combined = combined[-2000:]
    return f": {combined}"
