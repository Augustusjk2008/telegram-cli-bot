from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from bot.assistant.home import AssistantHome
from bot.assistant.perf import list_perf_records

_STAGES = ("sync_ms", "index_ms", "recall_ms", "cli_ms", "db_ms", "trace_ms", "plugin_ms")


def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record_dt(record: dict[str, Any]) -> datetime | None:
    return _parse_dt(str(record.get("created_at") or ""))


def _matches(
    record: dict[str, Any],
    *,
    source: str,
    status: str,
    user_id: int | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> bool:
    if source and str(record.get("source") or "") != source:
        return False
    if status and str(record.get("status") or "") != status:
        return False
    if user_id is not None and int(record.get("user_id") or -1) != user_id:
        return False
    created_at = _record_dt(record)
    if from_dt is not None and created_at is not None and created_at < from_dt:
        return False
    if to_dt is not None and created_at is not None and created_at > to_dt:
        return False
    return True


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [int(item.get("elapsed_ms") or 0) for item in records]
    by_source = Counter(str(item.get("source") or "") for item in records)
    by_status = Counter(str(item.get("status") or "") for item in records)
    stage_totals: dict[str, int] = {stage: 0 for stage in _STAGES}
    for item in records:
        stage_durations = item.get("stage_durations")
        stages = stage_durations if isinstance(stage_durations, dict) else {}
        for stage in _STAGES:
            stage_totals[stage] += int(stages.get(stage) or 0)
    error_counter: Counter[str] = Counter()
    latest_by_error: dict[str, str] = {}
    for item in records:
        message = str(item.get("error") or "").strip()
        if not message:
            continue
        error_counter[message] += 1
        latest_by_error[message] = max(latest_by_error.get(message, ""), str(item.get("created_at") or ""))
    return {
        "total": len(records),
        "success": by_status.get("completed", 0) + by_status.get("success", 0),
        "failed": by_status.get("failed", 0) + by_status.get("error", 0),
        "avg_elapsed_ms": int(round(sum(elapsed) / len(elapsed))) if elapsed else 0,
        "p95_elapsed_ms": _p95(elapsed),
        "by_source": dict(by_source),
        "by_status": dict(by_status),
        "slow_stages": [
            {
                "stage": stage,
                "total_ms": total_ms,
                "avg_ms": int(round(total_ms / len(records))) if records else 0,
            }
            for stage, total_ms in sorted(stage_totals.items(), key=lambda item: item[1], reverse=True)
            if total_ms > 0
        ],
        "error_groups": [
            {
                "message": message,
                "count": count,
                "latest_at": latest_by_error.get(message, ""),
            }
            for message, count in error_counter.most_common(10)
        ],
    }


def get_perf_diagnostics(
    home: AssistantHome,
    *,
    limit: int,
    source: str = "",
    status: str = "",
    user_id: int | None = None,
    from_value: str = "",
    to_value: str = "",
) -> dict[str, Any]:
    from_dt = _parse_dt(from_value)
    to_dt = _parse_dt(to_value)
    raw = list_perf_records(home, limit=max(1, int(limit)) * 5)
    items = [
        item
        for item in raw
        if _matches(item, source=source, status=status, user_id=user_id, from_dt=from_dt, to_dt=to_dt)
    ][: max(1, int(limit))]
    return {"items": items, "summary": _summary(items)}
