from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bot.cli import ClaudeJsonStreamParser
from bot.codex_usage.claude_rate_limits import (
    ClaudeAuthStatus,
    ClaudeAuthStatusReader,
    samples_from_rate_limit_info,
)
from bot.codex_usage.service import CodexUsageService
from bot.codex_usage.store import CodexUsageStore


# Shape captured from Claude Code 2.1.318 `--output-format stream-json --verbose`.
_RATE_LIMIT_EVENT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1793900400,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "isUsingOverage": False,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.01, "resetsAt": 1793900400, "status": "allowed"},
            "seven_day": {"utilization": 0.02, "resetsAt": 1793941200, "status": "allowed"},
        },
    },
    "uuid": "23cb254d-6200-4a86-9039-17bee656dc6e",
    "session_id": "1fd7a353-2c7a-41f5-844c-dd38c35d469f",
}
_SAMPLED_AT = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
_SUBSCRIPTION = ClaudeAuthStatus(
    logged_in=True,
    auth_method="claude.ai",
    api_provider="firstParty",
    subscription_type="max",
)


class _AuthReader:
    def __init__(self, status: ClaudeAuthStatus | None) -> None:
        self.status = status
        self.calls: list[str] = []

    def read(self, *, executable, env):
        self.calls.append(executable)
        return self.status

    def cached(self):
        return self.status


def _parsed_stream(*events: dict):
    parser = ClaudeJsonStreamParser(raw_tail_max_bytes=4096, final_text_max_bytes=4096)
    for event in events:
        parser.consume_line(json.dumps(event) + "\n")
    return parser.result()


def test_unified_windows_convert_fraction_utilization_to_percent_samples():
    info = {
        "unifiedWindows": {
            **_RATE_LIMIT_EVENT["rate_limit_info"]["unifiedWindows"],
            "seven_day_overage_included": {"utilization": 1.3, "resetsAt": 1793941200},
            "unknown_window": {"utilization": 0.5, "resetsAt": 1793941200},
        },
    }

    samples = samples_from_rate_limit_info(info, sampled_at=_SAMPLED_AT, plan_type="max")

    assert [(s.limit_id, s.window_minutes, s.used_percent) for s in samples] == [
        ("claude", 300, 1.0),
        ("claude", 10080, 2.0),
        # Utilization may legitimately exceed 1; the stored percentage is capped.
        ("claude_overage_included", 10080, 100.0),
    ]
    assert samples[1].resets_at == datetime.fromtimestamp(1793941200, timezone.utc)
    assert {s.plan_type for s in samples} == {"max"}
    assert samples_from_rate_limit_info(
        {"unifiedWindows": {"seven_day": {"utilization": "0.2", "resetsAt": 1}}},
        sampled_at=_SAMPLED_AT,
    ) == ()


def test_claude_stream_parser_keeps_latest_rate_limit_event():
    later = json.loads(json.dumps(_RATE_LIMIT_EVENT))
    later["rate_limit_info"]["unifiedWindows"]["seven_day"]["utilization"] = 0.05

    result = _parsed_stream(
        {"type": "system", "subtype": "init", "session_id": "s1"},
        _RATE_LIMIT_EVENT,
        later,
        {"type": "result", "subtype": "success", "result": "ok", "session_id": "s1"},
    )

    assert result.final_text == "ok"
    assert result.rate_limit_info["unifiedWindows"]["seven_day"]["utilization"] == 0.05
    assert result.rate_limit_observed_at is not None
    assert _parsed_stream({"type": "result", "result": "ok"}).rate_limit_info is None


@pytest.mark.asyncio
async def test_claude_capture_records_subscription_windows_once(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    reader = _AuthReader(_SUBSCRIPTION)
    service = CodexUsageService(
        store=CodexUsageStore(tmp_path / "usage.sqlite3"),
        claude_auth_status_reader=reader,
    )
    await service.set_enabled(True, "claude")
    parsed = _parsed_stream(_RATE_LIMIT_EVENT)

    capture = await service.create_claude_capture(env={}, command=["/opt/claude", "-p", "hi"])
    assert await capture.record_once(parsed) is True
    assert await capture.record_once(parsed) is False

    day = parsed.rate_limit_observed_at
    weekly = await service.query(day, day, "claude")
    assert [(s.limit_id, s.used_percent, s.plan_type) for s in weekly] == [("claude", 2.0, "max")]
    assert await service.query(day, day, "codex") == ()
    assert reader.calls == ["/opt/claude"]
    service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "env", "status"),
    [
        (False, {}, _SUBSCRIPTION),
        (True, {"ANTHROPIC_BASE_URL": "https://relay.example/v1"}, _SUBSCRIPTION),
        (True, {}, ClaudeAuthStatus(True, "api_key", "firstParty", None)),
    ],
    ids=["disabled", "custom-base-url", "api-key-login"],
)
async def test_claude_capture_skips_non_subscription_sources(tmp_path, enabled, env, status):
    service = CodexUsageService(
        store=CodexUsageStore(tmp_path / "usage.sqlite3"),
        claude_auth_status_reader=_AuthReader(status),
    )
    await service.set_enabled(enabled, "claude")
    parsed = _parsed_stream(_RATE_LIMIT_EVENT)

    capture = await service.create_claude_capture(env=env, command=["claude"])

    assert await capture.record_once(parsed) is False
    assert await service.available_range("claude") == (None, None)
    service.close()


@pytest.mark.asyncio
async def test_claude_config_reports_base_url_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://Relay.Example/v1/")
    service = CodexUsageService(
        store=CodexUsageStore(tmp_path / "usage.sqlite3"),
        claude_auth_status_reader=_AuthReader(_SUBSCRIPTION),
    )

    provider = (await service.config_snapshot(provider="claude"))["current_provider"]

    assert provider["kind"] == "base_url"
    assert provider["base_url"] == "https://relay.example/v1"
    service.close()


def test_auth_status_reader_caches_and_drops_identity_fields():
    raw = json.dumps({
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "subscriptionType": "pro",
        "email": "someone@example.com",
        "orgId": "org-1",
    })
    calls: list[str] = []

    def runner(*, executable, env):
        calls.append(executable)
        return raw

    reader = ClaudeAuthStatusReader(runner=runner, clock=lambda: 100.0)

    first = reader.read(executable="claude", env={"CLAUDE_CONFIG_DIR": "/tmp/c"})
    second = reader.read(executable="claude", env={"CLAUDE_CONFIG_DIR": "/tmp/c"})

    assert first == second == ClaudeAuthStatus(True, "claude.ai", "firstParty", "pro")
    assert calls == ["claude"]
    assert "example.com" not in repr(first)
