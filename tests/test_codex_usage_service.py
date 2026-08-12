from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from bot.codex_usage import models
from bot.codex_usage.models import CodexTokenUsage, ProviderInfo
from bot.codex_usage.service import CodexUsageService
from bot.codex_usage.store import CodexUsageStore


class _ProviderResolver:
    def __init__(self, provider: ProviderInfo) -> None:
        self.provider = provider
        self.calls = 0

    def resolve(self, **_kwargs: object) -> ProviderInfo:
        self.calls += 1
        return self.provider


class _RateLimitResolver:
    def __init__(self, result: object | None) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object | None:
        self.calls.append(kwargs)
        return self.result


def _provider(kind: str = "openai_official") -> ProviderInfo:
    if kind == "base_url":
        return ProviderInfo(
            key="custom:https://example.test",
            kind="base_url",
            base_url="https://example.test",
        )
    return ProviderInfo(key=kind, kind=kind, base_url=None)


def _sample() -> object:
    return models.CodexRateLimitSample(
        sampled_at=datetime(2026, 8, 11, 4, 57, 53, 123_000, tzinfo=timezone.utc),
        used_percent=8,
        window_minutes=10_080,
        resets_at=datetime(2026, 8, 18, 0, 1, 25, tzinfo=timezone.utc),
        plan_type="pro",
    )


@pytest.mark.asyncio
async def test_disabled_capture_does_not_resolve_or_record_rate_limit(tmp_path: Path) -> None:
    provider_resolver = _ProviderResolver(_provider())
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=provider_resolver,
        rate_limit_resolver=rate_limit_resolver,
    )

    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})
    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    )

    assert recorded is False
    assert provider_resolver.calls == 0
    assert rate_limit_resolver.calls == []
    assert not (tmp_path / "usage.sqlite3").exists()


@pytest.mark.asyncio
async def test_official_capture_records_one_rate_limit_sample(tmp_path: Path) -> None:
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=rate_limit_resolver,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    first = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        terminal_at=date(2026, 8, 11),
        session_id=" session-1 ",
    )
    second = await capture.record_once(
        CodexTokenUsage(input_tokens=9, output_tokens=9),
        session_id="session-1",
    )
    result = await service.query(date(2026, 8, 11), date(2026, 8, 11))

    assert first is True
    assert second is False
    assert len(rate_limit_resolver.calls) == 1
    assert rate_limit_resolver.calls[0]["session_id"] == "session-1"
    assert result.totals.request_count == 1
    assert result.rate_limit_samples == (_sample(),)


@pytest.mark.asyncio
async def test_spark_capture_excludes_general_rate_limit(tmp_path: Path) -> None:
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=rate_limit_resolver,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(
        env={"CODEX_HOME": str(tmp_path)},
        argv=["codex", "exec", "--model", "gpt-5.3-codex-spark"],
    )

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        terminal_at=date(2026, 8, 11),
        session_id="session-1",
    )
    result = await service.query(date(2026, 8, 11), date(2026, 8, 11))

    assert capture.model == "gpt-5.3-codex-spark"
    assert recorded is True
    assert [item.model for item in result.by_provider_model] == ["gpt-5.3-codex-spark"]
    assert rate_limit_resolver.calls == []
    assert result.rate_limit_samples == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["base_url", "unknown"])
async def test_non_official_capture_does_not_resolve_rate_limit(
    tmp_path: Path,
    kind: str,
) -> None:
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / f"{kind}.sqlite3",
        resolver=_ProviderResolver(_provider(kind)),
        rate_limit_resolver=rate_limit_resolver,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    assert await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    ) is True
    assert rate_limit_resolver.calls == []


@pytest.mark.asyncio
async def test_official_capture_records_rate_limit_without_token_usage(tmp_path: Path) -> None:
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
        failed_usage_resolver=lambda **_kwargs: None,
        rate_limit_resolver=rate_limit_resolver,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    recorded = await capture.record_once(None, failed=True, session_id="session-1")
    result = await service.query(date(2026, 8, 11), date(2026, 8, 11))

    assert recorded is False
    assert len(rate_limit_resolver.calls) == 1
    assert result.totals.request_count == 0
    assert result.rate_limit_samples == (_sample(),)


