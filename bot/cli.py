"""CLI 可执行文件解析、命令构建、输出解析"""

import json
import logging
import os
import queue
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from bot.config import SUPPORTED_CLI_TYPES
from bot.cli_params import build_cli_args_from_config, CliParamsConfig
from bot.platform.executables import resolve_cli_executable as _resolve_cli_executable

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_]")
CONTEXT_LEFT_RE = re.compile(r"\d+%\s+context\s+left", re.IGNORECASE)
GENERIC_LEFT_RE = re.compile(r"\d+%\s+left", re.IGNORECASE)
CODEX_STATUS_FALLBACK_WAIT_SECONDS = 8.0


def resolve_cli_executable(cli_path: str, working_dir: Optional[str] = None) -> Optional[str]:
    """解析 CLI 可执行文件路径，兼容 Windows 下 cmd/bat 可执行项。"""
    return _resolve_cli_executable(cli_path, working_dir)


def normalize_cli_type(cli_type: str) -> str:
    return (cli_type or "").strip().lower()


def validate_cli_type(cli_type: str) -> str:
    normalized = normalize_cli_type(cli_type)
    if normalized not in SUPPORTED_CLI_TYPES:
        supported = ", ".join(sorted(SUPPORTED_CLI_TYPES))
        raise ValueError(f"不支持的 cli_type: {cli_type} (支持: {supported})")
    return normalized


def build_cli_command(
    cli_type: str,
    resolved_cli: str,
    user_text: str,
    env: Dict[str, str],
    params_config: CliParamsConfig,
    session_id: Optional[str] = None,
    resume_session: bool = False,
    json_output: bool = False,
) -> Tuple[List[str], bool]:
    """构建不同 CLI 的命令行。所有支持的 CLI 均强制 yolo 模式。

    Args:
        cli_type: CLI 类型 (kimi/claude/codex)
        resolved_cli: 解析后的 CLI 可执行文件路径
        user_text: 用户输入文本
        env: 环境变量字典（会被修改以设置 CLI 特定的环境变量）
        params_config: CLI 参数配置
        session_id: 会话 ID
        resume_session: 是否恢复会话
        json_output: 是否使用 JSON 输出（Codex）
        params_config: CLI 参数配置
    """
    kind = validate_cli_type(cli_type)
    cmd, use_stdin = build_cli_args_from_config(
        cli_type=kind,
        resolved_cli=resolved_cli,
        params_config=params_config,
        user_text=user_text,
        session_id=session_id,
        resume_session=resume_session,
    )
    if kind == "claude":
        params = params_config.get_params("claude")
        if params.get("disable_prompts"):
            env["CLAUDE_CODE_DISABLE_PROMPTS"] = "1"
    return cmd, use_stdin


# ============ Codex JSON 解析相关函数 ============

def _extract_nested_nonempty_str(payload: Dict[str, Any], *path: str) -> Optional[str]:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str) and node.strip():
        return node.strip()
    return None


def _extract_codex_thread_id(event: Dict[str, Any]) -> Optional[str]:
    candidate_paths = (
        ("thread_id",),
        ("session_id",),
        ("conversation_id",),
        ("thread", "id"),
        ("session", "id"),
        ("conversation", "id"),
        ("data", "thread_id"),
        ("data", "session_id"),
        ("data", "conversation_id"),
    )
    for path in candidate_paths:
        value = _extract_nested_nonempty_str(event, *path)
        if value:
            return value
    return None


