from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def _extract_text_blocks(content: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(content, list):
        return result
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip()
        if block_type not in {"text", "output_text"}:
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
        assistant_messages.append(value)


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


def _extract_claude_user_text(item: dict[str, Any]) -> str:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    parts: list[str] = []
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").strip() != "text":
            continue
        text = _stringify_value(block.get("text"))
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _new_turn_state(user_text: str = "", created_at: str = "") -> dict[str, Any]:
    return {
        "user_text": _stringify_value(user_text),
        "created_at": _stringify_value(created_at),
        "updated_at": _stringify_value(created_at),
        "trace": [],
        "assistant_messages": [],
    }


def _touch_turn(turn: dict[str, Any], timestamp: str) -> None:
    ts = _stringify_value(timestamp)
    if not ts:
        return
    if not turn.get("created_at"):
        turn["created_at"] = ts
    turn["updated_at"] = ts


def _finalize_turn(
    provider: str,
    session_id: str,
    turn_index: int,
    turn: dict[str, Any],
) -> dict[str, Any] | None:
    if not turn.get("user_text") and not turn.get("trace") and not turn.get("assistant_messages"):
        return None

    assistant_messages = turn.get("assistant_messages") or []
    trace = [dict(item) for item in turn.get("trace") or []]
    summary_text = assistant_messages[-1] if assistant_messages else ""
    if not summary_text and trace:
        summary_text = _stringify_value(trace[-1].get("summary"))

    return {
        "id": f"{provider}-{session_id}-{turn_index}",
        "role": "assistant",
        "content": summary_text or "已终止，未返回可显示内容",
        "created_at": _stringify_value(turn.get("created_at") or turn.get("updated_at")),
        "updated_at": _stringify_value(turn.get("updated_at") or turn.get("created_at")),
        "user_text": _stringify_value(turn.get("user_text")),
        "meta": {
            "completion_state": "completed",
            "summary_kind": "final" if summary_text else "partial_preview",
            "trace_version": 1,
            "trace": trace,
            "native_source": {
                "provider": provider,
                "session_id": session_id,
            },
        },
    }


def _consume_codex_line(item: dict[str, Any], turn: dict[str, Any]) -> None:
    item_type = str(item.get("type") or "").strip()
    trace = turn["trace"]
    assistant_messages = turn["assistant_messages"]

    if item_type == "response_item":
        payload = item.get("item") if isinstance(item.get("item"), dict) else {}
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "message":
            for text in _extract_text_blocks(payload.get("content")):
                _append_assistant_text(assistant_messages, text)
                trace.append(_trace_event("commentary", raw_type="message", summary=text))
            return
        if payload_type == "function_call":
            name = _stringify_value(payload.get("name")) or "function_call"
            raw_arguments = payload.get("arguments")
            arguments = _parse_jsonish(raw_arguments)
            trace.append(
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
            )
            return
        if payload_type == "function_call_output":
            output = payload.get("output")
            trace.append(
                _trace_event(
                    "tool_result",
                    raw_type="function_call_output",
                    call_id=_stringify_value(payload.get("call_id")),
                    summary=_stringify_value(output) or "工具调用已返回",
                    payload={"output": output},
                )
            )
            return
        trace.append(
            _trace_event(
                "unknown",
                raw_type=payload_type or item_type or "unknown",
                summary=_safe_json_dumps(payload),
                payload=payload,
            )
        )
        return

    if item_type == "event_msg":
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        message = _stringify_value(payload.get("message"))
        if message:
            _append_assistant_text(assistant_messages, message)
            trace.append(
                _trace_event(
                    "commentary",
                    raw_type=_stringify_value(payload.get("type")) or "event_msg",
                    summary=message,
                    payload=payload,
                )
            )
        return

    if item_type not in {"turn_context", "session_meta"}:
        trace.append(
            _trace_event(
                "unknown",
                raw_type=item_type or "unknown",
                summary=_safe_json_dumps(item),
                payload=item,
            )
        )


def _consume_claude_line(item: dict[str, Any], turn: dict[str, Any]) -> None:
    item_type = str(item.get("type") or "").strip()
    trace = turn["trace"]
    assistant_messages = turn["assistant_messages"]
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []

    if item_type == "assistant":
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type == "text":
                text = _stringify_value(block.get("text"))
                if text:
                    _append_assistant_text(assistant_messages, text)
                    trace.append(_trace_event("commentary", raw_type="text", summary=text))
                continue
            if block_type == "tool_use":
                name = _stringify_value(block.get("name")) or "tool_use"
                payload = block.get("input")
                trace.append(
                    _trace_event(
                        "tool_call",
                        raw_type="tool_use",
                        title=name,
                        tool_name=name,
                        call_id=_stringify_value(block.get("id")),
                        summary=_summarize_tool_payload(name, payload),
                        payload=payload,
                    )
                )
                continue
            trace.append(
                _trace_event(
                    "unknown",
                    raw_type=block_type or item_type or "unknown",
                    summary=_safe_json_dumps(block),
                    payload=block,
                )
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
            trace.append(
                _trace_event(
                    "tool_result",
                    raw_type="tool_result",
                    call_id=_stringify_value(block.get("tool_use_id")),
                    summary=summary or "工具调用已返回",
                    payload={
                        "content": raw_content,
                        "is_error": bool(block.get("is_error")),
                    },
                )
            )
        return

    trace.append(
        _trace_event(
            "unknown",
            raw_type=item_type or "unknown",
            summary=_safe_json_dumps(item),
            payload=item,
        )
    )


def load_native_transcript(provider: str, transcript_path: Path, *, session_id: str) -> list[dict[str, Any]]:
    if not transcript_path.is_file():
        return []

    turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None
    turn_index = 0

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
            finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {})
            if finalized is not None:
                turns.append(finalized)
                turn_index += 1
            current_turn = _new_turn_state(item.get("content"), timestamp)
            continue

        if provider == "claude" and item_type == "user":
            user_text = _extract_claude_user_text(item)
            if user_text:
                finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {})
                if finalized is not None:
                    turns.append(finalized)
                    turn_index += 1
                current_turn = _new_turn_state(user_text, timestamp)

        if current_turn is None:
            current_turn = _new_turn_state(created_at=timestamp)

        _touch_turn(current_turn, timestamp)
        if provider == "codex":
            _consume_codex_line(item, current_turn)
        else:
            _consume_claude_line(item, current_turn)

    finalized = _finalize_turn(provider, session_id, turn_index, current_turn or {})
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
    if not event_type.startswith("item."):
        return []

    payload = item.get("item") if isinstance(item.get("item"), dict) else {}
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
    _consume_claude_line(item, turn)
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
