"""按可维护的 CSV 单价生成用量费用快照。"""

from __future__ import annotations

import csv
import logging
import math
import re
from collections.abc import Mapping
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any

from bot import config

logger = logging.getLogger(__name__)
DEFAULT_PRICES_PATH = Path(__file__).parent / "data" / "model_prices.csv"
_CATEGORIES = ("input", "cache_read", "cache_write", "output")
_PRECISION = Decimal("0.0000000001")


@lru_cache(maxsize=1)
def _read_prices(path: Path, mtime_ns: int, size: int) -> dict[str, dict[str, Any]]:
    prices: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                model = row["model"].strip()
                currency = row["currency"].strip().upper()
                if not model or model in prices or not re.fullmatch(r"[A-Z]{3}", currency):
                    raise ValueError("模型不能为空或重复，币种须为三位代码")
                rates = {key: Decimal(row[f"{key}_per_million"]) for key in _CATEGORIES}
                rates["cache_write_1h"] = Decimal(
                    row.get("cache_write_1h_per_million") or str(rates["cache_write"])
                )
                if any(not value.is_finite() or value < 0 for value in rates.values()):
                    raise ValueError("单价须为有限非负数")
                prices[model] = {"currency": currency, **rates}
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, AttributeError, ValueError, DecimalException) as exc:
        logger.warning("模型价格表不可用，跳过费用估算：%s (%s)", path, exc)
        return {}
    return prices


def _model_price(model: str) -> tuple[str, dict[str, Any]] | None:
    path = Path(config.MODEL_PRICES_FILE).expanduser() if config.MODEL_PRICES_FILE else DEFAULT_PRICES_PATH
    try:
        stat = path.stat()
    except (OSError, ValueError):
        return None
    prices = _read_prices(path, stat.st_mtime_ns, stat.st_size)
    # Pi 的配置使用 provider/model；完整 ID 的显式单价优先。
    for key in dict.fromkeys((model.strip(), model.strip().rsplit("/", 1)[-1])):
        if key in prices:
            return key, prices[key]
    return None


def _token_count(usage: Mapping[str, Any], key: str, *, default: int | None = None) -> int:
    value = usage.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"无效的 {key}")
    return value


def estimate_usage_cost(
    model: str,
    usage: Mapping[str, Any],
    *,
    protocol: str,
    scope: str,
) -> dict[str, Any] | None:
    """用上游报告的范围直接计价；不对会话累计快照做跨轮差分。"""
    if not isinstance(model, str) or not model.strip() or not isinstance(usage, Mapping):
        return None
    if scope not in {"session", "turn", "request"}:
        return None
    matched = _model_price(model)
    if matched is None:
        return None
    price_model, price = matched
    try:
        cache_write_1h = 0
        if protocol == "codex":
            input_tokens = _token_count(usage, "input_tokens")
            output = _token_count(usage, "output_tokens")
            cache_read = _token_count(usage, "cached_input_tokens", default=0)
            cache_write = _token_count(usage, "cache_write_input_tokens", default=0)
            ordinary_input = input_tokens - cache_read - cache_write
            if ordinary_input < 0:
                return None
        elif protocol == "claude":
            ordinary_input = _token_count(usage, "input_tokens")
            output = _token_count(usage, "output_tokens")
            cache_read = _token_count(usage, "cache_read_input_tokens", default=0)
            creation = usage.get("cache_creation")
            if isinstance(creation, Mapping):
                cache_write_1h = _token_count(creation, "ephemeral_1h_input_tokens", default=0)
                cache_write = _token_count(creation, "ephemeral_5m_input_tokens", default=0) + cache_write_1h
            else:
                cache_write = 0
            cache_write = _token_count(usage, "cache_creation_input_tokens", default=cache_write)
            if cache_write_1h > cache_write:
                return None
        elif protocol == "pi":
            ordinary_input = _token_count(usage, "input")
            output = _token_count(usage, "output")
            cache_read = _token_count(usage, "cacheRead", default=0)
            cache_write = _token_count(usage, "cacheWrite", default=0)
        else:
            return None

        # cache/reasoning 是明细；各输入分项互斥，reasoning 已在 output 中。
        counts = dict(zip(_CATEGORIES, (ordinary_input, cache_read, cache_write, output)))
        amounts = {key: Decimal(counts[key]) * price[key] / 1_000_000 for key in _CATEGORIES}
        amounts["cache_write"] += Decimal(cache_write_1h) * (price["cache_write_1h"] - price["cache_write"]) / 1_000_000
        amounts = {key: value.quantize(_PRECISION, rounding=ROUND_HALF_UP) for key, value in amounts.items()}
        values = {key: float(value) for key, value in amounts.items()}
        values["total"] = float(sum(amounts.values()))
        if not all(math.isfinite(value) for value in values.values()):
            return None
    except (ValueError, DecimalException, OverflowError):
        return None
    return {"model": price_model, "currency": price["currency"], "scope": scope, **values}
