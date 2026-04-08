"""CLI 可执行文件解析、命令构建、输出解析"""

import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from bot.config import SUPPORTED_CLI_TYPES
from bot.cli_params import build_cli_args_from_config, CliParamsConfig

logger = logging.getLogger(__name__)


def resolve_cli_executable(cli_path: str, working_dir: Optional[str] = None) -> Optional[str]:
    """解析 CLI 可执行文件路径，兼容 Windows 下 cmd/bat 可执行项。"""
    path = (cli_path or "").strip().strip('"').strip("'")
    if not path:
        return None

    def _existing_file(p: str) -> Optional[str]:
        if os.path.isfile(p):
            return os.path.abspath(p)
        return None

    # 1) 绝对路径或显式相对路径
    if os.path.isabs(path):
        found = _existing_file(path)
        if found:
            return found
    if any(sep in path for sep in ("/", "\\")):
        candidates = []
        if working_dir:
            candidates.append(os.path.join(working_dir, path))
        candidates.append(path)
        for c in candidates:
            found = _existing_file(os.path.abspath(os.path.expanduser(c)))
            if found:
                return found

    # 2) PATH 搜索
    found = shutil.which(path)
    if found:
        return found

    # 3) Windows: 自动补扩展名
    if os.name == "nt" and not os.path.splitext(path)[1]:
        for ext in (".cmd", ".bat", ".exe", ".com"):
            found = shutil.which(path + ext)
            if found:
                return found

    # 4) Windows: npm 全局目录兜底（PATH 未包含时）
    if os.name == "nt" and not any(sep in path for sep in ("/", "\\")):
        appdata = os.getenv("APPDATA")
        userprofile = os.getenv("USERPROFILE")
        npm_dirs: List[str] = []
        if appdata:
            npm_dirs.append(os.path.join(appdata, "npm"))
        if userprofile:
            npm_dirs.append(os.path.join(userprofile, "AppData", "Roaming", "npm"))
        # 去重并保持顺序
        seen = set()
        npm_dirs = [d for d in npm_dirs if not (d in seen or seen.add(d))]

        if os.path.splitext(path)[1]:
            names = [path]
        else:
            names = [path + ext for ext in (".cmd", ".bat", ".exe", ".com", ".ps1")]

        for npm_dir in npm_dirs:
            for name in names:
                found = _existing_file(os.path.join(npm_dir, name))
                if found:
                    return found

    return None


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
        "invalid session",
        "no such session",
        "not a valid session",
        "could not resume",
        "failed to resume",
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