def _extract_codex_error_text(event: Dict[str, Any]) -> Optional[str]:
    for key in ("message", "error", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _extract_nested_nonempty_str(value, "message")
            if nested:
                return nested
            nested = _extract_nested_nonempty_str(value, "detail")
            if nested:
                return nested
            nested = _extract_nested_nonempty_str(value, "error")
            if nested:
                return nested
    return None


def parse_codex_json_line(line: str) -> Dict[str, Optional[str]]:
    """解析 codex --json 的单行事件。"""
    result: Dict[str, Optional[str]] = {
        "thread_id": None,
        "completed_text": None,
        "delta_text": None,
        "error_text": None,
    }
    try:
        event: Any = json.loads(line)
    except json.JSONDecodeError:
        return result

    if not isinstance(event, dict):
        return result

    result["thread_id"] = _extract_codex_thread_id(event)
    event_type = str(event.get("type", "")).strip()

    if event_type == "error":
        result["error_text"] = _extract_codex_error_text(event)
        return result

    if not event_type.startswith("item."):
        return result

    item = event.get("item")
    if not isinstance(item, dict):
        return result

    item_type = str(item.get("type", "")).strip()
    if item_type not in ("agent_message", "assistant_message"):
        return result

    text_value = item.get("text")
    delta_value = item.get("delta")

    if event_type == "item.completed":
        if isinstance(text_value, str) and text_value:
            result["completed_text"] = text_value
            result["delta_text"] = text_value
        return result

    if event_type == "item.delta":
        if isinstance(delta_value, str) and delta_value:
            result["delta_text"] = delta_value
        elif isinstance(text_value, str) and text_value:
            result["delta_text"] = text_value
        return result

    return result


def parse_codex_json_output(raw_output: str) -> Tuple[str, Optional[str]]:
    """解析 codex --json 的完整输出文本，提取 assistant 文本和 thread_id。"""
    raw_lines: List[str] = []
    completed_parts: List[str] = []
    delta_parts: List[str] = []
    error_parts: List[str] = []
    thread_id: Optional[str] = None

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_lines.append(stripped)
        parsed = parse_codex_json_line(stripped)
        if parsed["thread_id"]:
            thread_id = parsed["thread_id"]
        if parsed["completed_text"]:
            completed_parts.append(parsed["completed_text"])
        if parsed["delta_text"]:
            delta_parts.append(parsed["delta_text"])
        if parsed["error_text"]:
            error_parts.append(parsed["error_text"])

    if completed_parts:
        final_text = "\n\n".join(part for part in completed_parts if part.strip()).strip()
    else:
        final_text = "".join(delta_parts).strip()

    if not final_text and error_parts:
        final_text = "\n".join(error_parts).strip()
    if not final_text:
        final_text = "\n".join(raw_lines).strip()
    if not final_text:
        final_text = "(无输出)"

    return final_text, thread_id


def strip_ansi_terminal_text(text: str) -> str:
    """清洗终端控制字符，保留可读文本。"""
    return ANSI_ESCAPE_RE.sub("", (text or "").replace("\r", "\n"))


def extract_codex_status(raw_output: str) -> Dict[str, Optional[str]]:
    """从 Codex 交互终端输出中提取状态行。"""
    cleaned_output = strip_ansi_terminal_text(raw_output)
    lines = [" ".join(line.split()) for line in cleaned_output.splitlines() if line.strip()]

    def _find_status(target_lines: List[str], source_prefix: str) -> Optional[Dict[str, Optional[str]]]:
        for line in reversed(target_lines):
            match = CONTEXT_LEFT_RE.search(line)
            if match:
                return {"status_line": match.group(0), "source": f"{source_prefix}_context"}
        for line in reversed(target_lines):
            if ("·" in line or "•" in line) and GENERIC_LEFT_RE.search(line):
                return {"status_line": line.strip(), "source": f"{source_prefix}_footer"}
        for line in reversed(target_lines):
            match = GENERIC_LEFT_RE.search(line)
            if match:
                return {"status_line": match.group(0), "source": f"{source_prefix}_generic"}
        return None

    status_indices = [index for index, line in enumerate(lines) if "/status" in line]
    if status_indices:
        after_status = _find_status(lines[status_indices[-1] + 1 :], "status_command")
        if after_status:
            return {
                "status_line": after_status["status_line"],
                "source": after_status["source"],
                "cleaned_output": cleaned_output,
            }

    fallback = _find_status(lines, "fallback")
    if fallback:
        return {
            "status_line": fallback["status_line"],
            "source": fallback["source"],
            "cleaned_output": cleaned_output,
        }

    return {"status_line": None, "source": None, "cleaned_output": cleaned_output}


def _build_codex_status_terminal_argv(resolved_cli: str) -> List[str]:
    ext = os.path.splitext(resolved_cli)[1].lower()
    if ext == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            resolved_cli,
            "--no-alt-screen",
        ]
    if ext in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/c", resolved_cli, "--no-alt-screen"]
    return [resolved_cli, "--no-alt-screen"]


def _should_finish_codex_status_poll(
    parsed: Dict[str, Optional[str]],
    initial_status_line: Optional[str],
    sent_at: Optional[float],
    now: float,
    fallback_wait_seconds: float = CODEX_STATUS_FALLBACK_WAIT_SECONDS,
) -> bool:
    """判断 /status 发出后，当前状态是否足够新，可以结束轮询。"""
    status_line = parsed.get("status_line")
    source = str(parsed.get("source") or "")

    if not status_line:
        return False
    if source.startswith("status_command"):
        return True
    if initial_status_line and status_line != initial_status_line:
        return True
    if sent_at is None:
        return False
    return now - sent_at >= fallback_wait_seconds


