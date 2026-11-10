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
from .claude_rate_limits import (
    ClaudeAuthStatusReader,
    resolve_claude_provider,
    samples_from_rate_limit_info,
)
from .models import (
    KNOWN_USAGE_PROVIDERS,
    CodexRateLimitSample,
    DayLike,
    ProviderInfo,
    UsageProvider,
    normalize_origin_label,
    normalize_usage_provider,
)
from .provider import CodexProviderResolver
from .rollout import TurnRateLimitResolution, resolve_turn_rate_limit_resolution
from .store import CodexUsageStore
from .transfer import (
    build_export_document,
    export_filename,
    local_origin_label,
    parse_import_document,
)


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


class ClaudeQuotaCapture:
    """One Claude process snapshot recording its last ``rate_limit_event`` once."""

    def __init__(
        self,
        service: CodexUsageService,
        *,
        enabled: bool,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> None:
        self._service = service
        self.enabled = enabled
        self.executable = executable
        self.environment = dict(environment) if environment is not None else None
        self._attempted = False

    async def record_once(self, parsed_result: Any = None, **_: Any) -> bool:
        if self._attempted:
            return False
        self._attempted = True
        info = getattr(parsed_result, "rate_limit_info", None)
        if not self.enabled or not isinstance(info, Mapping):
            return False
        observed_at = getattr(parsed_result, "rate_limit_observed_at", None)
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            observed_at = datetime.now(timezone.utc)
        return await self._service._record_claude_rate_limit_info(
            info,
            sampled_at=observed_at,
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
        claude_auth_status_reader: ClaudeAuthStatusReader | Any | None = None,
    ) -> None:
        if store is None:
            store = CodexUsageStore(_default_db_path() if db_path is None else db_path)
        self._store = store
        self._resolver = resolver or CodexProviderResolver()
        self._rate_limit_resolver = rate_limit_resolver or resolve_turn_rate_limit_resolution
        self._account_rate_limit_resolver = account_rate_limit_resolver or resolve_account_rate_limits
        self._claude_auth_status_reader = claude_auth_status_reader or ClaudeAuthStatusReader()
        self._diagnostics_lock = threading.RLock()
        self._enabled_snapshot: dict[UsageProvider, bool] = {}
        self._write_count = 0
        self._write_failure_count = 0
        self._provider_resolution_failure_count = 0
        self._last_write_at: str | None = None
        self._last_error_code: str | None = None

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    async def get_enabled(self, provider: UsageProvider = "codex") -> bool:
        normalized_provider = normalize_usage_provider(provider)
        enabled = await asyncio.to_thread(self._store.get_enabled, normalized_provider)
        with self._diagnostics_lock:
            self._enabled_snapshot[normalized_provider] = enabled
        return enabled

    enabled = get_enabled

    async def set_enabled(self, enabled: bool, provider: UsageProvider = "codex") -> None:
        normalized_provider = normalize_usage_provider(provider)
        await asyncio.to_thread(self._store.set_enabled, enabled, normalized_provider)
        with self._diagnostics_lock:
            self._enabled_snapshot[normalized_provider] = enabled

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

    async def create_claude_capture(
        self,
        *,
        env: Mapping[str, str] | None = None,
        command: Sequence[str] | str | None = None,
    ) -> ClaudeQuotaCapture:
        return ClaudeQuotaCapture(
            self,
            enabled=await self.get_enabled("claude"),
            executable=_command_executable(command) if command else "claude",
            environment=env,
        )

    async def _record_claude_rate_limit_info(
        self,
        info: Mapping[str, Any],
        *,
        sampled_at: datetime,
        executable: str,
        environment: Mapping[str, str] | None,
    ) -> bool:
        try:
            auth_status = await asyncio.to_thread(
                self._claude_auth_status_reader.read,
                executable=executable,
                env=environment,
            )
            provider = resolve_claude_provider(env=environment, auth_status=auth_status)
        except Exception as exc:
            self._mark_provider_resolution_failure(exc)
            return False
        if provider.kind != "claude_official":
            return False
        samples = samples_from_rate_limit_info(
            info,
            sampled_at=sampled_at,
            plan_type=auth_status.subscription_type if auth_status is not None else None,
        )
        return await self._store_samples(samples, "claude")

    async def _store_samples(
        self,
        samples: Sequence[CodexRateLimitSample],
        provider: UsageProvider,
    ) -> bool:
        recorded = False
        for sample in samples:
            try:
                await asyncio.to_thread(self._store.record_rate_limit_sample, sample, provider)
            except Exception as exc:
                with self._diagnostics_lock:
                    self._write_failure_count += 1
                    self._last_error_code = "write_failed"
                logger.warning("%s 限额写入失败，已忽略: %s", provider, type(exc).__name__)
                continue
            recorded = True
            with self._diagnostics_lock:
                self._write_count += 1
                self._last_write_at = datetime.now(timezone.utc).isoformat()
        return recorded

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
        return await self._store_samples(tuple(samples_by_limit_id.values()), "codex")

    async def query(
        self,
        start_day: DayLike,
        end_day: DayLike,
        provider: UsageProvider = "codex",
    ) -> tuple[CodexRateLimitSample, ...]:
        normalized_provider = normalize_usage_provider(provider)
        return await asyncio.to_thread(self._store.query, start_day, end_day, normalized_provider)

    async def available_range(self, provider: UsageProvider = "codex") -> tuple[date | None, date | None]:
        normalized_provider = normalize_usage_provider(provider)
        return await asyncio.to_thread(self._store.available_range, normalized_provider)

    async def record_rate_limit_sample(
        self,
        sample: CodexRateLimitSample,
        provider: UsageProvider = "codex",
    ) -> None:
        normalized_provider = normalize_usage_provider(provider)
        await asyncio.to_thread(self._store.record_rate_limit_sample, sample, normalized_provider)

    async def config_snapshot(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
        provider: UsageProvider = "codex",
    ) -> dict[str, Any]:
        normalized_provider = normalize_usage_provider(provider)
        enabled = await self.get_enabled(normalized_provider)
        current_provider = (
            await self._safe_current_provider(env=env, argv=argv)
            if normalized_provider == "codex"
            else await self._safe_claude_provider(env=env, argv=argv)
        )
        first_date, last_date = await self.available_range(normalized_provider)
        return {
            "enabled": enabled,
            "current_provider": _provider_payload(current_provider, usage_provider=normalized_provider),
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
        }

    async def update_enabled(
        self,
        enabled: bool,
        provider: UsageProvider = "codex",
    ) -> dict[str, Any]:
        normalized_provider = normalize_usage_provider(provider)
        await self.set_enabled(enabled, normalized_provider)
        return await self.config_snapshot(provider=normalized_provider)

    async def query_stats(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        provider: UsageProvider = "codex",
    ) -> dict[str, Any]:
        normalized_provider = normalize_usage_provider(provider)
        start, end = _resolve_query_dates(start_date, end_date)
        samples = await self.query(start, end, normalized_provider)
        first_date, last_date = await self.available_range(normalized_provider)
        return {
            "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "enabled": await self.get_enabled(normalized_provider),
            "time_basis": _time_basis_payload(),
            "available_range": _available_range_payload(first_date, last_date),
            "rate_limit_samples": [_rate_limit_payload(sample) for sample in samples],
        }

    async def export_samples(
        self,
        *,
        start_date: date,
        end_date: date,
        origin_label: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build a portable file of the Codex and Claude samples in a queried date range.

        Dates follow the server-local calendar used by ``query_stats``.
        """

        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        source = normalize_origin_label(origin_label) or await asyncio.to_thread(local_origin_label)
        exported_at = now or datetime.now(timezone.utc)
        samples = await asyncio.to_thread(
            self._store.export_rate_limit_samples,
            start_date,
            end_date,
        )
        document = await asyncio.to_thread(
            build_export_document,
            samples,
            source=source,
            exported_at=exported_at,
        )
        return {
            "filename": export_filename(source, exported_at),
            "sample_count": len(samples),
            "document": document,
        }

    async def import_samples(self, document: object) -> dict[str, Any]:
        """Merge another machine's export; raises ``SampleDocumentError`` for unusable files."""

        return await asyncio.to_thread(self._import_samples_sync, document)

    def _import_samples_sync(self, document: object) -> dict[str, Any]:
        parsed = parse_import_document(document)
        counts = self._store.import_rate_limit_samples(parsed.samples)
        return {
            "total": parsed.total,
            "inserted": counts.inserted,
            "duplicates": counts.duplicates,
            "invalid": parsed.invalid,
            "inserted_by_provider": {
                provider: counts.inserted_by_provider.get(provider, 0)
                for provider in KNOWN_USAGE_PROVIDERS
            },
        }

    async def delete_imported_samples(self) -> dict[str, int]:
        return {"deleted": await asyncio.to_thread(self._store.delete_imported_samples)}

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

    async def _safe_claude_provider(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
    ) -> ProviderInfo:
        try:
            # Prefer the status cached by recent turns over spawning another CLI.
            auth_status = self._claude_auth_status_reader.cached() if argv is None else None
            if auth_status is None:
                auth_status = await asyncio.to_thread(
                    self._claude_auth_status_reader.read,
                    executable=_command_executable(argv) if argv else "claude",
                    env=env,
                )
            return resolve_claude_provider(env=env, auth_status=auth_status)
        except Exception as exc:
            self._mark_provider_resolution_failure(exc)
            return ProviderInfo(key="unknown", kind="unknown", base_url=None, resolution="config_invalid")

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
        enabled = await self.get_enabled("codex")
        store_diagnostics = await asyncio.to_thread(self._store.diagnostics)
        return self._diagnostics_payload(enabled=enabled, store_diagnostics=store_diagnostics)

    def diagnostics(self) -> _AwaitableDiagnostics:
        with self._diagnostics_lock:
            enabled = self._enabled_snapshot.get("codex", False)
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


def _provider_payload(
    provider: ProviderInfo,
    *,
    usage_provider: UsageProvider = "codex",
) -> dict[str, str | None]:
    if usage_provider == "claude" and provider.kind == "claude_official":
        label = "Claude 官方订阅"
    elif usage_provider == "claude" and provider.resolution == "unsupported_override":
        label = "非订阅登录（无订阅额度）"
    else:
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
        "credits_balance": sample.credits_balance,
        "origin": sample.origin,
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
