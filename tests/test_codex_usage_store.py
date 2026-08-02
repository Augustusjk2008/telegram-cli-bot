from __future__ import annotations

import asyncio
import importlib
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


def _core_modules():
    try:
        return (
            importlib.import_module("bot.codex_usage.models"),
            importlib.import_module("bot.codex_usage.store"),
            importlib.import_module("bot.codex_usage.service"),
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"Codex usage store/service 核心包尚未实现: {exc}")


def _official_provider(models):
    return models.ProviderInfo(
        key="openai_official",
        kind="openai_official",
        base_url=None,
        resolution="resolved",
    )


def _custom_provider(models, suffix: str = "one"):
    base_url = f"https://{suffix}.example/v1"
    return models.ProviderInfo(
        key=f"base_url_sha256:{suffix}",
        kind="base_url",
        base_url=base_url,
        resolution="resolved",
    )


def _usage(models, *, input_tokens: int = 100, cached_input_tokens: int = 40, output_tokens: int = 25, reasoning_output_tokens: int = 5):
    return models.CodexTokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )


def test_disabled_store_reads_and_close_are_lazy_without_creating_database(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    store = store_module.CodexUsageStore(db_path)

    assert store.get_enabled() is False
    assert store.query(date(2026, 7, 1), date(2026, 7, 31)).totals.request_count == 0
    store.close()

    assert not db_path.exists()


def test_store_initializes_schema_v2_with_model_detail_and_required_sqlite_pragmas(tmp_path: Path) -> None:
    _, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    store = store_module.CodexUsageStore(db_path)
    store.set_enabled(True)
    connection = store._connection

    assert connection is not None
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 100
    assert connection.execute("PRAGMA journal_size_limit").fetchone()[0] == 1048576
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    with sqlite3.connect(db_path) as check:
        tables = {
            row[0]: row[1]
            for row in check.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        indexes = {
            row[0]
            for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }

    assert {"settings", "providers", "daily_usage", "daily_model_usage"}.issubset(tables)
    assert "WITHOUT ROWID" in tables["settings"].upper()
    assert "WITHOUT ROWID" in tables["daily_usage"].upper()
    assert "WITHOUT ROWID" in tables["daily_model_usage"].upper()
    assert "idx_daily_usage_provider_day" in indexes
    assert "idx_daily_model_usage_provider_day" in indexes
    store.close()


def test_store_migrates_v1_provider_totals_to_default_model_without_changing_them(
    tmp_path: Path,
) -> None:
    _, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE providers (
                provider_id INTEGER PRIMARY KEY,
                provider_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                base_url TEXT
            );
            CREATE TABLE daily_usage (
                day INTEGER NOT NULL,
                provider_id INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                reasoning_output_tokens INTEGER NOT NULL,
                PRIMARY KEY (day, provider_id)
            ) WITHOUT ROWID;
            INSERT INTO providers(provider_id, provider_key, kind, base_url)
            VALUES (1, 'openai_official', 'openai_official', NULL);
            INSERT INTO daily_usage(
                day, provider_id, request_count, input_tokens,
                cached_input_tokens, output_tokens, reasoning_output_tokens
            ) VALUES (20260726, 1, 3, 1200000, 200000, 50000, 10000);
            PRAGMA user_version=1;
            """
        )

    store = store_module.CodexUsageStore(db_path)
    result = store.query(
        date(2026, 7, 26),
        date(2026, 7, 26),
        daily_page=1,
        daily_page_size=10,
    )

    assert result.totals.request_count == 3
    assert result.totals.total_tokens == 1_250_000
    assert len(result.by_provider_model) == 1
    assert result.by_provider_model[0].model == "gpt-5.6-sol"
    assert result.by_provider_model[0].totals == result.totals
    assert len(result.daily_by_provider_model) == 1
    assert result.daily_by_provider_model[0].model == "gpt-5.6-sol"
    assert result.daily_pagination is not None
    assert result.daily_pagination.total_items == 1
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()


def test_store_atomically_aggregates_daily_usage_and_derives_token_totals(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    provider = _official_provider(models)
    usage = _usage(models)

    store.record(provider, usage, terminal_at=datetime(2026, 7, 26, 23, 59, 59))
    store.record(provider, usage, terminal_at=datetime(2026, 7, 26, 23, 59, 59))
    result = store.query(date(2026, 7, 26), date(2026, 7, 26))

    assert result.totals.request_count == 2
    assert result.totals.input_tokens == 200
    assert result.totals.cached_input_tokens == 80
    assert result.totals.uncached_input_tokens == 120
    assert result.totals.output_tokens == 50
    assert result.totals.reasoning_output_tokens == 10
    assert result.totals.total_tokens == 250
    assert result.totals.cache_hit_rate == pytest.approx(0.4)
    assert len(result.by_provider) == len(result.by_day) == len(result.daily_by_provider) == 1
    assert result.daily_by_provider[0].day == date(2026, 7, 26)
    assert result.daily_by_provider[0].provider.key == "openai_official"
    store.close()


def test_store_aggregates_by_provider_and_normalized_model_without_unknown_bucket(
    tmp_path: Path,
) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    provider = _official_provider(models)

    store.record(
        provider,
        _usage(
            models,
            input_tokens=10,
            cached_input_tokens=2,
            output_tokens=3,
            reasoning_output_tokens=1,
        ),
        model_key="gpt-5.4",
        terminal_at=date(2026, 7, 26),
    )
    store.record(
        provider,
        _usage(
            models,
            input_tokens=20,
            cached_input_tokens=4,
            output_tokens=5,
            reasoning_output_tokens=1,
        ),
        model_key="unknown",
        terminal_at=date(2026, 7, 26),
    )
    result = store.query(date(2026, 7, 26), date(2026, 7, 26))

    assert result.totals.request_count == 2
    assert [(item.model, item.totals.request_count) for item in result.by_provider_model] == [
        ("gpt-5.4", 1),
        ("gpt-5.6-sol", 1),
    ]
    assert {item.model for item in result.daily_by_provider_model} == {
        "gpt-5.4",
        "gpt-5.6-sol",
    }
    store.close()


def test_store_query_paginates_daily_model_rows_in_sqlite_without_changing_full_aggregates(
    tmp_path: Path,
) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    official = _official_provider(models)
    custom = _custom_provider(models, "pagination")

    for current_day in (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)):
        store.record(
            official,
            _usage(
                models,
                input_tokens=10,
                cached_input_tokens=1,
                output_tokens=2,
                reasoning_output_tokens=0,
            ),
            model_key="official-model",
            terminal_at=current_day,
        )
        store.record(
            custom,
            _usage(
                models,
                input_tokens=20,
                cached_input_tokens=2,
                output_tokens=3,
                reasoning_output_tokens=0,
            ),
            model_key="custom-model",
            terminal_at=current_day,
        )

    connection = store._connection
    assert connection is not None
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    second_page = store.query(
        date(2026, 7, 1),
        date(2026, 7, 3),
        daily_page=2,
        daily_page_size=2,
    )
    connection.set_trace_callback(None)
    out_of_range = store.query(
        date(2026, 7, 1),
        date(2026, 7, 3),
        daily_page=4,
        daily_page_size=2,
    )
    legacy_result = store.query(date(2026, 7, 1), date(2026, 7, 3))

    assert second_page.daily_pagination is not None
    assert second_page.daily_pagination.page == 2
    assert second_page.daily_pagination.page_size == 2
    assert second_page.daily_pagination.total_items == 6
    assert second_page.daily_pagination.total_pages == 3
    assert second_page.daily_pagination.has_previous is True
    assert second_page.daily_pagination.has_next is True
    assert [
        (item.day, item.provider.key, item.model)
        for item in second_page.daily_by_provider_model
    ] == [
        (date(2026, 7, 2), official.key, "official-model"),
        (date(2026, 7, 2), custom.key, "custom-model"),
    ]
    assert second_page.totals.request_count == 6
    assert [item.totals.request_count for item in second_page.by_provider] == [3, 3]
    assert [item.totals.request_count for item in second_page.by_provider_model] == [3, 3]
    assert [item.totals.request_count for item in second_page.by_day] == [2, 2, 2]
    assert second_page.daily_by_provider == ()
    assert out_of_range.daily_by_provider_model == ()
    assert out_of_range.daily_pagination is not None
    assert out_of_range.daily_pagination.total_items == 6
    assert out_of_range.daily_pagination.total_pages == 3
    assert out_of_range.daily_pagination.has_previous is True
    assert out_of_range.daily_pagination.has_next is False
    assert legacy_result.daily_pagination is None
    assert len(legacy_result.daily_by_provider_model) == 6
    assert any(
        "DAILY_MODEL_USAGE" in statement.upper() and "COUNT(*)" in statement.upper()
        for statement in statements
    )
    assert any(
        "DAILY_MODEL_USAGE" in statement.upper()
        and re.search(r"\bLIMIT\s+2\s+OFFSET\s+2\b", statement, re.IGNORECASE)
        for statement in statements
    )
    store.close()


def test_store_rejects_daily_page_size_above_api_limit(tmp_path: Path) -> None:
    _, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")

    with pytest.raises(ValueError, match="不能超过 100"):
        store.query(
            date(2026, 7, 1),
            date(2026, 7, 1),
            daily_page=1,
            daily_page_size=101,
        )

    store.close()


def test_store_empty_pagination_preserves_requested_page_and_zero_pages(tmp_path: Path) -> None:
    _, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")

    result = store.query(
        date(2026, 7, 1),
        date(2026, 7, 1),
        daily_page=4,
        daily_page_size=10,
    )

    assert result.daily_by_provider_model == ()
    assert result.daily_pagination is not None
    assert result.daily_pagination.page == 4
    assert result.daily_pagination.total_items == 0
    assert result.daily_pagination.total_pages == 0
    assert result.daily_pagination.has_previous is True
    assert result.daily_pagination.has_next is False
    store.close()


def test_store_returns_none_cache_hit_rate_when_input_is_zero(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")

    store.record(
        _official_provider(models),
        _usage(models, input_tokens=0, cached_input_tokens=0, output_tokens=3, reasoning_output_tokens=1),
        terminal_at=date(2026, 7, 26),
    )
    result = store.query(date(2026, 7, 26), date(2026, 7, 26))

    assert result.totals.total_tokens == 3
    assert result.totals.cache_hit_rate is None
    store.close()


def test_store_queries_date_range_and_multiple_provider_keys(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")
    official = _official_provider(models)
    first = _custom_provider(models, "first")
    second = _custom_provider(models, "second")

    store.record(official, _usage(models, input_tokens=10, cached_input_tokens=1), terminal_at=date(2026, 7, 1))
    store.record(first, _usage(models, input_tokens=20, cached_input_tokens=2), terminal_at=date(2026, 7, 2))
    store.record(second, _usage(models, input_tokens=30, cached_input_tokens=3), terminal_at=date(2026, 7, 3))

    result = store.query(
        date(2026, 7, 1),
        date(2026, 7, 3),
        provider_keys=[official.key, second.key],
    )

    assert result.totals.request_count == 2
    assert result.totals.input_tokens == 40
    assert [item.provider.key for item in result.by_provider] == [official.key, second.key]
    assert store.available_range() == (date(2026, 7, 1), date(2026, 7, 3))
    assert {item.key for item in store.list_providers()} == {official.key, first.key, second.key}
    store.close()


def test_store_serializes_concurrent_writers_and_keeps_one_daily_row(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    store = store_module.CodexUsageStore(db_path)
    provider = _official_provider(models)
    usage = _usage(models, input_tokens=1, cached_input_tokens=0, output_tokens=1, reasoning_output_tokens=0)
    workers = 8
    writes_per_worker = 50
    start = threading.Event()

    def write_many() -> None:
        start.wait()
        for _ in range(writes_per_worker):
            store.record(provider, usage, terminal_at=date(2026, 7, 26))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(write_many) for _ in range(workers)]
        start.set()
        for future in futures:
            future.result()

    result = store.query(date(2026, 7, 26), date(2026, 7, 26))
    with sqlite3.connect(db_path) as connection:
        daily_rows = connection.execute("SELECT COUNT(*) FROM daily_usage").fetchone()[0]

    assert result.totals.request_count == workers * writes_per_worker
    assert daily_rows == 1
    store.close()


def test_store_closes_connection_when_schema_initialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store_module, _ = _core_modules()
    real_connect = sqlite3.connect
    opened_connections: list[sqlite3.Connection] = []

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened_connections.append(connection)
        return connection

    def fail_schema(_connection: sqlite3.Connection) -> None:
        raise RuntimeError("unsupported schema")

    monkeypatch.setattr(store_module.sqlite3, "connect", tracking_connect)
    monkeypatch.setattr(
        store_module.CodexUsageStore,
        "_ensure_schema",
        staticmethod(fail_schema),
    )
    store = store_module.CodexUsageStore(tmp_path / "usage.sqlite3")

    with pytest.raises(RuntimeError, match="unsupported schema"):
        store.set_enabled(True)

    assert len(opened_connections) == 1
    connection = opened_connections[0]
    try:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


def test_ten_thousand_writes_stay_in_one_daily_provider_row(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    store = store_module.CodexUsageStore(db_path)
    provider = _official_provider(models)
    usage = _usage(models, input_tokens=1, cached_input_tokens=0, output_tokens=0, reasoning_output_tokens=0)

    for _ in range(10_000):
        store.record(provider, usage, terminal_at=date(2026, 7, 26))

    with sqlite3.connect(db_path) as connection:
        row_count, request_count = connection.execute(
            "SELECT COUNT(*), SUM(request_count) FROM daily_usage"
        ).fetchone()

    assert row_count == 1
    assert request_count == 10_000
    store.close()


def test_enabled_setting_and_usage_survive_close_and_reopen(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    provider = _official_provider(models)
    first = store_module.CodexUsageStore(db_path)
    first.set_enabled(True)
    first.record(provider, _usage(models), terminal_at=date(2026, 7, 26))
    first.close()

    second = store_module.CodexUsageStore(db_path)
    assert second.get_enabled() is True
    assert second.query(date(2026, 7, 26), date(2026, 7, 26)).totals.request_count == 1
    second.set_enabled(False)
    assert second.get_enabled() is False
    assert second.query(date(2026, 7, 26), date(2026, 7, 26)).totals.request_count == 1
    second.close()


class _StaticResolver:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.calls = 0

    def resolve(self, *, env=None, argv=()):
        self.calls += 1
        return self.provider


def test_codex_model_resolution_uses_effective_override_and_never_returns_unknown() -> None:
    _, _, service_module = _core_modules()

    assert service_module.resolve_codex_model(None) == "gpt-5.6-sol"
    assert service_module.resolve_codex_model(["codex", "exec", "--model", "unknown"]) == "gpt-5.6-sol"
    assert service_module.resolve_codex_model(["codex", "exec", "-m", "gpt-5.6-pro"]) == "gpt-5.6-pro"
    assert service_module.resolve_codex_model(
        ["codex", "exec", "--model", "gpt-5.4", "-c", 'model="gpt-5.6-sol"']
    ) == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_service_skips_provider_io_and_database_creation_while_disabled(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    resolver = _StaticResolver(_official_provider(models))
    service = service_module.CodexUsageService(db_path=db_path, resolver=resolver)

    capture = await service.create_capture(env={"CODEX_HOME": str(tmp_path / "codex")}, argv=("codex", "exec"))

    assert capture.enabled is False
    assert resolver.calls == 0
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is False
    await service.aclose()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_service_snapshots_enabled_and_provider_then_records_once(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    resolver = _StaticResolver(_official_provider(models))
    service = service_module.CodexUsageService(db_path=db_path, resolver=resolver)
    await service.set_enabled(True)

    capture = await service.create_capture(argv=("codex", "exec"))
    resolver.provider = _custom_provider(models, "changed-after-start")
    await service.set_enabled(False)

    assert capture.enabled is True
    assert capture.provider.key == "openai_official"
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is True
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is False
    result = await service.query(date(2026, 7, 26), date(2026, 7, 26))
    diagnostics = await service.diagnostics()

    assert result.totals.request_count == 1
    assert diagnostics["write_count"] == 1
    assert diagnostics["duplicate_terminal_count"] == 1
    assert diagnostics["enabled"] is False
    await service.aclose()


@pytest.mark.asyncio
async def test_service_persists_enabled_setting_across_instances(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    first = service_module.CodexUsageService(db_path=db_path, resolver=_StaticResolver(_official_provider(models)))
    await first.set_enabled(True)
    await first.aclose()

    second = service_module.CodexUsageService(db_path=db_path, resolver=_StaticResolver(_official_provider(models)))
    assert await second.get_enabled() is True
    await second.aclose()


@pytest.mark.asyncio
async def test_service_uses_to_thread_for_sqlite_and_provider_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models, _, service_module = _core_modules()
    calls: list[str] = []

    async def immediate_to_thread(function, /, *args, **kwargs):
        calls.append(getattr(function, "__name__", type(function).__name__))
        return function(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", immediate_to_thread)
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.get_enabled()
    await service.set_enabled(True)
    capture = await service.create_capture()
    await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26))
    await service.query(date(2026, 7, 26), date(2026, 7, 26))
    await service.diagnostics_async()
    await service.aclose()

    assert "get_enabled" in calls
    assert "set_enabled" in calls
    assert "resolve" in calls
    assert "record" in calls
    assert "query" in calls
    assert "close" in calls


@pytest.mark.asyncio
async def test_service_keeps_capture_callers_safe_when_recording_fails(tmp_path: Path) -> None:
    models, store_module, service_module = _core_modules()

    class FailingStore(store_module.CodexUsageStore):
        def record(self, provider, usage, *, model_key="gpt-5.6-sol", terminal_at=None) -> None:
            raise OSError("simulated disk failure")

    store = FailingStore(tmp_path / "usage.sqlite3")
    service = service_module.CodexUsageService(
        store=store,
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    capture = await service.create_capture()

    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is False
    diagnostics = await service.diagnostics()
    assert diagnostics["write_failure_count"] == 1
    assert diagnostics["last_error_code"] == "write_failed"
    await service.aclose()


@pytest.mark.asyncio
async def test_service_marks_invalid_usage_without_raising_to_capture_caller(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    capture = await service.create_capture()

    assert await capture.record_once(
        {
            "input_tokens": True,
            "cached_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 0,
        },
        terminal_at=date(2026, 7, 26),
    ) is False
    diagnostics = await service.diagnostics()
    assert diagnostics["invalid_usage_count"] == 1
    assert diagnostics["last_error_code"] == "invalid_usage"
    await service.aclose()


@pytest.mark.asyncio
async def test_service_records_unknown_provider_when_resolution_fails(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()

    class FailingResolver:
        def resolve(self, *, env=None, argv=()):
            raise ValueError("bad root config")

    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=FailingResolver(),
    )
    await service.set_enabled(True)
    capture = await service.create_capture()

    assert capture.enabled is True
    assert capture.provider.key == "unknown"
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is True
    diagnostics = await service.diagnostics()
    assert diagnostics["provider_resolution_failure_count"] == 1
    assert "database_path" not in diagnostics
    assert str(tmp_path.resolve()) not in repr(diagnostics)
    assert diagnostics["database_size_bytes"] > 0
    assert diagnostics["wal_size_bytes"] >= 0
    await service.aclose()


@pytest.mark.asyncio
async def test_capture_accepts_cli_usage_sample_command_and_parser_diagnostics(tmp_path: Path) -> None:
    from bot.cli import CodexTokenUsage as CliTokenUsage
    from bot.cli import CodexUsageSample

    models, _, service_module = _core_modules()
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    sample = CodexUsageSample(
        token_usage=CliTokenUsage(
            input_tokens=12,
            cached_input_tokens=2,
            output_tokens=4,
            reasoning_output_tokens=1,
        ),
        completed_at=datetime(2026, 7, 26, 23, 59, 59),
    )

    capture = await service.start_capture(
        env={"CODEX_HOME": str(tmp_path / "codex-home")},
        command=["codex", "exec", "hello"],
    )
    assert await capture.record_once(
        sample,
        invalid_usage_count=2,
        duplicate_terminal_count=3,
    ) is True
    result = await service.query(date(2026, 7, 26), date(2026, 7, 26))
    diagnostics = await service.diagnostics()

    assert result.totals.input_tokens == 12
    assert result.totals.cached_input_tokens == 2
    assert result.totals.output_tokens == 4
    assert diagnostics["invalid_usage_count"] == 2
    assert diagnostics["duplicate_terminal_count"] == 3
    await service.aclose()


@pytest.mark.asyncio
async def test_capture_uses_rollout_only_for_explicit_failed_turn_and_snapshots_model(
    tmp_path: Path,
) -> None:
    models, _, service_module = _core_modules()
    resolver_calls: list[tuple[str, datetime, Path]] = []

    def failed_usage_resolver(*, session_id: str, started_at: datetime, codex_home: Path):
        resolver_calls.append((session_id, started_at, codex_home))
        return _usage(
            models,
            input_tokens=30,
            cached_input_tokens=4,
            output_tokens=7,
            reasoning_output_tokens=2,
        )

    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
        failed_usage_resolver=failed_usage_resolver,
    )
    await service.set_enabled(True)
    codex_home = tmp_path / "codex-home"

    manual_capture = await service.create_capture(
        env={"CODEX_HOME": str(codex_home)},
        command=["codex", "exec", "--model", "unknown", "-"],
    )
    assert await manual_capture.record_once(None, failed=False, session_id="manual") is False
    assert resolver_calls == []

    failed_capture = await service.create_capture(
        env={"CODEX_HOME": str(codex_home)},
        command=["codex", "exec", "--model", "gpt-5.6-pro", "-"],
    )
    assert await failed_capture.record_once(
        None,
        failed=True,
        session_id="failed-session",
        terminal_at=date(2026, 7, 26),
    ) is True
    result = await service.query(date(2026, 7, 26), date(2026, 7, 26))

    assert len(resolver_calls) == 1
    assert resolver_calls[0][0] == "failed-session"
    assert resolver_calls[0][1].tzinfo is not None
    assert resolver_calls[0][2] == codex_home
    assert result.by_provider_model[0].model == "gpt-5.6-pro"
    assert result.totals.total_tokens == 37
    await service.aclose()


@pytest.mark.asyncio
async def test_capture_record_once_is_concurrent_safe(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    capture = await service.create_capture()

    results = await asyncio.gather(
        *[
            capture.record_once(_usage(models), terminal_at=date(2026, 7, 26))
            for _ in range(10)
        ]
    )
    stats = await service.query(date(2026, 7, 26), date(2026, 7, 26))
    diagnostics = await service.diagnostics()

    assert results.count(True) == 1
    assert results.count(False) == 9
    assert stats.totals.request_count == 1
    assert diagnostics["duplicate_terminal_count"] == 9
    await service.aclose()


@pytest.mark.asyncio
async def test_service_exposes_admin_config_and_stats_views(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    provider = _custom_provider(models, "admin")
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(provider),
    )

    config = await service.update_enabled(True)
    capture = await service.start_capture(command=["codex", "exec"])
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is True
    stats = await service.query_stats(
        start_date=date(2026, 7, 26),
        end_date=date(2026, 7, 26),
        provider_keys=[provider.key],
    )
    updated_config = await service.update_enabled(False)

    assert config["enabled"] is True
    assert config["current_provider"]["key"] == provider.key
    assert stats["range"] == {"start_date": "2026-07-26", "end_date": "2026-07-26"}
    assert stats["selected_provider_keys"] == [provider.key]
    assert stats["totals"]["request_count"] == 1
    assert stats["by_provider"][0]["provider"]["base_url"] == provider.base_url
    assert stats["by_provider_model"][0]["model"] == "gpt-5.6-sol"
    assert stats["daily_by_provider"] == []
    assert stats["daily_by_provider_model"][0]["model"] == "gpt-5.6-sol"
    assert stats["daily_pagination"] == {
        "page": 1,
        "page_size": 10,
        "total_items": 1,
        "total_pages": 1,
        "has_previous": False,
        "has_next": False,
    }
    assert updated_config["enabled"] is False
    await service.aclose()


@pytest.mark.asyncio
async def test_service_stats_defaults_daily_model_detail_to_ten_rows(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    provider = _official_provider(models)
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(provider),
    )
    for day in range(1, 12):
        service._store.record(
            provider,
            _usage(
                models,
                input_tokens=day,
                cached_input_tokens=0,
                output_tokens=1,
                reasoning_output_tokens=0,
            ),
            model_key=f"model-{day:02d}",
            terminal_at=date(2026, 7, day),
        )

    stats = await service.query_stats(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 11),
        provider_keys=[provider.key],
    )

    assert stats["totals"]["request_count"] == 11
    assert len(stats["by_day"]) == 11
    assert stats["daily_by_provider"] == []
    assert [item["date"] for item in stats["daily_by_provider_model"]] == [
        f"2026-07-{day:02d}" for day in range(11, 1, -1)
    ]
    assert stats["daily_pagination"] == {
        "page": 1,
        "page_size": 10,
        "total_items": 11,
        "total_pages": 2,
        "has_previous": False,
        "has_next": True,
    }
    await service.aclose()


def test_store_uses_weighted_cache_rate_and_only_real_day_provider_combinations(tmp_path: Path) -> None:
    models, store_module, _ = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    store = store_module.CodexUsageStore(db_path)
    official = _official_provider(models)
    custom = _custom_provider(models, "weighted")

    store.record(
        official,
        _usage(models, input_tokens=100, cached_input_tokens=10, output_tokens=1, reasoning_output_tokens=0),
        terminal_at=date(2026, 7, 25),
    )
    store.record(
        official,
        _usage(models, input_tokens=10, cached_input_tokens=9, output_tokens=1, reasoning_output_tokens=0),
        terminal_at=date(2026, 7, 26),
    )
    store.record(
        custom,
        _usage(models, input_tokens=10, cached_input_tokens=0, output_tokens=1, reasoning_output_tokens=0),
        terminal_at=date(2026, 7, 26),
    )

    result = store.query(date(2026, 7, 25), date(2026, 7, 26))
    with sqlite3.connect(db_path) as connection:
        daily_row_count = connection.execute("SELECT COUNT(*) FROM daily_usage").fetchone()[0]

    assert daily_row_count == 3
    assert result.totals.cache_hit_rate == pytest.approx(19 / 120)
    assert [item.day for item in result.by_day] == [date(2026, 7, 25), date(2026, 7, 26)]
    assert [item.provider.kind for item in result.by_provider] == ["openai_official", "base_url"]
    store.close()


@pytest.mark.asyncio
async def test_service_config_and_diagnostics_are_lazy_when_never_enabled(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    service = service_module.CodexUsageService(
        db_path=db_path,
        resolver=_StaticResolver(_official_provider(models)),
    )

    config = await service.config_snapshot()
    diagnostics = await service.diagnostics()
    await service.aclose()

    assert config["enabled"] is False
    assert config["available_range"] == {"first_date": None, "last_date": None}
    assert {
        "enabled",
        "write_count",
        "write_failure_count",
        "invalid_usage_count",
        "duplicate_terminal_count",
        "provider_resolution_failure_count",
        "last_write_at",
        "last_error_code",
        "database_size_bytes",
        "wal_size_bytes",
    }.issubset(diagnostics)
    assert "database_path" not in diagnostics
    assert str(tmp_path.resolve()) not in repr(diagnostics)
    assert diagnostics["database_size_bytes"] == 0
    assert diagnostics["wal_size_bytes"] == 0
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_failed_capture_write_is_never_retried_by_the_same_capture(tmp_path: Path) -> None:
    models, store_module, service_module = _core_modules()

    class FailingStore(store_module.CodexUsageStore):
        def __init__(self, db_path: Path) -> None:
            super().__init__(db_path)
            self.record_calls = 0

        def record(self, provider, usage, *, model_key="gpt-5.6-sol", terminal_at=None) -> None:
            self.record_calls += 1
            raise OSError("simulated lock failure")

    store = FailingStore(tmp_path / "usage.sqlite3")
    service = service_module.CodexUsageService(
        store=store,
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    capture = await service.create_capture()

    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is False
    assert await capture.record_once(_usage(models), terminal_at=date(2026, 7, 26)) is False
    diagnostics = await service.diagnostics()

    assert store.record_calls == 1
    assert diagnostics["write_failure_count"] == 1
    assert diagnostics["duplicate_terminal_count"] == 1
    await service.aclose()


@pytest.mark.asyncio
async def test_invalid_usage_variants_never_write_a_daily_row(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    service = service_module.CodexUsageService(
        db_path=tmp_path / "usage.sqlite3",
        resolver=_StaticResolver(_official_provider(models)),
    )
    await service.set_enabled(True)
    invalid_samples = [
        {"cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0},
        {"input_tokens": -1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0},
        {"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1, "reasoning_output_tokens": 0},
        {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 2},
    ]

    for invalid_sample in invalid_samples:
        capture = await service.create_capture()
        assert await capture.record_once(invalid_sample, terminal_at=date(2026, 7, 26)) is False

    result = await service.query(date(2026, 7, 26), date(2026, 7, 26))
    diagnostics = await service.diagnostics()
    assert result.totals.request_count == 0
    assert diagnostics["invalid_usage_count"] == len(invalid_samples)
    await service.aclose()


@pytest.mark.asyncio
async def test_singleton_uses_runtime_db_path_without_opening_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.codex_usage as codex_usage
    from bot.runtime_paths import get_codex_usage_db_path

    await codex_usage.close_codex_usage_service()
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "runtime-data"))
    expected_path = get_codex_usage_db_path()
    service = codex_usage.get_codex_usage_service()

    assert service.db_path == expected_path.resolve()
    assert not expected_path.exists()
    await codex_usage.close_codex_usage_service()
    assert not expected_path.exists()


def test_service_exposes_a_synchronous_runtime_diagnostics_snapshot(tmp_path: Path) -> None:
    models, _, service_module = _core_modules()
    db_path = tmp_path / "usage.sqlite3"
    service = service_module.CodexUsageService(
        db_path=db_path,
        resolver=_StaticResolver(_official_provider(models)),
    )

    snapshot = service.diagnostics()

    assert isinstance(snapshot, dict)
    assert snapshot["enabled"] is False
    assert snapshot["database_size_bytes"] == 0
    assert not db_path.exists()
