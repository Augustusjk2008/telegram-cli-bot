from __future__ import annotations

import gc
import json
import weakref
from collections import UserDict
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _write_event(handle, timestamp: str, payload: dict[str, object]) -> None:
    handle.write(
        json.dumps(
            {"timestamp": timestamp, "type": "event_msg", "payload": payload},
            separators=(",", ":"),
        )
        + "\n"
    )


def _usage(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_output_tokens: int,
) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _rate_limit(
    *,
    limit_id: str = "codex",
    used_percent: object = 8,
    window_minutes: object = 10_080,
    resets_at: object = 1_787_011_285,
    plan_type: object = "pro",
) -> dict[str, object]:
    selected_window = {
        "used_percent": used_percent,
        "window_minutes": window_minutes,
        "resets_at": resets_at,
    }
    return {
        "type": "token_count",
        "rate_limits": {
            "limit_id": limit_id,
            "primary": (
                {
                    "used_percent": 42,
                    "window_minutes": 300,
                    "resets_at": 1_787_011_285,
                }
                if limit_id == "codex_bengalfox"
                else selected_window
            ),
            **({"secondary": selected_window} if limit_id == "codex_bengalfox" else {}),
            "plan_type": plan_type,
        },
    }


def test_failed_turn_usage_uses_last_cumulative_delta_for_capture_turn(tmp_path: Path) -> None:
    from bot.codex_usage.rollout import read_failed_turn_usage

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-07-27T01:59:58Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-07-27T01:59:59Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(100, 20, 30, 2)}},
        )
        _write_event(handle, "2026-07-27T02:00:01Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-07-27T02:00:02Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(120, 22, 35, 3)}},
        )
        _write_event(
            handle,
            "2026-07-27T02:00:03Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(130, 24, 37, 4)}},
        )
        _write_event(handle, "2026-07-27T02:00:04Z", {"type": "turn_aborted"})
        _write_event(handle, "2026-07-27T02:01:00Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-07-27T02:01:01Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(999, 99, 99, 9)}},
        )

    usage = read_failed_turn_usage(
        rollout,
        started_at=datetime(2026, 7, 27, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert usage is not None
    assert usage.input_tokens == 30
    assert usage.cached_input_tokens == 4
    assert usage.output_tokens == 7
    assert usage.reasoning_output_tokens == 2
    assert usage.total_tokens == 37


def test_failed_turn_usage_rejects_missing_or_decreasing_cumulative_sample(tmp_path: Path) -> None:
    from bot.codex_usage.rollout import read_failed_turn_usage

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(
            handle,
            "2026-07-27T01:59:59Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(100, 20, 30, 2)}},
        )
        _write_event(handle, "2026-07-27T02:00:01Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-07-27T02:00:02Z",
            {"type": "token_count", "info": {"total_token_usage": _usage(90, 19, 29, 1)}},
        )

    assert read_failed_turn_usage(
        rollout,
        started_at=datetime(2026, 7, 27, 2, 0, 0, tzinfo=timezone.utc),
    ) is None


def test_turn_rate_limit_uses_last_valid_codex_sample_inside_target_turn(
    tmp_path: Path,
) -> None:
    from bot.codex_usage.rollout import read_turn_rate_limit

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T01:59:58Z", {"type": "task_started"})
        _write_event(handle, "2026-08-11T01:59:59Z", _rate_limit(used_percent=1))
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-08-11T02:00:02Z",
            _rate_limit(limit_id="codex_bengalfox", used_percent=99),
        )
        _write_event(
            handle,
            "2026-08-11T02:00:03Z",
            _rate_limit(limit_id="other", used_percent=88),
        )
        _write_event(handle, "2026-08-11T02:00:04Z", _rate_limit(used_percent=8))
        _write_event(handle, "2026-08-11T02:00:05.123Z", _rate_limit(used_percent=9.5))
        _write_event(handle, "2026-08-11T02:00:06Z", _rate_limit(used_percent=101))
        _write_event(handle, "2026-08-11T02:01:00Z", {"type": "task_started"})
        _write_event(handle, "2026-08-11T02:01:01Z", _rate_limit(used_percent=77))

    sample = read_turn_rate_limit(
        rollout,
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert sample is not None
    assert sample.sampled_at == datetime(
        2026, 8, 11, 2, 0, 5, 123_000, tzinfo=timezone.utc
    )
    assert sample.used_percent == 9.5
    assert sample.window_minutes == 10_080
    assert sample.resets_at == datetime.fromtimestamp(1_787_011_285, timezone.utc)
    assert sample.plan_type == "pro"
    assert sample.limit_id == "codex"


def test_turn_rate_limit_resolution_flags_bengalfox_for_general_refresh(
    tmp_path: Path,
) -> None:
    from bot.codex_usage.rollout import read_turn_rate_limit_resolution

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})
        _write_event(
            handle,
            "2026-08-11T02:00:02Z",
            _rate_limit(limit_id="codex_bengalfox"),
        )

    resolution = read_turn_rate_limit_resolution(
        rollout,
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert resolution.sample is not None
    assert resolution.sample.limit_id == "codex_bengalfox"
    assert resolution.sample.used_percent == 8
    assert resolution.sample.window_minutes == 10_080
    assert resolution.refresh_general is True


def test_turn_rate_limit_resolution_uses_last_relevant_bucket(
    tmp_path: Path,
) -> None:
    from bot.codex_usage.rollout import read_turn_rate_limit_resolution

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})
        _write_event(handle, "2026-08-11T02:00:02Z", _rate_limit(used_percent=8))
        _write_event(
            handle,
            "2026-08-11T02:00:03Z",
            _rate_limit(limit_id="codex_bengalfox", used_percent=99),
        )

    resolution = read_turn_rate_limit_resolution(
        rollout,
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert resolution.sample is not None
    assert resolution.sample.limit_id == "codex_bengalfox"
    assert resolution.refresh_general is True


@pytest.mark.parametrize(
    "timestamp,rate_limit",
    [
        ("2026-08-11T02:00:02Z", _rate_limit(used_percent=-1)),
        ("2026-08-11T02:00:02Z", _rate_limit(used_percent=101)),
        ("2026-08-11T02:00:02Z", _rate_limit(used_percent=float("nan"))),
        ("2026-08-11T02:00:02Z", _rate_limit(used_percent=10**400)),
        ("2026-08-11T02:00:02Z", _rate_limit(window_minutes=0)),
        ("2026-08-11T02:00:02Z", _rate_limit(window_minutes=1.5)),
        ("2026-08-11T02:00:02Z", _rate_limit(window_minutes=2**63)),
        ("2026-08-11T02:00:02Z", _rate_limit(window_minutes=10**400)),
        ("2026-08-11T02:00:02Z", _rate_limit(resets_at=-1)),
        ("2026-08-11T02:00:02Z", _rate_limit(resets_at="soon")),
        ("2026-08-11T02:00:02Z", _rate_limit(limit_id="other")),
        (
            "2026-08-11T02:00:02Z",
            {"type": "token_count", "rate_limits": {"limit_id": "codex"}},
        ),
        ("invalid", _rate_limit()),
    ],
)
def test_turn_rate_limit_rejects_invalid_samples(
    tmp_path: Path,
    timestamp: str,
    rate_limit: dict[str, object],
) -> None:
    from bot.codex_usage.rollout import read_turn_rate_limit

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})
        _write_event(handle, timestamp, rate_limit)

    assert read_turn_rate_limit(
        rollout,
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
    ) is None


