from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from bot.native_agent.config_store import find_configured_model


def resolve_native_agent_context_usage(
    *,
    session_id: str,
    model_id: str,
    messages: list[dict[str, Any]],
    session_payload: dict[str, Any] | None = None,
    run_usage: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if isinstance(run_usage, dict) and run_usage:
        usage = _build_usage(
            session_id=session_id,
            model_id=model_id,
            tokens=run_usage,
            source="native_agent_run_tokens",
            scope="turn",
        )
        if usage is not None:
            return usage

    session_tokens = _session_tokens_payload(session_payload)
    if session_tokens:
        usage = _build_usage(
            session_id=session_id,
            model_id=model_id,
            tokens=session_tokens,
            source="native_agent_session_tokens",
            scope="session",
        )
        if usage is not None:
            return usage

    assistant_message = _latest_assistant_message_with_tokens(messages)
    if assistant_message is None:
        return None
    tokens = _tokens_payload(assistant_message)
    if not tokens:
        return None
    return _build_usage(
        session_id=session_id,
        model_id=model_id,
        tokens=tokens,
        source="native_agent_tokens",
        scope="turn",
    )


def _build_usage(
    *,
    session_id: str,
    model_id: str,
    tokens: dict[str, Any],
    source: str,
    scope: str,
) -> dict[str, Any] | None:
    input_tokens = _as_non_negative_int(_pick(tokens, "input", "tokens_input", "input_tokens", "inputTokens", "tokensInput"))
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    cache_read_tokens = _as_non_negative_int(_pick(tokens, "cache_read", "cache_read_tokens", "cacheReadTokens", "cacheRead"))
    cache_write_tokens = _as_non_negative_int(_pick(tokens, "cache_write", "cache_write_tokens", "cacheWriteTokens", "cacheWrite"))
    if isinstance(cache, dict):
        cache_read_tokens = cache_read_tokens or _as_non_negative_int(_pick(cache, "read", "read_tokens", "readTokens"))
        cache_write_tokens = cache_write_tokens or _as_non_negative_int(_pick(cache, "write", "write_tokens", "writeTokens"))
    output_tokens = _as_non_negative_int(_pick(tokens, "output", "output_tokens", "outputTokens"))
    reasoning_tokens = _as_non_negative_int(_pick(tokens, "reasoning", "reasoning_tokens", "reasoningTokens"))
    used_tokens = input_tokens + cache_read_tokens + cache_write_tokens
    if used_tokens <= 0:
        return None

    model = find_configured_model(model_id)
    context_window = _as_positive_int(model.get("context_window")) if model else None
    usage: dict[str, Any] = {
        "provider": "native_agent",
        "source": source,
        "scope": scope,
        "session_id": session_id,
        "model": model_id,
        "used_tokens": used_tokens,
        "context_used": used_tokens,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "used_display": _format_tokens(used_tokens),
        "status_text": f"{_format_tokens(used_tokens)} context used",
    }
    if context_window:
        left_percent = _clamp_percent(_round_half_up((context_window - used_tokens) / context_window * 100))
        used_percent = _clamp_percent(_round_half_up(used_tokens / context_window * 100))
        usage.update(
            {
                "context_window": context_window,
                "context_left_percent": left_percent,
                "context_used_percent": used_percent,
                "window_display": _format_tokens(context_window),
                "status_text": f"{used_percent}% context used · {_format_tokens(used_tokens)} / {_format_tokens(context_window)}",
            }
        )
    cost = tokens.get("cost")
    if cost is not None:
        usage["cost"] = cost
    return usage


def _latest_assistant_message_with_tokens(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        if _tokens_payload(message):
            return message
    return None


def _tokens_payload(message: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        message.get("tokens"),
        message.get("usage"),
        message.get("tokenUsage"),
        message.get("token_usage"),
    ]
    info = message.get("info") if isinstance(message.get("info"), dict) else {}
    candidates.extend([
        info.get("tokens"),
        info.get("usage"),
        info.get("tokenUsage"),
        info.get("token_usage"),
    ])
    for item in candidates:
        if isinstance(item, dict):
            return item
    return {}


def _session_tokens_payload(session_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(session_payload, dict):
        return {}
    candidates = [session_payload]
    for key in ("data", "session", "info"):
        value = session_payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for item in candidates:
        tokens = _tokens_payload(item)
        if tokens:
            return tokens
    return {}


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _as_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _as_positive_int(value: Any) -> int | None:
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
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}M"
    if value >= 100_000:
        return f"{_round_half_up(value / 1000)}K"
    if value >= 1_000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}K"
    return str(value)