def _run_codex_status_terminal(resolved_cli: str, working_dir: str, timeout: float) -> str:
    if os.name != "nt":
        raise RuntimeError("unsupported_platform")

    try:
        from winpty import PtyProcess
    except ImportError as exc:
        raise RuntimeError("pty_unavailable") from exc

    process = PtyProcess.spawn(_build_codex_status_terminal_argv(resolved_cli), cwd=working_dir)
    output_queue: "queue.Queue[str]" = queue.Queue()

    def _reader() -> None:
        try:
            while True:
                chunk = process.read(4096)
                if not chunk:
                    break
                output_queue.put(chunk)
        except Exception:
            return

    threading.Thread(target=_reader, daemon=True).start()

    chunks: List[str] = []
    sent_status = False
    sent_at: Optional[float] = None
    initial_status_line: Optional[str] = None
    started_at = time.time()

    try:
        while time.time() - started_at < timeout:
            try:
                chunk = output_queue.get(timeout=0.5)
            except queue.Empty:
                chunk = ""

            if chunk:
                chunks.append(chunk)

            parsed = extract_codex_status("".join(chunks))
            if not sent_status and parsed["status_line"]:
                initial_status_line = parsed["status_line"]
                process.write("/status\r")
                sent_status = True
                sent_at = time.time()
                continue

            if sent_status and _should_finish_codex_status_poll(
                parsed,
                initial_status_line=initial_status_line,
                sent_at=sent_at,
                now=time.time(),
            ):
                return "".join(chunks)

        raise TimeoutError("timeout")
    finally:
        try:
            process.terminate(force=True)
        except Exception:
            pass


def read_codex_status_from_terminal(cli_path: str, working_dir: str, timeout: float = 15.0) -> Dict[str, Optional[str]]:
    """通过 PTY 启动 Codex 交互界面并读取 /status。"""
    resolved_cli = resolve_cli_executable(cli_path, working_dir)
    if not resolved_cli:
        return {"ok": False, "error": "not_found", "status_line": None}

    if os.name != "nt":
        return {"ok": False, "error": "unsupported_platform", "status_line": None}

    try:
        raw_output = _run_codex_status_terminal(resolved_cli, working_dir, timeout)
    except TimeoutError:
        return {"ok": False, "error": "timeout", "status_line": None}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "status_line": None}
    except Exception as exc:
        logger.warning("读取 Codex 状态失败: %s", exc)
        return {"ok": False, "error": str(exc), "status_line": None}

    parsed = extract_codex_status(raw_output)
    status_line = parsed.get("status_line")
    if status_line:
        return {
            "ok": True,
            "error": None,
            "status_line": status_line,
            "source": parsed.get("source"),
        }

    return {
        "ok": False,
        "error": "no_status",
        "status_line": None,
        "source": parsed.get("source"),
    }


# ============ 会话重置判定函数 ============

def should_reset_codex_session(session_id: Optional[str], response: str, returncode: int) -> bool:
    """仅在明确是会话失效错误时清空 session_id。"""
    if not session_id or returncode == 0:
        return False

    lower = (response or "").lower()
    if not lower:
        return False

    invalid_markers = (
        "session not found",
        "thread not found",
        "conversation not found",
        "unknown session",
        "unknown thread",
        "invalid session",
        "invalid thread",
        "no such session",
        "no such thread",
        "failed to resume",
        "cannot resume",
        "could not resume",
        "not a valid session",
        "not a valid thread",
    )
    return any(marker in lower for marker in invalid_markers)


def should_reset_claude_session(response: str, returncode: int) -> bool:
    """Claude 会话失效时重置 session_id。"""
    if returncode == 0:
        return False
    lower = (response or "").lower()
    if not lower:
        return False
    reset_markers = (
        "session not found",
        "session id not found",
        "invalid session",
        "no such session",
        "not a valid session",
        "could not resume",
        "failed to resume",
        "conversation not found",
    )
    return any(marker in lower for marker in reset_markers)


def should_mark_claude_session_initialized(response: str, returncode: int) -> bool:
    """判断 Claude 会话是否已经成功建立，后续应改用 -r 恢复。

    Claude 偶尔会在已经输出有效回复后仍以非 0 退出，这时如果仅依赖 returncode，
    下一次会错误地继续使用 --session-id，触发 "Session ID ... is already in use"。
    因此这里对“明显是网络/鉴权类失败”的响应保持保守，其余非空输出都视为会话已建立。
    """
    if returncode == 0:
        return True

    lower = (response or "").lower()
    if not lower.strip():
        return False

    if "session id" in lower and "already in use" in lower:
        return True

    if should_reset_claude_session(response, returncode):
        return False

    non_initialized_markers = (
        "not authenticated",
        "login required",
        "authentication failed",
        "invalid api key",
        "rate limit",
        "quota exceeded",
        "overloaded",
        "network error",
        "connection error",
        "unable to connect",
        "fetch failed",
        "timed out",
        "timeout",
        "certificate",
        "permission denied",
    )
    if any(marker in lower for marker in non_initialized_markers):
        return False

    return True


def should_reset_kimi_session(response: str, returncode: int) -> bool:
    """Kimi 会话失效时重置 session_id。"""
    if returncode == 0:
        return False
    lower = (response or "").lower()
    if not lower:
        return False
    reset_markers = (
        "session not found",
        "invalid session",
        "conversation not found",
        "session expired",
        "session id not found",
        "unauthorized",
        "authentication failed",
        "invalid token",
    )
    return any(marker in lower for marker in reset_markers)
