"""Persist Codex realtime voice turns independently of the browser socket."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from typing import Any

from bot.codex_server.voice import voice_handoff_has_input
from bot.models import BotProfile, UserSession
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatTurnHandle


_TERMINAL_METHODS = {"turn/completed", "turn/failed", "runtime/error", "runtime/closed"}
_TRACE_ITEM_MARKERS = (
    "commandexecution",
    "mcptoolcall",
    "dynamictoolcall",
    "websearch",
    "filechange",
    "collabagenttoolcall",
)


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "transcript", "output_text", "value", "content", "message"):
            if key in value:
                result = _text(value.get(key))
                if result:
                    return result
    return ""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def _safe_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep protocol identifiers and small status fields, never audio/SDP/payload blobs."""
    allowed = {
        "type", "id", "itemId", "item_id", "turnId", "turn_id", "status", "phase", "name",
        "tool", "server", "command", "exitCode", "exit_code", "arguments", "result", "error",
        "contentItems", "content_items", "realtimeSessionId", "realtime_session_id",
    }
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key in {"arguments", "result", "error", "contentItems", "content_items"}:
            # These fields are useful for trace display, but bound their size and remove binary data.
            value = _safe_event_payload(_record(value)) if isinstance(value, dict) else _text(value)[:4000]
        elif isinstance(value, str):
            value = value[:4000]
        result[key] = value
    return result


def _item_role(item: dict[str, Any], method: str) -> str:
    kind = str(item.get("type") or "").replace("_", "").replace("-", "").lower()
    method_key = method.replace("_", "").replace("-", "").lower()
    if "agentmessage" in method_key or kind in {"agentmessage", "assistantmessage", "assistant"}:
        return "assistant"
    if "usermessage" in method_key or "transcription" in method_key or kind in {
        "usermessage", "user", "inputaudiotranscription", "audiotranscription",
    }:
        return "user"
    role = str(item.get("role") or "").strip().lower()
    return role if role in {"user", "assistant"} else ""


def _event_id(method: str, payload: dict[str, Any], turn_id: str, item_id: str) -> str:
    nested = _record(payload.get("event"))
    value = payload.get("eventId") or payload.get("event_id") or nested.get("eventId") or nested.get("event_id")
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    stable = {
        "method": method,
        "turn_id": turn_id,
        "item_id": item_id,
        "payload": _safe_event_payload(payload),
        "text": _text(payload.get("delta") or payload.get("transcript") or payload.get("text"))[:4000],
    }
    return "voice:" + hashlib.sha256(_canonical_json(stable).encode("utf-8")).hexdigest()[:48]


def _turn_id(payload: dict[str, Any], runtime: Any) -> str:
    turn = _record(payload.get("turn"))
    return str(payload.get("turnId") or payload.get("turn_id") or turn.get("id")
               or getattr(runtime, "voice_turn_id", "") or "").strip()


def _realtime_session_id(payload: dict[str, Any], runtime: Any) -> str:
    item = _record(payload.get("item"))
    return str(payload.get("realtimeSessionId") or payload.get("realtime_session_id")
               or item.get("realtimeSessionId") or getattr(getattr(runtime, "voice_lease", None),
                                                             "realtime_session_id", "") or "").strip()


def _transcript_event(method: str, payload: dict[str, Any], item_id: str) -> tuple[str, str, bool] | None:
    item = _record(payload.get("item"))
    role = _item_role(item, method)
    method_key = method.replace("_", "").replace("-", "").lower()
    has_transcript_marker = any(marker in method_key for marker in (
        "transcript", "transcription", "agentmessagedelta", "usermessagedelta",
    ))
    if not role and not has_transcript_marker:
        return None
    if not role:
        role = "assistant" if "agent" in method_key or "output" in method_key else "user"
    value = payload.get("delta")
    if value is None:
        value = payload.get("transcript", payload.get("text"))
    if value is None:
        value = item.get("delta", item.get("transcript", item.get("text", item.get("content"))))
    transcript = _text(value)
    if not transcript:
        return None
    final = method in {"item/completed", "item/complete", "transcript.completed", "response.audio_transcript.done"}
    final = final or bool(payload.get("final") or payload.get("isFinal") or payload.get("is_final"))
    return role, transcript[:4 * 1024 * 1024], final


def _terminal_state(method: str, payload: dict[str, Any]) -> tuple[str, str, str] | None:
    if method == "runtime/error":
        error = _record(payload.get("error"))
        return "unknown", "runtime_error", _text(error or payload.get("message")) or "语音运行时错误，结果待确认"
    if method == "runtime/closed":
        return "unknown", "runtime_closed", "语音运行时已关闭，结果待确认"
    if method not in {"turn/completed", "turn/failed"}:
        return None
    turn = _record(payload.get("turn"))
    status = str(turn.get("status") or payload.get("status") or "").strip().lower()
    if method == "turn/completed" and status in {"", "completed", "complete", "success", "succeeded"}:
        return "completed", "", ""
    if status in {"interrupted", "cancelled", "canceled"}:
        return "interrupted", "interrupted", "语音任务已中断"
    error = _text(turn.get("error") or payload.get("error"))
    return "failed", "voice_turn_failed", error or "语音任务失败"


