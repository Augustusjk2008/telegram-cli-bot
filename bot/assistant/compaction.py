from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from bot.assistant_home import AssistantHome

STATE_PATH = Path("state/compaction.json")
CAPTURE_THRESHOLD = 6
TIME_THRESHOLD_SECONDS = 30 * 60
STRONG_SIGNAL_TOKENS = ("不要", "必须", "只能", "固定", "全局")
CompactionFinalizeResult = Literal["none", "changed", "noop"]


def _default_compaction_state() -> dict[str, Any]:
    return {
        "latest_capture_id": None,
        "latest_capture_at": None,
        "pending": False,
        "pending_reason": None,
        "pending_capture_count": 0,
        "cursor_capture_id": None,
        "last_compacted_at": None,
        "last_compaction_result": None,
    }


def _state_path(home: AssistantHome) -> Path:
    return home.root / STATE_PATH


def load_compaction_state(home: AssistantHome) -> dict[str, Any]:
    path = _state_path(home)
    if not path.exists():
        return _default_compaction_state()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_compaction_state()

    if not isinstance(data, dict):
        return _default_compaction_state()

    merged = _default_compaction_state()
    merged.update(data)
    return merged


def save_compaction_state(home: AssistantHome, payload: dict[str, Any]) -> dict[str, Any]:
    state = _default_compaction_state()
    state.update(payload)
    path = _state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return state


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _list_capture_records(home: AssistantHome) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in (home.root / "inbox" / "captures").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        capture_id = str(payload.get("id") or path.stem).strip()
        created_at = str(payload.get("created_at") or "").strip()
        if not capture_id:
            continue
        records.append(
            {
                "id": capture_id,
                "created_at": created_at,
            }
        )

    return sorted(records, key=lambda item: (item["created_at"], item["id"]))


def _get_unseen_capture_records(home: AssistantHome, cursor_capture_id: str | None) -> list[dict[str, str]]:
    records = _list_capture_records(home)
    if not cursor_capture_id:
        return records

    for index, record in enumerate(records):
        if record["id"] == cursor_capture_id:
            return records[index + 1 :]
    return records


def list_pending_capture_ids(home: AssistantHome) -> list[str]:
    state = load_compaction_state(home)
    unseen_records = _get_unseen_capture_records(home, state.get("cursor_capture_id"))
    return [record["id"] for record in unseen_records if record.get("id")]


def _has_strong_signal(latest_capture: dict[str, Any] | None) -> bool:
    if not isinstance(latest_capture, dict):
        return False
    user_text = str(latest_capture.get("user_text") or "")
    return any(token in user_text for token in STRONG_SIGNAL_TOKENS)


def refresh_compaction_state(home: AssistantHome, *, latest_capture: dict[str, Any] | None) -> dict[str, Any]:
    state = load_compaction_state(home)
    latest_capture_id = None
    latest_capture_at = None
    if isinstance(latest_capture, dict):
        latest_capture_id = str(latest_capture.get("id") or "").strip() or None
        latest_capture_at = str(latest_capture.get("created_at") or "").strip() or None

    unseen_records = _get_unseen_capture_records(home, state.get("cursor_capture_id"))
    pending_capture_count = len(unseen_records)

    pending_reason = None
    if pending_capture_count >= CAPTURE_THRESHOLD:
        pending_reason = "capture_threshold"
    elif pending_capture_count >= 2:
        last_compacted_at = _parse_iso_datetime(state.get("last_compacted_at"))
        if last_compacted_at is not None:
            elapsed_seconds = (datetime.now(UTC) - last_compacted_at).total_seconds()
            if elapsed_seconds >= TIME_THRESHOLD_SECONDS:
                pending_reason = "time_threshold"
    elif _has_strong_signal(latest_capture):
        pending_reason = "strong_signal"

    return save_compaction_state(
        home,
        {
            **state,
            "latest_capture_id": latest_capture_id,
            "latest_capture_at": latest_capture_at,
            "pending": bool(pending_reason),
            "pending_reason": pending_reason,
            "pending_capture_count": pending_capture_count,
        },
    )


def build_compaction_memory_block(home: AssistantHome) -> str:
    state = load_compaction_state(home)
    if not state.get("pending"):
        return ""
    return (
        "maintenance:\n"
        "- 后台维护任务：如有必要，请静默更新固定 working 文件：current_goal.md、open_loops.md、user_prefs.md、recent_summary.md。\n"
        "- working 记忆应以简短 Markdown 列表为主；标题可以存在，但宿主主要读取列表项。\n"
        "- 不要创建任意新的 working 记忆文件，否则不会进入宿主维护的 prompt。\n"
        "- 如出现不应自动生效的长期规则或升级建议，请创建 .assistant/proposals/*.json。\n"
        "- 不要在回复中主动提及这些后台维护动作，除非用户明确询问。\n"
        f"- 当前待压缩 captures: {int(state.get('pending_capture_count') or 0)}\n"
    )


def is_compaction_prompt_active(home: AssistantHome) -> bool:
    return bool(load_compaction_state(home).get("pending"))


def snapshot_managed_surface(home: AssistantHome) -> dict[str, str]:
    surface: dict[str, str] = {}
    for path in sorted((home.root / "memory" / "working").glob("*.md")):
        surface[str(path.relative_to(home.root))] = sha256(path.read_bytes()).hexdigest()
    proposal_ids = [path.stem for path in sorted((home.root / "proposals").glob("*.json"))]
    surface["proposals"] = ",".join(proposal_ids)
    return surface


def finalize_compaction(
    home: AssistantHome,
    *,
    before: dict[str, str],
    after: dict[str, str],
    consumed_capture_ids: list[str],
    review_prompt_active: bool,
) -> CompactionFinalizeResult:
    surface_changed = before != after
    if not surface_changed and not review_prompt_active:
        return "none"

    state = load_compaction_state(home)
    timestamp = datetime.now(UTC).isoformat()
    result: CompactionFinalizeResult = "changed" if surface_changed else "noop"
    audit_path = home.root / "audit" / "compactions.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    from_cursor_capture_id = state.get("cursor_capture_id")
    to_cursor_capture_id = consumed_capture_ids[-1] if consumed_capture_ids else from_cursor_capture_id
    event = {
        "created_at": timestamp,
        "result": result,
        "surface_changed": surface_changed,
        "review_prompt_active": review_prompt_active,
        "from_cursor_capture_id": from_cursor_capture_id,
        "to_cursor_capture_id": to_cursor_capture_id,
        "consumed_capture_count": len(consumed_capture_ids),
        "consumed_capture_ids": list(consumed_capture_ids),
        "before": before,
        "after": after,
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    save_compaction_state(
        home,
        {
            **state,
            "pending": False,
            "pending_reason": None,
            "pending_capture_count": 0,
            "cursor_capture_id": consumed_capture_ids[-1] if consumed_capture_ids else state.get("cursor_capture_id"),
            "last_compacted_at": timestamp,
            "last_compaction_result": result,
        },
    )
    return result
