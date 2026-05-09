from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any


def clip_text(
    value: Any,
    *,
    limit: int,
    strip: bool = False,
    ellipsis: str = "",
) -> str:
    text = str(value or "")
    if strip:
        text = text.strip()
    max_length = max(0, int(limit))
    if len(text) <= max_length:
        return text
    if not ellipsis:
        return text[:max_length]
    head_length = max(0, max_length - len(ellipsis))
    return text[:head_length].rstrip() + ellipsis


def parse_iso_datetime(
    value: Any,
    *,
    allow_z: bool = False,
    assume_tz: tzinfo | None = None,
    normalize_tz: tzinfo | None = None,
) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if allow_z:
        text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None and assume_tz is not None:
        parsed = parsed.replace(tzinfo=assume_tz)
    if parsed.tzinfo is not None and normalize_tz is not None:
        return parsed.astimezone(normalize_tz)
    return parsed

