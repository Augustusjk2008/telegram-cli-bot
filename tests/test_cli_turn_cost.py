from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot import config
from bot.model_pricing import estimate_usage_cost
from bot.web import cli_turn_cost
from bot.web.cli_turn_cost import CliTurnCost


@pytest.fixture(autouse=True)
def prices(tmp_path, monkeypatch):
    path = tmp_path / "prices.csv"
    path.write_text(
        "model,currency,input_per_million,cache_read_per_million,cache_write_per_million,output_per_million\n"
        "test-model,USD,2,0.2,2.5,10\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(path))


def rollout_event(time, kind, **payload):
    return {"type": "event_msg", "timestamp": f"2026-09-08T08:{time}Z", "payload": {"type": kind, **payload}}


def token_event(time, input_tokens, output_tokens, cached_input_tokens=0):
    return rollout_event(time, "token_count", info={"total_token_usage": {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "cached_input_tokens": cached_input_tokens,
    }})


def codex_turn(tmp_path, monkeypatch, events):
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events) + '\n{"unfinished":', encoding="utf-8")
    monkeypatch.setattr(cli_turn_cost, "locate_codex_transcript", lambda _session: SimpleNamespace(path=path))
    turn = CliTurnCost("codex", "test-model")
    turn.started_at = datetime(2026, 9, 8, 8, 1, tzinfo=timezone.utc)
    return turn


def test_codex_partial_cost_is_scoped_to_current_turn_and_deduplicates_totals(tmp_path, monkeypatch):
    turn = codex_turn(tmp_path, monkeypatch, [
        rollout_event("00:00", "task_started"), token_event("00:01", 1000, 100, 200),
        rollout_event("01:00", "task_started"), token_event("01:01", 1000, 100, 200),
        token_event("01:02", 2000, 200, 700), token_event("01:03", 2000, 200, 700),
        token_event("01:04", 3000, 300, 1200),
        rollout_event("02:00", "task_started"), token_event("02:01", 9000, 900, 5000),
    ])
    expected = estimate_usage_cost("test-model", {
        "input_tokens": 2000, "output_tokens": 200, "cached_input_tokens": 1000,
    }, protocol="codex", scope="turn")
    assert turn.estimate_partial("session") == {**expected, "is_partial": True}


@pytest.mark.parametrize("current_events", [
    [],
    [rollout_event("01:00", "task_started")],
    [rollout_event("01:00", "task_started"), token_event("01:01", 1000, 100)],
    [rollout_event("01:00", "task_started"), token_event("01:01", 2000, "invalid")],
])
def test_codex_missing_current_usage_never_charges_previous_turn(tmp_path, monkeypatch, current_events):
    turn = codex_turn(tmp_path, monkeypatch, [
        rollout_event("00:00", "task_started"), token_event("00:01", 1000, 100), *current_events,
    ])
    assert turn.estimate_partial("session") is None


def test_codex_counter_reset_keeps_only_reliable_deltas(tmp_path, monkeypatch):
    turn = codex_turn(tmp_path, monkeypatch, [
        token_event("00:01", 1000, 100), rollout_event("01:00", "task_started"),
        token_event("01:01", 2000, 200), token_event("01:02", 0, 0), token_event("01:03", 1000, 100),
    ])
    assert turn.estimate_partial("session")["total"] == 0.006


def test_claude_partial_cost_uses_message_snapshots_and_skips_unpriced_usage():
    turn = CliTurnCost("claude", "test-model")
    assert turn.estimate_partial("") is None
    usage = {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 500}

    def observe(message_id, tokens=usage, **extra):
        turn.observe(json.dumps({"type": "assistant", "message": {
            "id": message_id, "model": "test-model", "usage": tokens,
        }, **extra}))

    observe("first", {**usage, "output_tokens": 50})
    observe("first")
    observe("first")
    observe("child", parent_tool_use_id="tool")
    observe("second")
    observe("invalid", {"input_tokens": 1000})
    cost = turn.estimate_partial("")
    assert cost["total"] == 0.0062
    assert cost["is_partial"] is True
    assert CliTurnCost("claude", "test-model").estimate_partial("") is None


def test_claude_missing_or_unpriced_usage_is_not_reported_as_zero():
    turn = CliTurnCost("claude", "unknown-model")
    for usage in [{}, {"input_tokens": 1000}, {"input_tokens": 1000, "output_tokens": 100}]:
        turn.observe(json.dumps({"type": "assistant", "message": {"id": "message", "usage": usage}}))
        assert turn.estimate_partial("") is None
