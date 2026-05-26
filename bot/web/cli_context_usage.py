from __future__ import annotations

import json
import re
import threading
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from bot.cli import normalize_cli_type
from bot.web.native_history_locator import locate_claude_transcript, locate_codex_transcript

_CODEX_CONTEXT_BASELINE_TOKENS = 12_000
_CLAUDE_CONTEXT_WINDOW_TOKENS = 1_000_000
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CLAUDE_TOKENS_RE = re.compile(
    r"(?:Tokens\s*:\s*)?(?P<used>\d+(?:\.\d+)?\s*[kKmM]?)\s*/\s*"
    r"(?P<window>\d+(?:\.\d+)?\s*[kKmM]?)(?:\s+tokens)?\s*"
    r"\((?P<used_percent>\d+(?:\.\d+)?)%\)",
    re.IGNORECASE,
)
_CLAUDE_FREE_RE = re.compile(
    r"Free space\s*(?:\||:)?\s*(?P<free>\d+(?:\.\d+)?\s*[kKmM]?)"
    r"\s*(?:\|)?\s*\(?(?P<free_percent>\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)
_CACHE_LOCK = threading.Lock()
_CONTEXT_USAGE_CACHE: dict[tuple[str, str, str, int, int], dict[str, Any] | None] = {}
_CONTEXT_USAGE_CACHE_ORDER: list[tuple[str, str, str, int, int]] = []
_CONTEXT_USAGE_CACHE_LIMIT = 128


def clear_context_usage_cache() -> None:
    with _CACHE_LOCK:
        _CONTEXT_USAGE_CACHE.clear()
        _CONTEXT_USAGE_CACHE_ORDER.clear()


def _transcript_cache_key(provider: str, session_id: str, transcript_path: Path) -> tuple[str, str, str, int, int] | None:
    try:
        stat = transcript_path.stat()
    except OSError:
        return None
    return (
        provider,
        session_id,
        str(transcript_path),
        int(stat.st_mtime_ns),
        int(stat.st_size),
    )


def _get_cached_context_usage(key: tuple[str, str, str, int, int]) -> dict[str, Any] | None | object:
    with _CACHE_LOCK:
        if key not in _CONTEXT_USAGE_CACHE:
            return _CACHE_MISS
        value = _CONTEXT_USAGE_CACHE[key]
        return dict(value) if isinstance(value, dict) else None


def _set_cached_context_usage(key: tuple[str, str, str, int, int], value: dict[str, Any] | None) -> None:
    with _CACHE_LOCK:
        if key not in _CONTEXT_USAGE_CACHE:
            _CONTEXT_USAGE_CACHE_ORDER.append(key)
        _CONTEXT_USAGE_CACHE[key] = dict(value) if isinstance(value, dict) else None
        while len(_CONTEXT_USAGE_CACHE_ORDER) > _CONTEXT_USAGE_CACHE_LIMIT:
            old_key = _CONTEXT_USAGE_CACHE_ORDER.pop(0)
            _CONTEXT_USAGE_CACHE.pop(old_key, None)


_CACHE_MISS = object()


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _format_tokens(value: int) -> str:
    if value >= 100_000:
        return f"{_round_half_up(value / 1000)}K"
    if value >= 1_000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}K"
    return str(value)


