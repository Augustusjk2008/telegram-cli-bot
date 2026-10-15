from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import tempfile
import time
from decimal import Decimal, ROUND_HALF_UP
from io import SEEK_END
from pathlib import Path
from typing import Any

from bot.cli import normalize_cli_type, parse_antigravity_statusline_json
from bot.web.native_history_locator import locate_claude_transcript, locate_codex_transcript
from bot.runtime_paths import get_tcb_home_root

_CODEX_CONTEXT_BASELINE_TOKENS = 12_000
_CLAUDE_DEFAULT_CONTEXT_WINDOW_TOKENS = 256_000
_CLAUDE_OPUS_CONTEXT_WINDOW_TOKENS = 1_000_000
_CLAUDE_OPUS_MODEL_RE = re.compile(r"(?:^|[-_/])opus(?:$|[-_/])")
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
_ContextCacheKey = tuple[str, str, str, int, int, int]
_CACHE_LOCK = threading.Lock()
_CONTEXT_USAGE_CACHE: dict[_ContextCacheKey, dict[str, Any] | None] = {}
_CONTEXT_USAGE_CACHE_ORDER: list[_ContextCacheKey] = []
_CONTEXT_USAGE_CACHE_LIMIT = 128
_TRANSCRIPT_STATE: dict[tuple[str, str, str], dict[str, Any]] = {}
_TAIL_WINDOW_BYTES = 256 * 1024
ANTIGRAVITY_STATUSLINE_TTL_SECONDS = 30.0
_ANTIGRAVITY_STATUSLINE_ROOT_NAME = "antigravity-statusline"


def clear_context_usage_cache() -> None:
    with _CACHE_LOCK:
        _CONTEXT_USAGE_CACHE.clear()
        _CONTEXT_USAGE_CACHE_ORDER.clear()
        _TRANSCRIPT_STATE.clear()


