from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from bot.native_agent.aggregator import NativeAgentAggregationResult, NativeAgentAggregator
from bot.native_agent.events import NativeAgentEvent

ListMessages = Callable[[str], Awaitable[list[dict[str, Any]]] | list[dict[str, Any]]]


@dataclass
class NativeAgentTurnState:
    native_session_id: str
    user_message_id: str
    assistant_message_id: str = ""
    baseline_message_count: int = 0
    baseline_known: bool = False
    has_text: bool = False
    done: bool = False
    completion_state: str = "completed"
    last_non_transport_at: float = 0.0
    last_reconcile_at: float = 0.0
    reconcile_attempts: int = 0
    stable_reconcile_count: int = 0
    last_reconcile_text: str = ""
    max_stable_reconciles: int = 2

    def observe(self, event: NativeAgentEvent, result: NativeAgentAggregationResult, *, now: float) -> None:
        if not event.transport:
            self.last_non_transport_at = now
        if result.assistant_message_id:
            self.assistant_message_id = result.assistant_message_id
        if result.delta or result.snapshot:
            self.has_text = True
        if result.error:
            self.completion_state = "error"
            self.done = True
        if result.done:
            self.done = True

    def should_reconcile(self, *, now: float, force: bool = False, interval_seconds: float = 0.35) -> bool:
        if self.done:
            return False
        if force:
            return True
        return now - self.last_reconcile_at >= interval_seconds

    async def maybe_reconcile(
        self,
        list_messages: ListMessages,
        aggregator: NativeAgentAggregator,
        *,
        now: float,
    ) -> dict[str, Any]:
        self.last_reconcile_at = now
        self.reconcile_attempts += 1
        messages_result = list_messages(self.native_session_id)
        if inspect.isawaitable(messages_result):
            messages = await messages_result
        else:
            messages = messages_result
        if not isinstance(messages, list):
            return {"done": False, "text": ""}

        current_messages = self.current_turn_messages(messages)
        if not current_messages:
            return {"done": False, "text": ""}

        text = aggregator.reconcile_messages(current_messages)
        assistant = _last_assistant_message(current_messages)
        if text:
            self.has_text = True
        if assistant:
            message_id = _message_id(assistant)
            if message_id:
                self.assistant_message_id = message_id
        if assistant and _message_completed(assistant):
            self.done = True
            return {"done": True, "text": text}

        if not text:
            self.last_reconcile_text = ""
            self.stable_reconcile_count = 0
            return {"done": False, "text": ""}
        if assistant and _message_expects_followup(assistant):
            self.last_reconcile_text = text
            self.stable_reconcile_count = 0
            return {"done": False, "text": ""}

        if text == self.last_reconcile_text:
            self.stable_reconcile_count += 1
        else:
            self.last_reconcile_text = text
            self.stable_reconcile_count = 1
        if self.has_text and self.stable_reconcile_count >= self.max_stable_reconciles:
            self.done = True
        return {"done": self.done, "text": text}

    def current_turn_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return []
        user_index = _find_message_index(messages, self.user_message_id)
        if user_index >= 0:
            return messages[user_index + 1 :]
        assistant_index = _find_message_index(messages, self.assistant_message_id)
        if assistant_index >= 0:
            return messages[assistant_index:]
        baseline = max(0, int(self.baseline_message_count or 0))
        if self.baseline_known and len(messages) > baseline:
            return messages[baseline:]
        return []


def _last_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role") or "").lower() == "assistant":
            return message
    return {}


def _message_completed(message: dict[str, Any]) -> bool:
    if _message_expects_followup(message):
        return False
    time_payload = message.get("time")
    if isinstance(time_payload, dict) and time_payload.get("completed"):
        return True
    for key in ("completed", "completed_at", "completedAt"):
        if message.get(key):
            return True
    state = str(message.get("state") or message.get("status") or "").strip().lower()
    return state in {"completed", "done", "idle", "success"}


def _message_expects_followup(message: dict[str, Any]) -> bool:
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    return finish in {"tool-calls", "tool_calls", "tool-call", "tool_call"}


def _message_id(message: dict[str, Any]) -> str:
    for key in ("id", "messageID", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)
    return ""


def _find_message_index(messages: list[dict[str, Any]], message_id: str) -> int:
    target = str(message_id or "").strip()
    if not target:
        return -1
    for index, message in enumerate(messages):
        if isinstance(message, dict) and _message_id(message) == target:
            return index
    return -1
