from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


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
