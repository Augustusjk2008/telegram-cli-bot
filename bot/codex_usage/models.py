from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Mapping


ProviderKind = Literal["openai_official", "base_url", "unknown"]
DEFAULT_CODEX_MODEL = "gpt-5.6-sol"


def normalize_model_key(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized.casefold() == "unknown":
        return DEFAULT_CODEX_MODEL
    return normalized


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} 必须是非负整数")
    return value


@dataclass(frozen=True, slots=True)
class CodexTokenUsage:
    """One terminal Codex token usage sample.

    ``cached_input_tokens`` and ``reasoning_output_tokens`` are subsets of the
    input and output counts respectively, so derived totals never add them twice.
    """

    input_tokens: int
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    def __post_init__(self) -> None:
        input_tokens = _require_non_negative_int(self.input_tokens, "input_tokens")
        cached_input_tokens = _require_non_negative_int(
            self.cached_input_tokens,
            "cached_input_tokens",
        )
        output_tokens = _require_non_negative_int(self.output_tokens, "output_tokens")
        reasoning_output_tokens = _require_non_negative_int(
            self.reasoning_output_tokens,
            "reasoning_output_tokens",
        )
        if cached_input_tokens > input_tokens:
            raise ValueError("cached_input_tokens 不能大于 input_tokens")
        if reasoning_output_tokens > output_tokens:
            raise ValueError("reasoning_output_tokens 不能大于 output_tokens")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CodexTokenUsage:
        return cls(
            input_tokens=value.get("input_tokens"),
            cached_input_tokens=value.get("cached_input_tokens", 0),
            output_tokens=value.get("output_tokens"),
            reasoning_output_tokens=value.get("reasoning_output_tokens", 0),
        )

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float | None:
        if self.input_tokens == 0:
            return None
        return self.cached_input_tokens / self.input_tokens


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """A safe provider identity; raw TOML contents are never retained."""

    key: str
    kind: ProviderKind
    base_url: str | None
    resolution: str = "resolved"


@dataclass(frozen=True, slots=True)
class UsageTotals:
    request_count: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float | None:
        if self.input_tokens == 0:
            return None
        return self.cached_input_tokens / self.input_tokens

    def plus(self, other: UsageTotals) -> UsageTotals:
        return UsageTotals(
            request_count=self.request_count + other.request_count,
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=(
                self.reasoning_output_tokens + other.reasoning_output_tokens
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    provider: ProviderInfo
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class ProviderModelUsage:
    provider: ProviderInfo
    model: str
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class DayUsage:
    day: date
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class DailyProviderUsage:
    day: date
    provider: ProviderInfo
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class DailyProviderModelUsage:
    day: date
    provider: ProviderInfo
    model: str
    totals: UsageTotals


@dataclass(frozen=True, slots=True)
class UsageQueryResult:
    totals: UsageTotals
    by_provider: tuple[ProviderUsage, ...]
    by_day: tuple[DayUsage, ...]
    daily_by_provider: tuple[DailyProviderUsage, ...]
    by_provider_model: tuple[ProviderModelUsage, ...]
    daily_by_provider_model: tuple[DailyProviderModelUsage, ...]


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


def coerce_token_usage(value: CodexTokenUsage | Mapping[str, Any] | Any) -> CodexTokenUsage:
    if isinstance(value, CodexTokenUsage):
        return value
    if isinstance(value, Mapping):
        return CodexTokenUsage.from_mapping(value)
    nested_usage = getattr(value, "token_usage", None)
    if nested_usage is not None:
        return coerce_token_usage(nested_usage)
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    if all(hasattr(value, field) for field in fields):
        return CodexTokenUsage(
            input_tokens=getattr(value, "input_tokens"),
            cached_input_tokens=getattr(value, "cached_input_tokens"),
            output_tokens=getattr(value, "output_tokens"),
            reasoning_output_tokens=getattr(value, "reasoning_output_tokens"),
        )
    raise ValueError("usage 必须是 CodexTokenUsage 或映射")


TokenUsage = CodexTokenUsage
ProviderSnapshot = ProviderInfo
