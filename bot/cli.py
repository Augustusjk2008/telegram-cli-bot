"""CLI 可执行文件解析、命令构建、输出解析"""

import json
import logging
import math
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from bot.config import SUPPORTED_CLI_TYPES
from bot.cli_params import (
    CliParamsConfig,
    build_cli_args_from_config,
    build_codex_project_trust_config_arg,
    get_cli_output_limits,
)
from bot.deepseek_cli import is_desktop_dsh_invocation
from bot.platform.executables import build_executable_invocation
from bot.platform.executables import resolve_cli_executable as _resolve_cli_executable

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_]")
CONTEXT_LEFT_RE = re.compile(r"\d+%\s+context\s+left", re.IGNORECASE)
GENERIC_LEFT_RE = re.compile(r"\d+%\s+left", re.IGNORECASE)
CODEX_STATUS_FALLBACK_WAIT_SECONDS = 8.0


class _BoundedText:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(1, int(max_bytes))
        self._data = bytearray()
        self.truncated = False

    def append(self, text: str, *, separator: str = "") -> None:
        value = str(text or "")
        if not value:
            return
        if self._data and separator:
            self._data.extend(separator.encode("utf-8", errors="replace"))
        self._data.extend(value.encode("utf-8", errors="replace"))
        if len(self._data) > self.max_bytes:
            del self._data[: len(self._data) - self.max_bytes]
            self.truncated = True

    def replace(self, text: str) -> None:
        encoded = str(text or "").encode("utf-8", errors="replace")
        self.truncated = len(encoded) > self.max_bytes
        if len(encoded) > self.max_bytes:
            encoded = encoded[-self.max_bytes :]
        self._data = bytearray(encoded)

    @property
    def text(self) -> str:
        return bytes(self._data).decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class CliStreamParseResult:
    final_text: str
    session_id: Optional[str]
    error_text: Optional[str]
    raw_tail: str
    total_bytes: int
    truncated: bool
    terminal_usage: Optional[Dict[str, Any]] = None
    terminal_status: Optional[str] = None
    terminal_error: Optional[str] = None
    denied_actions: Optional[List[Any]] = None
    model: Optional[str] = None
    terminal_usage_complete: bool = True


