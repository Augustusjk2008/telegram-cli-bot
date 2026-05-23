from __future__ import annotations

import logging
import os
from typing import Any


def diag_enabled() -> bool:
    return str(os.environ.get("TCB_DIAG_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return max(0, value)


def diag_slow_ms() -> int:
    return _read_int_env("TCB_DIAG_SLOW_MS", 500)


def diag_loop_lag_ms() -> int:
    return _read_int_env("TCB_DIAG_LOOP_LAG_MS", 1000)


def diag_should_log(elapsed_ms: int | float, threshold_ms: int | None = None) -> bool:
    if not diag_enabled():
        return False
    threshold = diag_slow_ms() if threshold_ms is None else max(0, int(threshold_ms))
    return int(elapsed_ms) >= threshold


def _safe_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    if len(text) > 160:
        return text[:157].rstrip() + "..."
    return text


def _format_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(fields):
        value = _safe_value(fields[key])
        if value:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def diag_log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    if not diag_enabled():
        return
    suffix = _format_fields(fields)
    logger.info("TCB_DIAG event=%s%s", event, f" {suffix}" if suffix else "")


def diag_log_slow(
    logger: logging.Logger,
    event: str,
    elapsed_ms: int | float,
    *,
    threshold_ms: int | None = None,
    **fields: Any,
) -> None:
    if not diag_should_log(elapsed_ms, threshold_ms):
        return
    suffix = _format_fields({**fields, "elapsed_ms": int(elapsed_ms)})
    logger.warning("TCB_DIAG event=%s slow=1 %s", event, suffix)
