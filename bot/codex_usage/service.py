from __future__ import annotations

import asyncio
import logging
import os
import shlex
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import (
    DEFAULT_CODEX_MODEL,
    CodexRateLimitSample,
    CodexTokenUsage,
    DayLike,
    ProviderInfo,
    UsageQueryResult,
    normalize_model_key,
)
from .app_server_rate_limits import resolve_account_rate_limit
from .provider import CodexProviderResolver
from .rollout import (
    TurnRateLimitResolution,
    resolve_failed_turn_usage,
    resolve_turn_rate_limit_resolution,
)
from .store import CodexUsageStore

try:
    import tomllib
except ImportError:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]


logger = logging.getLogger(__name__)


def _model_from_config_override(value: str) -> str | None:
    try:
        parsed = tomllib.loads(value)
    except (TypeError, tomllib.TOMLDecodeError):
        return None
    model = parsed.get("model") if isinstance(parsed, Mapping) else None
    return model if isinstance(model, str) else None


def resolve_codex_model(argv: Sequence[str] | str | None) -> str:
    if argv is None:
        return DEFAULT_CODEX_MODEL
    arguments = shlex.split(argv) if isinstance(argv, str) else [str(item) for item in argv]
    selected: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        config_override: str | None = None
        if argument in {"--model", "-m"}:
            if index + 1 < len(arguments):
                index += 1
                selected = arguments[index]
        elif argument.startswith("--model="):
            selected = argument.split("=", 1)[1]
        elif argument.startswith("-m") and not argument.startswith("--") and len(argument) > 2:
            selected = argument[2:]
        elif argument in {"-c", "--config"}:
            if index + 1 < len(arguments):
                index += 1
                config_override = arguments[index]
        elif argument.startswith("--config="):
            config_override = argument.split("=", 1)[1]
        elif argument.startswith("-c") and len(argument) > 2:
            config_override = argument[2:]
        if config_override is not None:
            configured_model = _model_from_config_override(config_override)
            if configured_model is not None:
                selected = configured_model
        index += 1
    return normalize_model_key(selected)


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
        model: str,
        started_at: datetime,
        codex_home: Path,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> None:
        self._service = service
        self.enabled = enabled
        self.provider = provider
        self.model = normalize_model_key(model)
        self.started_at = started_at
        self.codex_home = codex_home
        self.executable = executable
        self.environment = dict(environment) if environment is not None else None
        self._attempted = False

    async def record_once(
        self,
        usage: CodexTokenUsage | Mapping[str, Any] | None,
        *,
        terminal_at: datetime | date | None = None,
        terminal_time: datetime | date | None = None,
        invalid_usage_count: int = 0,
        duplicate_terminal_count: int = 0,
        failed: bool = False,
        session_id: str | None = None,
    ) -> bool:
        """Best-effort record that never lets usage accounting fail chat execution."""

        self._service.note_invalid_usage(invalid_usage_count)
        self._service.note_duplicate_terminal(duplicate_terminal_count)
        if self._attempted:
            self._service.note_duplicate_terminal()
            return False
        self._attempted = True
        if not self.enabled:
            return False
        normalized_session_id = str(session_id or "").strip()
        if usage is None and normalized_session_id:
            usage = await self._service._resolve_failed_capture_usage(
                session_id=normalized_session_id,
                started_at=self.started_at,
                codex_home=self.codex_home,
            )
        token_recorded = False
        if usage is not None:
            timestamp = terminal_at if terminal_at is not None else terminal_time
            if timestamp is None:
                sample_time = getattr(usage, "completed_at", None)
                if isinstance(sample_time, (datetime, date)):
                    timestamp = sample_time
            token_recorded = await self._service._record_capture(
                self.provider,
                self.model,
                usage,
                timestamp,
            )
        if (
            self.provider.kind == "openai_official"
            and normalized_session_id
            and self.model.casefold() != "gpt-5.3-codex-spark"
        ):
            await self._service._record_rate_limit_capture(
                session_id=normalized_session_id,
                started_at=self.started_at,
                codex_home=self.codex_home,
                executable=self.executable,
                environment=self.environment,
            )
        return token_recorded


