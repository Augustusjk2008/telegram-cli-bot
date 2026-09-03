from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.codex_usage.models import (
    GENERAL_CODEX_RATE_LIMIT_ID,
    SECONDARY_CODEX_RATE_LIMIT_ID,
    CodexRateLimitSample,
    ProviderInfo,
)
from bot.codex_usage.rollout import TurnRateLimitResolution
from bot.codex_usage.service import CodexUsageService
from bot.codex_usage.store import CodexUsageStore


def _sample(
    *,
    limit_id: str = GENERAL_CODEX_RATE_LIMIT_ID,
    used_percent: float = 35,
) -> CodexRateLimitSample:
    sampled_at = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
    return CodexRateLimitSample(
        sampled_at=sampled_at,
        used_percent=used_percent,
        window_minutes=10_080,
        resets_at=sampled_at + timedelta(days=3),
        plan_type="pro",
        limit_id=limit_id,
    )


class _Resolver:
    def __init__(self, provider: ProviderInfo) -> None:
        self.provider = provider
        self.calls = 0

    def resolve(self, **_kwargs: object) -> ProviderInfo:
        self.calls += 1
        return self.provider


def _provider(kind: str = "openai_official") -> ProviderInfo:
    if kind == "base_url":
        return ProviderInfo(
            key="base_url:https://example.test/v1",
            kind="base_url",
            base_url="https://example.test/v1",
        )
    return ProviderInfo(key=kind, kind=kind, base_url=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_disabled_capture_does_not_resolve_or_collect_quota(tmp_path: Path) -> None:
    resolver = _Resolver(_provider())
    account_calls = 0

    def account_resolver(**_kwargs: object) -> tuple[CodexRateLimitSample, ...]:
        nonlocal account_calls
        account_calls += 1
        return (_sample(),)

    service = CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=resolver,
        account_rate_limit_resolver=account_resolver,
    )

    capture = await service.create_capture(env={}, command=["codex"])
    assert await capture.record_once(session_id="session-1") is False
    assert resolver.calls == 0
    assert account_calls == 0
    assert not service.db_path.exists()


@pytest.mark.asyncio
async def test_official_capture_records_rollout_and_account_quota(tmp_path: Path) -> None:
    general = _sample()
    secondary = _sample(
        limit_id=SECONDARY_CODEX_RATE_LIMIT_ID,
        used_percent=64,
    )
    service = CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_Resolver(_provider()),
        rate_limit_resolver=lambda **_kwargs: TurnRateLimitResolution(sample=secondary),
        account_rate_limit_resolver=lambda **_kwargs: (general,),
    )
    await service.set_enabled(True)

    capture = await service.create_capture(env={}, command=["codex"])
    assert await capture.record_once(session_id="session-1") is True

    assert await service.query(date(2026, 8, 10), date(2026, 8, 10)) == (
        secondary,
        general,
    )


@pytest.mark.asyncio
async def test_capture_is_idempotent_and_can_query_account_without_session_id(
    tmp_path: Path,
) -> None:
    service = CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_Resolver(_provider()),
        account_rate_limit_resolver=lambda **_kwargs: (_sample(),),
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={}, command=["codex"])

    assert await capture.record_once() is True
    assert await capture.record_once(session_id="session-1") is False
    assert len(await service.query(date(2026, 8, 10), date(2026, 8, 10))) == 1


@pytest.mark.asyncio
async def test_custom_provider_does_not_collect_openai_quota(tmp_path: Path) -> None:
    account_calls = 0

    def account_resolver(**_kwargs: object) -> tuple[CodexRateLimitSample, ...]:
        nonlocal account_calls
        account_calls += 1
        return (_sample(),)

    service = CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_Resolver(_provider("base_url")),
        account_rate_limit_resolver=account_resolver,
    )
    await service.set_enabled(True)

    capture = await service.create_capture(env={}, command=["codex"])
    assert await capture.record_once(session_id="session-1") is False
    assert account_calls == 0


@pytest.mark.asyncio
async def test_query_stats_contains_only_quota_contract(tmp_path: Path) -> None:
    service = CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_Resolver(_provider()),
    )
    await service.set_enabled(True)
    service._store.record_rate_limit_sample(_sample())

    payload = await service.query_stats(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
    )

    assert set(payload) == {
        "range",
        "enabled",
        "time_basis",
        "available_range",
        "rate_limit_samples",
    }
    assert payload["rate_limit_samples"][0]["used_percent"] == 35
    assert "totals" not in payload
    assert "by_provider" not in payload


class _FailingStore(CodexUsageStore):
    def record_rate_limit_sample(self, _sample: CodexRateLimitSample) -> None:
        raise OSError("disk full")


@pytest.mark.asyncio
async def test_quota_write_failure_is_isolated_and_reported(tmp_path: Path) -> None:
    service = CodexUsageService(
        store=_FailingStore(tmp_path / "usage.sqlite3"),
        resolver=_Resolver(_provider()),
        account_rate_limit_resolver=lambda **_kwargs: (_sample(),),
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={}, command=["codex"])

    assert await capture.record_once(session_id="session-1") is False
    diagnostics = await service.diagnostics_async()
    assert diagnostics["write_failure_count"] == 1
    assert diagnostics["last_error_code"] == "write_failed"