@pytest.mark.asyncio
async def test_spark_only_rate_limit_result_is_not_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from bot.web import native_history_locator

    rollout = tmp_path / "rollout.jsonl"
    events = [
        {
            "timestamp": "2026-08-11T02:00:01Z",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": "2026-08-11T02:00:02Z",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "limit_id": "codex_bengalfox",
                    "primary": {
                        "used_percent": 10,
                        "window_minutes": 300,
                        "resets_at": 1_787_011_285,
                    },
                    "plan_type": "pro",
                },
            },
        },
    ]
    rollout.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        native_history_locator,
        "locate_codex_transcript",
        lambda *_args, **_kwargs: SimpleNamespace(path=rollout),
    )
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})
    capture.started_at = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    )
    rollout_day = datetime(2026, 8, 11, 2, 0, 2, tzinfo=timezone.utc).astimezone().date()
    result = await service.query(rollout_day, rollout_day)

    assert recorded is True
    assert result.rate_limit_samples == ()


@pytest.mark.asyncio
async def test_rate_limit_resolution_failure_does_not_affect_token_recording(
    tmp_path: Path,
) -> None:
    def fail_rate_limit(**_kwargs: object) -> None:
        raise RuntimeError("rollout failed")

    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=fail_rate_limit,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    )
    result = await service.query(date.today(), date.today())

    assert recorded is True
    assert result.totals.request_count == 1
    assert result.rate_limit_samples == ()


class _FailingRateLimitStore(CodexUsageStore):
    def record_rate_limit_sample(self, _sample: object) -> None:
        raise RuntimeError("rate limit write failed")


class _FailingTokenStore(CodexUsageStore):
    def record(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("token write failed")


@pytest.mark.asyncio
async def test_rate_limit_write_failure_does_not_affect_token_recording(
    tmp_path: Path,
) -> None:
    store = _FailingRateLimitStore(tmp_path / "usage.sqlite3")
    service = CodexUsageService(
        store=store,
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=_RateLimitResolver(_sample()),
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    )
    result = await service.query(date.today(), date.today())

    assert recorded is True
    assert result.totals.request_count == 1


@pytest.mark.asyncio
async def test_blank_session_id_records_tokens_without_resolving_rate_limit(
    tmp_path: Path,
) -> None:
    rate_limit_resolver = _RateLimitResolver(_sample())
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=rate_limit_resolver,
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id=" \t ",
    )
    result = await service.query(date.today(), date.today())

    assert recorded is True
    assert result.totals.request_count == 1
    assert rate_limit_resolver.calls == []


@pytest.mark.asyncio
async def test_token_write_failure_still_records_rate_limit_sample(tmp_path: Path) -> None:
    store = _FailingTokenStore(tmp_path / "usage.sqlite3")
    service = CodexUsageService(
        store=store,
        resolver=_ProviderResolver(_provider()),
        rate_limit_resolver=_RateLimitResolver(_sample()),
    )
    await service.set_enabled(True)
    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path)})

    recorded = await capture.record_once(
        CodexTokenUsage(input_tokens=2, output_tokens=1),
        session_id="session-1",
    )
    sample_day = _sample().sampled_at.astimezone().date()
    result = await service.query(sample_day, sample_day)

    assert recorded is False
    assert result.totals.request_count == 0
    assert result.rate_limit_samples == (_sample(),)


@pytest.mark.asyncio
async def test_query_stats_returns_local_rate_limit_payload(tmp_path: Path) -> None:
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider()),
    )
    service._store.record_rate_limit_sample(_sample())

    payload = await service.query_stats(
        start_date=date(2026, 8, 11),
        end_date=date(2026, 8, 11),
    )

    assert payload["rate_limit_samples"] == [
        {
            "sampled_at": _sample().sampled_at.astimezone().isoformat(),
            "used_percent": 8.0,
            "window_minutes": 10_080,
            "resets_at": _sample().resets_at.astimezone().isoformat(),
            "plan_type": "pro",
        }
    ]


@pytest.mark.asyncio
async def test_query_stats_can_filter_official_when_only_rate_limit_data_exists(
    tmp_path: Path,
) -> None:
    service = CodexUsageService(
        tmp_path / "usage.sqlite3",
        resolver=_ProviderResolver(_provider("base_url")),
    )
    service._store.record_rate_limit_sample(_sample())

    payload = await service.query_stats(
        start_date=date(2026, 8, 11),
        end_date=date(2026, 8, 11),
        provider_keys=["openai_official"],
    )

    assert payload["selected_provider_keys"] == ["openai_official"]
    assert len(payload["rate_limit_samples"]) == 1
    assert any(
        provider["key"] == "openai_official"
        for provider in payload["available_providers"]
    )
