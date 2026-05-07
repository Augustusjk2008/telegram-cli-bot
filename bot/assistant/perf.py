from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from bot.assistant.home import AssistantHome

_STAGE_KEYS = ("sync_ms", "index_ms", "recall_ms", "cli_ms", "db_ms", "trace_ms", "plugin_ms")
_ACTIVE_CAPTURE: ContextVar[dict[str, int] | None] = ContextVar("assistant_perf_capture", default=None)


def new_stage_durations() -> dict[str, int]:
    return {key: 0 for key in _STAGE_KEYS}


@contextmanager
def activate_perf_capture(stage_durations: dict[str, int]) -> Iterator[None]:
    token = _ACTIVE_CAPTURE.set(stage_durations)
    try:
        yield
    finally:
        _ACTIVE_CAPTURE.reset(token)


def add_stage_duration(stage_key: str, elapsed_ms: int | float) -> None:
    capture = _ACTIVE_CAPTURE.get()
    if capture is None:
        return
    if stage_key not in capture:
      capture[stage_key] = 0
    capture[stage_key] += max(0, int(round(float(elapsed_ms))))


def add_db_duration(elapsed_seconds: float) -> None:
    add_stage_duration("db_ms", elapsed_seconds * 1000)


def write_perf_record(
    home: AssistantHome,
    *,
    run_id: str,
    bot_alias: str,
    source: str,
    task_mode: str,
    interactive: bool,
    user_id: int,
    status: str,
    stage_durations: dict[str, int] | None = None,
    elapsed_ms: int = 0,
    prompt_chars: int = 0,
    output_chars: int = 0,
    trace_count: int = 0,
    tool_call_count: int = 0,
    process_count: int = 0,
    error: str = "",
) -> dict[str, Any]:
    created_at = datetime.now(UTC).isoformat()
    record = {
        "run_id": run_id,
        "created_at": created_at,
        "bot_alias": bot_alias,
        "source": source,
        "task_mode": task_mode,
        "interactive": bool(interactive),
        "user_id": int(user_id),
        "status": status,
        "stage_durations": {
            **new_stage_durations(),
            **{key: int(value) for key, value in dict(stage_durations or {}).items()},
        },
        "elapsed_ms": int(elapsed_ms),
        "prompt_chars": int(prompt_chars),
        "output_chars": int(output_chars),
        "trace_count": int(trace_count),
        "tool_call_count": int(tool_call_count),
        "process_count": int(process_count),
        "error": str(error or ""),
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = home.root / "audit" / "perf" / f"{timestamp}-{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def list_perf_records(home: AssistantHome, *, limit: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    perf_root = home.root / "audit" / "perf"
    for path in sorted(perf_root.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(payload)
        if len(items) >= max(1, int(limit)):
            break
    return items


@contextmanager
def time_stage(stage_durations: dict[str, int], stage_key: str) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        with activate_perf_capture(stage_durations):
            yield
    finally:
        stage_durations[stage_key] = stage_durations.get(stage_key, 0) + max(
            0,
            int(round((time.perf_counter() - started_at) * 1000)),
        )
