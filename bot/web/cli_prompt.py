"""Run one-shot text prompts through the configured local CLI providers."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any
from uuid import uuid4

from bot import config
from bot.cli import (
    DeepSeekJsonStreamParser,
    build_cli_command,
    parse_antigravity_json_output,
    parse_claude_stream_json_output,
    parse_codex_json_output,
    resolve_cli_executable,
)
from bot.cli_params import CliParamsConfig, with_global_extra_args
from bot.codex_server.runtime import CodexServerRegistry, CodexServerRuntimeRequest
from bot.platform.processes import build_hidden_process_kwargs, terminate_process_tree_sync
from bot.platform.subprocess_streams import close_process_streams


class CliPromptError(RuntimeError):
    """A one-shot CLI prompt failed before producing a usable response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if os.name == "nt":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    return env


async def _run_codex_server(
    *,
    resolved_cli: str,
    prompt_text: str,
    working_dir: str,
    env: dict[str, str],
    params_config: CliParamsConfig,
) -> tuple[str, int]:
    registry = CodexServerRegistry()
    request = CodexServerRuntimeRequest(
        owner_key=(0, 0, "one-shot-cli-prompt"),
        conversation_id=uuid4().hex,
        command=resolved_cli,
        cwd=working_dir,
        env=dict(env),
        params_config=params_config,
    )
    try:
        runtime = await registry.open_or_create(request)
        try:
            lines = [
                json.dumps(event, ensure_ascii=False)
                async for event in runtime.stream_turn(prompt_text)
            ]
        except TimeoutError:
            raise
        if runtime.returncode is None:
            raise CliPromptError("cli_failed", "CLI server 未返回完成状态")
        return "\n".join(lines), int(runtime.returncode)
    finally:
        await registry.aclose()


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None:
            terminate_process_tree_sync(process)
    except Exception:
        pass


async def _run_process(
    cmd: list[str],
    *,
    use_stdin: bool,
    prompt_text: str,
    working_dir: str,
    env: dict[str, str],
    timeout_seconds: float,
) -> tuple[str, int]:
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if use_stdin else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=working_dir,
            env=env,
            encoding="utf-8",
            errors="replace",
            **build_hidden_process_kwargs(),
        )
    except FileNotFoundError as exc:
        raise CliPromptError("cli_not_found", "未找到 CLI 可执行文件") from exc
    try:
        output, _ = await asyncio.wait_for(
            asyncio.to_thread(process.communicate, input=prompt_text + "\n" if use_stdin else None),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        _terminate(process)
        raise CliPromptError("timeout", "CLI 翻译请求超时") from exc
    except (BrokenPipeError, OSError) as exc:
        _terminate(process)
        raise CliPromptError("cli_failed", f"写入 CLI 失败: {exc}") from exc
    finally:
        close_process_streams(process)
    return str(output or ""), int(process.returncode or 0)


def parse_cli_prompt_output(raw_output: str, cli_type: str) -> str:
    normalized = str(cli_type or "").strip().lower()
    if normalized in {"codex", "codex_server"}:
        return parse_codex_json_output(raw_output)[0]
    if normalized == "claude":
        return parse_claude_stream_json_output(raw_output)[0]
    if normalized == "antigravity":
        return parse_antigravity_json_output(raw_output).final_text
    if normalized == "deepseek":
        output_size = max(1, len(str(raw_output or "").encode("utf-8", errors="replace")))
        parser = DeepSeekJsonStreamParser(raw_tail_max_bytes=output_size, final_text_max_bytes=output_size)
        for line in str(raw_output or "").splitlines(keepends=True):
            parser.consume_line(line)
        return parser.result().final_text
    return str(raw_output or "").strip()


async def run_cli_prompt(
    *,
    cli_type: str,
    cli_path: str,
    cli_params: dict[str, Any] | None,
    prompt_text: str,
    working_dir: str | None,
    timeout_seconds: float,
) -> tuple[str, int]:
    normalized_type = str(cli_type or "").strip().lower()
    cwd = str(working_dir or os.getcwd()).strip() or os.getcwd()
    resolved_cli = resolve_cli_executable(str(cli_path or "").strip(), cwd)
    if not resolved_cli:
        raise CliPromptError("cli_not_found", f"未找到 CLI 可执行文件: {cli_path}")
    params_config = with_global_extra_args(
        CliParamsConfig.from_dict(cli_params),
        config.CLI_GLOBAL_EXTRA_ARGS,
    )
    env = _build_env()
    if normalized_type == "codex_server":
        raw_output, returncode = await asyncio.wait_for(
            _run_codex_server(
                resolved_cli=resolved_cli,
                prompt_text=prompt_text,
                working_dir=cwd,
                env=env,
                params_config=params_config,
            ),
            timeout=timeout_seconds,
        )
    else:
        try:
            cmd, use_stdin = build_cli_command(
                cli_type=normalized_type,
                resolved_cli=resolved_cli,
                user_text=prompt_text,
                env=env,
                params_config=params_config,
                session_id=None,
                resume_session=False,
                json_output=True,
                working_dir=cwd,
            )
        except ValueError as exc:
            raise CliPromptError("invalid_cli_config", str(exc)) from exc
        raw_output, returncode = await _run_process(
            cmd,
            use_stdin=use_stdin,
            prompt_text=prompt_text,
            working_dir=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    return parse_cli_prompt_output(raw_output, normalized_type), returncode