def _parse_token_display(value: str) -> int | None:
    text = str(value or "").strip().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", text)
    if not match:
        return None
    number = Decimal(match.group(1))
    suffix = match.group(2).lower()
    multiplier = Decimal(1)
    if suffix == "k":
        multiplier = Decimal(1000)
    elif suffix == "m":
        multiplier = Decimal(1_000_000)
    return int((number * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _format_tokens_claude(value: int) -> str:
    if value >= 1_000_000:
        if value % 1_000_000 == 0:
            return f"{value // 1_000_000}m"
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}m"
    if value >= 1_000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    return str(value)


def _clean_claude_context_text(value: str) -> str:
    text = _ANSI_ESCAPE_RE.sub("", str(value or ""))
    return text.replace("<local-command-stdout>", "").replace("</local-command-stdout>", "")


def _extract_codex_token_count(line: str) -> tuple[int, int] | None:
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None

    payload = item.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    last_usage = info.get("last_token_usage")
    if not isinstance(last_usage, dict):
        return None

    used_tokens = _as_int(last_usage.get("total_tokens"))
    context_window = _as_int(info.get("model_context_window"))
    if used_tokens is None or context_window is None:
        return None
    return used_tokens, context_window


def _resolve_codex_context_usage(session_id: str, transcript_path: Path) -> dict[str, Any] | None:
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    token_count: tuple[int, int] | None = None
    for line in reversed(lines):
        token_count = _extract_codex_token_count(line.strip())
        if token_count is not None:
            break
    if token_count is None:
        return None

    used_tokens, context_window = token_count
    available = context_window - _CODEX_CONTEXT_BASELINE_TOKENS
    if available <= 0:
        return None

    used_effective = max(used_tokens - _CODEX_CONTEXT_BASELINE_TOKENS, 0)
    left_percent = _clamp_percent(_round_half_up((available - used_effective) / available * 100))
    used_display = _format_tokens(used_tokens)
    window_display = _format_tokens(context_window)
    return {
        "provider": "codex",
        "source": "codex_session_token_count",
        "session_id": session_id,
        "used_tokens": used_tokens,
        "context_window": context_window,
        "context_left_percent": left_percent,
        "used_display": used_display,
        "window_display": window_display,
        "status_text": f"{left_percent}% context left · {used_display} / {window_display}",
    }


def _parse_claude_context_text(session_id: str, text: str) -> dict[str, Any] | None:
    cleaned = _clean_claude_context_text(text)
    token_match = _CLAUDE_TOKENS_RE.search(cleaned)
    if not token_match:
        return None

    used_tokens = _parse_token_display(token_match.group("used"))
    context_window = _parse_token_display(token_match.group("window"))
    if used_tokens is None or context_window is None or context_window <= 0:
        return None

    free_match = _CLAUDE_FREE_RE.search(cleaned)
    if free_match:
        left_percent = _clamp_percent(_round_half_up(float(free_match.group("free_percent"))))
    else:
        left_percent = _clamp_percent(_round_half_up((context_window - used_tokens) / context_window * 100))

    used_display = token_match.group("used").replace(" ", "")
    window_display = token_match.group("window").replace(" ", "")
    return {
        "provider": "claude",
        "source": "claude_context_command",
        "session_id": session_id,
        "used_tokens": used_tokens,
        "context_window": context_window,
        "context_left_percent": left_percent,
        "used_display": used_display,
        "window_display": window_display,
        "status_text": f"{left_percent}% context left · {used_display} / {window_display}",
    }


def _extract_claude_context_from_line(session_id: str, line: str) -> dict[str, Any] | None:
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None

    content = ""
    message = item.get("message")
    if isinstance(message, dict):
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
    if not content:
        raw = item.get("content")
        if isinstance(raw, str):
            content = raw

    if "Context Usage" not in content and "tokens (" not in content:
        return None
    return _parse_claude_context_text(session_id, content)


def _extract_claude_message_usage(line: str) -> int | None:
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict) or item.get("type") != "assistant":
        return None

    message = item.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    return _as_int(usage.get("input_tokens"))


def _build_claude_usage_estimate(session_id: str, used_tokens: int) -> dict[str, Any] | None:
    context_window = _CLAUDE_CONTEXT_WINDOW_TOKENS
    left_percent = _clamp_percent(_round_half_up((context_window - used_tokens) / context_window * 100))
    used_display = _format_tokens_claude(used_tokens)
    window_display = _format_tokens_claude(context_window)
    return {
        "provider": "claude",
        "source": "claude_message_usage_estimate",
        "session_id": session_id,
        "used_tokens": used_tokens,
        "context_window": context_window,
        "context_left_percent": left_percent,
        "used_display": used_display,
        "window_display": window_display,
        "status_text": f"{left_percent}% context left · {used_display} / {window_display}",
    }


def _resolve_claude_context_usage(session_id: str, transcript_path: Path) -> dict[str, Any] | None:
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in reversed(lines):
        context_usage = _extract_claude_context_from_line(session_id, line.strip())
        if context_usage is not None:
            return context_usage

    for line in reversed(lines):
        used_tokens = _extract_claude_message_usage(line.strip())
        if used_tokens is not None:
            return _build_claude_usage_estimate(session_id, used_tokens)

    return None


def resolve_cli_context_usage(
    cli_type: str,
    session_id: str | None,
    cwd_hint: str | None = None,
) -> dict[str, Any] | None:
    provider = normalize_cli_type(str(cli_type or ""))
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None

    try:
        if provider == "codex":
            ref = locate_codex_transcript(normalized_session_id)
            if ref is None:
                return None
            key = _transcript_cache_key(provider, normalized_session_id, ref.path)
            if key is not None:
                cached = _get_cached_context_usage(key)
                if cached is not _CACHE_MISS:
                    return cached
            result = _resolve_codex_context_usage(normalized_session_id, ref.path)
            if key is not None:
                _set_cached_context_usage(key, result)
            return result

        if provider == "claude":
            ref = locate_claude_transcript(normalized_session_id, cwd_hint=cwd_hint)
            if ref is None:
                return None
            key = _transcript_cache_key(provider, normalized_session_id, ref.path)
            if key is not None:
                cached = _get_cached_context_usage(key)
                if cached is not _CACHE_MISS:
                    return cached
            result = _resolve_claude_context_usage(normalized_session_id, ref.path)
            if key is not None:
                _set_cached_context_usage(key, result)
            return result

        return None
    except Exception:
        return None
