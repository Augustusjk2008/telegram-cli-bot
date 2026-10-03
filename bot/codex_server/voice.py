"""Memory-only realtime delivery and exclusive, client-bound voice leases."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .client import CodexServerUnknownOutcome

MAX_SDP_BYTES = 128_000
MAX_MESSAGE_BYTES = 160_000
MAX_REQUEST_IDS = 1024
VOICE_BUSY_MESSAGE = "当前有活动任务，语音任务/混合输入将在 M2 支持"
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_PRIVATE_KEY = re.compile(r"credential|secret|token|authorization|cookie|password|apikey|sdp|base64|^audio$|^audiodata$", re.I)


class VoiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def voice_capability(*, enabled: bool, cli_type: str, execution_mode: str,
                     can_send: bool, valid_session: bool = True) -> dict:
    reason = ("disabled" if not enabled else "unsupported_cli" if cli_type != "codex_server"
              else "unsupported_execution_mode" if execution_mode != "cli"
              else "forbidden" if not can_send else "invalid_session" if not valid_session else "available")
    return {"enabled": reason == "available", "reason": reason}


def validate_message(value: Any, seen: set[str]) -> dict:
    if not isinstance(value, dict):
        raise VoiceError("invalid_voice_message", "语音消息必须是 JSON 对象")
    request_id = value.get("id")
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise VoiceError("invalid_voice_request_id", "无效的语音操作 ID")
    if request_id in seen:
        raise VoiceError("duplicate_voice_request", "该操作 ID 已处理，不会重发", 409)
    if len(seen) >= MAX_REQUEST_IDS:
        raise VoiceError("voice_request_limit", "语音操作数量超过限制", 429)
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise VoiceError("voice_message_too_large", "语音消息超过大小限制", 413)
    op = value.get("op")
    fields = {"start": {"sdp"}, "stop_voice": set(), "summary": set(), "browser_event": {"name", "data"}}
    if not isinstance(op, str) or op not in fields:
        raise VoiceError("unknown_voice_operation", "不支持的语音操作")
    if set(value) - {"id", "op", *fields[op]}:
        raise VoiceError("invalid_voice_message", "不支持的语音字段；会话标识由服务器绑定")
    if op == "start":
        sdp = value.get("sdp")
        if not isinstance(sdp, str) or not sdp.startswith("v=0") or "\x00" in sdp:
            raise VoiceError("invalid_voice_sdp", "无效的 SDP offer")
        if len(sdp.encode("utf-8")) > MAX_SDP_BYTES:
            raise VoiceError("voice_sdp_too_large", "SDP offer 超过大小限制", 413)
    if op == "browser_event":
        if (not isinstance(value.get("name"), str) or not _ID.fullmatch(value["name"])
                or not isinstance(value.get("data", {}), dict)):
            raise VoiceError("invalid_browser_event", "无效的浏览器语音事件")
    seen.add(request_id)
    return value


def _public_event(value: Any, name: str = "") -> Any:
    if isinstance(value, dict):
        kind = str(value.get("type") or name)
        return {key: _public_event(child, kind) for key, child in value.items()
                if not _PRIVATE_KEY.search(key.replace("_", "").replace("-", ""))
                and not (key in {"data", "delta"} and isinstance(child, str)
                         and "audio" in kind.lower() and "transcript" not in kind.lower())}
    if isinstance(value, list):
        return [_public_event(child, name) for child in value]
    return value


class VoiceEvents:
    """Only the runtime's reader publishes protocol packets here."""
    def __init__(self):
        self.sequence = 0
        self.subscribers: set[asyncio.Queue] = set()
        self.instance_id = uuid.uuid4().hex

    def subscribe(self, *, maxsize: int = 64) -> asyncio.Queue:
        if len(self.subscribers) >= 4:
            raise VoiceError("voice_subscriber_limit", "语音订阅数量超过限制", 429)
        queue = asyncio.Queue(maxsize=max(1, min(maxsize, 64)))
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)
        while not queue.empty():
            queue.get_nowait()

    def publish(self, message: dict) -> int:
        self.sequence += 1
        event = {**message, "seq": self.sequence}
        oversized = len(json.dumps(event, ensure_ascii=False).encode("utf-8")) > MAX_MESSAGE_BYTES
        for queue in tuple(self.subscribers):
            if queue.full() or oversized:
                self.unsubscribe(queue)
                queue.put_nowait({"type": "voice.state", "seq": self.sequence, "state": "unknown",
                                  "code": "voice_slow_consumer", "terminal": True})
            else:
                queue.put_nowait(copy.deepcopy(event))
        return self.sequence

    def packet(self, packet: dict, thread_id: str) -> None:
        name, data = packet.get("method", ""), packet.get("params") or {}
        if not (name.startswith("thread/realtime/") or name.startswith("turn/")
                or name.startswith("item/") or name in {"runtime/error", "runtime/closed"}):
            return
        item, turn = data.get("item") or {}, data.get("turn") or {}
        if not isinstance(item, dict):
            item = {}
        if not isinstance(turn, dict):
            turn = {}
        nested = data.get("event") if isinstance(data.get("event"), dict) else {}
        event_id = data.get("eventId") or nested.get("event_id") or nested.get("eventId")
        self.publish({"type": "voice.event", "name": name,
                      "event_id": str(event_id or f"{self.instance_id}:{self.sequence + 1}"),
                      "thread_id": thread_id, "turn_id": str(data.get("turnId") or turn.get("id") or ""),
                      "realtime_session_id": str(data.get("realtimeSessionId") or item.get("realtimeSessionId") or ""),
                      "item_id": str(data.get("itemId") or item.get("id") or ""),
                      "data": _public_event(data, name)})


