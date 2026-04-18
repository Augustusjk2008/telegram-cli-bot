from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

_ASSISTANT_REREAD_NOTICE = "AGENTS.md 和 CLAUDE.md 已更新，请重新读取。"


def _trace_event(kind: str, **extra: Any) -> dict[str, Any]:
    summary = str(extra.get("summary") or "").strip()
    event = {
        "kind": kind,
        "source": "native",
        "summary": summary,
    }
    event.update(extra)
    return event


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _stringify_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _safe_json_dumps(value).strip()
    return str(value).strip()


def _extract_text_blocks(content: Any, *, block_types: Iterable[str] | None = None) -> list[str]:
    result: list[str] = []
    allowed_types = set(block_types or {"text", "output_text"})
    if not isinstance(content, list):
        return result
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip()
        if block_type not in allowed_types:
            continue
        text_value = _stringify_value(block.get("text"))
        if text_value:
            result.append(text_value)
    return result


def _extract_timestamp(item: dict[str, Any]) -> str:
    for key in ("timestamp", "created_at", "updated_at"):
        value = _stringify_value(item.get(key))
        if value:
            return value
    return ""


def _append_assistant_text(assistant_messages: list[str], text: Any) -> None:
    value = _stringify_value(text)
    if value:
        if assistant_messages and assistant_messages[-1] == value:
            return
        assistant_messages.append(value)


def _normalize_user_text(value: Any) -> str:
    text = _stringify_value(value)
    if not text:
        return ""
    if text.startswith(_ASSISTANT_REREAD_NOTICE):
        remainder = text[len(_ASSISTANT_REREAD_NOTICE):].lstrip()
        if remainder:
            return remainder
    return text


def _assign_user_text(turn: dict[str, Any], text: Any) -> None:
    value = _normalize_user_text(text)
    if not value:
        return
    current = _stringify_value(turn.get("user_text"))
    if not current:
        turn["user_text"] = value
        return
    if current == value:
        return
    turn["user_text"] = f"{current}\n{value}".strip()


def _extract_input_text_blocks(content: Any) -> list[str]:
    return _extract_text_blocks(content, block_types={"input_text", "text", "output_text"})


def _resolve_payload(item: dict[str, Any]) -> dict[str, Any]:
    nested_item = item.get("item")
    if isinstance(nested_item, dict):
        return nested_item
    payload = item.get("payload")
    if isinstance(payload, dict):
        return payload
    return {}


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return stripped


