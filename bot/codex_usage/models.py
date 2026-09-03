from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


ProviderKind = Literal["openai_official", "base_url", "unknown"]
GENERAL_CODEX_RATE_LIMIT_ID = "codex"
SECONDARY_CODEX_RATE_LIMIT_ID = "codex_bengalfox"
GPT_RESERVE_RATE_LIMIT_ID = "base_model_inference"
KNOWN_CODEX_RATE_LIMIT_IDS = (
    GENERAL_CODEX_RATE_LIMIT_ID,
    SECONDARY_CODEX_RATE_LIMIT_ID,
    GPT_RESERVE_RATE_LIMIT_ID,
)
SQLITE_INT64_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class CodexRateLimitSample:
    sampled_at: datetime
    used_percent: float
    window_minutes: int
    resets_at: datetime
    plan_type: str | None = None
    limit_id: str = GENERAL_CODEX_RATE_LIMIT_ID

    def __post_init__(self) -> None:
        for field_name in ("sampled_at", "resets_at"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError(f"{field_name} 必须是带时区的时间")
            try:
                timestamp = value.timestamp()
            except (OSError, OverflowError, ValueError) as exc:
                raise ValueError(f"{field_name} 无效") from exc
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError(f"{field_name} 无效")
        if (
            isinstance(self.used_percent, bool)
            or not isinstance(self.used_percent, (int, float))
            or (
                isinstance(self.used_percent, float)
                and not math.isfinite(self.used_percent)
            )
            or not 0 <= self.used_percent <= 100
        ):
            raise ValueError("used_percent 必须在 0 到 100 之间")
        object.__setattr__(self, "used_percent", float(self.used_percent))
        if (
            isinstance(self.window_minutes, bool)
            or not isinstance(self.window_minutes, int)
            or self.window_minutes <= 0
            or self.window_minutes > SQLITE_INT64_MAX
        ):
            raise ValueError("window_minutes 必须是 SQLite 有符号 64 位正整数")
        if self.plan_type is not None and not isinstance(self.plan_type, str):
            raise ValueError("plan_type 必须是字符串或空值")
        normalized_limit_id = str(self.limit_id or "").strip()
        if not normalized_limit_id:
            raise ValueError("limit_id 不能为空")
        object.__setattr__(self, "limit_id", normalized_limit_id)


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """A safe provider identity; raw TOML contents are never retained."""

    key: str
    kind: ProviderKind
    base_url: str | None
    resolution: str = "resolved"


DayLike = date | datetime | int | str


def day_number(value: DayLike) -> int:
    """Return a ``YYYYMMDD`` day key in the server's local calendar."""

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone()
        value = value.date()
    if isinstance(value, date):
        return value.year * 10_000 + value.month * 100 + value.day
    if isinstance(value, bool):
        raise ValueError("日期不能是布尔值")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().replace("-", "")
    else:
        raise ValueError("日期格式无效")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("日期必须是 YYYY-MM-DD 或 YYYYMMDD")
    parsed = date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return parsed.year * 10_000 + parsed.month * 100 + parsed.day


def day_from_number(value: int) -> date:
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError("数据库中的日期无效")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))