@dataclass
class VoiceLease:
    key: tuple[int, int, str, str]
    actor_id: tuple[str, int]
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    client_generation: str = field(default_factory=lambda: uuid.uuid4().hex)
    thread_id: str = ""
    realtime_session_id: str = ""
    state: str = "idle"
    last_seq: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    runtime: Any = field(default=None, repr=False)
    attached: bool = True
    _stop_attempted: bool = False
    _started: bool = False
    _closed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def owner_key(self) -> tuple[int, int, str]:
        return self.key[:3]

    def bind(self, runtime: Any) -> None:
        if (runtime.request.owner_key != self.owner_key or runtime.request.conversation_id != self.key[3]
                or not runtime.request.experimental_api):
            raise VoiceError("voice_session_changed", "语音会话绑定已失效", 409)
        if runtime.active:
            raise VoiceError("voice_task_active", VOICE_BUSY_MESSAGE, 409)
        self.runtime, self.thread_id = runtime, runtime.thread_id
        runtime.voice_lease = self

    def publish(self, message: dict) -> None:
        self.last_activity = time.time()
        self.last_seq = self.runtime.voice_events.publish({**message, "connection_id": self.connection_id})

    def summary(self, request_id: str = "") -> None:
        self.publish({"type": "voice.state", "state": self.state, "id": request_id,
                      "thread_id": self.thread_id, "realtime_session_id": self.realtime_session_id,
                      "client_generation": self.client_generation, "last_seq": self.last_seq})

    def transition(self, state: str) -> None:
        self.state = state
        if state == "closed":
            self._closed.set()
        self.summary()

    def observe(self, packet: dict) -> None:
        name, data = packet.get("method"), packet.get("params") or {}
        session_id = str(data.get("realtimeSessionId") or "")
        if session_id and self.realtime_session_id and session_id != self.realtime_session_id:
            return
        if name == "thread/realtime/started" and self.state in {"negotiating", "active"}:
            self.realtime_session_id = session_id
            self.transition("active")
        elif name == "thread/realtime/closed":
            self.transition("closed")
        elif name == "thread/realtime/error":
            self.transition("error")
        elif name in {"runtime/error", "runtime/closed"} and self.state != "closed":
            self.transition("unknown")
        elif name == "thread/realtime/sdp" and self.state in {"negotiating", "active"}:
            sdp = data.get("sdp")
            if isinstance(sdp, str) and len(sdp.encode("utf-8")) <= MAX_SDP_BYTES:
                self.publish({"type": "voice.sdp", "sdp": sdp})

    async def start(self, sdp: str) -> None:
        if self._started or self.state != "idle":
            raise VoiceError("voice_already_started", "该连接已启动，不会重发", 409)
        if self.runtime.active:
            raise VoiceError("voice_task_active", VOICE_BUSY_MESSAGE, 409)
        self._started = True
        self.transition("negotiating")
        try:
            await self.runtime.start_realtime(sdp)
        except BaseException as exc:
            self.transition("unknown" if isinstance(exc, (CodexServerUnknownOutcome, asyncio.CancelledError))
                            or not self.runtime.alive else "error")
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise VoiceError("voice_start_failed", "语音启动失败；请检查 Codex 0.159.2 兼容性和连接状态", 502) from exc

    async def stop_voice(self, *, timeout: float = 10) -> None:
        if not self._started or self.state == "closed":
            if self.state != "closed":
                self.transition("closed")
            return
        if self._stop_attempted:
            return
        self._stop_attempted = True
        self.transition("stopping")
        try:
            await self.runtime.stop_realtime()
            # An acknowledgement is not proof of closure.
            await asyncio.wait_for(self._closed.wait(), timeout)
        except BaseException as exc:
            if self.state != "closed":
                self.transition("unknown")
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def disconnect(self) -> None:
        try:
            if self.runtime is not None:
                await self.stop_voice()
        finally:
            self.attached = False


class VoiceLeaseRegistry:
    def __init__(self):
        self._leases: dict[tuple[int, int, str, str], VoiceLease] = {}
        self._lock = threading.RLock()

    def acquire(self, key: tuple[int, int, str, str], actor_id: tuple[str, int]) -> VoiceLease:
        with self._lock:
            for old_key, old in list(self._leases.items()):
                if not old.attached and (old.state == "closed" or old.runtime is None or not old.runtime.alive):
                    self._leases.pop(old_key)
            if key in self._leases:
                raise VoiceError("voice_connection_occupied", "当前会话已有语音连接", 409)
            if len(self._leases) >= 128:
                raise VoiceError("voice_connection_limit", "语音连接数量超过限制", 429)
            lease = VoiceLease(key, actor_id)
            self._leases[key] = lease
            return lease

    def owner_busy(self, owner_key: tuple[int, int, str]) -> bool:
        with self._lock:
            return any(lease.owner_key == owner_key and lease.state != "closed"
                       and (lease.attached or (lease.runtime is not None and lease.runtime.alive))
                       for lease in self._leases.values())

    def release(self, lease: VoiceLease) -> None:
        with self._lock:
            if self._leases.get(lease.key) is not lease or lease.state not in {"idle", "closed", "error"}:
                return
            self._leases.pop(lease.key, None)
            if lease.runtime is not None and lease.runtime.voice_lease is lease:
                lease.runtime.voice_lease = None


voice_leases = VoiceLeaseRegistry()
