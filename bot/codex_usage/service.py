from __future__ import annotations

import asyncio
import logging
import os
import shlex
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .app_server_rate_limits import resolve_account_rate_limits
from .models import CodexRateLimitSample, DayLike, ProviderInfo
from .provider import CodexProviderResolver
from .rollout import TurnRateLimitResolution, resolve_turn_rate_limit_resolution
from .store import CodexUsageStore


logger = logging.getLogger(__name__)


def _command_executable(argv: Sequence[str] | str | None) -> str:
    if isinstance(argv, str):
        arguments = shlex.split(argv)
    elif argv is None:
        arguments = []
    else:
        arguments = [str(item) for item in argv]
    return arguments[0] if arguments else "codex"


def _codex_home(env: Mapping[str, str] | None) -> Path:
    source = os.environ if env is None else env
    configured = str(source.get("CODEX_HOME") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _default_db_path() -> Path:
    from bot.runtime_paths import get_codex_usage_db_path

    return get_codex_usage_db_path()


class _AwaitableDiagnostics(dict[str, int | bool | str | None]):
    def __await__(self):
        async def _result() -> _AwaitableDiagnostics:
            return self

        return _result().__await__()


class CodexQuotaCapture:
    """One process-start snapshot with idempotent quota recording."""

    def __init__(
        self,
        service: CodexUsageService,
        *,
        enabled: bool,
        provider: ProviderInfo,
        started_at: datetime,
        codex_home: Path,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> None:
        self._service = service
        self.enabled = enabled
        self.provider = provider
        self.started_at = started_at
        self.codex_home = codex_home
        self.executable = executable
        self.environment = dict(environment) if environment is not None else None
        self._attempted = False

    async def record_once(self, *, session_id: str | None = None) -> bool:
        if self._attempted:
            return False
        self._attempted = True
        if not self.enabled or self.provider.kind != "openai_official":
            return False
        return await self._service._record_rate_limit_capture(
            session_id=str(session_id or "").strip(),
            started_at=self.started_at,
            codex_home=self.codex_home,
            executable=self.executable,
            environment=self.environment,
        )


class CodexUsageService:
    """Async facade for Codex quota collection and persistence."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        store: CodexUsageStore | None = None,
        resolver: CodexProviderResolver | Any | None = None,
        rate_limit_resolver: Any | None = None,
        account_rate_limit_resolver: Any | None = None,
    ) -> None:
        if store is None:
            store = CodexUsageStore(_default_db_path() if db_path is None else db_path)
        self._store = store
        self._resolver = resolver or CodexProviderResolver()
        self._rate_limit_resolver = rate_limit_resolver or resolve_turn_rate_limit_resolution
        self._account_rate_limit_resolver = account_rate_limit_resolver or resolve_account_rate_limits
        self._diagnostics_lock = threading.RLock()
        self._enabled_snapshot = False
        self._write_count = 0
        self._write_failure_count = 0
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
    ) -> CodexQuotaCapture:
        effective_argv = argv if argv is not None else command
        started_at = datetime.now(timezone.utc)
        enabled = await self.get_enabled()
        if not enabled:
            return CodexQuotaCapture(
                self,
                enabled=False,
                provider=ProviderInfo(
                    key="openai_official",
                    kind="openai_official",
                    base_url=None,
                    resolution="disabled",
                ),
                started_at=started_at,
                codex_home=_codex_home(env),
                executable=_command_executable(effective_argv),
                environment=env,
            )
        try:
            provider = await self.resolve_current_provider(
                env=env,
                argv=argv,
                command=command,
            )
        except Exception as exc:
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
        return CodexQuotaCapture(
            self,
            enabled=True,
            provider=provider,
            started_at=started_at,
            codex_home=_codex_home(env),
            executable=_command_executable(effective_argv),
            environment=env,
        )

    capture_for_process = create_capture
    start_capture = create_capture

    async def _record_rate_limit_capture(
        self,
        *,
        session_id: str,
        started_at: datetime,
        codex_home: Path,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> bool:
        samples_by_limit_id: dict[str, CodexRateLimitSample] = {}
        if session_id:
            try:
                resolution = await asyncio.to_thread(
                    self._rate_limit_resolver,
                    session_id=session_id,
                    started_at=started_at,
                    codex_home=codex_home,
                )
            except Exception as exc:
                logger.warning("Codex 限额解析失败，已跳过: %s", type(exc).__name__)
            else:
                if isinstance(resolution, TurnRateLimitResolution):
                    sample = resolution.sample
                elif isinstance(resolution, CodexRateLimitSample):
                    sample = resolution
                else:
                    sample = None
                if sample is not None:
                    samples_by_limit_id[sample.limit_id] = sample
        try:
            account_result = await asyncio.to_thread(
                self._account_rate_limit_resolver,
                executable=executable,
                env=environment,
            )
        except Exception as exc:
            logger.warning("Codex 限额主动查询失败，已跳过: %s", type(exc).__name__)
            account_result = ()
        account_samples = (
            (account_result,)
            if isinstance(account_result, CodexRateLimitSample)
            else tuple(account_result or ())
        )
        for sample in account_samples:
            if isinstance(sample, CodexRateLimitSample):
                samples_by_limit_id[sample.limit_id] = sample

        recorded = False
        for sample in samples_by_limit_id.values():
            try:
                await asyncio.to_thread(self._store.record_rate_limit_sample, sample)
            except Exception as exc:
                with self._diagnostics_lock:
                    self._write_failure_count += 1
                    self._last_error_code = "write_failed"
                logger.warning("Codex 限额写入失败，已忽略: %s", type(exc).__name__)
                continue
            recorded = True
            with self._diagnostics_lock:
                self._write_count += 1
                self._last_write_at = datetime.now(timezone.utc).isoformat()
        return recorded

    async def query(self, start_day: DayLike, end_day: DayLike) -> tuple[CodexRateLimitSample, ...]:
        return await asyncio.to_thread(self._store.query, start_day, end_day)

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
    ) -> dict[str, Any]:
        start, end = _resolve_query_dates(start_date, end_date)
        samples = await self.query(start, end)
        first_date, last_date = await self.available_range()
        return {
            "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "enabled": await self.get_enabled(),
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
            "rate_limit_samples": [_rate_limit_payload(sample) for sample in samples],
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

    def _mark_provider_resolution_failure(self, exc: Exception | None) -> None:
        with self._diagnostics_lock:
            self._provider_resolution_failure_count += 1
            self._last_error_code = "provider_resolution_failed"
        if exc is not None:
            logger.warning("Codex provider 解析失败，按 unknown 处理: %s", type(exc).__name__)

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
                "provider_resolution_failure_count": self._provider_resolution_failure_count,
                "last_write_at": self._last_write_at,
                "last_error_code": self._last_error_code,
            }

    async def diagnostics_async(self) -> dict[str, int | bool | str | None]:
        enabled = await self.get_enabled()
        store_diagnostics = await asyncio.to_thread(self._store.diagnostics)
        return self._diagnostics_payload(enabled=enabled, store_diagnostics=store_diagnostics)

    def diagnostics(self) -> _AwaitableDiagnostics:
        with self._diagnostics_lock:
            enabled = self._enabled_snapshot
        return _AwaitableDiagnostics(
            self._diagnostics_payload(
                enabled=enabled,
                store_diagnostics=self._store.diagnostics(),
            )
        )

    async def refresh_diagnostics(self) -> dict[str, int | bool | str | None]:
        return await self.diagnostics_async()

    def close(self) -> None:
        self._store.close()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)


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


def _rate_limit_payload(sample: CodexRateLimitSample) -> dict[str, Any]:
    return {
        "limit_id": sample.limit_id,
        "sampled_at": sample.sampled_at.astimezone().isoformat(),
        "used_percent": sample.used_percent,
        "window_minutes": sample.window_minutes,
        "resets_at": sample.resets_at.astimezone().isoformat(),
        "plan_type": sample.plan_type,
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


UsageService = CodexUsageService