@dataclass
class VoiceTaskPersistence:
    """Runtime-owned coordinator; the browser is only a subscriber."""

    service: ChatHistoryService
    profile: BotProfile
    session: UserSession
    conversation_id: str
    runtime: Any
    actor: dict[str, Any] | None = None
    handle: ChatTurnHandle | None = None
    task_submission_key: str = ""
    codex_turn_id: str = ""
    realtime_session_id: str = ""
    state: str = "idle"
    transcript_state: str = "syncing"
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _seen_event_ids: set[str] = field(default_factory=set, repr=False)
    _transcripts: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _terminal_seen: bool = False
    _completed: bool = False
    _handoff_pending: bool = field(default=False, repr=False)
    _steer_results: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def cached_steer_result(self, request_id: str) -> dict[str, Any] | None:
        normalized = str(request_id or "").strip()
        result = self._steer_results.get(normalized) if normalized else None
        return dict(result) if result is not None else None

    def cache_steer_result(self, request_id: str, result: dict[str, Any]) -> None:
        normalized = str(request_id or "").strip()
        if not normalized:
            return
        self._steer_results[normalized] = dict(result)
        if len(self._steer_results) > 256:
            self._steer_results.pop(next(iter(self._steer_results)))

    async def _call(self, function, *args, **kwargs):
        result = await asyncio.to_thread(function, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _publish_task(self) -> None:
        if self.handle is None:
            return
        self.runtime.voice_events.publish({
            "type": "voice.task",
            "tcb_turn_id": self.handle.turn_id,
            "assistant_message_id": self.handle.assistant_message_id,
            "user_message_id": self.handle.user_message_id,
            "conversation_id": self.handle.conversation_id,
            "codex_turn_id": self.codex_turn_id,
            "realtime_session_id": self.realtime_session_id,
            "task_submission_key": self.task_submission_key,
            "state": self.state,
            "transcript_state": self.transcript_state,
            "session_epoch": max(0, int(getattr(self.session, "session_epoch", 0) or 0)),
        })

    async def _ensure(self, turn_id: str, realtime_session_id: str) -> None:
        if self.handle is not None:
            return
        if not turn_id:
            return
        self.codex_turn_id = turn_id
        self.realtime_session_id = realtime_session_id
        self.task_submission_key = ":".join((str(getattr(self.runtime, "thread_id", "")), realtime_session_id, turn_id))
        ensure_kwargs = {
            "bot_alias": self.profile.alias,
            "conversation_id": self.conversation_id,
            "task_submission_key": self.task_submission_key,
            "codex_turn_id": turn_id,
            "realtime_session_id": realtime_session_id,
            "actor": self.actor,
        }
        try:
            parameters = inspect.signature(self.service.ensure_voice_turn).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "conversation_id" not in parameters:
            ensure_kwargs.pop("conversation_id", None)
        self.handle = await self._call(self.service.ensure_voice_turn, self.session, **ensure_kwargs)
        self.state = "active"
        with self.session._lock:
            self.session.is_processing = True
            self.session.running_user_text = "语音输入"
            if self.session.running_started_at is None:
                from datetime import datetime
                self.session.running_started_at = datetime.now().isoformat()
            self.session.running_updated_at = self.session.running_started_at
        self.session.persist_debounced()
        self._publish_task()

    async def observe(self, packet: dict[str, Any]) -> None:
        payload = _record(packet.get("params"))
        if payload.get("threadId") and str(payload.get("threadId")) != str(getattr(self.runtime, "thread_id", "")):
            return
        method = str(packet.get("method") or "").strip()
        if method == "thread/realtime/itemAdded":
            if voice_handoff_has_input(payload):
                self._handoff_pending = True
            return
        if method in {"thread/realtime/closed", "thread/realtime/error", "runtime/closed", "runtime/error"}:
            self._handoff_pending = False
        turn_id = _turn_id(payload, self.runtime)
        realtime_session_id = _realtime_session_id(payload, self.runtime)
        if self.handle is not None and self._terminal_seen and turn_id and turn_id != self.codex_turn_id:
            # A single realtime session can contain multiple Codex turns.
            # Retain the completed row in ChatStore and start a fresh binding.
            self.handle = None
            self.task_submission_key = ""
            self.codex_turn_id = ""
            self.realtime_session_id = ""
            self.state = "idle"
            self.transcript_state = "syncing"
            self._seen_event_ids.clear()
            self._transcripts.clear()
            self._terminal_seen = False
            self._completed = False
        if turn_id and not self.handle and self._handoff_pending:
            await self._ensure(turn_id, realtime_session_id)
            self._handoff_pending = False
        if self.handle is None:
            return
        async with self._lock:
            if turn_id and self.codex_turn_id and turn_id != self.codex_turn_id:
                return
            if realtime_session_id and not self.realtime_session_id:
                self.realtime_session_id = realtime_session_id
            item = _record(payload.get("item"))
            item_id = str(payload.get("itemId") or payload.get("item_id") or item.get("id") or "").strip()
            event_id = _event_id(method, payload, self.codex_turn_id, item_id)
            terminal = _terminal_state(method, payload)
            transcript = _transcript_event(method, payload, item_id)
            event: dict[str, Any] = {
                "event_id": event_id,
                "seq": int(getattr(getattr(self.runtime, "voice_events", None), "sequence", 0) or 0),
                "event_name": method,
                "codex_turn_id": self.codex_turn_id,
                "native_session_id": str(getattr(self.runtime, "thread_id", "") or ""),
                "realtime_session_id": self.realtime_session_id,
                "item_id": item_id,
                "role": transcript[0] if transcript else "",
                "transcript_text": "",
                "transcript_final": False,
            }
            if transcript:
                role, text, is_final = transcript
                key = (role, item_id)
                if method.endswith("delta"):
                    text = self._transcripts.get(key, "") + text
                self._transcripts[key] = text
                event.update({"role": role, "transcript_text": text, "transcript_final": is_final})
                self.transcript_state = "syncing"
            elif method in {"turn/completed", "turn/failed"}:
                # Some app-server versions only include final message items on the
                # terminal turn notification.
                final_user = ""
                final_assistant = ""
                for raw_item in _record(payload.get("turn")).get("items") or []:
                    item_value = _record(raw_item)
                    item_value_id = str(item_value.get("id") or "").strip()
                    item_transcript = _transcript_event("item/completed", {"item": item_value}, item_value_id)
                    if not item_transcript:
                        continue
                    item_role, item_text, _ = item_transcript
                    self._transcripts[(item_role, item_value_id)] = item_text
                    if item_role == "assistant":
                        final_assistant = item_text
                    elif item_role == "user":
                        final_user = item_text
                if final_assistant:
                    event.update({"role": "assistant", "item_id": item_id, "transcript_text": final_assistant,
                                  "transcript_final": True})
                elif final_user:
                    event.update({"role": "user", "item_id": item_id, "transcript_text": final_user,
                                  "transcript_final": True})
            if method.startswith("item/") and any(marker in method.replace("_", "").lower() for marker in _TRACE_ITEM_MARKERS):
                kind = "tool_result" if method.endswith("completed") else "tool_call"
                event["trace_events"] = [{
                    "kind": kind,
                    "raw_type": method,
                    "title": str(item.get("type") or method),
                    "tool_name": str(item.get("tool") or item.get("name") or item.get("type") or ""),
                    "call_id": item_id,
                    "summary": _text(item.get("result") or item.get("command") or item.get("status") or method)[:4000],
                    "payload": _safe_event_payload(item),
                }]
            if terminal:
                state, code, message = terminal
                if not self._terminal_seen:
                    self._terminal_seen = True
                    self.state = state
                    event.update({"task_state": state, "terminal_code": code, "terminal_message": message})
            if event_id not in self._seen_event_ids:
                self._seen_event_ids.add(event_id)
                if len(self._seen_event_ids) > 4096:
                    self._seen_event_ids.pop()
                # Terminal state, transcript and identifiers are committed by
                # record_voice_event in one transaction. The explicit complete
                # call below remains an idempotent compatibility fallback.
                await self._call(self.service.record_voice_event, self.handle, event)
            if terminal and self._terminal_seen and not self._completed and self.state in {"completed", "failed", "interrupted", "unknown"}:
                self._completed = True
                content = ""
                for (role, _item_id), text in self._transcripts.items():
                    if role == "assistant" and text:
                        content = text
                state = self.state
                await self._call(
                    self.service.complete_voice_turn,
                    self.handle,
                    content=content,
                    completion_state=state,
                    native_session_id=str(getattr(self.runtime, "thread_id", "") or ""),
                    error_code=event.get("terminal_code") or None,
                    error_message=event.get("terminal_message") or None,
                )
                self.transcript_state = "saved"
                with self.session._lock:
                    self.session.is_processing = False
                    self.session.running_user_text = None
                    self.session.running_preview_text = ""
                    self.session.running_started_at = None
                    self.session.running_updated_at = None
                self.session.persist_debounced()
                self._publish_task()

    async def close(self, *, unknown: bool = True, message: str = "语音运行时已关闭，结果待确认") -> None:
        if self.handle is None or self._terminal_seen:
            return
        packet = {"method": "runtime/closed", "params": {"threadId": getattr(self.runtime, "thread_id", ""),
                                                            "message": message}}
        await self.observe(packet)


__all__ = ["VoiceTaskPersistence"]
