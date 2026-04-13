from __future__ import annotations

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


def _overlay_to_turn(overlay: dict[str, Any], native_trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
            "trace": _merge_trace_lists(native_trace, overlay.get("trace") or []),
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
    limit: int,
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
            merged.append(_overlay_to_turn(overlay))
            continue

        existing = merged[target_index]
        summary_kind = str(existing.get("meta", {}).get("summary_kind") or "")
        if summary_kind == "final":
            continue

        native_trace = existing.get("meta", {}).get("trace") or []
        merged[target_index] = _overlay_to_turn(overlay, native_trace=native_trace)

    merged.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("updated_at") or ""), str(item.get("id") or "")))
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


def build_web_chat_history(profile, session, *, limit: int = 50) -> list[dict[str, Any]]:
    provider = normalize_cli_type(getattr(profile, "cli_type", ""))
    native_turns: list[dict[str, Any]] = []

    if provider == "codex" and session.codex_session_id:
        ref = locate_codex_transcript(session.codex_session_id)
        if ref is not None:
            native_turns = load_native_transcript("codex", ref.path, session_id=ref.session_id)
    elif provider == "claude" and session.claude_session_id:
        ref = locate_claude_transcript(session.claude_session_id, cwd_hint=session.working_dir)
        if ref is not None:
            native_turns = load_native_transcript("claude", ref.path, session_id=ref.session_id)

    merged_turns = merge_native_turns_with_overlay(
        native_turns,
        getattr(session, "web_turn_overlays", []),
        limit=max(1, limit),
    )

    messages: list[dict[str, Any]] = []
    for turn in merged_turns:
        messages.extend(_turn_to_messages(turn))
    return messages[-max(1, limit):]


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
    current_items = build_web_chat_history(profile, session, limit=max(20, limit))
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

    current_items = build_web_chat_history(profile, session, limit=max(20, limit))
    matched = _select_latest_assistant_message(
        current_items,
        provider=provider,
        session_id=session_id,
        user_text=requested_user_text,
    )
    if matched is not None:
        return matched
    return _turn_to_messages(_overlay_to_turn(overlay))[-1]