class DeepSeekJsonStreamParser:
    """Parse the headless JSON projection without promoting diagnostics to a reply."""

    def __init__(self, *, raw_tail_max_bytes: int, final_text_max_bytes: int) -> None:
        self._raw_tail = _BoundedText(raw_tail_max_bytes)
        self._text = _BoundedText(final_text_max_bytes)
        self._final = _BoundedText(final_text_max_bytes)
        self._errors = _BoundedText(raw_tail_max_bytes)
        self._has_final = False
        self._projection_truncated = False
        self._step_usage: dict[tuple[int, int], dict[str, int]] = {}
        self.model: Optional[str] = None
        self.session_id: Optional[str] = None
        self.terminal_status: Optional[str] = None
        self.total_bytes = 0

    def consume_line(self, line: str) -> Dict[str, Optional[str]]:
        value = str(line or "")
        self.total_bytes += len(value.encode("utf-8", errors="replace"))
        self._raw_tail.append(value)
        parsed: Dict[str, Optional[str]] = {
            "session_id": None, "completed_text": None, "delta_text": None, "error_text": None,
        }
        if not value.strip():
            return parsed
        try:
            event = json.loads(value)
        except (json.JSONDecodeError, RecursionError):
            self._errors.append("DeepSeek Harness 输出了无效 JSON", separator="\n")
            return parsed
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self._errors.append("DeepSeek Harness 事件缺少有效 type", separator="\n")
            return parsed
        kind = event["type"]
        self._projection_truncated |= event.get("truncated") is True
        if self._has_final and kind in {"session", "status", "text", "thinking", "tool_call", "tool_result", "final", "error", "orbit_model"}:
            self._errors.append("DeepSeek Harness 在 final 后继续输出运行事件", separator="\n")
        if kind == "orbit_model":
            model = event.get("model")
            if isinstance(model, str) and model.strip():
                self.model = model.strip()
        elif kind == "session":
            session_id = event.get("sessionId")
            if not isinstance(session_id, str) or not session_id.strip():
                self._errors.append("DeepSeek Harness 未提供有效 sessionId", separator="\n")
            elif self.session_id is not None and self.session_id != session_id:
                self._errors.append("DeepSeek Harness 在同一进程中更换了 sessionId", separator="\n")
            else:
                self.session_id = parsed["session_id"] = session_id
        elif kind in {"text", "final"}:
            text = event.get("text")
            if not isinstance(text, str):
                self._errors.append(f"DeepSeek Harness {kind} 事件缺少有效正文", separator="\n")
            elif kind == "final":
                self._has_final = True
                self._final.replace(text)
                parsed["completed_text"] = text
                if self._final.truncated or event.get("truncated") is True:
                    self._errors.append("DeepSeek Harness 最终回复超过输出限制", separator="\n")
            else:
                self._text.append(text, separator="\n")
                parsed["delta_text"] = text
        elif kind == "status":
            phase = event.get("phase")
            if phase == "turn_end":
                reason = event.get("reason")
                status = reason.get("kind") if isinstance(reason, dict) else None
                if not isinstance(status, str) or status not in {"completed", "error", "aborted"}:
                    self._errors.append("DeepSeek Harness 缺少合法的结束原因", separator="\n")
                else:
                    self.terminal_status = status
                    if status != "completed":
                        error = _extract_codex_error_text(reason) or f"DeepSeek Harness 执行结束：{status}"
                        self._errors.append(error, separator="\n")
                        parsed["error_text"] = error
            elif phase == "step_end":
                self._record_usage(event)
        elif kind == "error":
            error = _extract_codex_error_text(event) or "DeepSeek Harness 执行失败"
            self._errors.append(error, separator="\n")
            parsed["error_text"] = error
        return parsed

    def _record_usage(self, event: dict[str, Any]) -> None:
        turn, step, usage = event.get("turn"), event.get("step"), event.get("usage")
        if type(turn) is not int or type(step) is not int:
            return
        usage = usage if isinstance(usage, dict) else {}
        names = {
            "inputTokens": "input_tokens", "outputTokens": "output_tokens",
            "cacheReadTokens": "cache_read_input_tokens",
            "cacheWriteTokens": "cache_creation_input_tokens", "totalTokens": "total_tokens",
        }
        if any(type(usage[key]) is not int or usage[key] < 0 for key in names if key in usage):
            self._step_usage[(turn, step)] = {}
            return
        self._step_usage[(turn, step)] = {
            target: usage[source] for source, target in names.items()
            if source in usage
        }

    @property
    def terminal_usage(self) -> Optional[Dict[str, Any]]:
        rows = list(self._step_usage.values())
        if not rows:
            return None
        common = set(rows[0]).intersection(*(set(row) for row in rows[1:]))
        return {key: sum(row[key] for row in rows) for key in common} or None

    @property
    def preview_text(self) -> Optional[str]:
        text = self._final.text if self._has_final else self._text.text
        return text.strip() or None

    def result(self) -> CliStreamParseResult:
        error = self._errors.text.strip()
        if not error:
            if not self.session_id:
                error = "DeepSeek Harness 未返回会话 ID"
            elif not self._has_final:
                error = "DeepSeek Harness 未返回 final 事件"
            elif self.terminal_status != "completed":
                error = "DeepSeek Harness 未返回成功结束状态"
        text = self.preview_text or "(无输出)"
        if self._has_final and self._final.truncated:
            text = f"[回复前部已截断]\n{text}"
        usage = self.terminal_usage
        # 可选缓存桶在部分步骤缺失时，公共字段仍可显示，但不足以生成完整费用。
        usage_complete = usage is not None and all(
            key in usage for row in self._step_usage.values() for key in row
            if key != "total_tokens"
        )
        return CliStreamParseResult(
            final_text=text,
            session_id=self.session_id,
            error_text=error or None,
            raw_tail=self._raw_tail.text,
            total_bytes=self.total_bytes,
            truncated=self._projection_truncated or any(
                value.truncated for value in (self._raw_tail, self._text, self._final, self._errors)
            ),
            terminal_usage=usage,
            terminal_status="failed" if error else self.terminal_status,
            terminal_error=error or None,
            model=self.model,
            terminal_usage_complete=usage_complete,
        )


def _parse_terminal_usage(line: str, *, cli_type: str) -> Optional[Dict[str, Any]]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    terminal_types = ("turn.completed", "turn.failed") if cli_type == "codex" else ("result",)
    if event.get("type") not in terminal_types:
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    token_fields = ("input_tokens", "output_tokens") + (
        ("cached_input_tokens", "cache_write_input_tokens")
        if cli_type == "codex"
        else ("cache_read_input_tokens", "cache_creation_input_tokens")
    )
    if any(key not in usage for key in ("input_tokens", "output_tokens")):
        return None
    selected = {key: usage[key] for key in token_fields if key in usage}
    if any(type(value) is not int or value < 0 for value in selected.values()):
        return None
    if cli_type == "claude" and "cache_creation" in usage:
        creation = usage["cache_creation"]
        if not isinstance(creation, dict):
            return None
        lifetimes = {
            key: creation[key]
            for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
            if key in creation
        }
        if any(type(value) is not int or value < 0 for value in lifetimes.values()):
            return None
        selected["cache_creation"] = lifetimes
    return selected


