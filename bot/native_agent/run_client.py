from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bot.config as config
from bot.cli import resolve_cli_executable
from bot.native_agent.run_config import runtime_config_key, write_runtime_opencode_config
from bot.platform.executables import build_executable_invocation
from bot.platform.processes import build_chat_cli_process_kwargs


class NativeAgentRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        raw_output: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.raw_output = raw_output


@dataclass(frozen=True)
class NativeAgentRunRequest:
    cwd: str
    prompt: str
    command: str = ""
    session_id: str = ""
    model_id: str = ""
    agent_id: str = ""
    variant: str = ""
    native_agent: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeAgentExportRequest:
    cwd: str
    session_id: str
    command: str = ""
    native_agent: dict[str, Any] = field(default_factory=dict)


class NativeAgentRunClient:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.config_path: Path | None = None
        self.stderr_text = ""
        self.raw_output_text = ""

    def build_run_command(self, request: NativeAgentRunRequest) -> tuple[list[str], dict[str, str], Path]:
        cwd = _normalize_cwd(request.cwd)
        command = _command_text(request.command)
        key = runtime_config_key(working_dir=cwd, command=command, native_agent=request.native_agent)
        config_path = write_runtime_opencode_config(key=key, native_agent=request.native_agent)
        invocation = _resolve_invocation(command, cwd)
        args = [
            *invocation,
            "run",
            "--format",
            "json",
            "--dir",
            cwd,
        ]
        if str(request.session_id or "").strip():
            args.extend(["--session", str(request.session_id).strip()])
        if str(request.model_id or "").strip():
            args.extend(["--model", str(request.model_id).strip()])
        if str(request.agent_id or "").strip():
            args.extend(["--agent", str(request.agent_id).strip()])
        if str(request.variant or "").strip():
            args.extend(["--variant", str(request.variant).strip()])
        args.append(str(request.prompt or ""))
        env = _base_env(config_path)
        return args, env, config_path

    async def stream(self, request: NativeAgentRunRequest) -> AsyncIterator[dict[str, Any]]:
        args, env, config_path = self.build_run_command(request)
        self.config_path = config_path
        cwd = _normalize_cwd(request.cwd)
        stderr_lines: list[str] = []
        raw_lines: list[str] = []
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **build_chat_cli_process_kwargs(),
            )
        except FileNotFoundError as exc:
            raise NativeAgentRunError(f"未找到原生 agent 命令: {args[0]}，请检查 NATIVE_AGENT_COMMAND") from exc
        except OSError as exc:
            raise NativeAgentRunError(f"原生 agent run 启动失败: {exc}") from exc
        self.process = process

        stderr_thread = threading.Thread(target=_read_stream_to_list, args=(process.stderr, stderr_lines), daemon=True)
        stderr_thread.start()
        assert process.stdout is not None
        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if line == "":
                break
            raw_line = line.rstrip("\r\n")
            if not raw_line:
                continue
            raw_lines.append(raw_line)
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                yield {"type": "raw_text", "raw_text": raw_line}
                continue
            if isinstance(payload, dict):
                yield payload
            else:
                yield {"type": "raw_json", "value": payload}
        returncode = await asyncio.to_thread(process.wait)
        stderr_thread.join(timeout=0.5)
        self.stderr_text = "".join(stderr_lines)
        self.raw_output_text = "\n".join(raw_lines)
        if returncode != 0:
            detail = _format_failure_detail(self.stderr_text, self.raw_output_text)
            raise NativeAgentRunError(
                f"原生 agent run 退出码 {returncode}{detail}",
                returncode=returncode,
                stderr=self.stderr_text,
                raw_output=self.raw_output_text,
            )

    async def export_session(self, request: NativeAgentExportRequest) -> list[dict[str, Any]]:
        session_id = str(request.session_id or "").strip()
        if not session_id:
            return []
        cwd = _normalize_cwd(request.cwd)
        command = _command_text(request.command)
        key = runtime_config_key(working_dir=cwd, command=command, native_agent=request.native_agent)
        config_path = write_runtime_opencode_config(key=key, native_agent=request.native_agent)
        args = [*_resolve_invocation(command, cwd), "export", session_id]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                args,
                cwd=cwd,
                env=_base_env(config_path),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                **build_chat_cli_process_kwargs(),
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        try:
            payload = json.loads(completed.stdout or "")
        except json.JSONDecodeError:
            return []
        return _extract_export_messages(payload)

    def kill(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()


def is_session_unavailable_error(exc: BaseException) -> bool:
    text = f"{exc}".lower()
    if "session" not in text:
        return False
    return any(marker in text for marker in ("not found", "missing", "invalid", "does not exist", "unknown", "不存在", "无效"))


def _normalize_cwd(cwd: str) -> str:
    return str(Path(str(cwd or ".")).expanduser().resolve())


def _command_text(command: str) -> str:
    return str(command or config.NATIVE_AGENT_COMMAND or config.NATIVE_AGENT_PATH or "opencode").strip() or "opencode"


def _resolve_invocation(command: str, cwd: str) -> list[str]:
    resolved = resolve_cli_executable(command, cwd)
    if resolved:
        return build_executable_invocation(resolved)
    return [command]


def _base_env(config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(config_path)
    env["PYTHONUNBUFFERED"] = "1"
    if os.name == "nt":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    return env


def _read_stream_to_list(stream: Any, target: list[str]) -> None:
    if stream is None:
        return
    try:
        for line in stream:
            target.append(str(line))
    except Exception:
        return


def _format_failure_detail(stderr_text: str, raw_output: str) -> str:
    combined = "\n".join(item for item in (stderr_text.strip(), raw_output.strip()) if item)
    if not combined:
        return ""
    return f": {combined[:2000]}"


def _extract_export_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    session = payload.get("session")
    if isinstance(session, dict):
        return _extract_export_messages(session)
    return []
