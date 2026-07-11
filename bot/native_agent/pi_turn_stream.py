from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any


PI_TURN_REPLAY_MAX_EVENTS = max(32, int(os.environ.get("TCB_PI_TURN_REPLAY_MAX_EVENTS", "1024")))
PI_TURN_REPLAY_MAX_BYTES = max(64 * 1024, int(os.environ.get("TCB_PI_TURN_REPLAY_MAX_BYTES", str(4 * 1024 * 1024))))
PI_TURN_CONTROL_MAX_EVENTS = max(8, int(os.environ.get("TCB_PI_TURN_CONTROL_MAX_EVENTS", "128")))
PI_TURN_CONTROL_MAX_BYTES = max(16 * 1024, int(os.environ.get("TCB_PI_TURN_CONTROL_MAX_BYTES", str(1024 * 1024))))
PI_TURN_RECONNECT_GRACE_SECONDS = max(0.1, float(os.environ.get("TCB_PI_TURN_RECONNECT_GRACE_SECONDS", "20")))

_CRITICAL_TYPES = {"done", "error", "eof", "meta", "permission"}


def pi_turn_reconnect_enabled() -> bool:
    value = os.environ.get("TCB_PI_TURN_RECONNECT", "false")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _event_bytes(event: dict[str, Any]) -> int:
    try:
        return len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(event).encode("utf-8", errors="replace"))


def _is_critical(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "").strip().lower()
    if event_type in _CRITICAL_TYPES or "permission" in event_type:
        return True
    return False


@dataclass(slots=True)
class _ReplayFrame:
    sequence: int
    payload: dict[str, Any]
    size: int
    critical: bool