def _summarize_tool_payload(name: str, payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("command", "cmd", "script", "path", "query", "prompt"):
            candidate = _stringify_value(payload.get(key))
            if candidate:
                return candidate
        rendered = _safe_json_dumps(payload).strip()
        return rendered or name
    if isinstance(payload, list):
        rendered = _safe_json_dumps(payload).strip()
        return rendered or name
    rendered = _stringify_value(payload)
    return rendered or name


def _normalize_custom_tool_output(value: Any) -> tuple[str, Any]:
    parsed = _parse_jsonish(value)
    if isinstance(parsed, dict):
        nested_output = parsed.get("output")
        nested_summary = _stringify_value(nested_output)
        if nested_summary:
            return nested_summary, nested_output
    summary = _stringify_value(parsed) or "工具调用已返回"
    return summary, parsed


def _extract_claude_message_blocks(item: dict[str, Any]) -> list[dict[str, Any]]:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _extract_claude_user_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in _extract_claude_message_blocks(item):
        if str(block.get("type") or "").strip() != "text":
            continue
        text = _stringify_value(block.get("text"))
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _is_claude_skill_injection_text(text: Any) -> bool:
    value = _stringify_value(text)
    if not value:
        return False
    return (
        value.startswith("Base directory for this skill:")
        or ("## Checklist" in value and "## Process Flow" in value)
        or (value.startswith("# ") and "Visual Companion" in value)
    )


def _is_claude_system_injection_text(text: Any) -> bool:
    value = _stringify_value(text)
    if not value:
        return False
    return (
        value.startswith("<system-reminder>")
        or value.startswith("# AGENTS.md instructions for ")
        or "<environment_context>" in value
    )


def _new_claude_parser_state() -> dict[str, Any]:
    return {
        "last_tool_use_name_by_id": {},
        "expect_injection_after_skill": False,
    }


def _remember_claude_tool_use(state: dict[str, Any], *, call_id: str, tool_name: str) -> None:
    normalized_call_id = _stringify_value(call_id)
    normalized_tool_name = _stringify_value(tool_name)
    if not normalized_call_id or not normalized_tool_name:
        return
    state["last_tool_use_name_by_id"][normalized_call_id] = normalized_tool_name


def _is_skill_tool_result(state: dict[str, Any], tool_use_id: Any) -> bool:
    normalized_id = _stringify_value(tool_use_id)
    if not normalized_id:
        return False
    return state.get("last_tool_use_name_by_id", {}).get(normalized_id) == "Skill"


def _classify_claude_user_text(item: dict[str, Any], parser_state: dict[str, Any]) -> str:
    user_text = _extract_claude_user_text(item)
    if not user_text:
        return ""
    if parser_state.get("expect_injection_after_skill") and _is_claude_skill_injection_text(user_text):
        return "skill_injection"
    if _is_claude_system_injection_text(user_text):
        return "system_injection"
    return "real_user_text"


def _is_codex_instruction_message(text: Any) -> bool:
    value = _stringify_value(text)
    if not value:
        return False
    return (
        value.startswith("# AGENTS.md instructions for ")
        or value.startswith("<environment_context>")
        or "<environment_context>" in value
    )


def _new_turn_state(
    user_text: str = "",
    created_at: str = "",
    *,
    has_turn_context: bool = False,
) -> dict[str, Any]:
    return {
        "user_text": _stringify_value(user_text),
        "created_at": _stringify_value(created_at),
        "updated_at": _stringify_value(created_at),
        "trace": [],
        "trace_count": 0,
        "tool_call_count": 0,
        "process_count": 0,
        "last_trace_summary": "",
        "last_trace_signature": None,
        "assistant_messages": [],
        "has_turn_context": bool(has_turn_context),
    }


def _touch_turn(turn: dict[str, Any], timestamp: str) -> None:
    ts = _stringify_value(timestamp)
    if not ts:
        return
    if not turn.get("created_at"):
        turn["created_at"] = ts
    turn["updated_at"] = ts


def _trace_signature(event: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(event.get("kind") or "")
    summary = _stringify_value(event.get("summary"))
    if kind in {"tool_call", "tool_result"}:
        return kind, _stringify_value(event.get("call_id")), summary
    return kind, "", summary


def _append_trace_event(turn: dict[str, Any], event: dict[str, Any], *, include_trace: bool) -> None:
    signature = _trace_signature(event)
    if turn.get("last_trace_signature") == signature:
        return

    turn["last_trace_signature"] = signature
    turn["trace_count"] = int(turn.get("trace_count") or 0) + 1
    kind = str(event.get("kind") or "")
    if kind == "tool_call":
        turn["tool_call_count"] = int(turn.get("tool_call_count") or 0) + 1
    elif kind != "tool_result":
        turn["process_count"] = int(turn.get("process_count") or 0) + 1

    summary = _stringify_value(event.get("summary"))
    if summary:
        turn["last_trace_summary"] = summary

    turn["trace"].append(event)


def _is_trace_summary_redundant(summary_text: str, event_summary: str) -> bool:
    final_summary = _stringify_value(summary_text)
    trace_summary = _stringify_value(event_summary)
    if not final_summary or not trace_summary:
        return False
    if final_summary == trace_summary:
        return True
    return final_summary.startswith(trace_summary) and len(final_summary) > len(trace_summary)


def _prune_redundant_summary_trace(trace: list[dict[str, Any]], summary_text: str) -> list[dict[str, Any]]:
    if not trace:
        return []

    pruned = [dict(item) for item in trace]
    while pruned:
        kind = str(pruned[-1].get("kind") or "")
        if kind != "commentary":
            break
        if not _is_trace_summary_redundant(summary_text, pruned[-1].get("summary")):
            break
        pruned.pop()
    return pruned


def _finalize_turn(
    provider: str,
    session_id: str,
    turn_index: int,
    turn: dict[str, Any],
    *,
    include_trace: bool,
) -> dict[str, Any] | None:
    if (
        not turn.get("user_text")
        and not turn.get("assistant_messages")
        and not turn.get("trace_count")
        and not turn.get("last_trace_summary")
    ):
        return None

    assistant_messages = turn.get("assistant_messages") or []
    has_final_output = bool(assistant_messages)
    summary_text = assistant_messages[-1] if has_final_output else ""
    if not summary_text:
        summary_text = _stringify_value(turn.get("last_trace_summary"))
    trace = _prune_redundant_summary_trace(turn.get("trace") or [], summary_text)
    trace_count = len(trace)
    tool_call_count = sum(1 for item in trace if str(item.get("kind") or "") == "tool_call")
    process_count = sum(1 for item in trace if str(item.get("kind") or "") not in {"tool_call", "tool_result"})

    return {
        "id": f"{provider}-{session_id}-{turn_index}",
        "role": "assistant",
        "content": summary_text or "已终止，未返回可显示内容",
        "created_at": _stringify_value(turn.get("created_at") or turn.get("updated_at")),
        "updated_at": _stringify_value(turn.get("updated_at") or turn.get("created_at")),
        "user_text": _stringify_value(turn.get("user_text")),
        "meta": {
            "completion_state": "completed",
            "summary_kind": "final" if has_final_output else "partial_preview",
            "trace_version": 1,
            "trace_count": trace_count,
            "tool_call_count": tool_call_count,
            "process_count": process_count,
            **({"trace": trace} if include_trace and trace else {}),
            "native_source": {
                "provider": provider,
                "session_id": session_id,
            },
        },
    }


def _consume_codex_line(item: dict[str, Any], turn: dict[str, Any], *, include_trace: bool) -> None:
    item_type = str(item.get("type") or "").strip()
    assistant_messages = turn["assistant_messages"]

    if item_type == "compacted":
        return

    if item_type == "response_item":
        payload = _resolve_payload(item)
        payload_type = str(payload.get("type") or "").strip()
        payload_phase = _stringify_value(payload.get("phase")).lower()
        if payload_type == "compacted":
            return
        if payload_type == "reasoning":
            return
        if payload_type == "message":
            payload_role = _stringify_value(payload.get("role")).lower()
            if payload_role in {"developer", "system"}:
                return
            if payload_role == "user":
                user_text = "\n".join(_extract_input_text_blocks(payload.get("content"))).strip()
                if not turn.get("has_turn_context") and _is_codex_instruction_message(user_text):
                    return
                _assign_user_text(turn, user_text)
                return
            for text in _extract_text_blocks(payload.get("content")):
                if payload_phase in {"final", "final_answer"}:
                    _append_assistant_text(assistant_messages, text)
                else:
                    _append_trace_event(turn, _trace_event("commentary", raw_type="message", summary=text), include_trace=include_trace)
            return
        if payload_type == "function_call":
            name = _stringify_value(payload.get("name")) or "function_call"
            raw_arguments = payload.get("arguments")
            arguments = _parse_jsonish(raw_arguments)
            _append_trace_event(
                turn,
                _trace_event(
                    "tool_call",
                    raw_type="function_call",
                    title=name,
                    tool_name=name,
                    call_id=_stringify_value(payload.get("call_id")),
                    summary=_summarize_tool_payload(name, arguments),
                    payload={
                        "arguments": arguments,
                        "raw_arguments": raw_arguments,
                    },
                ),
                include_trace=include_trace,
            )
            return
        if payload_type == "custom_tool_call":
            name = _stringify_value(payload.get("name")) or "custom_tool_call"
            tool_input = _parse_jsonish(payload.get("input"))
            _append_trace_event(
                turn,
                _trace_event(
                    "tool_call",
                    raw_type="custom_tool_call",
                    title=name,
                    tool_name=name,
                    call_id=_stringify_value(payload.get("call_id")),
                    summary=_summarize_tool_payload(name, tool_input),
                    payload=tool_input,
                ),
                include_trace=include_trace,
            )
            return
        if payload_type == "function_call_output":
            output = payload.get("output")
            _append_trace_event(
                turn,
                _trace_event(
                    "tool_result",
                    raw_type="function_call_output",
                    call_id=_stringify_value(payload.get("call_id")),
                    summary=_stringify_value(output) or "工具调用已返回",
                    payload={"output": output},
                ),
                include_trace=include_trace,
            )
            return
        if payload_type == "custom_tool_call_output":
            summary, normalized_output = _normalize_custom_tool_output(payload.get("output"))
            _append_trace_event(
                turn,
                _trace_event(
                    "tool_result",
                    raw_type="custom_tool_call_output",
                    call_id=_stringify_value(payload.get("call_id")),
                    summary=summary,
                    payload=normalized_output,
                ),
                include_trace=include_trace,
            )
            return
        _append_trace_event(
            turn,
            _trace_event(
                "unknown",
                raw_type=payload_type or item_type or "unknown",
                summary=_safe_json_dumps(payload),
                payload=payload,
            ),
            include_trace=include_trace,
        )
        return

    if item_type == "event_msg":
        payload = _resolve_payload(item)
        payload_type = _stringify_value(payload.get("type"))
        payload_phase = _stringify_value(payload.get("phase")).lower()
        if payload_type == "user_message":
            _assign_user_text(turn, payload.get("message"))
            return
        message = _stringify_value(payload.get("message"))
        if message:
            if payload_type == "agent_message":
                _append_trace_event(
                    turn,
                    _trace_event(
                        "commentary",
                        raw_type=payload_type or "event_msg",
                        summary=message,
                        payload=payload,
                    ),
                    include_trace=include_trace,
                )
                return
            _append_assistant_text(assistant_messages, message)
            _append_trace_event(
                turn,
                _trace_event(
                    "commentary",
                    raw_type=payload_type or "event_msg",
                    summary=message,
                    payload=payload,
                ),
                include_trace=include_trace,
            )
        return

    if item_type not in {"turn_context", "session_meta"}:
        _append_trace_event(
            turn,
            _trace_event(
                "unknown",
                raw_type=item_type or "unknown",
                summary=_safe_json_dumps(item),
                payload=item,
            ),
            include_trace=include_trace,
        )


def _consume_claude_line(
    item: dict[str, Any],
    turn: dict[str, Any],
    *,
    include_trace: bool = True,
    parser_state: dict[str, Any] | None = None,
) -> None:
    parser_state = parser_state or _new_claude_parser_state()
    item_type = str(item.get("type") or "").strip()
    assistant_messages = turn["assistant_messages"]
    content = _extract_claude_message_blocks(item)

    if item_type == "assistant":
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type == "text":
                text = _stringify_value(block.get("text"))
                if text:
                    _append_assistant_text(assistant_messages, text)
                    _append_trace_event(turn, _trace_event("commentary", raw_type="text", summary=text), include_trace=include_trace)
                continue
            if block_type == "tool_use":
                name = _stringify_value(block.get("name")) or "tool_use"
                payload = block.get("input")
                _append_trace_event(
                    turn,
                    _trace_event(
                        "tool_call",
                        raw_type="tool_use",
                        title=name,
                        tool_name=name,
                        call_id=_stringify_value(block.get("id")),
                        summary=_summarize_tool_payload(name, payload),
                        payload=payload,
                    ),
                    include_trace=include_trace,
                )
                _remember_claude_tool_use(
                    parser_state,
                    call_id=_stringify_value(block.get("id")),
                    tool_name=name,
                )
                continue
            _append_trace_event(
                turn,
                _trace_event(
                    "unknown",
                    raw_type=block_type or item_type or "unknown",
                    summary=_safe_json_dumps(block),
                    payload=block,
                ),
                include_trace=include_trace,
            )
        return

    if item_type == "user":
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type != "tool_result":
                continue
            raw_content = block.get("content")
            if isinstance(raw_content, list):
                summary = "\n".join(_extract_text_blocks(raw_content)).strip()
            else:
                summary = _stringify_value(raw_content)
            _append_trace_event(
                turn,
                _trace_event(
                    "tool_result",
                    raw_type="tool_result",
                    call_id=_stringify_value(block.get("tool_use_id")),
                    summary=summary or "工具调用已返回",
                    payload={
                        "content": raw_content,
                        "is_error": bool(block.get("is_error")),
                    },
                ),
                include_trace=include_trace,
            )
            if _is_skill_tool_result(parser_state, block.get("tool_use_id")):
                summary_text = summary or "工具调用已返回"
                if summary_text.startswith("Launching skill:"):
                    parser_state["expect_injection_after_skill"] = True
        return

    _append_trace_event(
        turn,
        _trace_event(
            "unknown",
            raw_type=item_type or "unknown",
            summary=_safe_json_dumps(item),
            payload=item,
        ),
        include_trace=include_trace,
    )


def load_native_transcript(
    provider: str,
    transcript_path: Path,
    *,
    session_id: str,
    include_trace: bool = True,
) -> list[dict[str, Any]]:
    if not transcript_path.is_file():
        return []

    turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None
    turn_index = 0
    claude_parser_state = _new_claude_parser_state() if provider == "claude" else None

    for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue

        timestamp = _extract_timestamp(item)
        item_type = str(item.get("type") or "").strip()

        if provider == "codex" and item_type == "turn_context":
            finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {}, include_trace=include_trace)
            if finalized is not None:
                turns.append(finalized)
                turn_index += 1
            current_turn = _new_turn_state(
                _resolve_payload(item).get("content") or item.get("content"),
                timestamp,
                has_turn_context=True,
            )
            continue

        if provider == "claude" and item_type == "user":
            classification = _classify_claude_user_text(item, claude_parser_state or {})
            user_text = _extract_claude_user_text(item)
            if classification == "real_user_text" and user_text:
                finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {}, include_trace=include_trace)
                if finalized is not None:
                    turns.append(finalized)
                    turn_index += 1
                current_turn = _new_turn_state(user_text, timestamp)
                if claude_parser_state is not None:
                    claude_parser_state["expect_injection_after_skill"] = False
            elif classification == "skill_injection" and claude_parser_state is not None:
                claude_parser_state["expect_injection_after_skill"] = False

        if current_turn is None:
            current_turn = _new_turn_state(created_at=timestamp)

        _touch_turn(current_turn, timestamp)
        if provider == "codex":
            _consume_codex_line(item, current_turn, include_trace=include_trace)
        else:
            _consume_claude_line(
                item,
                current_turn,
                include_trace=include_trace,
                parser_state=claude_parser_state,
            )

    finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {}, include_trace=include_trace)
    if finalized is not None:
        turns.append(finalized)

    return turns


