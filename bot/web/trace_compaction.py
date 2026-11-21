"""Compact transport projections of CLI trace events.

Tool results routinely carry megabytes of output, while the transcript only
shows a one-line summary until an entry is expanded. A client that asks for
compact trace events receives a capped summary and payload preview plus the
original sizes, and reads the full event on demand (``get_message_trace_event``).

The projection never touches what is persisted. The same event must project
the same way whether it is streamed live or read from history, because the
client matches the two by summary; so only tool events with a ``call_id`` get
a capped summary, and an event that the client could not address later (no
row id and no tool ``call_id``) is left intact.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

TRACE_PAYLOAD_PREVIEW_CHARS = 1500
TRACE_SUMMARY_PREVIEW_CHARS = 500

_TOOL_KINDS = frozenset({"tool_call", "tool_result"})
# History reads show tool calls with these raw types under another kind
# (``PROCESS_TRACE_RAW_TYPES`` in chat_store); keep their summaries whole in both forms.
REMAPPED_PROCESS_RAW_TYPES = frozenset({"file.edited", "file.watcher.updated"})
# Bounds for work done per event on the event loop.
_ESTIMATE_NODE_LIMIT = 20_000
_PREVIEW_MAX_DEPTH = 24


def estimate_json_chars(value: Any, *, node_limit: int = _ESTIMATE_NODE_LIMIT) -> int:
    """Approximate the serialized size of a JSON value without serializing it.

    The walk stops after ``node_limit`` values, so for a payload made of very many
    small values the result is a lower bound; that is enough to rank versions of an
    event and to decide whether it exceeds the preview limit.
    """
    total = 0
    visited = 0
    stack = [value]
    while stack:
        item = stack.pop()
        visited += 1
        if isinstance(item, str):
            total += len(item) + 2
        elif isinstance(item, dict):
            total += 2
            for key, child in item.items():
                total += len(str(key)) + 4
                stack.append(child)
        elif isinstance(item, (list, tuple)):
            total += 2 + len(item)
            stack.extend(item)
        elif item is None or isinstance(item, bool):
            total += 5
        else:
            total += 8
        if visited >= node_limit:
            break
    return total


def _preview(value: Any, budget: list[int], depth: int) -> Any:
    """Head of a JSON value in document order.

    Text is cut and later items are dropped once ``budget`` characters are spent, so
    the work is proportional to the preview, not to the payload.
    """
    if isinstance(value, str):
        if len(value) <= budget[0]:
            budget[0] -= len(value)
            return value
        text = value[: max(0, budget[0])]
        budget[0] = 0
        return text
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        if depth >= _PREVIEW_MAX_DEPTH:
            return result
        for key, child in value.items():
            if budget[0] <= 0:
                break
            budget[0] -= len(str(key)) + 4
            result[key] = _preview(child, budget, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        items: list[Any] = []
        if depth >= _PREVIEW_MAX_DEPTH:
            return items
        for child in value:
            if budget[0] <= 0:
                break
            budget[0] -= 2
            items.append(_preview(child, budget, depth + 1))
        return items
    budget[0] -= 5
    return value


def is_trace_event_addressable(event: Mapping[str, Any]) -> bool:
    """Whether the client can read this event back: by row id, or by tool kind and call_id."""
    if str(event.get("id") or "").strip():
        return True
    return _has_tool_call_ref(event)


def _has_tool_call_ref(event: Mapping[str, Any]) -> bool:
    return (
        str(event.get("kind") or "").strip() in _TOOL_KINDS
        and bool(str(event.get("call_id") or "").strip())
    )


def _compact(event: Mapping[str, Any], payload_limit: int, summary_limit: int) -> Any:
    compact: dict[str, Any] | None = None
    summary = event.get("summary")
    if (
        isinstance(summary, str)
        and len(summary) > summary_limit
        and _has_tool_call_ref(event)
        and str(event.get("raw_type") or "") not in REMAPPED_PROCESS_RAW_TYPES
    ):
        compact = dict(event)
        compact["summary"] = summary[:summary_limit]
        compact["summary_chars"] = len(summary)

    payload = event.get("payload")
    if payload is not None:
        payload_chars = estimate_json_chars(payload)
        if payload_chars > payload_limit:
            if compact is None:
                compact = dict(event)
            compact["payload"] = _preview(payload, [payload_limit], 0)
            compact["payload_chars"] = payload_chars

    if compact is None:
        return event
    compact["content_truncated"] = True
    return compact


def compact_trace_event(
    event: Any,
    *,
    payload_limit: int = TRACE_PAYLOAD_PREVIEW_CHARS,
    summary_limit: int = TRACE_SUMMARY_PREVIEW_CHARS,
) -> Any:
    """Return ``event`` unchanged when it is small, else a capped copy with size markers."""
    if not isinstance(event, Mapping) or not is_trace_event_addressable(event):
        return event
    try:
        return _compact(event, payload_limit, summary_limit)
    except Exception:  # pragma: no cover - a projection must never fail the stream or the read
        logger.debug("过程事件压缩失败，按完整事件发送", exc_info=True)
        return event


def compact_trace_events(events: Iterable[Any]) -> list[Any]:
    return [compact_trace_event(event) for event in events]
