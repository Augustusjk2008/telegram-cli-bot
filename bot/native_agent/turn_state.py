from __future__ import annotations

import inspect
from dataclasses import dataclass, field
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
    final_candidate_first_seen_at: float = 0.0
    final_candidate_seen_at: float = 0.0
    final_candidate_message_id: str = ""
    final_candidate_message_ids: set[str] = field(default_factory=set)

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
        candidate = _completed_assistant_message_from_event(event)
        if candidate:
            self.observe_final_candidate(candidate, now=now)

    def observe_final_candidate(self, message: dict[str, Any], *, now: float) -> None:
        message_id = _message_id(message)
        key = message_id or f"candidate-{len(self.final_candidate_message_ids) + 1}"
        if key not in self.final_candidate_message_ids:
            self.final_candidate_message_ids.add(key)
        if message_id:
            self.final_candidate_message_id = message_id
        if not self.final_candidate_first_seen_at:
            self.final_candidate_first_seen_at = now
        self.final_candidate_seen_at = now

    def has_final_candidate(self) -> bool:
        return bool(self.final_candidate_first_seen_at)

    def final_candidate_should_reconcile(
        self,
        *,
        now: float,
        force: bool = False,
        completed_count: int = 2,
        grace_seconds: float = 2.0,
        max_seconds: float = 4.0,
    ) -> bool:
        if force:
            return self.has_final_candidate() or self.has_text
        if not self.has_final_candidate():
            return False
        if len(self.final_candidate_message_ids) >= completed_count:
            return True
        age = now - self.final_candidate_first_seen_at
        return age >= max_seconds or age >= grace_seconds

    def should_reconcile(self, *, now: float, force: bool = False, interval_seconds: float = 0.35) -> bool:
        if force:
            return True
        if self.done:
            return False
        return now - self.last_reconcile_at >= interval_seconds

    async def maybe_reconcile(
        self,
        list_messages: ListMessages,
        aggregator: NativeAgentAggregator,
        *,
        now: float,
        require_completed_assistant: bool = False,
        through_message_id: str = "",
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

        current_messages = self.current_turn_messages(messages, through_message_id=through_message_id)
        if not current_messages:
            return {"done": False, "text": ""}

        text = aggregator.reconcile_messages(current_messages, require_completed=require_completed_assistant)
        trace = aggregator.pop_reconciled_trace()
        assistant = _last_completed_assistant_message(current_messages) if require_completed_assistant else _last_assistant_message(current_messages)
        if text:
            self.has_text = True
        if assistant:
            message_id = _message_id(assistant)
            if message_id:
                self.assistant_message_id = message_id
        result = {"done": self.done, "text": text}
        if trace:
            result["trace"] = trace
        if assistant and _message_completed(assistant):
            self.done = True
            result["done"] = True
        return result

    def current_turn_messages(self, messages: list[dict[str, Any]], *, through_message_id: str = "") -> list[dict[str, Any]]:
        if not messages:
            return []
        user_index = _find_message_index(messages, self.user_message_id)
        if user_index >= 0:
            return _truncate_messages(
                _filter_messages_for_user_parent(messages[user_index + 1 :], self.user_message_id),
                through_message_id,
            )
        assistant_index = _find_message_index(messages, self.assistant_message_id)
        if assistant_index >= 0:
            return _truncate_messages(
                _filter_messages_for_user_parent(messages[assistant_index:], self.user_message_id),
                through_message_id,
            )
        baseline = max(0, int(self.baseline_message_count or 0))
        if self.baseline_known and len(messages) > baseline:
            return _truncate_messages(
                _filter_messages_for_user_parent(messages[baseline:], self.user_message_id),
                through_message_id,
            )
        return []


def _last_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role") or "").lower() == "assistant":
            return message
    return {}


def _last_completed_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() == "assistant" and _message_completed(message):
            return message
    return {}


def _completed_assistant_message_from_event(event: NativeAgentEvent) -> dict[str, Any]:
    if event.type != "message.updated":
        return {}
    message = _message_from_event(event)
    if str(message.get("role") or "").lower() != "assistant":
        return {}
    if not _message_completed(message):
        return {}
    message_id = _message_id(message) or event.message_id
    if message_id and not _message_id(message):
        message = {**message, "id": message_id}
    return message


def _message_from_event(event: NativeAgentEvent) -> dict[str, Any]:
    payload = event.payload
    message = payload.get("message")
    if isinstance(message, dict):
        return dict(message)
    properties = payload.get("properties")
    if isinstance(properties, dict):
        message = properties.get("message") or properties.get("info")
        if isinstance(message, dict):
            return dict(message)
    info = payload.get("info")
    if isinstance(info, dict):
        return dict(info)
    return dict(payload)


def _message_completed(message: dict[str, Any]) -> bool:
    if _message_expects_followup(message):
        return False
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    if finish in {"stop", "stopped", "complete", "completed", "done", "success", "end", "finished"}:
        return True
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


def _message_parent_id(message: dict[str, Any]) -> str:
    for key in ("parentID", "parent_id", "parentId"):
        value = message.get(key)
        if value:
            return str(value)
    return ""


def _filter_messages_for_user_parent(messages: list[dict[str, Any]], user_message_id: str) -> list[dict[str, Any]]:
    target = str(user_message_id or "").strip()
    if not target:
        return messages
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        parent_id = _message_parent_id(message)
        if role == "assistant" and parent_id and parent_id != target:
            continue
        filtered.append(message)
    return filtered


def _find_message_index(messages: list[dict[str, Any]], message_id: str) -> int:
    target = str(message_id or "").strip()
    if not target:
        return -1
    for index, message in enumerate(messages):
        if isinstance(message, dict) and _message_id(message) == target:
            return index
    return -1


def _truncate_messages(messages: list[dict[str, Any]], through_message_id: str) -> list[dict[str, Any]]:
    target = str(through_message_id or "").strip()
    if not target:
        return messages
    index = _find_message_index(messages, target)
    if index < 0:
        return []
    return messages[: index + 1]
