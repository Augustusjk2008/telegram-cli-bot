from __future__ import annotations

import os

import pytest

from bot import config
from bot.model_pricing import DEFAULT_PRICES_PATH, estimate_usage_cost
from bot.native_agent.context_usage import PiTurnCost


@pytest.fixture
def price_file(tmp_path, monkeypatch):
    path = tmp_path / "prices.csv"
    path.write_text(
        "model,currency,input_per_million,cache_read_per_million,cache_write_per_million,output_per_million,cache_write_1h_per_million\n"
        "test-model,USD,2,0.2,2.5,10,4\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(path))
    return path


def test_codex_prices_cumulative_snapshot_without_double_charging_cache_or_reasoning(price_file):
    usage = dict(input_tokens=1_000_000, cached_input_tokens=600_000, cache_write_input_tokens=100_000,
                 output_tokens=100_000, reasoning_output_tokens=80_000)
    cost = estimate_usage_cost("test-model", usage, protocol="codex", scope="session")
    assert cost == dict(model="test-model", currency="USD", scope="session",
                        input=0.6, cache_read=0.12, cache_write=0.25, output=1.0, total=1.97)
    # 连续保存同一累计快照不产生计价器自身的累计或差分。
    assert estimate_usage_cost("test-model", usage, protocol="codex", scope="session") == cost


def test_claude_prices_disjoint_cache_and_both_write_lifetimes(price_file):
    cost = estimate_usage_cost("test-model", {
        "input_tokens": 100_000, "output_tokens": 10_000,
        "cache_read_input_tokens": 300_000, "cache_creation_input_tokens": 200_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 150_000, "ephemeral_1h_input_tokens": 50_000},
    }, protocol="claude", scope="turn")
    assert cost["input"] == 0.2
    assert cost["cache_write"] == 0.575
    assert cost["total"] == 0.935


@pytest.mark.parametrize("usage", [
    {"input_tokens": 3},
    {"input_tokens": True, "output_tokens": 1},
    {"input_tokens": 3, "output_tokens": -1},
    {"input_tokens": 3, "output_tokens": float("nan")},
    {"input_tokens": 3, "output_tokens": 1, "cached_input_tokens": 4},
])
def test_incomplete_or_invalid_usage_has_no_estimate(price_file, usage):
    assert estimate_usage_cost("test-model", usage, protocol="codex", scope="session") is None


def test_price_edits_apply_to_new_snapshots_only_and_missing_models_are_skipped(price_file):
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    before = estimate_usage_cost("test-model", usage, protocol="codex", scope="session")
    old_stat = price_file.stat()
    price_file.write_text(price_file.read_text(encoding="utf-8-sig").replace(",USD,2,", ",USD,3,"), encoding="utf-8")
    os.utime(price_file, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000))
    assert estimate_usage_cost("test-model", usage, protocol="codex", scope="session")["total"] == 3
    assert before["total"] == 2
    assert estimate_usage_cost("missing", usage, protocol="codex", scope="session") is None
    price_file.unlink()
    assert estimate_usage_cost("test-model", usage, protocol="codex", scope="session") is None


@pytest.mark.parametrize("row", [
    "test-model,USD,NaN,0.2,2.5,10,4\n",
    "test-model,USD,-2,0.2,2.5,10,4\n",
    "test-model,USD,1e999999,0.2,2.5,10,4\n",
    "test-model,USD,2,0.2,2.5,10,4\ntest-model,USD,3,0.2,2.5,10,4\n",
])
def test_bad_price_table_does_not_break_chat(price_file, row):
    header = price_file.read_text(encoding="utf-8-sig").splitlines()[0]
    price_file.write_text(header + "\n" + row, encoding="utf-8")
    assert estimate_usage_cost("test-model", {"input_tokens": 1000, "output_tokens": 1},
                               protocol="codex", scope="session") is None


def test_pi_counts_finished_calls_once_and_skips_incomplete_turns(price_file):
    turn = PiTurnCost("provider/test-model")
    message = {"role": "assistant", "id": "first", "usage": {
        "input": 100_000, "cacheRead": 300_000, "cacheWrite": 0, "output": 10_000,
    }}
    turn.observe({"type": "message_update", "message": message})
    assert turn.estimate() is None
    turn.observe({"type": "message_end", "message": message})
    turn.observe({"type": "message_end", "message": message})
    turn.observe({"type": "message_end", "message": {"role": "toolResult"}})
    turn.observe({"type": "message_end", "message": {**message, "id": "second"}})
    assert turn.estimate()["total"] == 0.72
    assert turn.estimate()["scope"] == "turn"
    assert turn.estimate(usage_complete=False) is None
    turn.observe({"type": "message_end", "message": {"role": "assistant", "id": "third"}})
    assert turn.estimate() is None


@pytest.mark.parametrize("provider", ["custom", None])
def test_pi_prefers_provider_specific_price(price_file, provider):
    with price_file.open("a", encoding="utf-8") as file:
        file.write("custom/test-model,USD,30,0.2,2.5,10,4\n")
    turn = PiTurnCost("custom/test-model")
    turn.observe({"type": "message_end", "message": {
        "role": "assistant", "model": "test-model", "provider": provider,
        "usage": {"input": 1_000_000, "output": 0},
    }})
    assert turn.estimate()["model"] == "custom/test-model"
    assert turn.estimate()["total"] == 30


def test_default_csv_is_usable_and_small_charges_remain_visible(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(DEFAULT_PRICES_PATH))
    cost = estimate_usage_cost("gpt-5.4", {"input_tokens": 1, "output_tokens": 0},
                               protocol="codex", scope="session")
    assert cost["currency"] == "USD"
    assert 0 < cost["total"] < 0.00001
