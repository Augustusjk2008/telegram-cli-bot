"""Translate v2 app-server notifications into the existing Codex JSON consumers."""
from __future__ import annotations

import json
from typing import Any


TOKEN_FIELDS = {
    "inputTokens": "input_tokens", "cachedInputTokens": "cached_input_tokens",
    "cacheWriteInputTokens": "cache_write_input_tokens", "outputTokens": "output_tokens",
    "reasoningOutputTokens": "reasoning_output_tokens", "totalTokens": "total_tokens",
}


def tokens(value: dict[str, Any]) -> dict[str, int]:
    return {out: max(0, value.get(key, 0)) if type(value.get(key, 0)) is int else 0
            for key, out in TOKEN_FIELDS.items()}


class CodexServerEventMapper:
    def __init__(self, thread_id: str, baseline: dict[str, int] | None, *, text_limit: int = 4 * 1024 * 1024):
        self.thread_id = thread_id
        self.turn_id = ""
        self.baseline = baseline
        self.total_usage = baseline
        self.usage: dict[str, int] | None = None
        self.context_usage: dict[str, Any] = {}
        self.done = False
        self.text_limit = text_limit
        self._items: set[tuple[str, str]] = set()
        self._text: dict[str, str] = {}
        self._phases: dict[str, str] = {}
        self._final: str = ""
        self._candidate: str = ""
        self._compactions: set[str] = set()

    def _usage(self, payload: dict) -> None:
        usage = payload.get("tokenUsage") or {}
        total = tokens(usage.get("total") or {})
        last = tokens(usage.get("last") or {})
        if self.baseline is None:
            # Resumed transcripts may predate token persistence. The first new
            # inference establishes the historical prefix, never charging it.
            self.baseline = {key: max(0, total[key] - last[key]) for key in total}
        previous = self.total_usage or self.baseline
        if any(total[key] < previous.get(key, 0) for key in ("input_tokens", "output_tokens")):
            return  # stale/out-of-order cumulative snapshot
        self.total_usage = total
        self.usage = {key: max(0, total[key] - self.baseline.get(key, 0)) for key in total}
        window = usage.get("modelContextWindow")
        used = last["total_tokens"]
        if type(window) is int and window > 0:
            available = max(1, window - 12000)
            left = max(0, min(100, int((available - max(0, used - 12000)) / available * 100 + .5)))
            self.context_usage.update({
                "provider": "codex", "source": "codex_server_token_count", "session_id": self.thread_id,
                "used_tokens": used, "context_window": window, "context_left_percent": left,
                "used_display": str(used), "window_display": str(window),
                "status_text": f"{left}% context left · {used} / {window}",
            })

    def consume(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        if self.done:
            return []
        method, payload = packet.get("method"), packet.get("params") or {}
        if payload.get("threadId") != self.thread_id:
            return []
        incoming_turn = payload.get("turnId") or (payload.get("turn") or {}).get("id")
        if self.turn_id and incoming_turn and incoming_turn != self.turn_id:
            return []
        if method == "turn/started":
            self.turn_id = str(incoming_turn or "")
            return []
        if method == "thread/tokenUsage/updated":
            self._usage(payload)
            return []
        if method == "item/agentMessage/delta":
            item_id = str(payload.get("itemId") or "")
            if ("item/completed", item_id) in self._items:
                return []
            delta = str(payload.get("delta") or "")
            text = self._text.get(item_id, "") + delta
            self._text[item_id] = text[-self.text_limit:]
            return [{"type": "item.delta", "item": {"id": item_id, "type": "agent_message", "delta": delta,
                                                      "phase": self._phases.get(item_id)}}]
        if method in {"item/started", "item/completed"}:
            return self._item(method, payload.get("item") or {})
        if method == "turn/completed":
            turn = payload.get("turn") or {}
            result = []
            for item in turn.get("items") or []:
                result.extend(self._item("item/completed", item))
            status = turn.get("status")
            error = (turn.get("error") or {}).get("message")
            result.extend(self.finish(status=status, error=error))
            return result
        if method == "error":
            error = payload.get("error") or {}
            # Retry notices must not turn a subsequently successful turn into a failure.
            if payload.get("willRetry"):
                return [{"type": "event_msg", "payload": {"type": "retry", "message": str(error.get("message") or error)}}]
            return [{"type": "error", "message": str(error.get("message") or error)}]
        return []

    def _item(self, method: str, item: dict) -> list[dict]:
        item_id, kind = str(item.get("id") or ""), item.get("type")
        key = (method, item_id)
        if key in self._items:
            return []
        self._items.add(key)
        completed = method == "item/completed"
        if kind == "agentMessage":
            phase = str(item.get("phase") or "")
            self._phases[item_id] = phase
            if not completed:
                return []
            text = str(item.get("text") or self._text.get(item_id) or "")[-self.text_limit:]
            self._text[item_id] = text
            if phase == "commentary":
                # Trace consumers see this, while the body parser does not append
                # the completed copy of text whose deltas it already received.
                return [{"type": "event_msg", "payload": {"type": "commentary", "message": text}}]
            if phase in {"final_answer", "final"}:
                self._final = text
            else:
                self._candidate = text
            return []
        if kind == "commandExecution":
            return [{"type": "item.completed" if completed else "item.started", "item": {
                "type": "command_execution", "id": item_id, "command": item.get("command", ""),
                "aggregated_output": item.get("aggregatedOutput", ""), "exit_code": item.get("exitCode"),
                "status": item.get("status", ""),
            }}]
        if kind == "contextCompaction" and completed:
            self._compactions.add(item_id)
            self.context_usage["compaction_count"] = len(self._compactions)
            return [{"type": "event_msg", "payload": {"type": "context_compacted", "message": "Context compacted"}}]
        if kind in {"fileChange", "mcpToolCall", "dynamicToolCall", "webSearch", "collabAgentToolCall"}:
            name = {"fileChange": "apply_patch", "webSearch": "web_search"}.get(kind) or item.get("tool") or kind
            if kind == "mcpToolCall":
                name = f"mcp__{item.get('server', '')}__{name}"
            arguments = item.get("arguments", item.get("changes", item.get("action", {"query": item.get("query")})))
            result = []
            if not completed or ("item/started", item_id) not in self._items:
                result.append({"type": "item.completed", "item": {"type": "function_call", "call_id": item_id,
                               "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}})
            if completed:
                output = item.get("error") or item.get("result") or item.get("contentItems") or item
                result.append({"type": "item.completed", "item": {"type": "function_call_output", "call_id": item_id,
                               "output": json.dumps(output, ensure_ascii=False)}})
            return result
        if kind in {"reasoning", "plan"} and completed:
            text = item.get("text") or "\n".join(item.get("summary") or item.get("content") or [])
            return [{"type": "event_msg", "payload": {"type": kind, "message": text}}] if text else []
        return []

    def finish(self, *, status: str = "failed", error: str | None = None) -> list[dict]:
        if self.done:
            return []
        self.done = True
        result = []
        partial = next((text for key, text in reversed(list(self._text.items())) if self._phases.get(key) != "commentary"), "")
        text = self._final or self._candidate or partial
        if text:
            result.append({"type": "response_item", "payload": {"type": "message", "role": "assistant",
                           "phase": "final_answer", "content": [{"type": "output_text", "text": text}]}})
        success = status == "completed"
        if not success:
            result.append({"type": "error", "message": error or ("Codex turn interrupted" if status == "interrupted" else "Codex turn failed")})
        terminal = {"type": "turn.completed" if success else "turn.failed", "status": status,
                    "thread_id": self.thread_id, "turn_id": self.turn_id}
        if self.usage is not None:
            terminal["usage"] = dict(self.usage)
        result.append(terminal)
        return result
