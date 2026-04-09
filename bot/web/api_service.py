"""Web 模式共享服务层。"""

from __future__ import annotations

import asyncio
import copy
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from bot.assistant.llm import (
    ANTHROPIC_AVAILABLE,
    call_claude_with_memory_tools_stream,
    get_tool_usage_stats,
)
from bot.assistant.memory import get_memory_store
from bot.cli_params import get_default_params, get_params_schema
from bot.cli import (
    build_cli_command,
    normalize_cli_type,
    parse_codex_json_line,
    parse_codex_json_output,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    should_reset_kimi_session,
)
from bot.config import CLI_EXEC_TIMEOUT
from bot.handlers.admin import execute_script, list_available_scripts
from bot.handlers.assistant import _build_system_prompt_with_memory
from bot.handlers.shell import strip_ansi_escape
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import BotProfile, UserSession
from bot.sessions import get_or_create_session, reset_session, sessions, sessions_lock, update_bot_working_dir
from bot.utils import is_dangerous_command, is_safe_filename


class WebApiError(Exception):
    """Web API 业务异常。"""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class AuthContext:
    """Web 请求的认证上下文。"""

    user_id: int
    token_used: bool


@dataclass
class CliAttemptState:
    """单次 CLI 尝试的会话状态。"""

    cli_session_id: Optional[str]
    resume_session: bool
    codex_session_id: Optional[str] = None
    new_kimi_session_id_created: bool = False


def _raise(status: int, code: str, message: str):
    raise WebApiError(status=status, code=code, message=message)


def get_profile_or_raise(manager: MultiBotManager, alias: str) -> BotProfile:
    alias = (alias or "").strip().lower()
    if alias == manager.main_profile.alias:
        return manager.main_profile
    profile = manager.managed_profiles.get(alias)
    if profile is None:
        _raise(404, "bot_not_found", f"未找到别名为 `{alias}` 的 Bot")
    return profile


def resolve_session_bot_id(manager: MultiBotManager, alias: str) -> int:
    app = manager.applications.get(alias)
    if app:
        bot_id = app.bot_data.get("bot_id")
        if isinstance(bot_id, int):
            return bot_id
    return -int(zlib.adler32(f"web:{alias}".encode("utf-8")))


def get_session_for_alias(manager: MultiBotManager, alias: str, user_id: int) -> UserSession:
    profile = get_profile_or_raise(manager, alias)
    return get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=user_id,
        default_working_dir=profile.working_dir,
    )


def _build_session_ids(session: UserSession) -> dict[str, Any]:
    return {
        "codex_session_id": session.codex_session_id,
        "kimi_session_id": session.kimi_session_id,
        "claude_session_id": session.claude_session_id,
        "claude_session_initialized": session.claude_session_initialized,
    }


def _build_running_reply_snapshot(session: UserSession) -> Optional[dict[str, Any]]:
    if not session.running_started_at:
        return None
    return {
        "user_text": session.running_user_text or "",
        "preview_text": session.running_preview_text or "",
        "started_at": session.running_started_at,
        "updated_at": session.running_updated_at or session.running_started_at,
    }


def build_session_snapshot(profile: BotProfile, session: UserSession) -> dict[str, Any]:
    with session._lock:
        return {
            "bot_alias": profile.alias,
            "bot_mode": profile.bot_mode,
            "cli_type": profile.cli_type,
            "cli_path": profile.cli_path,
            "working_dir": session.working_dir,
            "message_count": session.message_count,
            "history_count": len(session.history),
            "is_processing": session.is_processing,
            "running_reply": _build_running_reply_snapshot(session),
            "session_ids": _build_session_ids(session),
        }


def _build_capabilities(profile: BotProfile, is_main: bool) -> list[str]:
    capabilities = ["session", "history"]
    if profile.bot_mode == "cli":
        capabilities.extend(["chat", "exec", "files"])
    elif profile.bot_mode == "assistant":
        capabilities.extend(["chat", "memory"])
    elif profile.bot_mode == "webcli":
        capabilities.append("status")
    if is_main:
        capabilities.append("admin")
    return capabilities


def _build_run_status(manager: MultiBotManager, alias: str, profile: BotProfile) -> str:
    app = manager.applications.get(alias)
    if app:
        return "running"
    if alias == manager.main_profile.alias:
        return "configured"
    return "configured" if profile.enabled else "stopped"


