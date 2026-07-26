from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import CodexTokenUsage, DayLike, ProviderInfo, UsageQueryResult
from .provider import CodexProviderResolver
from .store import CodexUsageStore


logger = logging.getLogger(__name__)


def _default_db_path() -> Path:
    """Resolve the runtime path only when a default service is actually needed."""

    from bot.runtime_paths import get_codex_usage_db_path

    return get_codex_usage_db_path()


class _AwaitableDiagnostics(dict[str, int | bool | str | None]):
    """A mapping that also preserves compatibility with ``await diagnostics()``."""

    def __await__(self):
        async def _result() -> _AwaitableDiagnostics:
            return self

        return _result().__await__()


class CodexUsageCapture:
    """One process-start snapshot with an idempotent terminal usage recorder."""

    def __init__(
        self,
        service: CodexUsageService,
        *,
        enabled: bool,
        provider: ProviderInfo,
    ) -> None:
        self._service = service
        self.enabled = enabled
        self.provider = provider
        self._attempted = False

    async def record_once(
        self,
        usage: CodexTokenUsage | Mapping[str, Any] | None,
        *,
        terminal_at: datetime | date | None = None,
        terminal_time: datetime | date | None = None,
        invalid_usage_count: int = 0,
        duplicate_terminal_count: int = 0,
    ) -> bool:
        """Best-effort record that never lets usage accounting fail chat execution."""

        self._service.note_invalid_usage(invalid_usage_count)
        self._service.note_duplicate_terminal(duplicate_terminal_count)
        if self._attempted:
            self._service.note_duplicate_terminal()
            return False
        self._attempted = True
        if not self.enabled or usage is None:
            return False
        timestamp = terminal_at if terminal_at is not None else terminal_time
        if timestamp is None:
            sample_time = getattr(usage, "completed_at", None)
            if isinstance(sample_time, (datetime, date)):
                timestamp = sample_time
        return await self._service._record_capture(self.provider, usage, timestamp)


