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

from .client import APP_SERVER_VERSION, CodexServerUnknownOutcome

MAX_SDP_BYTES = 128_000
MAX_MESSAGE_BYTES = 160_000
MAX_REQUEST_IDS = 1024
VOICE_PROTOCOL_VERSION = 1
VOICE_LEASE_TTL = 90.0
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


def voice_handoff_has_input(payload: dict) -> bool:
    """Return true only for a realtime handoff carrying a new user utterance."""
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    text = item.get("input_transcript")
    return item.get("type") == "handoff_request" and isinstance(text, str) and bool(text.strip())


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
    last_activity: float = field(default_factory=time.monotonic)
    ttl: float = VOICE_LEASE_TTL
    runtime: Any = field(default=None, repr=False)
    attached: bool = True
    _stop_attempted: bool = False
    _started: bool = False
    _closed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _disconnect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _registry: Any = field(default=None, repr=False)
    _loop: Any = field(default=None, repr=False)
    _disconnecting: bool = field(default=False, repr=False)
    _cleanup_pending: bool = field(default=False, repr=False)
    _cleanup_runtime: Any = field(default=None, repr=False)
    _cleanup_connection_id: str = field(default="", repr=False)
    _cleanup_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def owner_key(self) -> tuple[int, int, str]:
        return self.key[:3]

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.last_activity >= self.ttl

    @property
    def task_active(self) -> bool:
        return bool(self.runtime is not None and self.runtime.alive
                    and getattr(self.runtime, "voice_task_active", False))

    @property
    def busy(self) -> bool:
        return self.attached and not self.expired and self.state not in {"closed", "error"}

    @property
    def cleanup_pending(self) -> bool:
        return self._cleanup_pending

    def renew(self) -> None:
        if not self.attached or self.expired:
            raise VoiceError("voice_lease_expired", "语音连接已过期，请重新连接", 409)
        self.last_activity = time.monotonic()

    def bind(self, runtime: Any) -> None:
        if (runtime.request.owner_key != self.owner_key or runtime.request.conversation_id != self.key[3]
                or not runtime.request.experimental_api):
            raise VoiceError("voice_session_changed", "语音会话绑定已失效", 409)
        if runtime.active or getattr(runtime, "voice_task_active", False):
            raise VoiceError("voice_task_active", VOICE_BUSY_MESSAGE, 409)
        if self._registry is not None and self._registry._cleanup_for_runtime(runtime) is not None:
            raise VoiceError("voice_cleanup_pending", "语音运行时正在清理，请稍后重试", 409)
        current = getattr(runtime, "voice_lease", None)
        if current is not None and current is not self:
            raise VoiceError("voice_runtime_bound", "语音运行时仍由其他连接绑定", 409)
        self.runtime, self.thread_id = runtime, runtime.thread_id
        self._loop = asyncio.get_running_loop()
        runtime.voice_lease = self
        runtime.voice_lease_generation = self.connection_id

    def publish(self, message: dict) -> None:
        self.last_seq = self.runtime.voice_events.publish({**message, "connection_id": self.connection_id})

    def summary(self, request_id: str = "") -> None:
        self.publish({"type": "voice.state", "state": self.state, "id": request_id,
                      "thread_id": self.thread_id, "realtime_session_id": self.realtime_session_id,
                      "client_generation": self.client_generation, "last_seq": self.last_seq,
                      "task_state": getattr(self.runtime, "voice_task_state", "idle"),
                      "turn_id": getattr(self.runtime, "voice_turn_id", "")})

    def transition(self, state: str, *, code: str = "", message: str = "") -> None:
        self.state = state
        if state == "closed":
            self._closed.set()
        if code:
            self.publish({"type": "voice.state", "state": state, "code": code, "message": message})
        else:
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
            self.detach()
        elif name == "thread/realtime/error":
            self.transition("error")
            self.detach()
        elif name in {"runtime/error", "runtime/closed"}:
            self._closed.set()
            if self.state != "closed":
                self.transition("unknown", code="voice_runtime_closed", message="语音运行时已关闭，结果待确认")
            self.detach()
        elif name == "thread/realtime/sdp" and self.state in {"negotiating", "active"}:
            sdp = data.get("sdp")
            if isinstance(sdp, str) and len(sdp.encode("utf-8")) <= MAX_SDP_BYTES:
                self.publish({"type": "voice.sdp", "sdp": sdp})

    async def start(self, sdp: str) -> None:
        self.renew()
        if self._started or self.state != "idle":
            raise VoiceError("voice_already_started", "该连接已启动，不会重发", 409)
        if self.runtime.active or getattr(self.runtime, "voice_task_active", False):
            raise VoiceError("voice_task_active", VOICE_BUSY_MESSAGE, 409)
        self._started = True
        self.transition("negotiating")
        try:
            await self.runtime.start_realtime(sdp)
        except BaseException as exc:
            self.transition("unknown" if isinstance(exc, (CodexServerUnknownOutcome, asyncio.CancelledError))
                            or not self.runtime.alive else "error")
            self.detach()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise VoiceError(
                "voice_start_failed",
                f"语音启动失败；请检查 Codex {APP_SERVER_VERSION} 兼容性和连接状态",
                502,
            ) from exc

    async def stop_voice(self, *, timeout: float = 10, _expected_connection_id: str = "") -> None:
        if not self._started or self.state == "closed":
            if self.state != "closed":
                self.transition("closed")
            self.detach()
            return
        if self.runtime is None or not self._owns_runtime_binding(_expected_connection_id):
            self.detach()
            return
        if _expected_connection_id and self.task_active:
            return
        if self._stop_attempted:
            return
        self._stop_attempted = True
        self.transition("stopping")
        try:
            await asyncio.wait_for(self.runtime.stop_realtime(), timeout)
            # An acknowledgement is not proof of closure.
            await asyncio.wait_for(self._closed.wait(), timeout)
        except BaseException as exc:
            if self.state != "closed":
                self.transition("unknown", code="voice_stop_unknown", message="语音停止结果待确认，不会自动重试")
            self.detach()
            if isinstance(exc, asyncio.CancelledError):
                raise

    def detach(self) -> None:
        self.attached = False
        if self._registry is not None:
            self._registry.release(self)

    async def disconnect(self) -> None:
        async with self._disconnect_lock:
            # Mark the browser control channel detached, but keep the runtime
            # binding until stop_voice can observe thread/realtime/closed.
            self._disconnecting = True
            self.attached = False
            try:
                if (self.runtime is not None and self.runtime.alive
                        and self._owns_runtime_binding()):
                    await self.stop_voice()
            finally:
                self._disconnecting = False
                self.detach()

    def _owns_runtime_binding(self, expected_connection_id: str = "") -> bool:
        runtime = self.runtime
        connection_id = expected_connection_id or self.connection_id
        return bool(runtime is not None and getattr(runtime, "voice_lease", None) is self
                    and getattr(runtime, "voice_lease_generation", connection_id) == connection_id)