def test_turn_rate_limit_ignores_sample_before_target_turn(tmp_path: Path) -> None:
    from bot.codex_usage.rollout import read_turn_rate_limit

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T01:59:58Z", {"type": "task_started"})
        _write_event(handle, "2026-08-11T01:59:59Z", _rate_limit())
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})

    assert read_turn_rate_limit(
        rollout,
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
    ) is None


def test_resolve_turn_rate_limit_uses_located_session_rollout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from bot.codex_usage.rollout import resolve_turn_rate_limit
    from bot.web import native_history_locator

    rollout = tmp_path / "rollout.jsonl"
    with rollout.open("w", encoding="utf-8") as handle:
        _write_event(handle, "2026-08-11T02:00:01Z", {"type": "task_started"})
        _write_event(handle, "2026-08-11T02:00:02Z", _rate_limit())
    calls: list[tuple[str, Path]] = []

    def locate(session_id: str, *, codex_home: Path):
        calls.append((session_id, codex_home))
        return SimpleNamespace(path=rollout)

    monkeypatch.setattr(native_history_locator, "locate_codex_transcript", locate)

    sample = resolve_turn_rate_limit(
        session_id="session-1",
        started_at=datetime(2026, 8, 11, 2, 0, 0, tzinfo=timezone.utc),
        codex_home=tmp_path,
    )

    assert sample is not None
    assert sample.used_percent == 8
    assert calls == [("session-1", tmp_path)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"sampled_at": datetime(2026, 8, 11, 2, 0)},
        {"used_percent": True},
        {"used_percent": float("inf")},
        {"window_minutes": 0},
        {"window_minutes": 2**63},
        {"window_minutes": 10**400},
        {"resets_at": datetime(2026, 8, 18, 2, 0)},
    ],
)
def test_rate_limit_sample_model_rejects_invalid_values(
    overrides: dict[str, object],
) -> None:
    from bot.codex_usage.models import CodexRateLimitSample

    values = {
        "sampled_at": datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc),
        "used_percent": 8,
        "window_minutes": 10_080,
        "resets_at": datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc),
        "plan_type": "pro",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        CodexRateLimitSample(**values)


def test_scan_turn_does_not_retain_unrelated_target_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot.codex_usage import rollout as rollout_module

    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "baseline\nstart\n"
        + "".join(f"junk-{index}\n" for index in range(32))
        + "usage\nrate\nnext\n",
        encoding="utf-8",
    )
    junk_refs: list[weakref.ReferenceType[UserDict[str, object]]] = []

    def parse(line: str):
        kind = line.strip()
        timestamp = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
        if kind == "baseline":
            payload = UserDict(
                {
                    "type": "token_count",
                    "info": {"total_token_usage": _usage(100, 20, 30, 2)},
                }
            )
        elif kind in {"start", "next"}:
            if kind == "next":
                timestamp = datetime(2026, 8, 11, 2, 1, tzinfo=timezone.utc)
            payload = UserDict({"type": "task_started"})
        elif kind == "usage":
            payload = UserDict(
                {
                    "type": "token_count",
                    "info": {"total_token_usage": _usage(120, 22, 35, 3)},
                }
            )
        elif kind == "rate":
            payload = UserDict(_rate_limit())
        else:
            payload = UserDict({"type": "tool_output", "text": "x" * 1024})
            junk_refs.append(weakref.ref(payload))
        return timestamp, payload

    monkeypatch.setattr(rollout_module, "_payload", parse)

    scanned = rollout_module._scan_turn(
        rollout,
        started_at=datetime(2026, 8, 11, 1, 59, tzinfo=timezone.utc),
    )
    gc.collect()

    assert scanned is not None
    assert len(junk_refs) == 32
    assert all(reference() is None for reference in junk_refs)