class CodexUsageService:
    """Async facade that keeps all SQLite and TOML I/O off the event loop."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        store: CodexUsageStore | None = None,
        resolver: CodexProviderResolver | Any | None = None,
    ) -> None:
        if store is None:
            store = CodexUsageStore(_default_db_path() if db_path is None else db_path)
        self._store = store
        self._resolver = resolver or CodexProviderResolver()
        self._diagnostics_lock = threading.RLock()
        self._enabled_snapshot = False
        self._write_count = 0
        self._write_failure_count = 0
        self._invalid_usage_count = 0
        self._duplicate_terminal_count = 0
        self._provider_resolution_failure_count = 0
        self._last_write_at: str | None = None
        self._last_error_code: str | None = None

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    async def get_enabled(self) -> bool:
        enabled = await asyncio.to_thread(self._store.get_enabled)
        with self._diagnostics_lock:
            self._enabled_snapshot = enabled
        return enabled

    enabled = get_enabled

    async def set_enabled(self, enabled: bool) -> None:
        await asyncio.to_thread(self._store.set_enabled, enabled)
        with self._diagnostics_lock:
            self._enabled_snapshot = enabled

    update_enabled = set_enabled

    async def resolve_current_provider(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
        command: Sequence[str] | str | None = None,
    ) -> ProviderInfo:
        effective_argv = argv if argv is not None else command
        return await asyncio.to_thread(self._resolver.resolve, env=env, argv=effective_argv)

    async def create_capture(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
        command: Sequence[str] | str | None = None,
    ) -> CodexUsageCapture:
        enabled = await self.get_enabled()
        if not enabled:
            return CodexUsageCapture(
                self,
                enabled=False,
                provider=ProviderInfo(
                    key="openai_official",
                    kind="openai_official",
                    base_url=None,
                    resolution="disabled",
                ),
            )
        try:
            provider = await self.resolve_current_provider(
                env=env,
                argv=argv,
                command=command,
            )
        except Exception as exc:  # Provider parsing must never block a CLI call.
            self._mark_provider_resolution_failure(exc)
            provider = ProviderInfo(
                key="unknown",
                kind="unknown",
                base_url=None,
                resolution="config_invalid",
            )
        else:
            if provider.kind == "unknown":
                self._mark_provider_resolution_failure(None)
        return CodexUsageCapture(self, enabled=True, provider=provider)

    capture_for_process = create_capture
    start_capture = create_capture

    async def _record_capture(
        self,
        provider: ProviderInfo,
        usage: CodexTokenUsage | Mapping[str, Any],
        terminal_at: datetime | date | None,
    ) -> bool:
        try:
            await asyncio.to_thread(
                self._store.record,
                provider,
                usage,
                terminal_at=terminal_at,
            )
        except ValueError as exc:
            with self._diagnostics_lock:
                self._invalid_usage_count += 1
                self._last_error_code = "invalid_usage"
            logger.warning("Codex 用量样本无效，已跳过: %s", type(exc).__name__)
            return False
        except Exception as exc:  # Accounting failures are intentionally isolated.
            with self._diagnostics_lock:
                self._write_failure_count += 1
                self._last_error_code = "write_failed"
            logger.warning("Codex 用量写入失败，已忽略: %s", type(exc).__name__)
            return False
        with self._diagnostics_lock:
            self._write_count += 1
            self._last_write_at = datetime.now(timezone.utc).isoformat()
        return True

    async def query(
        self,
        start_day: DayLike,
        end_day: DayLike,
        *,
        provider_keys: Sequence[str] | None = None,
    ) -> UsageQueryResult:
        return await asyncio.to_thread(
            self._store.query,
            start_day,
            end_day,
            provider_keys=provider_keys,
        )

    query_usage = query

    async def list_providers(self) -> tuple[ProviderInfo, ...]:
        return await asyncio.to_thread(self._store.list_providers)

    async def available_range(self) -> tuple[date | None, date | None]:
        return await asyncio.to_thread(self._store.available_range)

    async def config_snapshot(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        enabled = await self.get_enabled()
        provider = await self._safe_current_provider(env=env, argv=argv)
        first_date, last_date = await self.available_range()
        return {
            "enabled": enabled,
            "current_provider": _provider_payload(provider),
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
        }

    async def update_enabled(self, enabled: bool) -> dict[str, Any]:
        await self.set_enabled(enabled)
        return await self.config_snapshot()

    async def query_stats(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        provider_keys: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        start, end = _resolve_query_dates(start_date, end_date)
        selected_keys = list(
            dict.fromkeys(
                str(item).strip() for item in (provider_keys or ()) if str(item).strip()
            )
        )
        enabled = await self.get_enabled()
        current_provider = await self._safe_current_provider()
        historical_providers = await self.list_providers()
        available_providers = _merge_providers(historical_providers, current_provider)
        known_keys = {provider.key for provider in available_providers}
        if any(key not in known_keys for key in selected_keys):
            raise ValueError("存在未知的 provider")
        result = await self.query(
            start,
            end,
            provider_keys=selected_keys or None,
        )
        first_date, last_date = await self.available_range()
        return {
            "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "enabled": enabled,
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
            "available_providers": [_provider_payload(provider) for provider in available_providers],
            "selected_provider_keys": selected_keys,
            "totals": _totals_payload(result.totals),
            "by_provider": [
                {"provider": _provider_payload(item.provider), **_totals_payload(item.totals)}
                for item in result.by_provider
            ],
            "by_day": [
                {"date": item.day.isoformat(), **_totals_payload(item.totals)}
                for item in sorted(result.by_day, key=lambda value: value.day, reverse=True)
            ],
            "daily_by_provider": [
                {
                    "date": item.day.isoformat(),
                    "provider": _provider_payload(item.provider),
                    **_totals_payload(item.totals),
                }
                for item in sorted(
                    result.daily_by_provider,
                    key=lambda value: (
                        -value.day.toordinal(),
                        _provider_order(value.provider),
                        value.provider.key,
                    ),
                )
            ],
        }

    async def _safe_current_provider(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
    ) -> ProviderInfo:
        try:
            provider = await self.resolve_current_provider(env=env, argv=argv)
        except Exception as exc:
            self._mark_provider_resolution_failure(exc)
            return ProviderInfo(
                key="unknown",
                kind="unknown",
                base_url=None,
                resolution="config_invalid",
            )
        if provider.kind == "unknown":
            self._mark_provider_resolution_failure(None)
        return provider

    def note_invalid_usage(self, count: int = 1) -> None:
        normalized_count = _non_negative_counter(count)
        if not normalized_count:
            return
        with self._diagnostics_lock:
            self._invalid_usage_count += normalized_count
            self._last_error_code = "invalid_usage"

    def note_duplicate_terminal(self, count: int = 1) -> None:
        normalized_count = _non_negative_counter(count)
        if not normalized_count:
            return
        with self._diagnostics_lock:
            self._duplicate_terminal_count += normalized_count

    def _mark_provider_resolution_failure(self, exc: Exception | None) -> None:
        with self._diagnostics_lock:
            self._provider_resolution_failure_count += 1
            self._last_error_code = "provider_resolution_failed"
        if exc is not None:
            logger.warning("Codex provider 解析失败，按 unknown 归因: %s", type(exc).__name__)

    def _diagnostics_payload(
        self,
        *,
        enabled: bool,
        store_diagnostics: Mapping[str, int | bool | str],
    ) -> dict[str, int | bool | str | None]:
        with self._diagnostics_lock:
            return {
                "enabled": enabled,
                **store_diagnostics,
                "write_count": self._write_count,
                "write_failure_count": self._write_failure_count,
                "invalid_usage_count": self._invalid_usage_count,
                "duplicate_terminal_count": self._duplicate_terminal_count,
                "provider_resolution_failure_count": (
                    self._provider_resolution_failure_count
                ),
                "last_write_at": self._last_write_at,
                "last_error_code": self._last_error_code,
            }

    async def diagnostics_async(self) -> dict[str, int | bool | str | None]:
        enabled = await self.get_enabled()
        store_diagnostics = await asyncio.to_thread(self._store.diagnostics)
        return self._diagnostics_payload(
            enabled=enabled,
            store_diagnostics=store_diagnostics,
        )

    def diagnostics(self) -> _AwaitableDiagnostics:
        """Synchronous runtime-diagnostics callback with an awaitable result.

        It uses only cached enabled state and file metadata; SQLite reads remain
        available through :meth:`diagnostics_async` and always use ``to_thread``.
        """

        with self._diagnostics_lock:
            enabled = self._enabled_snapshot
        return _AwaitableDiagnostics(
            self._diagnostics_payload(
                enabled=enabled,
                store_diagnostics=self._store.diagnostics(),
            )
        )

    async def refresh_diagnostics(self) -> dict[str, int | bool | str | None]:
        """Explicit async alias for callers that need fresh persisted state."""

        return await self.diagnostics_async()

    def close(self) -> None:
        """Synchronous close for callers already dispatching shutdown I/O to a thread."""

        self._store.close()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)


def _non_negative_counter(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _provider_order(provider: ProviderInfo) -> int:
    return {"openai_official": 0, "base_url": 1, "unknown": 2}.get(provider.kind, 99)


def _provider_payload(provider: ProviderInfo) -> dict[str, str | None]:
    label = {
        "openai_official": "OpenAI 官方",
        "base_url": provider.base_url or "自定义 Provider",
        "unknown": "无法识别",
    }.get(provider.kind, "无法识别")
    return {
        "key": provider.key,
        "kind": provider.kind,
        "label": label,
        "base_url": provider.base_url,
        "resolution": provider.resolution,
    }


def _totals_payload(totals: Any) -> dict[str, int | float | None]:
    return {
        "request_count": totals.request_count,
        "input_tokens": totals.input_tokens,
        "cached_input_tokens": totals.cached_input_tokens,
        "uncached_input_tokens": totals.uncached_input_tokens,
        "output_tokens": totals.output_tokens,
        "reasoning_output_tokens": totals.reasoning_output_tokens,
        "total_tokens": totals.total_tokens,
        "cache_hit_rate": totals.cache_hit_rate,
    }


def _time_basis_payload(now: datetime | None = None) -> dict[str, str]:
    local_now = now or datetime.now().astimezone()
    offset = local_now.utcoffset() or timedelta()
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes = remainder // 60
    return {
        "mode": "server_local",
        "utc_offset": f"{sign}{hours:02d}:{minutes:02d}",
        "today": local_now.date().isoformat(),
    }


def _available_range_payload(
    first_date: date | None,
    last_date: date | None,
) -> dict[str, str | None]:
    return {
        "first_date": first_date.isoformat() if first_date is not None else None,
        "last_date": last_date.isoformat() if last_date is not None else None,
    }


def _resolve_query_dates(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if (start_date is None) != (end_date is None):
        raise ValueError("必须同时提供开始日期和结束日期")
    if start_date is None or end_date is None:
        end = datetime.now().astimezone().date()
        return end - timedelta(days=29), end
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    return start_date, end_date


def _merge_providers(
    historical: Sequence[ProviderInfo],
    current: ProviderInfo,
) -> tuple[ProviderInfo, ...]:
    by_key = {provider.key: provider for provider in historical}
    by_key[current.key] = current
    return tuple(
        sorted(
            by_key.values(),
            key=lambda provider: (_provider_order(provider), provider.key),
        )
    )


UsageService = CodexUsageService
