from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .store import (
    COST_PROVIDERS,
    CostCube,
    CostStatsStore,
    day_from_number,
    normalize_cost_provider,
)


logger = logging.getLogger(__name__)

GRANULARITIES: tuple[str, ...] = ("hour", "day", "week", "month")
_QUERY_CACHE_SIZE = 8
_MAX_HOUR_RANGE_DAYS = 7
# A wider request is answered at the next coarser granularity instead of
# materialising an unbounded bucket list.
_MAX_BUCKETS = 4000
_COARSER = {"hour": "day", "day": "week", "week": "month"}


def _default_db_path() -> Path:
    from bot.runtime_paths import get_cost_stats_db_path

    return get_cost_stats_db_path()


class CostStatsService:
    """Async facade for per-turn Codex and Claude cost statistics."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        store: CostStatsStore | None = None,
    ) -> None:
        if store is None:
            store = CostStatsStore(_default_db_path() if db_path is None else db_path)
        self._store = store
        self._state_lock = threading.RLock()
        # ``None`` until the flags were read once; afterwards the only source for record calls.
        self._enabled: dict[str, bool] | None = None
        self._revision = 0
        self._query_cache: OrderedDict[tuple[date, date, str], tuple[int, date, dict[str, Any]]] = OrderedDict()
        self._write_count = 0
        self._write_failure_count = 0
        self._last_write_at: str | None = None

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    # -- enable flags -----------------------------------------------------

    def enabled_snapshot(self) -> dict[str, bool] | None:
        """Cached flags without any I/O; ``None`` before the first load."""

        with self._state_lock:
            return dict(self._enabled) if self._enabled is not None else None

    def _load_enabled_sync(self) -> dict[str, bool]:
        with self._state_lock:
            if self._enabled is None:
                self._enabled = self._store.get_enabled_flags()
            return dict(self._enabled)

    async def get_enabled(self) -> dict[str, bool]:
        cached = self.enabled_snapshot()
        if cached is not None:
            return cached
        return await asyncio.to_thread(self._load_enabled_sync)

    async def is_enabled(self, provider: str) -> bool:
        return bool((await self.get_enabled()).get(normalize_cost_provider(provider)))

    def _set_enabled_sync(self, provider: str, enabled: bool) -> None:
        with self._state_lock:
            flags = self._load_enabled_sync()
            self._store.set_enabled(provider, enabled)
            flags[provider] = enabled
            self._enabled = flags
            self._revision += 1

    async def set_enabled(self, provider: str, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是布尔值")
        await asyncio.to_thread(self._set_enabled_sync, normalize_cost_provider(provider), enabled)

    # -- recording --------------------------------------------------------

    def _record_sync(self, fields: dict[str, Any]) -> bool:
        try:
            recorded = self._store.record_event(**fields)
        except Exception:
            with self._state_lock:
                self._write_failure_count += 1
            raise
        if recorded:
            with self._state_lock:
                self._revision += 1
                self._write_count += 1
                self._last_write_at = datetime.now(timezone.utc).isoformat()
        return recorded

    async def record_turn(
        self,
        *,
        invocation_id: str,
        provider: str,
        cli_type: str,
        bot_alias: str,
        agent_id: str,
        user: str,
        model: str,
        currency: str,
        total: float,
        cumulative: bool = False,
        previous_total: float | None = None,
        is_partial: bool = False,
        source: str | None = None,
        conversation_id: str | None = None,
        turn_id: str | None = None,
        native_session_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> bool:
        """Record one CLI invocation; returns ``False`` when disabled or rejected.

        A disabled provider returns from the cached flag without touching the disk.
        """

        normalized_provider = normalize_cost_provider(provider)
        enabled = self.enabled_snapshot()
        if enabled is None:
            enabled = await asyncio.to_thread(self._load_enabled_sync)
        if not enabled.get(normalized_provider):
            return False
        return await asyncio.to_thread(self._record_sync, {
            "invocation_id": invocation_id,
            "provider": normalized_provider,
            "cli_type": cli_type,
            "bot_alias": bot_alias,
            "agent_id": agent_id,
            "user": user,
            "model": model,
            "currency": currency,
            "total": total,
            "cumulative": cumulative,
            "previous_total": previous_total,
            "is_partial": is_partial,
            "source": source,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "native_session_id": native_session_id,
            "recorded_at": recorded_at,
        })

    # -- admin API --------------------------------------------------------

    def _config_sync(self) -> dict[str, Any]:
        enabled = self._load_enabled_sync()
        first_date, last_date = self._store.available_range()
        return {
            "enabled": enabled,
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
        }

    async def config_snapshot(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._config_sync)

    async def update_enabled(self, provider: str, enabled: bool) -> dict[str, Any]:
        await self.set_enabled(provider, enabled)
        return await self.config_snapshot()

    async def query_stats(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        granularity: str = "auto",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._query_stats_sync, start_date, end_date, granularity)

    def _query_stats_sync(
        self,
        start_date: date | None,
        end_date: date | None,
        granularity: str,
    ) -> dict[str, Any]:
        now = datetime.now().astimezone()
        today = now.date()
        start, end = _resolve_query_dates(start_date, end_date, today=today)
        resolved = resolve_granularity(granularity, start, end)
        key = (start, end, resolved)
        with self._state_lock:
            revision = self._revision
            cached = self._query_cache.get(key)
            if cached is not None and cached[0] == revision and cached[1] == today:
                self._query_cache.move_to_end(key)
                cube_payload = cached[2]
            else:
                cube_payload = None
        if cube_payload is None:
            cube_payload = self._build_cube_payload(start, end, resolved)
            with self._state_lock:
                # A write that landed meanwhile bumped the revision, so this entry is already stale.
                self._query_cache[key] = (revision, today, cube_payload)
                self._query_cache.move_to_end(key)
                while len(self._query_cache) > _QUERY_CACHE_SIZE:
                    self._query_cache.popitem(last=False)
        return {
            **cube_payload,
            "enabled": self._load_enabled_sync(),
            "time_basis": _time_basis_payload(now),
        }

    def _build_cube_payload(self, start: date, end: date, granularity: str) -> dict[str, Any]:
        span = end - start + timedelta(days=1)
        try:
            previous_start = start - span
            previous_end = start - timedelta(days=1)
        except OverflowError as exc:
            raise ValueError("日期超出可查询范围") from exc
        cube = self._store.query_cube(
            start,
            end,
            bucket={"hour": "hour", "day": "day", "week": "day", "month": "month"}[granularity],
            previous_start=previous_start,
            previous_end=previous_end,
        )
        buckets = list(_bucket_labels(start, end, granularity))
        dimensions, rows = _encode_cube(cube, buckets, granularity)
        return {
            "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "granularity": granularity,
            "available_range": _available_range_payload(*cube.available_range),
            "buckets": buckets,
            "dimensions": dimensions,
            "rows": rows,
            "previous_period": {
                "start_date": previous_start.isoformat(),
                "end_date": previous_end.isoformat(),
                "totals": [
                    {"provider": provider, "currency": currency, "amount": round(amount, 6), "turns": turns}
                    for provider, currency, amount, turns in cube.previous_totals
                ],
            },
        }

    # -- diagnostics and lifecycle ---------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        store_diagnostics = self._store.diagnostics()
        with self._state_lock:
            enabled = dict(self._enabled) if self._enabled is not None else None
            return {
                "enabled": enabled,
                **store_diagnostics,
                "write_count": self._write_count,
                "write_failure_count": self._write_failure_count,
                "last_write_at": self._last_write_at,
                "query_cache_entries": len(self._query_cache),
            }

    def close(self) -> None:
        with self._state_lock:
            self._query_cache.clear()
        self._store.close()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)


def resolve_granularity(granularity: str, start: date, end: date) -> str:
    """Pick the bucket size for a range; ``auto`` follows the range length."""

    requested = str(granularity or "auto").strip().lower()
    days = (end - start).days + 1
    if requested == "auto":
        if days <= 2:
            resolved = "hour"
        elif days <= 92:
            resolved = "day"
        elif days <= 730:
            resolved = "week"
        else:
            resolved = "month"
    elif requested in GRANULARITIES:
        resolved = requested
    else:
        raise ValueError(f"不支持的粒度: {granularity}")
    if resolved == "hour" and days > _MAX_HOUR_RANGE_DAYS:
        resolved = "day"
    while _bucket_count(days, resolved) > _MAX_BUCKETS:
        if resolved not in _COARSER:
            raise ValueError("查询范围过长")
        resolved = _COARSER[resolved]
    return resolved


def _bucket_count(days: int, granularity: str) -> int:
    return {
        "hour": days * 24,
        "day": days,
        "week": days // 7 + 2,
        "month": days // 28 + 2,
    }[granularity]


def _bucket_labels(start: date, end: date, granularity: str) -> Iterator[str]:
    if granularity == "hour":
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            for hour in range(24):
                yield f"{day}T{hour:02d}"
    elif granularity == "day":
        for offset in range((end - start).days + 1):
            yield (start + timedelta(days=offset)).isoformat()
    elif granularity == "week":
        current = start - timedelta(days=start.weekday())
        while current <= end:
            yield current.isoformat()
            current += timedelta(days=7)
    else:
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            yield f"{year:04d}-{month:02d}-01"
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _group_label(day: int, hour: int | None, granularity: str) -> str:
    value = day_from_number(day)
    if granularity == "hour":
        return f"{value.isoformat()}T{int(hour or 0):02d}"
    if granularity == "week":
        value -= timedelta(days=value.weekday())
    return value.isoformat()


def _encode_cube(
    cube: CostCube,
    buckets: list[str],
    granularity: str,
) -> tuple[dict[str, list[str]], list[list[Any]]]:
    """Dictionary-encode the SQL groups into index rows, folding days into weeks."""

    bucket_index = {label: index for index, label in enumerate(buckets)}
    names = ("bot", "agent", "user", "model", "currency")
    # Both providers are always listed so their index stays stable for clients.
    dimensions: dict[str, list[str]] = {"provider": list(COST_PROVIDERS), **{name: [] for name in names}}
    lookups: dict[str, dict[str, int]] = {
        "provider": {provider: index for index, provider in enumerate(COST_PROVIDERS)},
        **{name: {} for name in names},
    }

    def encode(name: str, value: object) -> int:
        text = str(value or "")
        lookup = lookups[name]
        index = lookup.get(text)
        if index is None:
            index = lookup[text] = len(dimensions[name])
            dimensions[name].append(text)
        return index

    folded: dict[tuple[int, ...], list[float]] = {}
    for day, hour, provider, bot, agent, user, model, currency, amount, turns, partial in cube.groups:
        bucket = bucket_index.get(_group_label(int(day), hour, granularity))
        if bucket is None or provider not in lookups["provider"]:
            continue
        key = (
            bucket,
            lookups["provider"][provider],
            encode("bot", bot),
            encode("agent", agent),
            encode("user", user),
            encode("model", model),
            encode("currency", currency),
        )
        totals = folded.get(key)
        if totals is None:
            folded[key] = [float(amount or 0.0), int(turns or 0), int(partial or 0)]
        else:
            totals[0] += float(amount or 0.0)
            totals[1] += int(turns or 0)
            totals[2] += int(partial or 0)
    rows = [
        [*key, round(totals[0], 6), int(totals[1]), int(totals[2])]
        for key, totals in sorted(folded.items())
    ]
    return dimensions, rows


def _time_basis_payload(now: datetime | None = None) -> dict[str, str]:
    # Same shape as the quota usage service, so both admin pages share one client helper.
    from bot.codex_usage.service import _time_basis_payload as usage_time_basis

    return usage_time_basis(now)


def _available_range_payload(first_date: date | None, last_date: date | None) -> dict[str, str | None]:
    return {
        "first_date": first_date.isoformat() if first_date is not None else None,
        "last_date": last_date.isoformat() if last_date is not None else None,
    }


def _resolve_query_dates(
    start_date: date | None,
    end_date: date | None,
    *,
    today: date,
) -> tuple[date, date]:
    if (start_date is None) != (end_date is None):
        raise ValueError("必须同时提供开始日期和结束日期")
    if start_date is None or end_date is None:
        return today - timedelta(days=29), today
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    return start_date, end_date