class CodexJsonStreamParser:
    def __init__(
        self,
        *,
        raw_tail_max_bytes: int,
        final_text_max_bytes: int,
    ) -> None:
        self._raw_tail = _BoundedText(raw_tail_max_bytes)
        self._completed = _BoundedText(final_text_max_bytes)
        self._delta = _BoundedText(final_text_max_bytes)
        self._errors = _BoundedText(raw_tail_max_bytes)
        self._plain = _BoundedText(raw_tail_max_bytes)
        self.session_id: Optional[str] = None
        self.terminal_usage: Optional[Dict[str, Any]] = None
        self.total_bytes = 0

    def consume_line(self, line: str) -> Dict[str, Optional[str]]:
        value = str(line or "")
        self.total_bytes += len(value.encode("utf-8", errors="replace"))
        self._raw_tail.append(value)
        stripped = value.strip()
        if not stripped:
            return {
                "thread_id": None,
                "completed_text": None,
                "delta_text": None,
                "error_text": None,
            }
        parsed = parse_codex_json_line(stripped)
        terminal_usage = _parse_terminal_usage(stripped, cli_type="codex")
        if terminal_usage is not None:
            self.terminal_usage = terminal_usage
        if parsed["thread_id"]:
            self.session_id = parsed["thread_id"]
        if parsed["completed_text"]:
            self._completed.replace(parsed["completed_text"])
        if parsed["delta_text"]:
            self._delta.append(parsed["delta_text"])
        if parsed["error_text"]:
            self._errors.append(parsed["error_text"], separator="\n")
        if not stripped.startswith("{"):
            self._plain.append(stripped, separator="\n")
        return parsed

    @property
    def preview_text(self) -> Optional[str]:
        value = self._delta.text or self._errors.text or self._plain.text
        return value.strip() or None

    def result(self) -> CliStreamParseResult:
        selected = next(
            (
                item
                for item in (self._completed, self._delta, self._errors, self._plain)
                if item.text.strip()
            ),
            None,
        )
        final_text = selected.text.strip() if selected is not None else "(无输出)"
        if selected is not None and selected.truncated:
            final_text = f"[回复前部已截断]\n{final_text}"
        error_text = self._errors.text.strip() or self._plain.text.strip() or None
        if error_text and (self._errors.truncated or self._plain.truncated):
            error_text = f"[错误输出前部已截断]\n{error_text}"
        return CliStreamParseResult(
            final_text=final_text,
            session_id=self.session_id,
            error_text=error_text,
            raw_tail=self._raw_tail.text,
            total_bytes=self.total_bytes,
            terminal_usage=self.terminal_usage,
            truncated=any(
                item.truncated
                for item in (self._raw_tail, self._completed, self._delta, self._errors, self._plain)
            ),
        )


class ClaudeJsonStreamParser:
    def __init__(
        self,
        *,
        raw_tail_max_bytes: int,
        final_text_max_bytes: int,
    ) -> None:
        self._raw_tail = _BoundedText(raw_tail_max_bytes)
        self._completed = _BoundedText(final_text_max_bytes)
        self._delta = _BoundedText(final_text_max_bytes)
        self._errors = _BoundedText(raw_tail_max_bytes)
        self._plain = _BoundedText(raw_tail_max_bytes)
        self.session_id: Optional[str] = None
        self.terminal_usage: Optional[Dict[str, Any]] = None
        self.total_bytes = 0

    def consume_line(self, line: str) -> Dict[str, Optional[str]]:
        value = str(line or "")
        self.total_bytes += len(value.encode("utf-8", errors="replace"))
        self._raw_tail.append(value)
        stripped = value.strip()
        if not stripped:
            return {
                "session_id": None,
                "completed_text": None,
                "delta_text": None,
                "error_text": None,
            }
        parsed = parse_claude_stream_json_line(stripped)
        terminal_usage = _parse_terminal_usage(stripped, cli_type="claude")
        if terminal_usage is not None:
            self.terminal_usage = terminal_usage
        if parsed["session_id"]:
            self.session_id = parsed["session_id"]
        if parsed["completed_text"]:
            self._completed.replace(parsed["completed_text"])
        if parsed["delta_text"]:
            self._delta.append(parsed["delta_text"])
        if parsed["error_text"]:
            self._errors.append(parsed["error_text"], separator="\n")
        if not stripped.startswith("{"):
            self._plain.append(stripped, separator="\n")
        return parsed

    @property
    def preview_text(self) -> Optional[str]:
        value = self._delta.text or self._completed.text or self._errors.text or self._plain.text
        return value.strip() or None

    def result(self) -> CliStreamParseResult:
        selected = next(
            (
                item
                for item in (self._completed, self._delta, self._errors, self._plain)
                if item.text.strip()
            ),
            None,
        )
        final_text = selected.text.strip() if selected is not None else "(无输出)"
        if selected is not None and selected.truncated:
            final_text = f"[回复前部已截断]\n{final_text}"
        error_text = self._errors.text.strip() or self._plain.text.strip() or None
        if error_text and (self._errors.truncated or self._plain.truncated):
            error_text = f"[错误输出前部已截断]\n{error_text}"
        return CliStreamParseResult(
            final_text=final_text,
            session_id=self.session_id,
            error_text=error_text,
            raw_tail=self._raw_tail.text,
            total_bytes=self.total_bytes,
            terminal_usage=self.terminal_usage,
            truncated=any(
                item.truncated
                for item in (self._raw_tail, self._completed, self._delta, self._errors, self._plain)
            ),
        )


