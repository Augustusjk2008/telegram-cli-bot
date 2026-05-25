from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from bot.cli import normalize_cli_type
from bot.web.native_history_locator import locate_codex_transcript

_CODEX_CONTEXT_BASELINE_TOKENS = 12_000


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


def resolve_cli_context_usage(
    cli_type: str,
    session_id: str | None,
    cwd_hint: str | None = None,
) -> dict[str, Any] | None:
    del cwd_hint
    provider = normalize_cli_type(str(cli_type or ""))
    normalized_session_id = str(session_id or "").strip()
    if provider != "codex" or not normalized_session_id:
        return None

    try:
        ref = locate_codex_transcript(normalized_session_id)
        if ref is None:
            return None
        return _resolve_codex_context_usage(normalized_session_id, ref.path)
    except Exception:
        return None