def create_stream_trace_state(provider: str) -> dict[str, Any]:
    return {
        "provider": str(provider or "").strip(),
        "buffer": "",
        "seen": set(),
    }


def _stream_event_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(event.get("kind") or ""),
        str(event.get("raw_type") or ""),
        str(event.get("call_id") or ""),
        str(event.get("summary") or ""),
    )


def _consume_live_codex_line(item: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = str(item.get("type") or "").strip()
    if event_type in {"response_item", "event_msg"}:
        turn = _new_turn_state()
        _consume_codex_line(item, turn, include_trace=True)
        return [dict(event) for event in turn["trace"]]
    if not event_type.startswith("item."):
        return []

    payload = _resolve_payload(item)
    payload_type = str(payload.get("type") or "").strip()
    if event_type != "item.completed":
        return []
    if payload_type == "function_call":
        name = _stringify_value(payload.get("name")) or "function_call"
        raw_arguments = payload.get("arguments")
        arguments = _parse_jsonish(raw_arguments)
        return [
            _trace_event(
                "tool_call",
                raw_type="function_call",
                title=name,
                tool_name=name,
                call_id=_stringify_value(payload.get("call_id")),
                summary=_summarize_tool_payload(name, arguments),
                payload={
                    "arguments": arguments,
                    "raw_arguments": raw_arguments,
                },
            )
        ]
    if payload_type == "custom_tool_call":
        name = _stringify_value(payload.get("name")) or "custom_tool_call"
        tool_input = _parse_jsonish(payload.get("input"))
        return [
            _trace_event(
                "tool_call",
                raw_type="custom_tool_call",
                title=name,
                tool_name=name,
                call_id=_stringify_value(payload.get("call_id")),
                summary=_summarize_tool_payload(name, tool_input),
                payload=tool_input,
            )
        ]
    if payload_type == "function_call_output":
        output = payload.get("output")
        return [
            _trace_event(
                "tool_result",
                raw_type="function_call_output",
                call_id=_stringify_value(payload.get("call_id")),
                summary=_stringify_value(output) or "工具调用已返回",
                payload={"output": output},
            )
        ]
    if payload_type == "custom_tool_call_output":
        summary, normalized_output = _normalize_custom_tool_output(payload.get("output"))
        return [
            _trace_event(
                "tool_result",
                raw_type="custom_tool_call_output",
                call_id=_stringify_value(payload.get("call_id")),
                summary=summary,
                payload=normalized_output,
            )
        ]
    if payload_type in {"assistant_message", "agent_message"}:
        text = _stringify_value(payload.get("text"))
        if text:
            return [
                _trace_event(
                    "commentary",
                    raw_type=payload_type,
                    summary=text,
                )
            ]
    return []


def _consume_live_claude_line(item: dict[str, Any]) -> list[dict[str, Any]]:
    item_type = str(item.get("type") or "").strip()
    if item_type == "stream_event":
        return []
    if item_type not in {"assistant", "user"}:
        return []

    turn = _new_turn_state()
    _consume_claude_line(item, turn, include_trace=True)
    return [dict(event) for event in turn["trace"]]


def consume_stream_trace_chunk(provider: str, chunk: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    state["buffer"] = str(state.get("buffer") or "") + str(chunk or "")
    if "\n" not in state["buffer"] and "\r" not in state["buffer"]:
        return events

    raw_lines = state["buffer"].splitlines(keepends=True)
    complete_lines: list[str] = []
    state["buffer"] = ""
    for raw_line in raw_lines:
        if raw_line.endswith("\n") or raw_line.endswith("\r"):
            complete_lines.append(raw_line)
        else:
            state["buffer"] = raw_line

    for raw_line in complete_lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue

        if provider == "codex":
            candidate_events = _consume_live_codex_line(item)
        elif provider == "claude":
            candidate_events = _consume_live_claude_line(item)
        else:
            candidate_events = []

        for event in candidate_events:
            event_key = _stream_event_key(event)
            if event_key in state["seen"]:
                continue
            state["seen"].add(event_key)
            events.append(event)
    return events