def _antigravity_statusline_root() -> Path:
    configured = str(os.environ.get("TCB_ANTIGRAVITY_STATUSLINE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    try:
        return get_tcb_home_root() / _ANTIGRAVITY_STATUSLINE_ROOT_NAME
    except Exception:
        return Path(tempfile.gettempdir()) / "orbit-safe-claw" / _ANTIGRAVITY_STATUSLINE_ROOT_NAME


def get_antigravity_statusline_telemetry_path(
    *,
    cwd_hint: str | None = None,
    telemetry_path: str | Path | None = None,
) -> Path:
    configured = str(telemetry_path or os.environ.get("TCB_ANTIGRAVITY_STATUSLINE_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()
    cwd = str(cwd_hint or "").strip()
    identity = str(Path(cwd).expanduser().absolute()) if cwd else "default"
    digest = hashlib.sha256(identity.lower().encode("utf-8", errors="replace")).hexdigest()[:24]
    return _antigravity_statusline_root() / f"{digest}.jsonl"


def cleanup_antigravity_statusline_telemetry(
    *,
    root: str | Path | None = None,
    now: float | None = None,
    max_age_seconds: float = ANTIGRAVITY_STATUSLINE_TTL_SECONDS,
) -> int:
    target_root = Path(root).expanduser() if root is not None else _antigravity_statusline_root()
    try:
        entries = [*target_root.glob("*.json"), *target_root.glob("*.jsonl")]
    except OSError:
        return 0
    current_time = time.time() if now is None else float(now)
    removed = 0
    for path in entries:
        try:
            if current_time - path.stat().st_mtime <= max(0.1, float(max_age_seconds)):
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def record_antigravity_statusline_payload(
    payload: Any,
    *,
    path: str | Path | None = None,
    cwd_hint: str | None = None,
) -> dict[str, Any] | None:
    """Append a validated statusline payload for a configured statusline hook."""
    normalized = parse_antigravity_statusline_json(payload)
    if normalized is None:
        return None
    target = get_antigravity_statusline_telemetry_path(cwd_hint=cwd_hint, telemetry_path=path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload).decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as handle:
        handle.write(raw.strip())
        handle.write("\n")
    return normalized


def _read_antigravity_statusline_payloads(path: Path) -> list[dict[str, Any]]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > _TAIL_WINDOW_BYTES:
        data = data[-_TAIL_WINDOW_BYTES:]
    payloads: list[dict[str, Any]] = []
    for line in reversed(data.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _statusline_payload_matches_workspace(payload: dict[str, Any], cwd_hint: str | None) -> bool:
    expected = str(cwd_hint or "").strip()
    if not expected:
        return True
    reported = str(payload.get("cwd") or "").strip()
    if not reported:
        workspace = payload.get("workspace")
        if isinstance(workspace, dict):
            reported = str(workspace.get("current_dir") or workspace.get("project_dir") or "").strip()
    if not reported:
        return True
    try:
        return Path(reported).expanduser().absolute().resolve() == Path(expected).expanduser().absolute().resolve()
    except OSError:
        return reported.lower() == expected.lower()


def _format_antigravity_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return str(value)


def resolve_antigravity_statusline_usage(
    session_id: str | None,
    cwd_hint: str | None = None,
    *,
    telemetry_path: str | Path | None = None,
    now: float | None = None,
    max_age_seconds: float = ANTIGRAVITY_STATUSLINE_TTL_SECONDS,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    path = get_antigravity_statusline_telemetry_path(
        cwd_hint=cwd_hint,
        telemetry_path=telemetry_path,
    )
    cleanup_antigravity_statusline_telemetry(
        root=path.parent,
        now=now,
        max_age_seconds=max_age_seconds,
    )
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return None
    current_time = time.time() if now is None else float(now)
    if current_time - modified_at > max(0.1, float(max_age_seconds)):
        try:
            path.unlink()
        except OSError:
            pass
        return None

    payloads = _read_antigravity_statusline_payloads(path)
    for require_matching_session in (True, False):
        for payload in payloads:
            if not _statusline_payload_matches_workspace(payload, cwd_hint):
                continue
            normalized = parse_antigravity_statusline_json(payload)
            if normalized is None:
                continue
            payload_session_id = str(normalized.get("session_id") or "").strip()
            if require_matching_session:
                if payload_session_id != normalized_session_id:
                    continue
            elif payload_session_id:
                continue
            normalized["session_id"] = normalized_session_id
            used_tokens = normalized.get("used_tokens")
            context_window = normalized.get("context_window")
            if isinstance(used_tokens, int):
                normalized["used_display"] = _format_antigravity_tokens(used_tokens)
            if isinstance(context_window, int):
                normalized["window_display"] = _format_antigravity_tokens(context_window)
            left_percent = normalized.get("context_left_percent")
            left_text = f"{float(left_percent):.1f}".rstrip("0").rstrip(".") if isinstance(left_percent, (int, float)) else ""
            usage_text = ""
            if normalized.get("used_display") and normalized.get("window_display"):
                usage_text = f"{normalized['used_display']} / {normalized['window_display']}"
            normalized["status_text"] = " · ".join(
                part for part in (f"{left_text}% context left" if left_text else "", usage_text) if part
            ) or "Antigravity context telemetry"
            return normalized
    return None


def _transcript_cache_key(provider: str, session_id: str, transcript_path: Path) -> _ContextCacheKey | None:
    try:
        stat = transcript_path.stat()
    except OSError:
        return None
    return (
        provider,
        session_id,
        str(transcript_path),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
        int(stat.st_size),
    )


def _get_cached_context_usage(key: _ContextCacheKey) -> dict[str, Any] | None | object:
    with _CACHE_LOCK:
        if key not in _CONTEXT_USAGE_CACHE:
            return _CACHE_MISS
        value = _CONTEXT_USAGE_CACHE[key]
        return dict(value) if isinstance(value, dict) else None


def _set_cached_context_usage(key: _ContextCacheKey, value: dict[str, Any] | None) -> None:
    with _CACHE_LOCK:
        if key not in _CONTEXT_USAGE_CACHE:
            _CONTEXT_USAGE_CACHE_ORDER.append(key)
        _CONTEXT_USAGE_CACHE[key] = dict(value) if isinstance(value, dict) else None
        while len(_CONTEXT_USAGE_CACHE_ORDER) > _CONTEXT_USAGE_CACHE_LIMIT:
            old_key = _CONTEXT_USAGE_CACHE_ORDER.pop(0)
            _CONTEXT_USAGE_CACHE.pop(old_key, None)


_CACHE_MISS = object()


def _transcript_state_key(provider: str, session_id: str, transcript_path: Path) -> tuple[str, str, str]:
    return (provider, session_id, str(transcript_path))


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


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


def _build_codex_context_usage(session_id: str, token_count: tuple[int, int] | None) -> dict[str, Any] | None:
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


def _resolve_codex_context_usage_from_lines(session_id: str, lines: list[str]) -> dict[str, Any] | None:
    token_count: tuple[int, int] | None = None
    for line in reversed(lines):
        token_count = _extract_codex_token_count(line.strip())
        if token_count is not None:
            break
    return _build_codex_context_usage(session_id, token_count)


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


def _normalize_claude_model_name(model: str | None) -> str:
    text = str(model or "").strip().lower()
    text = re.sub(r"\[[^\]]+\]\s*$", "", text).strip()
    return text


def _lookup_claude_context_window(model: str | None) -> int | None:
    normalized = _normalize_claude_model_name(model)
    if normalized and _CLAUDE_OPUS_MODEL_RE.search(normalized):
        return _CLAUDE_OPUS_CONTEXT_WINDOW_TOKENS
    return _CLAUDE_DEFAULT_CONTEXT_WINDOW_TOKENS


def _extract_claude_message_usage(line: str) -> tuple[int, str, dict[str, int]] | None:
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

    token_breakdown: dict[str, int] = {}
    for source_key, result_key in (
        ("input_tokens", "input_tokens"),
        ("cache_creation_input_tokens", "cache_write_tokens"),
        ("cache_read_input_tokens", "cache_read_tokens"),
        ("output_tokens", "output_tokens"),
    ):
        if source_key not in usage:
            continue
        value = _as_nonnegative_int(usage.get(source_key))
        if value is not None:
            token_breakdown[result_key] = value

    if "cache_write_tokens" not in token_breakdown and usage.get("cache_creation_input_tokens") is None:
        cache_creation = usage.get("cache_creation")
        if isinstance(cache_creation, dict):
            ttl_values = [
                value
                for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
                if key in cache_creation
                if (value := _as_nonnegative_int(cache_creation.get(key))) is not None
            ]
            if ttl_values:
                token_breakdown["cache_write_tokens"] = sum(ttl_values)

    # Prompt cache changes billing and latency, but cached input still occupies
    # the model context window. Output belongs to the response, not this input sum.
    used_tokens = sum(
        token_breakdown.get(key, 0)
        for key in ("input_tokens", "cache_write_tokens", "cache_read_tokens")
    )
    if used_tokens <= 0:
        return None
    return used_tokens, str(message.get("model") or "").strip(), token_breakdown


def _build_claude_usage_estimate(
    session_id: str,
    used_tokens: int,
    model: str | None,
    token_breakdown: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    used_display = _format_tokens_claude(used_tokens)
    context_window = _lookup_claude_context_window(model)
    result = {
        "provider": "claude",
        "source": "claude_message_usage_estimate",
        "session_id": session_id,
        "used_tokens": used_tokens,
        "used_display": used_display,
        "status_text": f"{used_display} context used",
    }
    result.update(token_breakdown or {})
    left_percent = _clamp_percent(_round_half_up((context_window - used_tokens) / context_window * 100))
    window_display = _format_tokens_claude(context_window)
    result.update(
        {
            "context_window": context_window,
            "context_left_percent": left_percent,
            "window_display": window_display,
            "status_text": f"{left_percent}% context left · {used_display} / {window_display}",
        }
    )
    return result


def _resolve_claude_context_usage_from_lines(session_id: str, lines: list[str]) -> dict[str, Any] | None:
    for line in reversed(lines):
        context_usage = _extract_claude_context_from_line(session_id, line.strip())
        if context_usage is not None:
            return context_usage

    for line in reversed(lines):
        message_usage = _extract_claude_message_usage(line.strip())
        if message_usage is not None:
            used_tokens, model, token_breakdown = message_usage
            return _build_claude_usage_estimate(session_id, used_tokens, model, token_breakdown)

    return None


def _read_transcript_lines_from_offset(transcript_path: Path, offset: int) -> tuple[list[str], int]:
    try:
        with transcript_path.open("rb") as handle:
            handle.seek(max(0, int(offset or 0)))
            data = handle.read()
            next_offset = handle.tell()
    except OSError:
        return [], max(0, int(offset or 0))
    return data.decode("utf-8", errors="replace").splitlines(), next_offset


def _read_transcript_tail_lines(transcript_path: Path, *, window_bytes: int = _TAIL_WINDOW_BYTES) -> list[str]:
    try:
        with transcript_path.open("rb") as handle:
            handle.seek(0, SEEK_END)
            size = handle.tell()
            start = max(0, size - max(window_bytes, 1024))
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    if start > 0:
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
    return text.splitlines()


def _resolve_incremental_context_usage(
    provider: str,
    session_id: str,
    transcript_path: Path,
    parser: Any,
) -> dict[str, Any] | None:
    try:
        stat = transcript_path.stat()
    except OSError:
        return None

    state_key = _transcript_state_key(provider, session_id, transcript_path)
    with _CACHE_LOCK:
        state = dict(_TRANSCRIPT_STATE.get(state_key) or {})

    current_size = int(stat.st_size)
    current_mtime_ns = int(stat.st_mtime_ns)
    usage: dict[str, Any] | None
    previous_size = int(state.get("size") or 0) if state else 0
    previous_offset = int(state.get("offset") or 0) if state else 0
    if state and current_size > previous_size and previous_offset <= current_size:
        appended_lines, next_offset = _read_transcript_lines_from_offset(transcript_path, int(state.get("offset") or 0))
        usage = parser(session_id, appended_lines) if appended_lines else None
        if usage is None:
            usage = state.get("last_usage")
        with _CACHE_LOCK:
            _TRANSCRIPT_STATE[state_key] = {
                "offset": next_offset,
                "size": current_size,
                "mtime_ns": current_mtime_ns,
                "last_usage": dict(usage) if isinstance(usage, dict) else None,
            }
        return dict(usage) if isinstance(usage, dict) else None

    tail_lines = _read_transcript_tail_lines(transcript_path)
    usage = parser(session_id, tail_lines)
    with _CACHE_LOCK:
        _TRANSCRIPT_STATE[state_key] = {
            "offset": current_size,
            "size": current_size,
            "mtime_ns": current_mtime_ns,
            "last_usage": dict(usage) if isinstance(usage, dict) else None,
        }
    return dict(usage) if isinstance(usage, dict) else None


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
        if provider == "antigravity":
            return resolve_antigravity_statusline_usage(normalized_session_id, cwd_hint)

        if provider == "codex":
            ref = locate_codex_transcript(normalized_session_id)
            if ref is None:
                return None
            key = _transcript_cache_key(provider, normalized_session_id, ref.path)
            if key is not None:
                cached = _get_cached_context_usage(key)
                if cached is not _CACHE_MISS:
                    return cached
            result = _resolve_incremental_context_usage(
                provider,
                normalized_session_id,
                ref.path,
                _resolve_codex_context_usage_from_lines,
            )
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
            result = _resolve_incremental_context_usage(
                provider,
                normalized_session_id,
                ref.path,
                _resolve_claude_context_usage_from_lines,
            )
            if key is not None:
                _set_cached_context_usage(key, result)
            return result

        return None
    except Exception:
        return None