def build_bot_summary(manager: MultiBotManager, alias: str, user_id: Optional[int] = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    app = manager.applications.get(alias)
    
    # 优先使用当前用户 session 的工作目录（如果用户已登录）
    working_dir = profile.working_dir
    if user_id is not None:
        try:
            session = get_session_for_alias(manager, alias, user_id)
            if session and session.working_dir:
                working_dir = session.working_dir
        except Exception:
            # 如果获取 session 失败，使用 profile 的工作目录
            pass
    
    return {
        "alias": profile.alias,
        "enabled": profile.enabled,
        "bot_mode": profile.bot_mode,
        "cli_type": profile.cli_type,
        "cli_path": profile.cli_path,
        "working_dir": working_dir,
        "is_main": alias == manager.main_profile.alias,
        "status": _build_run_status(manager, alias, profile),
        "bot_username": (app.bot_data.get("bot_username") if app else "") or "",
        "capabilities": _build_capabilities(profile, alias == manager.main_profile.alias),
    }


def list_bots(manager: MultiBotManager, user_id: Optional[int] = None) -> list[dict[str, Any]]:
    aliases = [manager.main_profile.alias, *sorted(manager.managed_profiles.keys())]
    return [build_bot_summary(manager, alias, user_id) for alias in aliases]


def get_overview(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    return {
        "bot": build_bot_summary(manager, alias),
        "session": build_session_snapshot(profile, session),
    }


def get_cli_params_payload(manager: MultiBotManager, alias: str, cli_type: Optional[str] = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    if not resolved_cli_type:
        _raise(400, "missing_cli_type", "缺少 CLI 类型")

    try:
        params = profile.cli_params.get_params(resolved_cli_type)
        schema = get_params_schema(resolved_cli_type)
        defaults = get_default_params(resolved_cli_type)
    except ValueError as exc:
        _raise(400, "invalid_cli_type", str(exc))

    return {
        "cli_type": resolved_cli_type,
        "params": copy.deepcopy(params),
        "schema": schema,
        "defaults": defaults,
    }


async def update_cli_params(
    manager: MultiBotManager,
    alias: str,
    cli_type: Optional[str],
    key: str,
    value: Any,
) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    if not key or not key.strip():
        _raise(400, "missing_param_key", "缺少参数名")

    try:
        await manager.set_bot_cli_param(alias, resolved_cli_type, key.strip(), value)
    except ValueError as exc:
        _raise(400, "invalid_param_value", str(exc))

    return get_cli_params_payload(manager, alias, resolved_cli_type)


async def reset_cli_params(manager: MultiBotManager, alias: str, cli_type: Optional[str] = None) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    resolved_cli_type = (cli_type or profile.cli_type or "").strip().lower()
    try:
        await manager.reset_bot_cli_params(alias, resolved_cli_type)
    except ValueError as exc:
        _raise(400, "invalid_cli_type", str(exc))
    return get_cli_params_payload(manager, alias, resolved_cli_type)


def _resolve_safe_path(session: UserSession, filename: str) -> str:
    if not is_safe_filename(filename):
        _raise(400, "unsafe_filename", "文件名包含非法字符")
    real_working = os.path.abspath(session.working_dir)
    real_path = os.path.abspath(os.path.join(session.working_dir, filename))
    try:
        common = os.path.commonpath([real_working, real_path])
    except ValueError:
        common = ""
    if common != real_working:
        _raise(400, "unsafe_path", "文件路径不安全")
    return real_path


def _list_directory_entries(working_dir: str) -> dict[str, Any]:
    entries = []
    for entry in sorted(os.scandir(working_dir), key=lambda item: (not item.is_dir(), item.name.lower())):
        item = {
            "name": entry.name,
            "is_dir": entry.is_dir(),
        }
        if entry.is_file():
            item["size"] = entry.stat().st_size
        entries.append(item)
    return {
        "working_dir": working_dir,
        "entries": entries,
    }


def get_directory_listing(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    try:
        return _list_directory_entries(session.working_dir)
    except FileNotFoundError:
        _raise(404, "working_dir_not_found", f"工作目录不存在: {session.working_dir}")
    except Exception as exc:
        _raise(500, "list_dir_failed", str(exc))


def get_working_directory(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    return {"working_dir": session.working_dir}


def change_working_directory(manager: MultiBotManager, alias: str, user_id: int, new_path: str) -> dict[str, Any]:
    if not new_path or not new_path.strip():
        _raise(400, "missing_path", "路径不能为空")
    profile = get_profile_or_raise(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    path = new_path.strip()
    if not os.path.isabs(path):
        path = os.path.join(session.working_dir, path)
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        _raise(404, "dir_not_found", f"目录不存在: {path}")

    if alias != manager.main_profile.alias:
        try:
            profile.working_dir = path
            manager._save_profiles()
            update_bot_working_dir(alias, path)
        except Exception as exc:
            _raise(500, "save_workdir_failed", str(exc))

    session.clear_session_ids()
    session.working_dir = path
    session.persist()
    return {"working_dir": session.working_dir}


def get_history(manager: MultiBotManager, alias: str, user_id: int, limit: int = 50) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    return {"items": session.history[-max(1, limit):]}


def reset_user_session(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    removed = reset_session(resolve_session_bot_id(manager, alias), user_id)
    return {"reset": removed}


def kill_user_process(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    with session._lock:
        if not session.is_processing or session.process is None:
            return {"killed": False, "message": msg("kill", "no_task")}
        process = session.process

    try:
        if process.poll() is None:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
            process.terminate()
            if process.poll() is None:
                process.kill()
            return {"killed": True, "message": msg("kill", "killed")}
        return {"killed": False, "message": msg("kill", "already_done")}
    except Exception as exc:
        _raise(500, "kill_failed", msg("kill", "error", error=str(exc)))


def _build_cli_env(cli_type: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if sys.platform == "win32":
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    if cli_type == "codex":
        env["CI"] = "true"
    return env


def _chunk_text(text: str, size: int = 160) -> list[str]:
    cleaned = text or ""
    if not cleaned:
        return []
    return [cleaned[index:index + size] for index in range(0, len(cleaned), size)]


def _prepare_cli_attempt_state(session: UserSession, cli_type: str) -> CliAttemptState:
    with session._lock:
        if cli_type == "codex":
            return CliAttemptState(
                cli_session_id=session.codex_session_id,
                resume_session=bool(session.codex_session_id),
                codex_session_id=session.codex_session_id,
            )
        if cli_type == "kimi":
            new_session_created = False
            if not session.kimi_session_id:
                session.kimi_session_id = f"kimi-{uuid.uuid4().hex}"
                new_session_created = True
            return CliAttemptState(
                cli_session_id=session.kimi_session_id,
                resume_session=False,
                new_kimi_session_id_created=new_session_created,
            )
        if cli_type == "claude":
            if not session.claude_session_id:
                session.claude_session_id = str(uuid.uuid4())
                session.claude_session_initialized = False
            return CliAttemptState(
                cli_session_id=session.claude_session_id,
                resume_session=session.claude_session_initialized,
            )
    return CliAttemptState(cli_session_id=None, resume_session=False)


def _clear_invalid_cli_session(session: UserSession, cli_type: str) -> bool:
    with session._lock:
        if cli_type == "codex":
            if session.codex_session_id is None:
                return False
            session.codex_session_id = None
            return True
        if cli_type == "kimi":
            if session.kimi_session_id is None:
                return False
            session.kimi_session_id = None
            return True
        if cli_type == "claude":
            changed = session.claude_session_id is not None or session.claude_session_initialized
            session.claude_session_id = None
            session.claude_session_initialized = False
            return changed
    return False


def _extract_codex_stream_preview(raw_output: str) -> Optional[str]:
    preview_parts: list[str] = []
    fallback_parts: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_codex_json_line(stripped)
        if parsed["delta_text"]:
            preview_parts.append(parsed["delta_text"])
            continue
        if parsed["error_text"]:
            fallback_parts.append(parsed["error_text"])
            continue
        if not stripped.startswith("{"):
            fallback_parts.append(stripped)

    preview_text = "".join(preview_parts).strip()
    if preview_text:
        return preview_text

    fallback_text = "\n".join(part for part in fallback_parts if part).strip()
    return fallback_text or None


def _build_stream_status_event(cli_type: str, elapsed_seconds: int, raw_output: str) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "status",
        "elapsed_seconds": elapsed_seconds,
    }
    if cli_type == "codex":
        preview_text = _extract_codex_stream_preview(raw_output)
        if preview_text:
            event["preview_text"] = preview_text[-800:]
    return event


def _wait_for_process_exit_sync(process: subprocess.Popen, timeout: float) -> Optional[int]:
    try:
        return process.wait(timeout=timeout)
    except Exception:
        return None


def _terminate_process_sync(process: subprocess.Popen, kill_timeout: float = 2.0) -> None:
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=kill_timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        process.kill()
        try:
            process.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            pass
    except Exception:
        pass


async def _communicate_process(process: subprocess.Popen) -> tuple[str, int, bool]:
    def run_process() -> tuple[str, int, bool]:
        try:
            stdout, _ = process.communicate(timeout=CLI_EXEC_TIMEOUT)
            return stdout or "", process.returncode or 0, False
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stdout, _ = process.communicate()
            return stdout or "", process.returncode or -1, True

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_process)


async def _communicate_codex_process(process: subprocess.Popen) -> tuple[str, Optional[str], int, bool]:
    raw_output, returncode, timed_out = await _communicate_process(process)
    final_text, thread_id = parse_codex_json_output(raw_output)
    if timed_out and not final_text:
        final_text = msg("chat", "timeout_no_output")
    elif not final_text:
        final_text = msg("chat", "no_output")
    return final_text, thread_id, returncode, timed_out


async def _stream_cli_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> AsyncIterator[dict[str, Any]]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "cli":
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    session = get_session_for_alias(manager, alias, user_id)
    text = (user_text or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.is_processing = True
    session.start_running_reply(text)

    try:
        session.touch()
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        session_id_changed = False
        history_added = False
        meta_sent = False
        max_attempts = 2 if cli_type == "claude" else 1

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type == "codex"),
                    params_config=profile.cli_params,
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            if not history_added:
                session.add_to_history("user", text)
                history_added = True

            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=session.working_dir,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )
            except FileNotFoundError:
                _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(text + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    process.wait()
                    _raise(500, "cli_write_failed", msg("chat", "cli_failed") + f": {exc}")

            with session._lock:
                session.process = process

            if not meta_sent:
                yield {
                    "type": "meta",
                    "alias": alias,
                    "cli_type": cli_type,
                    "working_dir": session.working_dir,
                    "resume_session": attempt.resume_session,
                }
                meta_sent = True

            output_queue: queue.Queue[Any] = queue.Queue()
            reader_done = threading.Event()
            raw_output_parts: list[str] = []
            thread_id: Optional[str] = None
            timed_out = False
            last_status_signature: tuple[int, Optional[str]] | None = None

            def read_stdout() -> None:
                try:
                    if process.stdout is None:
                        return
                    stdout = process.stdout
                    while True:
                        line = stdout.readline()
                        if line:
                            output_queue.put(line)
                            continue
                        if process.poll() is not None:
                            remaining = stdout.read()
                            if remaining:
                                output_queue.put(remaining)
                            break
                        time.sleep(0.05)
                except Exception as exc:  # pragma: no cover - defensive
                    output_queue.put(exc)
                finally:
                    reader_done.set()

            threading.Thread(target=read_stdout, daemon=True).start()

            try:
                while not reader_done.is_set() or not output_queue.empty():
                    if not timed_out and (loop.time() - started_at) >= CLI_EXEC_TIMEOUT and process.poll() is None:
                        timed_out = True
                        await loop.run_in_executor(None, _terminate_process_sync, process)

                    drained = False
                    while True:
                        try:
                            item = output_queue.get_nowait()
                        except queue.Empty:
                            break
                        drained = True
                        if isinstance(item, Exception):
                            raise item

                        text_chunk = str(item)
                        raw_output_parts.append(text_chunk)

                        if cli_type == "codex":
                            for line in text_chunk.splitlines():
                                stripped = line.strip()
                                if not stripped:
                                    continue
                                parsed = parse_codex_json_line(stripped)
                                if parsed["thread_id"]:
                                    thread_id = parsed["thread_id"]

                    status_event = _build_stream_status_event(
                        cli_type=cli_type,
                        elapsed_seconds=int(loop.time() - started_at),
                        raw_output="".join(raw_output_parts),
                    )
                    status_signature = (
                        int(status_event.get("elapsed_seconds", 0)),
                        status_event.get("preview_text"),
                    )
                    if status_signature != last_status_signature and (
                        status_signature[0] > 0 or status_signature[1]
                    ):
                        session.update_running_reply(status_event.get("preview_text"))
                        yield status_event
                        last_status_signature = status_signature

                    if not drained:
                        await asyncio.sleep(0.1)

                await loop.run_in_executor(None, _wait_for_process_exit_sync, process, 1.0)
                returncode = process.poll() if process is not None else -1
                if returncode is None:
                    returncode = -1
            finally:
                with session._lock:
                    session.process = None

            raw_output = "".join(raw_output_parts)
            if cli_type == "codex":
                response, parsed_thread_id = parse_codex_json_output(raw_output)
                thread_id = thread_id or parsed_thread_id
            else:
                response = raw_output.strip()

            if timed_out:
                response = response or msg("chat", "timeout_no_output")
            else:
                response = response or msg("chat", "no_output")

            if (
                cli_type == "claude"
                and not timed_out
                and attempt.resume_session
                and should_reset_claude_session(response, returncode)
                and attempt_index + 1 < max_attempts
            ):
                if _clear_invalid_cli_session(session, cli_type):
                    session_id_changed = True
                continue

            if cli_type == "codex":
                with session._lock:
                    if thread_id:
                        if session.codex_session_id != thread_id:
                            session.codex_session_id = thread_id
                            session_id_changed = True
                    elif should_reset_codex_session(attempt.codex_session_id, response, returncode):
                        if session.codex_session_id is not None:
                            session.codex_session_id = None
                            session_id_changed = True
            elif cli_type == "claude":
                with session._lock:
                    if timed_out:
                        pass
                    elif should_mark_claude_session_initialized(response, returncode):
                        if not session.claude_session_initialized:
                            session.claude_session_initialized = True
                            session_id_changed = True
                    elif should_reset_claude_session(response, returncode):
                        if session.claude_session_id is not None or session.claude_session_initialized:
                            session.claude_session_id = None
                            session.claude_session_initialized = False
                            session_id_changed = True
            elif cli_type == "kimi":
                with session._lock:
                    if not timed_out and should_reset_kimi_session(response, returncode):
                        if session.kimi_session_id is not None:
                            session.kimi_session_id = None
                            session_id_changed = True
                    elif not timed_out and attempt.new_kimi_session_id_created and session.kimi_session_id is not None:
                        session_id_changed = True

            if session_id_changed:
                session.persist()
                session_id_changed = False

            session.add_to_history("assistant", response)
            with session._lock:
                session.is_processing = False
            session.clear_running_reply()
            yield {
                "type": "done",
                "output": response,
                "returncode": returncode,
                "timed_out": timed_out,
                "session": build_session_snapshot(profile, session),
            }
            return
    finally:
        with session._lock:
            session.process = None
            session.is_processing = False
        session.clear_running_reply()


async def _stream_assistant_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> AsyncIterator[dict[str, Any]]:
    profile = get_profile_or_raise(manager, alias)
    yield {
        "type": "meta",
        "alias": alias,
        "cli_type": profile.cli_type,
        "working_dir": profile.working_dir,
        "resume_session": False,
    }
    data = await run_assistant_chat(manager, alias, user_id, user_text)
    for chunk in _chunk_text(data["output"]):
        yield {"type": "delta", "text": chunk}
    yield {"type": "done", "output": data["output"], "returncode": 0, "timed_out": False, "session": data["session"]}


async def run_cli_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "cli":
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持 CLI 对话")

    session = get_session_for_alias(manager, alias, user_id)
    text = (user_text or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")
    if text.startswith("//"):
        text = "/" + text[2:]

    cli_type = normalize_cli_type(profile.cli_type)
    env = _build_cli_env(cli_type)
    resolved_cli = resolve_cli_executable(profile.cli_path, session.working_dir)
    if resolved_cli is None:
        _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.is_processing = True
    session.start_running_reply(text)

    try:
        session.touch()
        session_id_changed = False
        history_added = False
        max_attempts = 2 if cli_type == "claude" else 1

        for attempt_index in range(max_attempts):
            attempt = _prepare_cli_attempt_state(session, cli_type)
            try:
                cmd, use_stdin = build_cli_command(
                    cli_type=cli_type,
                    resolved_cli=resolved_cli,
                    user_text=text,
                    env=env,
                    session_id=attempt.cli_session_id,
                    resume_session=attempt.resume_session,
                    json_output=(cli_type == "codex"),
                    params_config=profile.cli_params,
                )
            except ValueError as exc:
                _raise(400, "invalid_cli_command", str(exc))

            if not history_added:
                session.add_to_history("user", text)
                history_added = True

            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=session.working_dir,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )
            except FileNotFoundError:
                _raise(400, "cli_not_found", msg("chat", "no_cli", cli_path=profile.cli_path))

            if use_stdin:
                try:
                    assert process.stdin is not None
                    process.stdin.write(text + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    process.wait()
                    _raise(500, "cli_write_failed", msg("chat", "cli_failed") + f": {exc}")

            with session._lock:
                session.process = process

            try:
                if cli_type == "codex":
                    response, thread_id, returncode, timed_out = await _communicate_codex_process(process)
                else:
                    response, returncode, timed_out = await _communicate_process(process)
                    response = response.strip() or (msg("chat", "timeout_no_output") if timed_out else msg("chat", "no_output"))
            finally:
                with session._lock:
                    session.process = None

            if (
                cli_type == "claude"
                and not timed_out
                and attempt.resume_session
                and should_reset_claude_session(response, returncode)
                and attempt_index + 1 < max_attempts
            ):
                if _clear_invalid_cli_session(session, cli_type):
                    session_id_changed = True
                continue

            if cli_type == "codex":
                with session._lock:
                    if thread_id:
                        if session.codex_session_id != thread_id:
                            session.codex_session_id = thread_id
                            session_id_changed = True
                    elif should_reset_codex_session(attempt.codex_session_id, response, returncode):
                        if session.codex_session_id is not None:
                            session.codex_session_id = None
                            session_id_changed = True
            elif cli_type == "claude":
                with session._lock:
                    if timed_out:
                        pass
                    elif should_mark_claude_session_initialized(response, returncode):
                        if not session.claude_session_initialized:
                            session.claude_session_initialized = True
                            session_id_changed = True
                    elif should_reset_claude_session(response, returncode):
                        if session.claude_session_id is not None or session.claude_session_initialized:
                            session.claude_session_id = None
                            session.claude_session_initialized = False
                            session_id_changed = True
            elif cli_type == "kimi":
                with session._lock:
                    if not timed_out and should_reset_kimi_session(response, returncode):
                        if session.kimi_session_id is not None:
                            session.kimi_session_id = None
                            session_id_changed = True
                    elif not timed_out and attempt.new_kimi_session_id_created and session.kimi_session_id is not None:
                        session_id_changed = True

            if session_id_changed:
                session.persist()

            session.add_to_history("assistant", response)
            with session._lock:
                session.is_processing = False
            session.clear_running_reply()
            return {
                "output": response,
                "returncode": returncode,
                "timed_out": timed_out,
                "session": build_session_snapshot(profile, session),
            }
    finally:
        with session._lock:
            session.process = None
            session.is_processing = False
        session.clear_running_reply()


async def run_assistant_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "assistant":
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持助手对话")
    if not ANTHROPIC_AVAILABLE:
        _raise(503, "assistant_unavailable", "助手模式不可用：anthropic SDK 未安装")

    text = (user_text or "").strip()
    if not text:
        _raise(400, "empty_message", "消息不能为空")

    session = get_session_for_alias(manager, alias, user_id)
    with session._lock:
        if session.is_processing:
            _raise(409, "session_busy", msg("chat", "busy"))
        session.is_processing = True
    session.touch()
    session.start_running_reply(text)
    try:
        messages = []
        for item in session.history[-10:]:
            if item["role"] in ("user", "assistant"):
                messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": text})

        system_prompt = _build_system_prompt_with_memory(user_id, len(session.history) == 0)
        response_text = ""
        usage: dict[str, Any] = {}

        async for event in call_claude_with_memory_tools_stream(
            messages=messages,
            system_prompt=system_prompt,
            user_id=user_id,
        ):
            if event["type"] == "text":
                response_text += event["text"]
                session.update_running_reply(response_text)
            elif event["type"] == "usage":
                usage = event

        final_text = response_text
        if usage:
            final_text += (
                f"\n\n💰 Token 使用: {usage.get('input_tokens', 0)} 输入 + "
                f"{usage.get('output_tokens', 0)} 输出 = "
                f"{usage.get('input_tokens', 0) + usage.get('output_tokens', 0)} 总计"
            )

        session.add_to_history("user", text)
        session.add_to_history("assistant", response_text)
        with session._lock:
            session.is_processing = False
        session.clear_running_reply()
        return {
            "output": final_text,
            "usage": usage,
            "session": build_session_snapshot(profile, session),
        }
    finally:
        with session._lock:
            session.is_processing = False
        session.clear_running_reply()


async def run_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode == "cli":
        return await run_cli_chat(manager, alias, user_id, user_text)
    if profile.bot_mode == "assistant":
        return await run_assistant_chat(manager, alias, user_id, user_text)
    _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")


async def stream_chat(manager: MultiBotManager, alias: str, user_id: int, user_text: str) -> AsyncIterator[dict[str, Any]]:
    try:
        profile = get_profile_or_raise(manager, alias)
        if profile.bot_mode == "cli":
            async for event in _stream_cli_chat(manager, alias, user_id, user_text):
                yield event
            return
        if profile.bot_mode == "assistant":
            async for event in _stream_assistant_chat(manager, alias, user_id, user_text):
                yield event
            return
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，Web 对话暂不支持该模式")
    except WebApiError as exc:
        yield {"type": "error", "code": exc.code, "message": exc.message}
    except Exception as exc:  # pragma: no cover - defensive
        yield {"type": "error", "code": "internal_error", "message": str(exc)}


async def execute_shell_command(manager: MultiBotManager, alias: str, user_id: int, command: str) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "cli":
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持执行 Shell 命令")

    cmd = (command or "").strip()
    if not cmd:
        _raise(400, "empty_command", msg("shell", "usage"))
    if is_dangerous_command(cmd):
        _raise(400, "dangerous_command", msg("shell", "dangerous"))

    session = get_session_for_alias(manager, alias, user_id)

    def run_sync() -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=session.working_dir,
            timeout=60,
        )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, run_sync)
    except subprocess.TimeoutExpired:
        _raise(408, "shell_timeout", "命令执行超时 (60秒)")
    except Exception as exc:
        _raise(500, "shell_failed", str(exc))

    output = strip_ansi_escape(result.stdout or "")
    stderr = strip_ansi_escape(result.stderr or "")
    if stderr:
        output += f"\n\n[stderr]\n{stderr}"
    output = output or msg("shell", "no_output")
    return {
        "command": cmd,
        "output": output,
        "returncode": result.returncode,
        "working_dir": session.working_dir,
    }


def save_uploaded_file(manager: MultiBotManager, alias: str, user_id: int, filename: str, data: bytes) -> dict[str, Any]:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode != "cli":
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持上传文件")
    if not data:
        _raise(400, "empty_file", "文件内容不能为空")
    if len(data) > 20 * 1024 * 1024:
        _raise(400, "file_too_large", msg("upload", "file_too_large"))

    session = get_session_for_alias(manager, alias, user_id)
    file_path = _resolve_safe_path(session, filename)
    with open(file_path, "wb") as handle:
        handle.write(data)
    return {
        "filename": filename,
        "saved_path": file_path,
        "size": len(data),
    }


def get_file_metadata(manager: MultiBotManager, alias: str, user_id: int, filename: str) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    file_path = _resolve_safe_path(session, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")
    return {
        "filename": filename,
        "path": file_path,
        "size": os.path.getsize(file_path),
        "content_type": "application/octet-stream",
    }


def read_file_content(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    mode: str = "cat",
    lines: int = 20,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    file_path = _resolve_safe_path(session, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")

    file_size = os.path.getsize(file_path)
    if mode == "cat" and file_size > 1024 * 1024:
        _raise(400, "file_too_large", "文件太大，请使用下载接口")

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            if mode == "head":
                content_lines = []
                for index, line in enumerate(handle):
                    if index >= lines:
                        break
                    content_lines.append(line.rstrip("\n"))
                content = "\n".join(content_lines)
            else:
                content = handle.read()
    except UnicodeDecodeError:
        _raise(400, "unsupported_encoding", "文件不是文本文件或编码不支持")
    except Exception as exc:
        _raise(500, "read_file_failed", str(exc))

    return {
        "filename": filename,
        "mode": mode,
        "content": content,
        "working_dir": session.working_dir,
    }


def list_memories(user_id: int) -> dict[str, Any]:
    store = get_memory_store()
    return {"items": [memory.to_dict() for memory in store.get_user_memories(user_id)]}


def add_memory(user_id: int, content: str, category: str = "other", tags: Optional[list[str]] = None) -> dict[str, Any]:
    if not content or not content.strip():
        _raise(400, "empty_memory", "记忆内容不能为空")
    store = get_memory_store()
    memory = store.add_memory(user_id=user_id, content=content, category=category, tags=tags or [])
    return {"item": memory.to_dict()}


def search_memories(user_id: int, keyword: str, category: Optional[str] = None, limit: int = 10) -> dict[str, Any]:
    if not keyword or not keyword.strip():
        _raise(400, "empty_keyword", "搜索关键词不能为空")
    store = get_memory_store()
    memories = store.search_memories(user_id=user_id, keyword=keyword, category=category, limit=limit)
    return {"items": [memory.to_dict() for memory in memories]}


def delete_memory(memory_id: str) -> dict[str, Any]:
    store = get_memory_store()
    deleted = store.delete_memory(memory_id)
    if not deleted:
        _raise(404, "memory_not_found", f"未找到记忆: {memory_id}")
    return {"deleted": True}


def clear_memories(user_id: int) -> dict[str, Any]:
    store = get_memory_store()
    return {"deleted_count": store.clear_user_memories(user_id)}


def get_memory_tool_stats() -> dict[str, Any]:
    return {"items": get_tool_usage_stats()}


def list_system_scripts() -> dict[str, Any]:
    items = []
    for script_name, display_name, description, path in list_available_scripts():
        items.append(
            {
                "script_name": script_name,
                "display_name": display_name,
                "description": description,
                "path": str(path),
            }
        )
    return {"items": items}


async def run_system_script(script_name: str) -> dict[str, Any]:
    if not script_name or not script_name.strip():
        _raise(400, "empty_script_name", "脚本名不能为空")
    scripts = list_available_scripts()
    target_path: Optional[Path] = None
    for name, _, _, path in scripts:
        if name.lower() == script_name.strip().lower():
            target_path = path
            break
    if target_path is None:
        _raise(404, "script_not_found", f"未找到脚本: {script_name}")

    loop = asyncio.get_running_loop()
    success, output = await loop.run_in_executor(None, execute_script, target_path)
    return {
        "script_name": target_path.stem,
        "success": success,
        "output": output,
    }


async def add_managed_bot(
    manager: MultiBotManager,
    alias: str,
    token: str,
    bot_mode: str,
    cli_type: Optional[str],
    cli_path: Optional[str],
    working_dir: Optional[str],
) -> dict[str, Any]:
    profile = await manager.add_bot(alias, token, cli_type, cli_path, working_dir, bot_mode)
    return {"bot": build_bot_summary(manager, profile.alias)}


async def remove_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.remove_bot(alias)
    return {"removed": True, "alias": alias}


async def start_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.start_bot(alias)
    return {"bot": build_bot_summary(manager, alias)}


async def stop_managed_bot(manager: MultiBotManager, alias: str) -> dict[str, Any]:
    await manager.stop_bot(alias)
    return {"bot": build_bot_summary(manager, alias)}


async def update_bot_cli(manager: MultiBotManager, alias: str, cli_type: str, cli_path: str) -> dict[str, Any]:
    await manager.set_bot_cli(alias, cli_type, cli_path)
    return {"bot": build_bot_summary(manager, alias)}


async def update_bot_workdir(manager: MultiBotManager, alias: str, working_dir: str) -> dict[str, Any]:
    await manager.set_bot_workdir(alias, working_dir)
    return {"bot": build_bot_summary(manager, alias)}


def get_processing_sessions(alias: str) -> list[dict[str, Any]]:
    items = []
    with sessions_lock:
        for (bot_id, user_id), session in sessions.items():
            if session.bot_alias != alias:
                continue
            if not session.is_processing:
                continue
            items.append(
                {
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "working_dir": session.working_dir,
                    "message_count": session.message_count,
                }
            )
    return items