class PiTurnChannel:
    def __init__(
        self,
        producer: AsyncIterator[dict[str, Any]],
        *,
        replay_max_events: int = PI_TURN_REPLAY_MAX_EVENTS,
        replay_max_bytes: int = PI_TURN_REPLAY_MAX_BYTES,
        control_max_events: int = PI_TURN_CONTROL_MAX_EVENTS,
        control_max_bytes: int = PI_TURN_CONTROL_MAX_BYTES,
        reconnect_grace_seconds: float = PI_TURN_RECONNECT_GRACE_SECONDS,
        abort_turn: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.stream_id = f"pit_{uuid.uuid4().hex[:16]}"
        self.turn_id = ""
        self._producer = producer
        self._replay_max_events = max(1, int(replay_max_events))
        self._replay_max_bytes = max(1024, int(replay_max_bytes))
        self._control_max_events = max(1, int(control_max_events))
        self._control_max_bytes = max(1024, int(control_max_bytes))
        self._reconnect_grace_seconds = max(0.0, float(reconnect_grace_seconds))
        self._abort_turn = abort_turn
        self._frames: deque[_ReplayFrame] = deque()
        self._replay_bytes = 0
        self._sequence = 0
        self._gap_from = 0
        self._gap_to = 0
        self._dropped_count = 0
        self._active_consumers = 0
        self._finished = False
        self._finished_at = 0.0
        self._overflowed = False
        self._closed = False
        self._created_at = time.monotonic()
        self._last_used_at = self._created_at
        self._condition = asyncio.Condition()
        self._grace_task: asyncio.Task[None] | None = None
        self._producer_task = asyncio.create_task(self._run_producer(), name=f"pi-turn-{self.stream_id}")

    async def _run_producer(self) -> None:
        try:
            async for raw_event in self._producer:
                if not isinstance(raw_event, dict):
                    continue
                await self._append(raw_event)
                if self._overflowed:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._append({"type": "error", "code": "pi_turn_stream_error", "message": str(exc)})
        finally:
            async with self._condition:
                self._finished = True
                self._finished_at = time.monotonic()
                self._condition.notify_all()

    async def _append(self, raw_event: dict[str, Any]) -> None:
        self._sequence += 1
        event = dict(raw_event)
        event["stream_id"] = self.stream_id
        event["sequence"] = self._sequence
        discovered_turn_id = str(event.get("turn_id") or "").strip()
        if discovered_turn_id:
            self.turn_id = discovered_turn_id
        elif self.turn_id:
            event["turn_id"] = self.turn_id
        frame = _ReplayFrame(
            sequence=self._sequence,
            payload=event,
            size=_event_bytes(event),
            critical=_is_critical(event),
        )
        async with self._condition:
            self._frames.append(frame)
            self._replay_bytes += frame.size
            was_overflowed = self._overflowed
            self._enforce_budget_locked()
            if self._overflowed and not was_overflowed:
                self._sequence += 1
                overflow_event = {
                    "type": "error",
                    "code": "stream_overflow",
                    "message": "Pi turn 关键事件缓冲区已耗尽",
                    "stream_id": self.stream_id,
                    "turn_id": self.turn_id,
                    "sequence": self._sequence,
                    "truncated": True,
                    "snapshot_required": True,
                    "reason": "control_budget",
                }
                overflow_frame = _ReplayFrame(
                    sequence=self._sequence,
                    payload=overflow_event,
                    size=_event_bytes(overflow_event),
                    critical=True,
                )
                self._frames.append(overflow_frame)
                self._replay_bytes += overflow_frame.size
            self._last_used_at = time.monotonic()
            self._condition.notify_all()
        if self._overflowed and self._abort_turn is not None:
            await self._abort_turn()

    def _enforce_budget_locked(self) -> None:
        while len(self._frames) > self._replay_max_events or self._replay_bytes > self._replay_max_bytes:
            removable = next((frame for frame in self._frames if not frame.critical), None)
            if removable is None:
                break
            self._frames.remove(removable)
            self._replay_bytes -= removable.size
            self._record_gap(removable.sequence)

        critical = [frame for frame in self._frames if frame.critical]
        critical_bytes = sum(frame.size for frame in critical)
        if len(critical) <= self._control_max_events and critical_bytes <= self._control_max_bytes:
            return
        self._overflowed = True
        while self._frames and not self._frames[0].critical:
            removed = self._frames.popleft()
            self._replay_bytes -= removed.size
            self._record_gap(removed.sequence)

    def _record_gap(self, sequence: int) -> None:
        self._dropped_count += 1
        self._gap_from = sequence if not self._gap_from else min(self._gap_from, sequence)
        self._gap_to = max(self._gap_to, sequence)

    async def events(self, *, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]:
        cursor = max(0, int(after_sequence or 0))
        requested_after_sequence = cursor
        async with self._condition:
            if self._active_consumers:
                raise RuntimeError("Pi turn 已有活动恢复消费者")
            self._active_consumers = 1
            self._last_used_at = time.monotonic()
            if self._grace_task is not None:
                self._grace_task.cancel()
                self._grace_task = None
        gap_sent = False
        try:
            while True:
                async with self._condition:
                    if not gap_sent and self._gap_to > cursor:
                        gap_sent = True
                        prefix_frames = [
                            frame
                            for frame in self._frames
                            if frame.critical
                            and frame.sequence > cursor
                            and frame.sequence <= self._gap_to
                        ]
                        gap_event = {
                            "type": "gap",
                            "stream_id": self.stream_id,
                            "turn_id": self.turn_id,
                            "sequence": self._gap_to,
                            "gap_from": max(requested_after_sequence + 1, self._gap_from),
                            "gap_to": self._gap_to,
                            "truncated": True,
                            "snapshot_required": True,
                            "reason": "replay_evicted",
                        }
                    else:
                        gap_event = None
                        prefix_frames = []
                    frames = [frame for frame in self._frames if frame.sequence > cursor]
                    if not frames and not gap_event and not self._finished:
                        await self._condition.wait()
                        continue
                    finished = self._finished
                if gap_event is not None:
                    for frame in prefix_frames:
                        cursor = max(cursor, frame.sequence)
                        yield dict(frame.payload)
                    cursor = max(cursor, int(gap_event["sequence"]))
                    yield gap_event
                    continue
                for frame in frames:
                    if frame.sequence <= cursor:
                        continue
                    cursor = frame.sequence
                    yield dict(frame.payload)
                if finished:
                    return
        finally:
            async with self._condition:
                self._active_consumers = 0
                self._last_used_at = time.monotonic()
                if not self._finished and not self._closed:
                    self._grace_task = asyncio.create_task(self._expire_grace(), name=f"pi-turn-grace-{self.stream_id}")

    async def _expire_grace(self) -> None:
        try:
            await asyncio.sleep(self._reconnect_grace_seconds)
            async with self._condition:
                if self._active_consumers or self._finished or self._closed:
                    return
            if self._abort_turn is not None:
                await self._abort_turn()
        except asyncio.CancelledError:
            return

    async def wait_finished(self) -> None:
        await asyncio.shield(self._producer_task)

    async def close(self) -> None:
        self._closed = True
        if self._grace_task is not None:
            self._grace_task.cancel()
        if not self._producer_task.done():
            self._producer_task.cancel()
        await asyncio.gather(
            *(task for task in (self._grace_task, self._producer_task) if task is not None),
            return_exceptions=True,
        )
        aclose = getattr(self._producer, "aclose", None)
        if callable(aclose):
            await aclose()

    def diagnostics(self) -> dict[str, int | float | bool | str]:
        return {
            "stream_id": self.stream_id,
            "turn_id": self.turn_id,
            "replay_events": len(self._frames),
            "replay_bytes": self._replay_bytes,
            "replay_max_events": self._replay_max_events,
            "replay_max_bytes": self._replay_max_bytes,
            "dropped_count": self._dropped_count,
            "gap_from": self._gap_from,
            "gap_to": self._gap_to,
            "active_consumers": self._active_consumers,
            "finished": self._finished,
            "finished_age_seconds": (
                max(0.0, time.monotonic() - self._finished_at)
                if self._finished_at
                else 0.0
            ),
            "overflowed": self._overflowed,
            "age_seconds": max(0.0, time.monotonic() - self._created_at),
        }
