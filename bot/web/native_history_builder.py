from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bot.cli import normalize_cli_type
from bot.web.native_history_adapter import load_native_transcript
from bot.web.native_history_locator import locate_claude_transcript, locate_codex_transcript


def _turn_key(turn: dict[str, Any]) -> tuple[str, str, str]:
    native_source = turn.get("meta", {}).get("native_source", {})
    return (
        str(native_source.get("provider") or ""),
        str(native_source.get("session_id") or ""),
        str(turn.get("user_text") or ""),
    )


def _overlay_key(overlay: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(overlay.get("provider") or ""),
        str(overlay.get("native_session_id") or ""),
        str(overlay.get("user_text") or ""),
    )


def _parse_sort_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=UTC)

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)

    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or UTC
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(UTC)


def _turn_sort_key(item: dict[str, Any]) -> tuple[datetime, datetime, str]:
    return (
        _parse_sort_timestamp(item.get("created_at")),
        _parse_sort_timestamp(item.get("updated_at")),
        str(item.get("id") or ""),
    )


def _drop_active_native_turn(provider: str, session, native_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not native_turns:
        return native_turns

    running_user_text = str(getattr(session, "running_user_text", "") or "").strip()
    running_started_at = str(getattr(session, "running_started_at", "") or "").strip()
    if not running_user_text or not running_started_at:
        return native_turns

    session_key = (provider, _get_native_session_id(provider, session))
    pruned_turns = list(native_turns)

    while pruned_turns:
        last_turn = pruned_turns[-1]
        if _turn_key(last_turn)[:2] != session_key:
            break

        summary_kind = str(last_turn.get("meta", {}).get("summary_kind") or "")
        if summary_kind == "final":
            last_trace = list(last_turn.get("meta", {}).get("trace") or [])
            has_only_commentary = bool(last_trace) and all(
                str(item.get("kind") or "") == "commentary" for item in last_trace
            )
            if not has_only_commentary:
                break

        last_user_text = str(last_turn.get("user_text") or "").strip()
        if last_user_text and last_user_text != running_user_text:
            break

        pruned_turns.pop()

    return pruned_turns


def _trace_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("kind") or ""),
        str(item.get("raw_type") or ""),
        str(item.get("call_id") or ""),
        str(item.get("summary") or ""),
    )


def _merge_trace_lists(*sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in sources:
        for item in source or []:
            if not isinstance(item, dict):
                continue
            key = _trace_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))
    return merged


def _count_process_events(trace: list[dict[str, Any]] | None) -> int:
    return sum(
        1
        for item in trace or []
        if str(item.get("kind") or "") not in {"tool_call", "tool_result"}
    )


def _count_tool_calls(trace: list[dict[str, Any]] | None) -> int:
    return sum(1 for item in trace or [] if str(item.get("kind") or "") == "tool_call")


def _overlay_to_turn(
    overlay: dict[str, Any],
    native_trace: list[dict[str, Any]] | None = None,
    *,
    include_trace: bool = True,
) -> dict[str, Any]:
    trace = _merge_trace_lists(native_trace, overlay.get("trace") or [])
    return {
        "id": f"overlay-{overlay.get('provider')}-{overlay.get('started_at') or overlay.get('updated_at') or ''}",
        "role": "assistant",
        "content": str(overlay.get("summary_text") or "已终止，未返回可显示内容"),
        "created_at": str(overlay.get("started_at") or overlay.get("updated_at") or ""),
        "updated_at": str(overlay.get("updated_at") or overlay.get("started_at") or ""),
        "user_text": str(overlay.get("user_text") or ""),
        "meta": {
            "completion_state": str(overlay.get("completion_state") or "cancelled"),
            "summary_kind": str(overlay.get("summary_kind") or "partial_preview"),
            "trace_version": 1,
            "trace_count": len(trace),
            "tool_call_count": _count_tool_calls(trace),
            "process_count": _count_process_events(trace),
            **({"trace": trace} if include_trace and trace else {}),
            "native_source": {
                "provider": overlay.get("provider"),
                "session_id": overlay.get("native_session_id"),
            },
        },
    }


def merge_native_turns_with_overlay(
    native_turns: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    *,
    limit: int | None,
    include_trace: bool = True,
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in native_turns]
    for overlay in overlays:
        if not isinstance(overlay, dict):
            continue

        target_index = None
        for index, turn in enumerate(merged):
            if _turn_key(turn) == _overlay_key(overlay):
                target_index = index

        if target_index is None:
            merged.append(_overlay_to_turn(overlay, include_trace=include_trace))
            continue

        existing = merged[target_index]
        summary_kind = str(existing.get("meta", {}).get("summary_kind") or "")
        if summary_kind == "final":
            continue

        native_trace = existing.get("meta", {}).get("trace") or []
        merged[target_index] = _overlay_to_turn(overlay, native_trace=native_trace, include_trace=include_trace)

    merged.sort(key=_turn_sort_key)
    if limit is None:
        return merged
    return merged[-max(1, limit):]