def _extract_antigravity_conversation_id(event: Dict[str, Any]) -> Optional[str]:
    candidate_paths = (
        ("conversation_id",),
        ("init", "conversation_id"),
        ("result", "conversation_id"),
        ("step_update", "conversation_id"),
    )
    for path in candidate_paths:
        value = _extract_nested_nonempty_str(event, *path)
        if value:
            return value
    return None


def _extract_antigravity_error_text(event: Dict[str, Any]) -> Optional[str]:
    values: list[str] = []

    def append(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, dict):
            for key in ("message", "detail", "error", "reason", "code"):
                append(value.get(key))
        elif isinstance(value, list):
            for item in value:
                append(item)

    append(event.get("error"))
    append(event.get("message"))
    append(event.get("detail"))
    result = event.get("result")
    if isinstance(result, dict):
        append(result.get("error"))
        append(result.get("message"))
        append(result.get("detail"))
    return "\n".join(dict.fromkeys(values)).strip() or None


def _normalize_antigravity_usage(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    fields = (
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "cache_read_tokens",
        "total_tokens",
    )
    selected: Dict[str, Any] = {}
    for key in fields:
        if key not in value:
            continue
        token_value = value[key]
        if type(token_value) is not int or token_value < 0:
            return None
        selected[key] = token_value
    return selected or None


def _normalize_antigravity_statusline_token(value: Any) -> Optional[int]:
    if type(value) is not int or value < 0:
        return None
    return value


def _normalize_antigravity_statusline_percent(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0 or normalized > 100:
        return None
    return normalized


def parse_antigravity_statusline_json(payload: Any) -> Optional[Dict[str, Any]]:
    """Validate and normalize one Antigravity statusline state payload.

    Statusline state is an optional side channel, so malformed or partial input
    is ignored.  Percentages are accepted only from the CLI-provided
    ``context_window`` object; they are never derived from raw result usage.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None

    context_window = payload.get("context_window")
    if not isinstance(context_window, dict):
        return None
    window_size = _normalize_antigravity_statusline_token(context_window.get("context_window_size"))
    if window_size is None or window_size <= 0:
        return None
    used_percent = _normalize_antigravity_statusline_percent(context_window.get("used_percentage"))
    left_percent = _normalize_antigravity_statusline_percent(context_window.get("remaining_percentage"))
    if used_percent is None and left_percent is None:
        return None
    if used_percent is None:
        used_percent = max(0.0, min(100.0, 100.0 - left_percent))  # type: ignore[operator]
    if left_percent is None:
        left_percent = max(0.0, min(100.0, 100.0 - used_percent))
    if abs((used_percent + left_percent) - 100.0) > 1.5:
        return None

    current_usage_raw = context_window.get("current_usage")
    current_usage: Dict[str, int] = {}
    if isinstance(current_usage_raw, dict):
        aliases = (
            ("input_tokens", "input_tokens"),
            ("total_input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("total_output_tokens", "output_tokens"),
            ("thinking_tokens", "thinking_tokens"),
            ("cache_read_tokens", "cache_read_tokens"),
            ("cache_read_input_tokens", "cache_read_tokens"),
            ("cache_write_tokens", "cache_write_tokens"),
            ("cache_creation_input_tokens", "cache_write_tokens"),
            ("total_tokens", "total_tokens"),
        )
        for source_key, result_key in aliases:
            token = _normalize_antigravity_statusline_token(current_usage_raw.get(source_key))
            if token is not None:
                current_usage[result_key] = token

    for source_key, result_key in (
        ("total_input_tokens", "input_tokens"),
        ("total_output_tokens", "output_tokens"),
    ):
        if result_key not in current_usage:
            token = _normalize_antigravity_statusline_token(context_window.get(source_key))
            if token is not None:
                current_usage[result_key] = token

    used_tokens = current_usage.get("total_tokens")
    if used_tokens is None:
        used_tokens = sum(
            current_usage.get(key, 0)
            for key in ("input_tokens", "cache_read_tokens", "output_tokens")
        )
        if used_tokens <= 0:
            used_tokens = None

    result: Dict[str, Any] = {
        "provider": "antigravity",
        "source": "antigravity_statusline",
        "context_window": window_size,
        "context_used_percent": used_percent,
        "context_left_percent": left_percent,
        "usage_scope": "conversation",
    }
    conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "").strip()
    if conversation_id:
        result["session_id"] = conversation_id
    if used_tokens is not None:
        result["used_tokens"] = used_tokens
    if current_usage:
        result["current_usage"] = current_usage
        for key, value in current_usage.items():
            if key != "total_tokens":
                result[key] = value
    model = payload.get("model")
    if isinstance(model, dict):
        model_id = str(model.get("id") or model.get("display_name") or "").strip()
        if model_id:
            result["model"] = model_id
    elif isinstance(model, str) and model.strip():
        result["model"] = model.strip()
    return result


def _format_antigravity_denied_actions(value: Any) -> Optional[str]:
    if not isinstance(value, list) or not value:
        return None
    rendered: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            rendered.append(item.strip())
            continue
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("action") or item.get("tool") or "").strip()
            reason = str(
                item.get("reason")
                or item.get("message")
                or item.get("display_name")
                or ""
            ).strip()
            text = " — ".join(part for part in (name, reason) if part)
            if text:
                rendered.append(text)
    return "\n".join(rendered).strip() or "存在被拒绝的工具操作"


def parse_antigravity_model_options(raw_output: str) -> List[str]:
    """Parse the ``agy models`` table into model slugs for the Web selector."""
    options: List[str] = []
    seen: set[str] = set()
    for raw_line in str(raw_output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        slug = line.split(None, 1)[0].strip()
        if not slug or slug.lower() in {"fetching", "available", "models"}:
            continue
        if any(char.isspace() for char in slug):
            continue
        if slug not in seen:
            seen.add(slug)
            options.append(slug)
    return options


def parse_antigravity_json_line(line: str) -> Dict[str, Any]:
    """解析 Antigravity stream-json 的单行事件。"""
    result: Dict[str, Any] = {
        "conversation_id": None,
        "completed_text": None,
        "delta_text": None,
        "error_text": None,
        "terminal_status": None,
        "terminal_error": None,
        "denied_actions": None,
    }
    try:
        event: Any = json.loads(line)
    except json.JSONDecodeError:
        return result
    if not isinstance(event, dict):
        return result

    result["conversation_id"] = _extract_antigravity_conversation_id(event)
    event_type = str(event.get("event") or "").strip().lower()
    if event_type == "step_update":
        step = event.get("step_update") if isinstance(event.get("step_update"), dict) else event
        step_type = str(step.get("step_type") or "").strip().lower()
        if step_type == "agent_response":
            text_delta = step.get("text_delta")
            if not isinstance(text_delta, str):
                text_delta = step.get("text")
            if isinstance(text_delta, str) and text_delta:
                result["delta_text"] = text_delta
        usage = _normalize_antigravity_usage(step.get("usage"))
        if usage is not None:
            result["terminal_usage"] = usage
        return result

    if event_type != "result":
        return result

    result_payload = event.get("result") if isinstance(event.get("result"), dict) else event
    status = str(event.get("status") or result_payload.get("status") or "").strip().upper()
    if status:
        result["terminal_status"] = status
    response = result_payload.get("response")
    if isinstance(response, str) and response.strip():
        result["completed_text"] = response.strip()

    usage = _normalize_antigravity_usage(result_payload.get("usage", event.get("usage")))
    if usage is not None:
        result["terminal_usage"] = usage

    denied_actions = result_payload.get("denied_actions", event.get("denied_actions"))
    if isinstance(denied_actions, list) and denied_actions:
        result["denied_actions"] = denied_actions
        denied_text = _format_antigravity_denied_actions(denied_actions)
        if denied_text:
            result["terminal_error"] = denied_text

    error_text = _extract_antigravity_error_text(result_payload if result_payload is not event else event)
    if error_text:
        result["terminal_error"] = error_text
    if status and status != "SUCCESS" and not result["terminal_error"]:
        result["terminal_error"] = f"Antigravity 返回状态: {status}"
    if result["terminal_error"]:
        result["error_text"] = result["terminal_error"]
    return result


class AntigravityJsonStreamParser:
    def __init__(
        self,
        *,
        raw_tail_max_bytes: int,
        final_text_max_bytes: int,
    ) -> None:
        self._raw_tail = _BoundedText(raw_tail_max_bytes)
        self._completed = _BoundedText(final_text_max_bytes)
        self._delta = _BoundedText(final_text_max_bytes)
        self._errors = _BoundedText(raw_tail_max_bytes)
        self._plain = _BoundedText(raw_tail_max_bytes)
        self.session_id: Optional[str] = None
        self.terminal_usage: Optional[Dict[str, Any]] = None
        self.terminal_status: Optional[str] = None
        self.terminal_error: Optional[str] = None
        self.denied_actions: list[Any] = []
        self.total_bytes = 0

    def consume_line(self, line: str) -> Dict[str, Any]:
        value = str(line or "")
        self.total_bytes += len(value.encode("utf-8", errors="replace"))
        self._raw_tail.append(value)
        stripped = value.strip()
        if not stripped:
            return {
                "conversation_id": None,
                "completed_text": None,
                "delta_text": None,
                "error_text": None,
            }
        parsed = parse_antigravity_json_line(stripped)
        if parsed.get("conversation_id"):
            self.session_id = parsed["conversation_id"]
        if parsed.get("completed_text"):
            self._completed.replace(parsed["completed_text"])
        if parsed.get("delta_text"):
            self._delta.append(parsed["delta_text"])
        if parsed.get("error_text"):
            self._errors.append(parsed["error_text"], separator="\n")
        if parsed.get("terminal_usage") is not None:
            self.terminal_usage = parsed["terminal_usage"]
        if parsed.get("terminal_status"):
            self.terminal_status = parsed["terminal_status"]
        if parsed.get("terminal_error"):
            self.terminal_error = self._errors.text.strip()
        if parsed.get("denied_actions"):
            self.denied_actions = list(parsed["denied_actions"])
        if not stripped.startswith("{"):
            self._plain.append(stripped, separator="\n")
        return parsed

    @property
    def preview_text(self) -> Optional[str]:
        value = self._delta.text or self._completed.text or self._errors.text or self._plain.text
        return value.strip() or None

    def result(self) -> CliStreamParseResult:
        selected = next(
            (item for item in (self._completed, self._delta, self._errors, self._plain) if item.text.strip()),
            None,
        )
        final_text = selected.text.strip() if selected is not None else "(无输出)"
        if selected is not None and selected.truncated:
            final_text = f"[回复前部已截断]\n{final_text}"
        error_text = self._errors.text.strip() or self._plain.text.strip() or None
        if self.terminal_error and self.terminal_error not in (error_text or ""):
            error_text = "\n".join(item for item in (error_text, self.terminal_error) if item)
        if error_text and (self._errors.truncated or self._plain.truncated):
            error_text = f"[错误输出前部已截断]\n{error_text}"
        return CliStreamParseResult(
            final_text=final_text,
            session_id=self.session_id,
            error_text=error_text,
            raw_tail=self._raw_tail.text,
            total_bytes=self.total_bytes,
            terminal_usage=self.terminal_usage,
            terminal_status=self.terminal_status,
            terminal_error=self.terminal_error,
            denied_actions=list(self.denied_actions) or None,
            truncated=any(item.truncated for item in (self._raw_tail, self._completed, self._delta, self._errors, self._plain)),
        )


def parse_antigravity_json_output(raw_output: str) -> CliStreamParseResult:
    output_size = max(1, len(str(raw_output or "").encode("utf-8", errors="replace")))
    parser = AntigravityJsonStreamParser(raw_tail_max_bytes=output_size, final_text_max_bytes=output_size)
    for line in str(raw_output or "").splitlines(keepends=True):
        parser.consume_line(line)
    return parser.result()


def resolve_cli_executable(cli_path: str, working_dir: Optional[str] = None) -> Optional[str]:
    """解析 CLI 可执行文件路径，兼容 Windows 下 cmd/bat 可执行项。"""
    return _resolve_cli_executable(cli_path, working_dir)


def normalize_cli_type(cli_type: str) -> str:
    return (cli_type or "").strip().lower()


def cli_data_provider(cli_type: str) -> str:
    """Return the transcript/usage format without changing the execution entry."""
    normalized = normalize_cli_type(cli_type)
    return "codex" if normalized == "codex_server" else normalized


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
    working_dir: Optional[str] = None,
    task_mode: str = "standard",
) -> Tuple[List[str], bool]:
    """构建不同 CLI 的命令行，按传入参数配置决定是否启用危险执行选项。

    Args:
        cli_type: CLI 类型 (claude/codex)
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
    if kind == "codex_server":
        raise ValueError("codex server 必须通过 app-server 运行时执行，不能使用 exec")
    cmd, use_stdin = build_cli_args_from_config(
        cli_type=kind,
        resolved_cli=resolved_cli,
        params_config=params_config,
        user_text=user_text,
        session_id=session_id,
        resume_session=resume_session,
        working_dir=working_dir,
        task_mode=task_mode,
    )
    if kind == "claude":
        params = params_config.get_params("claude")
        if params.get("disable_prompts"):
            env["CLAUDE_CODE_DISABLE_PROMPTS"] = "1"
    elif kind == "deepseek":
        permission_mode = str(
            params_config.get_param("deepseek", "permission_mode", "workspace-write")
            or "workspace-write"
        ).strip()
        env["DSH_PERMISSION_MODE"] = permission_mode or "workspace-write"
        if is_desktop_dsh_invocation(cmd):
            # Scope Electron's Node mode to this child environment only.
            env["ELECTRON_RUN_AS_NODE"] = "1"
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


def _extract_codex_content_text(content: Any) -> Optional[str]:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None

    text_parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", "")).strip()
        if block_type not in ("text", "output_text"):
            continue
        text_value = block.get("text")
        if isinstance(text_value, str) and text_value.strip():
            text_parts.append(text_value.strip())

    if not text_parts:
        return None
    return "\n".join(text_parts).strip()


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

    if event_type in {"error", "turn.failed"}:
        result["error_text"] = _extract_codex_error_text(event)
        if not result["error_text"] and isinstance(event.get("error"), dict):
            result["error_text"] = _extract_codex_error_text({"error": event["error"]})
        return result

    if event_type in {"response_item", "event_msg"}:
        payload = event.get("item")
        if not isinstance(payload, dict):
            payload = event.get("payload")
        if not isinstance(payload, dict):
            return result

        payload_type = str(payload.get("type", "")).strip()
        if payload_type == "message":
            role = str(payload.get("role", "")).strip().lower()
            if role != "assistant":
                return result
            text_value = _extract_codex_content_text(payload.get("content"))
            if not text_value:
                return result
            phase = str(payload.get("phase", "")).strip().lower()
            if phase in {"final", "final_answer"}:
                result["completed_text"] = text_value
            else:
                result["delta_text"] = text_value
            return result

        if payload_type == "agent_message":
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                text_value = message.strip()
                phase = str(payload.get("phase", "")).strip().lower()
                if phase in {"commentary", "progress", "partial"}:
                    result["delta_text"] = text_value
                else:
                    result["completed_text"] = text_value
            return result

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
            phase = str(item.get("phase", "")).strip().lower()
            if phase in {"commentary", "progress", "partial"}:
                result["delta_text"] = text_value
            else:
                result["completed_text"] = text_value
        return result

    if event_type == "item.delta":
        if isinstance(delta_value, str) and delta_value:
            result["delta_text"] = delta_value
        elif isinstance(text_value, str) and text_value:
            result["delta_text"] = text_value
        return result

    return result


def parse_codex_json_output_result(raw_output: str) -> CliStreamParseResult:
    """Parse complete Codex JSON output while retaining terminal usage metadata."""

    output_size = max(1, len(str(raw_output or "").encode("utf-8", errors="replace")))
    parser = CodexJsonStreamParser(
        raw_tail_max_bytes=output_size,
        final_text_max_bytes=output_size,
    )
    for line in str(raw_output or "").splitlines(keepends=True):
        parser.consume_line(line)
    return parser.result()


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
        final_text = next((part.strip() for part in reversed(completed_parts) if part.strip()), "")
    else:
        final_text = "".join(delta_parts).strip()

    if not final_text and error_parts:
        final_text = "\n".join(error_parts).strip()
    if not final_text:
        final_text = "\n".join(raw_lines).strip()
    if not final_text:
        final_text = "(无输出)"

    return final_text, thread_id


def extract_codex_error_output(raw_output: str) -> Optional[str]:
    """提取 Codex JSON 输出里的 error 事件文本。"""
    error_parts: List[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = parse_codex_json_line(stripped)
        if parsed["error_text"]:
            error_parts.append(parsed["error_text"])
    if not error_parts:
        return None
    return "\n".join(part for part in error_parts if part).strip() or None


def _extract_claude_session_id(event: Dict[str, Any]) -> Optional[str]:
    candidate_paths = (
        ("session_id",),
        ("session", "id"),
        ("data", "session_id"),
    )
    for path in candidate_paths:
        value = _extract_nested_nonempty_str(event, *path)
        if value:
            return value
    return None


def _extract_claude_message_text(message: Any) -> Optional[str]:
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    if not isinstance(content, list):
        return None

    text_parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type", "")).strip() != "text":
            continue
        text_value = block.get("text")
        if isinstance(text_value, str) and text_value:
            text_parts.append(text_value)

    combined = "".join(text_parts).strip()
    return combined or None


def _extract_claude_error_text(event: Dict[str, Any]) -> Optional[str]:
    collected: List[str] = []

    errors = event.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, str) and item.strip():
                collected.append(item.strip())
                continue
            if isinstance(item, dict):
                nested = _extract_nested_nonempty_str(item, "message")
                if nested:
                    collected.append(nested)
                    continue
                nested = _extract_nested_nonempty_str(item, "detail")
                if nested:
                    collected.append(nested)
                    continue
                nested = _extract_nested_nonempty_str(item, "error")
                if nested:
                    collected.append(nested)

    for key in ("message", "error", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            collected.append(value.strip())
            continue
        if isinstance(value, dict):
            nested = _extract_nested_nonempty_str(value, "message")
            if nested:
                collected.append(nested)
                continue
            nested = _extract_nested_nonempty_str(value, "detail")
            if nested:
                collected.append(nested)
                continue
            nested = _extract_nested_nonempty_str(value, "error")
            if nested:
                collected.append(nested)

    if not collected:
        return None

    # 保留顺序去重，避免 result/errors 与 message 文本重复显示。
    unique: List[str] = []
    for item in collected:
        if item not in unique:
            unique.append(item)
    return "\n".join(unique)


def parse_claude_stream_json_line(line: str) -> Dict[str, Optional[str]]:
    """解析 Claude stream-json 的单行事件。"""
    result: Dict[str, Optional[str]] = {
        "session_id": None,
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

    result["session_id"] = _extract_claude_session_id(event)
    event_type = str(event.get("type", "")).strip()

    if event_type == "stream_event":
        inner_event = event.get("event")
        if not isinstance(inner_event, dict):
            return result
        if str(inner_event.get("type", "")).strip() != "content_block_delta":
            return result

        delta = inner_event.get("delta")
        if not isinstance(delta, dict):
            return result
        if str(delta.get("type", "")).strip() != "text_delta":
            return result

        text_value = delta.get("text")
        if isinstance(text_value, str) and text_value:
            result["delta_text"] = text_value
        return result

    if event_type == "assistant":
        completed_text = _extract_claude_message_text(event.get("message"))
        if completed_text:
            result["completed_text"] = completed_text
        return result

    if event_type == "result":
        result_text = event.get("result")
        if isinstance(result_text, str) and result_text.strip():
            result["completed_text"] = result_text.strip()
        error_text = _extract_claude_error_text(event)
        if error_text:
            result["error_text"] = error_text
        return result

    if event_type == "system":
        error_text = _extract_claude_error_text(event)
        if error_text:
            result["error_text"] = error_text
        return result

    return result


def parse_claude_stream_json_output(raw_output: str) -> Tuple[str, Optional[str]]:
    """解析 Claude stream-json 的完整输出文本，提取 assistant 文本和 session_id。"""
    raw_lines: List[str] = []
    completed_parts: List[str] = []
    delta_parts: List[str] = []
    error_parts: List[str] = []
    session_id: Optional[str] = None

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_lines.append(stripped)
        parsed = parse_claude_stream_json_line(stripped)
        if parsed["session_id"]:
            session_id = parsed["session_id"]
        if parsed["completed_text"]:
            completed_parts.append(parsed["completed_text"])
        if parsed["delta_text"]:
            delta_parts.append(parsed["delta_text"])
        if parsed["error_text"]:
            error_parts.append(parsed["error_text"])

    if completed_parts:
        final_text = completed_parts[-1].strip()
    else:
        final_text = "".join(delta_parts).strip()

    if not final_text and error_parts:
        final_text = "\n".join(part for part in error_parts if part.strip()).strip()
    if not final_text:
        final_text = "\n".join(raw_lines).strip()
    if not final_text:
        final_text = "(无输出)"

    return final_text, session_id


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


def _build_codex_status_terminal_argv(resolved_cli: str, working_dir: Optional[str] = None) -> List[str]:
    codex_args: List[str] = []
    trust_config_arg = build_codex_project_trust_config_arg(working_dir)
    if trust_config_arg:
        codex_args.extend(["-c", trust_config_arg])
    codex_args.append("--no-alt-screen")

    ext = os.path.splitext(resolved_cli)[1].lower()
    if ext == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            resolved_cli,
            *codex_args,
        ]
    if ext in {".cmd", ".bat"}:
        return [*build_executable_invocation(resolved_cli), *codex_args]
    return [resolved_cli, *codex_args]


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

    process = PtyProcess.spawn(_build_codex_status_terminal_argv(resolved_cli, working_dir), cwd=working_dir)
    output_limits = get_cli_output_limits()
    output_queue: "queue.Queue[str]" = queue.Queue(
        maxsize=output_limits.queue_max_chunks,
    )
    reader_stop = threading.Event()

    def _reader() -> None:
        try:
            while not reader_stop.is_set():
                chunk = process.read(4096)
                if not chunk:
                    break
                while not reader_stop.is_set():
                    try:
                        output_queue.put(chunk, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception:
            return

    threading.Thread(target=_reader, daemon=True).start()

    output = _BoundedText(output_limits.final_text_max_bytes)
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
                output.append(chunk)

            output_text = output.text
            parsed = extract_codex_status(output_text)
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
                return output_text

        raise TimeoutError("timeout")
    finally:
        reader_stop.set()
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


def should_suggest_reset_codex_session(session_id: Optional[str], response: str, returncode: int) -> bool:
    """Codex 恢复旧会话时遇到上游 500，提示用户手动新建会话。"""
    if not session_id or returncode == 0:
        return False

    lower = (response or "").lower().strip()
    if not lower:
        return False

    has_500 = (
        "status_code=500" in lower
        or "status code=500" in lower
        or "status code 500" in lower
    )
    if has_500 and "upstream error" in lower and "do request failed" in lower:
        return True

    oversized_markers = (
        "payload too large",
        "request too large",
    )
    return any(marker in lower for marker in oversized_markers)


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