class CodexUsageService:
    """Async facade that keeps all SQLite and TOML I/O off the event loop."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        store: CodexUsageStore | None = None,
        resolver: CodexProviderResolver | Any | None = None,
        failed_usage_resolver: Any | None = None,
        rate_limit_resolver: Any | None = None,
        account_rate_limit_resolver: Any | None = None,
    ) -> None:
        if store is None:
            store = CodexUsageStore(_default_db_path() if db_path is None else db_path)
        self._store = store
        self._resolver = resolver or CodexProviderResolver()
        self._failed_usage_resolver = failed_usage_resolver or resolve_failed_turn_usage
        self._rate_limit_resolver = rate_limit_resolver or resolve_turn_rate_limit_resolution
        self._account_rate_limit_resolver = account_rate_limit_resolver or resolve_account_rate_limit
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
        effective_argv = argv if argv is not None else command
        started_at = datetime.now(timezone.utc)
        model = resolve_codex_model(effective_argv)
        codex_home = _codex_home(env)
        executable = _command_executable(effective_argv)
        environment = dict(env) if env is not None else None
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
                model=model,
                started_at=started_at,
                codex_home=codex_home,
                executable=executable,
                environment=environment,
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
        return CodexUsageCapture(
            self,
            enabled=True,
            provider=provider,
            model=model,
            started_at=started_at,
            codex_home=codex_home,
            executable=executable,
            environment=environment,
        )

    capture_for_process = create_capture
    start_capture = create_capture

    async def _record_capture(
        self,
        provider: ProviderInfo,
        model: str,
        usage: CodexTokenUsage | Mapping[str, Any],
        terminal_at: datetime | date | None,
    ) -> bool:
        try:
            await asyncio.to_thread(
                self._store.record,
                provider,
                usage,
                model_key=model,
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

    async def _resolve_failed_capture_usage(
        self,
        *,
        session_id: str,
        started_at: datetime,
        codex_home: Path,
    ) -> CodexTokenUsage | Mapping[str, Any] | None:
        try:
            return await asyncio.to_thread(
                self._failed_usage_resolver,
                session_id=session_id,
                started_at=started_at,
                codex_home=codex_home,
            )
        except Exception as exc:
            logger.warning("Codex 未完整终态用量恢复失败，已跳过: %s", type(exc).__name__)
            return None

    async def _record_rate_limit_capture(
        self,
        *,
        session_id: str,
        started_at: datetime,
        codex_home: Path,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> None:
        try:
            resolution = await asyncio.to_thread(
                self._rate_limit_resolver,
                session_id=session_id,
                started_at=started_at,
                codex_home=codex_home,
            )
        except Exception as exc:
            logger.warning("Codex 限额解析失败，已跳过: %s", type(exc).__name__)
            return
        sample: CodexRateLimitSample | None = None
        refresh_general = False
        if isinstance(resolution, TurnRateLimitResolution):
            sample = resolution.sample
            refresh_general = resolution.refresh_general
        elif isinstance(resolution, CodexRateLimitSample):
            # Keep compatibility with injected legacy resolvers.
            sample = resolution
        if refresh_general:
            try:
                sample = await asyncio.to_thread(
                    self._account_rate_limit_resolver,
                    executable=executable,
                    env=environment,
                    limit_id="codex",
                )
            except Exception as exc:
                logger.warning("Codex 通用限额主动查询失败，已跳过: %s", type(exc).__name__)
                sample = None
        if sample is None:
            return
        try:
            await asyncio.to_thread(self._store.record_rate_limit_sample, sample)
        except Exception as exc:
            logger.warning("Codex 限额写入失败，已忽略: %s", type(exc).__name__)

    async def query(
        self,
        start_day: DayLike,
        end_day: DayLike,
        *,
        provider_keys: Sequence[str] | None = None,
        daily_page: int | None = None,
        daily_page_size: int | None = None,
    ) -> UsageQueryResult:
        return await asyncio.to_thread(
            self._store.query,
            start_day,
            end_day,
            provider_keys=provider_keys,
            daily_page=daily_page,
            daily_page_size=daily_page_size,
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
        daily_page: int = 1,
        daily_page_size: int = 10,
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
            daily_page=daily_page,
            daily_page_size=daily_page_size,
        )
        daily_pagination = result.daily_pagination
        if daily_pagination is None:  # pragma: no cover - query_stats always requests a page
            raise RuntimeError("Codex 用量分页结果缺失")
        first_date, last_date = await self.available_range()
        return {
            "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "enabled": enabled,
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
            "available_providers": [_provider_payload(provider) for provider in available_providers],
            "selected_provider_keys": selected_keys,
            "rate_limit_samples": [
                _rate_limit_payload(sample) for sample in result.rate_limit_samples
            ],
            "totals": _totals_payload(result.totals),
            "by_provider": [
                {"provider": _provider_payload(item.provider), **_totals_payload(item.totals)}
                for item in result.by_provider
            ],
            "by_day": [
                {"date": item.day.isoformat(), **_totals_payload(item.totals)}
                for item in sorted(result.by_day, key=lambda value: value.day, reverse=True)
            ],
            "daily_by_provider": [],
            "by_provider_model": [
                {
                    "provider": _provider_payload(item.provider),
                    "model": item.model,
                    **_totals_payload(item.totals),
                }
                for item in result.by_provider_model
            ],
            "daily_by_provider_model": [
                {
                    "date": item.day.isoformat(),
                    "provider": _provider_payload(item.provider),
                    "model": item.model,
                    **_totals_payload(item.totals),
                }
                for item in sorted(
                    result.daily_by_provider_model,
                    key=lambda value: (
                        -value.day.toordinal(),
                        _provider_order(value.provider),
                        value.provider.key,
                        value.model,
                    ),
                )
            ],
            "daily_pagination": {
                "page": daily_pagination.page,
                "page_size": daily_pagination.page_size,
                "total_items": daily_pagination.total_items,
                "total_pages": daily_pagination.total_pages,
                "has_previous": daily_pagination.has_previous,
                "has_next": daily_pagination.has_next,
            },
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


def _rate_limit_payload(sample: CodexRateLimitSample) -> dict[str, Any]:
    return {
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