def _turn_to_messages(turn: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    user_text = str(turn.get("user_text") or "").strip()
    created_at = str(turn.get("created_at") or "")
    native_source = dict(turn.get("meta", {}).get("native_source") or {})

    if user_text:
        messages.append(
            {
                "id": f"{turn.get('id')}-user",
                "role": "user",
                "content": user_text,
                "created_at": created_at,
                "meta": {
                    "native_source": native_source,
                },
            }
        )

    messages.append(
        {
            "id": str(turn.get("id") or ""),
            "role": "assistant",
            "content": str(turn.get("content") or ""),
            "created_at": created_at,
            "user_text": user_text,
            "meta": dict(turn.get("meta") or {}),
        }
    )
    return messages


def build_web_chat_history(
    profile,
    session,
    *,
    limit: int | None = 50,
    include_trace: bool = False,
) -> list[dict[str, Any]]:
    provider = normalize_cli_type(getattr(profile, "cli_type", ""))
    native_turns: list[dict[str, Any]] = []

    if provider == "codex" and session.codex_session_id:
        ref = locate_codex_transcript(session.codex_session_id)
        if ref is not None:
            native_turns = load_native_transcript("codex", ref.path, session_id=ref.session_id, include_trace=include_trace)
    elif provider == "claude" and session.claude_session_id:
        ref = locate_claude_transcript(session.claude_session_id, cwd_hint=session.working_dir)
        if ref is not None:
            native_turns = load_native_transcript("claude", ref.path, session_id=ref.session_id, include_trace=include_trace)

    native_turns = _drop_active_native_turn(provider, session, native_turns)

    merged_turns = merge_native_turns_with_overlay(
        native_turns,
        getattr(session, "web_turn_overlays", []),
        limit=max(1, limit) if isinstance(limit, int) else None,
        include_trace=include_trace,
    )

    messages: list[dict[str, Any]] = []
    for turn in merged_turns:
        messages.extend(_turn_to_messages(turn))
    return messages


def _locate_native_transcript(provider: str, session_id: str, *, cwd_hint: str | None) -> Any:
    if provider == "codex":
        return locate_codex_transcript(session_id)
    if provider == "claude":
        return locate_claude_transcript(session_id, cwd_hint=cwd_hint)
    return None


def _select_matching_native_turn(
    turns: list[dict[str, Any]],
    *,
    provider: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any] | None:
    normalized_user_text = str(user_text or "").strip()
    normalized_assistant_text = str(assistant_text or "").strip()

    scored: list[tuple[int, tuple[datetime, datetime, str], dict[str, Any]]] = []
    for turn in turns:
        if not _message_matches_turn(
            turn,
            provider=provider,
            session_id=session_id,
            user_text=normalized_user_text,
        ):
            continue
        score = 1
        if normalized_assistant_text and str(turn.get("content") or "").strip() == normalized_assistant_text:
            score += 2
        if int(turn.get("meta", {}).get("tool_call_count") or 0) > 0:
            score += 1
        scored.append((score, _turn_sort_key(turn), turn))

    if not scored and normalized_assistant_text:
        for turn in turns:
            if not _message_matches_turn(
                turn,
                provider=provider,
                session_id=session_id,
                user_text="",
            ):
                continue
            if str(turn.get("content") or "").strip() != normalized_assistant_text:
                continue
            score = 1
            if int(turn.get("meta", {}).get("tool_call_count") or 0) > 0:
                score += 1
            scored.append((score, _turn_sort_key(turn), turn))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return dict(scored[-1][2])


def resolve_native_trace_for_turn(
    provider: str,
    session_id: str,
    *,
    user_text: str,
    assistant_text: str = "",
    cwd_hint: str | None = None,
) -> dict[str, Any] | None:
    normalized_provider = normalize_cli_type(provider)
    normalized_session_id = str(session_id or "").strip()
    if normalized_provider not in {"codex", "claude"} or not normalized_session_id:
        return None

    ref = _locate_native_transcript(
        normalized_provider,
        normalized_session_id,
        cwd_hint=cwd_hint,
    )
    if ref is None:
        return None

    turns = load_native_transcript(
        normalized_provider,
        ref.path,
        session_id=ref.session_id,
        include_trace=True,
    )
    matched = _select_matching_native_turn(
        turns,
        provider=normalized_provider,
        session_id=ref.session_id,
        user_text=user_text,
        assistant_text=assistant_text,
    )
    if matched is None:
        return None

    meta = dict(matched.get("meta") or {})
    trace = [dict(item) for item in meta.get("trace") or [] if isinstance(item, dict)]
    return {
        "provider": normalized_provider,
        "session_id": ref.session_id,
        "trace": trace,
        "trace_count": int(meta.get("trace_count") or len(trace)),
        "tool_call_count": int(meta.get("tool_call_count") or _count_tool_calls(trace)),
        "process_count": int(meta.get("process_count") or _count_process_events(trace)),
        "content": str(matched.get("content") or ""),
        "user_text": str(matched.get("user_text") or ""),
        "transcript_path": str(ref.path),
    }


def _get_native_session_id(provider: str, session) -> str:
    if provider == "codex":
        return str(getattr(session, "codex_session_id", "") or "")
    if provider == "claude":
        return str(getattr(session, "claude_session_id", "") or "")
    return ""


def _message_matches_turn(
    item: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    user_text: str,
) -> bool:
    if str(item.get("role") or "") != "assistant":
        return False
    if user_text and str(item.get("user_text") or "") != user_text:
        return False

    native_source = item.get("meta", {}).get("native_source", {})
    item_provider = str(native_source.get("provider") or "")
    item_session_id = str(native_source.get("session_id") or "")
    if provider and item_provider and item_provider != provider:
        return False
    if session_id and item_session_id and item_session_id != session_id:
        return False
    return True


def _select_latest_assistant_message(
    items: list[dict[str, Any]],
    *,
    provider: str,
    session_id: str,
    user_text: str,
) -> dict[str, Any] | None:
    for item in reversed(items):
        if _message_matches_turn(item, provider=provider, session_id=session_id, user_text=user_text):
            return item
    return None


def finalize_web_chat_turn(
    profile,
    session,
    *,
    user_text: str,
    fallback_output: str,
    fallback_trace: list[dict[str, Any]] | None = None,
    completion_state: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    provider = normalize_cli_type(getattr(profile, "cli_type", ""))
    session_id = _get_native_session_id(provider, session)
    requested_user_text = str(user_text or "")
    current_items = build_web_chat_history(profile, session, limit=max(20, limit), include_trace=True)
    matched = _select_latest_assistant_message(
        current_items,
        provider=provider,
        session_id=session_id,
        user_text=requested_user_text,
    )

    resolved_completion_state = str(completion_state or ("cancelled" if getattr(session, "stop_requested", False) else "completed"))
    if (
        resolved_completion_state == "completed"
        and matched is not None
        and str(matched.get("meta", {}).get("summary_kind") or "") == "final"
    ):
        return matched

    summary_text = str(fallback_output or getattr(session, "running_preview_text", "") or "已终止，未返回可显示内容")
    summary_kind = "final" if resolved_completion_state == "completed" and summary_text else "partial_preview"
    overlay = {
        "provider": provider,
        "native_session_id": session_id,
        "user_text": requested_user_text,
        "started_at": getattr(session, "running_started_at", "") or getattr(session, "running_updated_at", "") or "",
        "updated_at": getattr(session, "running_updated_at", "") or getattr(session, "running_started_at", "") or "",
        "summary_text": summary_text,
        "summary_kind": summary_kind,
        "completion_state": resolved_completion_state,
        "trace": [dict(item) for item in (fallback_trace or []) if isinstance(item, dict)],
        "locator_hint": {"cwd": getattr(session, "working_dir", "")},
    }
    session.upsert_web_turn_overlay(overlay)

    current_items = build_web_chat_history(profile, session, limit=max(20, limit), include_trace=True)
    matched = _select_latest_assistant_message(
        current_items,
        provider=provider,
        session_id=session_id,
        user_text=requested_user_text,
    )
    if matched is not None:
        return matched
    return _turn_to_messages(_overlay_to_turn(overlay))[-1]


def get_web_chat_trace(profile, session, message_id: str) -> dict[str, Any] | None:
    target_id = str(message_id or "").strip()
    if not target_id:
        return None

    for item in build_web_chat_history(profile, session, limit=None, include_trace=True):
        if str(item.get("id") or "") != target_id:
            continue
        if str(item.get("role") or "") != "assistant":
            return None
        meta = dict(item.get("meta") or {})
        trace = [dict(event) for event in meta.get("trace") or [] if isinstance(event, dict)]
        return {
            "message_id": target_id,
            "trace": trace,
            "trace_count": int(meta.get("trace_count") or len(trace)),
            "tool_call_count": int(meta.get("tool_call_count") or _count_tool_calls(trace)),
            "process_count": int(meta.get("process_count") or _count_process_events(trace)),
        }
    return None