class VoiceLeaseRegistry:
    def __init__(self, *, ttl: float = VOICE_LEASE_TTL):
        self._leases: dict[tuple[int, int, str, str], VoiceLease] = {}
        self._tasks: dict[tuple[int, int, str], Any] = {}
        self._pending_cleanups: dict[int, VoiceLease] = {}
        self.ttl = ttl
        self._lock = threading.RLock()

    def _prune(self) -> None:
        for lease in list(self._leases.values()):
            if not lease.attached or lease.expired or (lease.runtime is not None and not lease.runtime.alive):
                self._begin_cleanup(lease)
        for owner, runtime in list(self._tasks.items()):
            if not runtime.alive or not getattr(runtime, "voice_task_active", False):
                if self._tasks.get(owner) is runtime:
                    self._tasks.pop(owner)
        for lease in list(self._pending_cleanups.values()):
            if lease.task_active:
                self._tasks[lease.owner_key] = lease.runtime
            else:
                self._schedule_cleanup(lease)

    def _cleanup_for_runtime(self, runtime: Any) -> VoiceLease | None:
        with self._lock:
            lease = self._pending_cleanups.get(id(runtime))
            if lease is not None and lease._cleanup_runtime is runtime and lease._cleanup_pending:
                return lease
            if lease is not None:
                self._pending_cleanups.pop(id(runtime), None)
            return None

    def _owns_runtime_binding(self, lease: VoiceLease, runtime: Any, connection_id: str) -> bool:
        return bool(getattr(runtime, "voice_lease", None) is lease
                    and getattr(runtime, "voice_lease_generation", connection_id) == connection_id)

    def _clear_runtime_binding(self, lease: VoiceLease, runtime: Any, connection_id: str) -> None:
        if self._owns_runtime_binding(lease, runtime, connection_id):
            runtime.voice_lease = None
            if getattr(runtime, "voice_lease_generation", None) == connection_id:
                runtime.voice_lease_generation = None

    def _begin_cleanup(self, lease: VoiceLease) -> None:
        if lease._cleanup_pending:
            return
        runtime = lease.runtime
        lease._cleanup_pending = True
        lease._cleanup_runtime = runtime
        lease._cleanup_connection_id = lease.connection_id
        lease.attached = False
        if runtime is None:
            if self._leases.get(lease.key) is lease:
                self._leases.pop(lease.key)
            lease._cleanup_pending = False
            lease._cleanup_runtime = None
            lease._cleanup_connection_id = ""
            return
        if lease.task_active:
            self._tasks[lease.owner_key] = runtime
        self._pending_cleanups[id(runtime)] = lease

    def _schedule_cleanup(self, lease: VoiceLease) -> None:
        if not lease._cleanup_pending or lease._cleanup_task is not None:
            return
        runtime = lease._cleanup_runtime
        if runtime is None or lease.task_active:
            return
        if not runtime.alive or not self._owns_runtime_binding(lease, runtime, lease._cleanup_connection_id):
            self._finish_cleanup(lease)
            return
        loop = lease._loop
        if loop is None or not loop.is_running():
            self._finish_cleanup(lease)
            return
        loop.call_soon_threadsafe(self._create_cleanup_task, lease)

    def _create_cleanup_task(self, lease: VoiceLease) -> None:
        with self._lock:
            if not lease._cleanup_pending or lease._cleanup_task is not None:
                return
            runtime = lease._cleanup_runtime
            connection_id = lease._cleanup_connection_id
            if runtime is None or lease.task_active:
                return
            if not runtime.alive or not self._owns_runtime_binding(lease, runtime, connection_id):
                self._finish_cleanup(lease)
                return
            lease._cleanup_task = asyncio.create_task(
                self._cleanup_expired(lease, runtime, connection_id),
                name="codex-voice-lease-cleanup",
            )

    async def _cleanup_expired(self, lease: VoiceLease, runtime: Any, connection_id: str) -> None:
        try:
            if not lease._cleanup_pending or not self._owns_runtime_binding(lease, runtime, connection_id):
                return
            if lease.task_active:
                return
            lease._disconnecting = True
            try:
                if lease._started and lease.state != "closed":
                    await lease.stop_voice(timeout=10, _expected_connection_id=connection_id)
                elif lease.state != "closed":
                    lease.transition("closed")
            finally:
                lease._disconnecting = False
        finally:
            with self._lock:
                lease._cleanup_task = None
                if not lease.task_active:
                    self._finish_cleanup(lease)

    def _finish_cleanup(self, lease: VoiceLease) -> None:
        runtime = lease._cleanup_runtime
        connection_id = lease._cleanup_connection_id
        if runtime is not None and self._pending_cleanups.get(id(runtime)) is lease:
            self._pending_cleanups.pop(id(runtime), None)
        if self._leases.get(lease.key) is lease:
            self._leases.pop(lease.key)
        if runtime is not None:
            self._clear_runtime_binding(lease, runtime, connection_id)
        lease._cleanup_pending = False
        lease._cleanup_runtime = None
        lease._cleanup_connection_id = ""

    def acquire(self, key: tuple[int, int, str, str], actor_id: tuple[str, int]) -> VoiceLease:
        with self._lock:
            self._prune()
            existing = self._leases.get(key)
            if existing is not None and existing._cleanup_pending:
                raise VoiceError("voice_cleanup_pending", "语音运行时正在清理，请稍后重试", 409)
            if existing is not None:
                raise VoiceError("voice_connection_occupied", "当前会话已有语音连接", 409)
            if key[:3] in self._tasks:
                raise VoiceError("voice_task_active", VOICE_BUSY_MESSAGE, 409)
            if len(self._leases) >= 128:
                raise VoiceError("voice_connection_limit", "语音连接数量超过限制", 429)
            lease = VoiceLease(key, actor_id, ttl=self.ttl, _registry=self)
            self._leases[key] = lease
            return lease

    def owner_busy(self, owner_key: tuple[int, int, str]) -> bool:
        with self._lock:
            self._prune()
            return (owner_key in self._tasks
                    or any(lease.owner_key == owner_key and (lease.busy or lease.task_active)
                           for lease in self._leases.values())
                    or any(lease.owner_key == owner_key for lease in self._pending_cleanups.values()))

    def release(self, lease: VoiceLease) -> None:
        with self._lock:
            lease.attached = False
            if not lease._cleanup_pending and self._leases.get(lease.key) is lease:
                self._leases.pop(lease.key)
            if lease.task_active:
                self._tasks[lease.owner_key] = lease.runtime
            elif (lease.runtime is not None and not lease._disconnecting
                  and not lease._cleanup_pending):
                self._clear_runtime_binding(lease, lease.runtime, lease.connection_id)


voice_leases = VoiceLeaseRegistry()
