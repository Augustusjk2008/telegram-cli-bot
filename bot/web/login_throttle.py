"""In-memory throttling for interactive Web login attempts."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _AttemptState:
    failures: list[float] = field(default_factory=list)
    blocked_until: float = 0.0


class LoginThrottle:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 300.0,
        base_lock_seconds: float = 2.0,
        max_lock_seconds: float = 60.0,
        max_keys: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max(2, int(max_attempts))
        self.window_seconds = max(10.0, float(window_seconds))
        self.base_lock_seconds = max(0.5, float(base_lock_seconds))
        self.max_lock_seconds = max(self.base_lock_seconds, float(max_lock_seconds))
        self.max_keys = max(128, int(max_keys))
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _AttemptState] = {}
        self._failure_count = 0
        self._blocked_count = 0

    @staticmethod
    def _key(client: str, username: str) -> str:
        normalized_client = str(client or "unknown").strip().lower()[:128] or "unknown"
        normalized_username = str(username or "").strip().casefold()[:64] or "unknown"
        return f"{normalized_client}\0{normalized_username}"

    def _prune_failures(self, state: _AttemptState, now: float) -> None:
        cutoff = now - self.window_seconds
        state.failures = [item for item in state.failures if item >= cutoff]
        if state.blocked_until <= now and not state.failures:
            state.blocked_until = 0.0

    def _retry_after(self, state: _AttemptState, now: float) -> int:
        return max(0, int(math.ceil(state.blocked_until - now)))

    def check(self, client: str, username: str) -> int:
        key = self._key(client, username)
        now = self._clock()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return 0
            self._prune_failures(state, now)
            retry_after = self._retry_after(state, now)
            if retry_after > 0:
                self._blocked_count += 1
            elif not state.failures:
                self._states.pop(key, None)
            return retry_after

    def record_failure(self, client: str, username: str) -> int:
        key = self._key(client, username)
        now = self._clock()
        with self._lock:
            state = self._states.setdefault(key, _AttemptState())
            self._prune_failures(state, now)
            state.failures.append(now)
            self._failure_count += 1
            if len(state.failures) >= self.max_attempts:
                exponent = min(10, len(state.failures) - self.max_attempts)
                duration = min(self.max_lock_seconds, self.base_lock_seconds * (2**exponent))
                state.blocked_until = max(state.blocked_until, now + duration)
            self._trim_locked(now)
            return self._retry_after(state, now)

    def record_success(self, client: str, username: str) -> None:
        with self._lock:
            self._states.pop(self._key(client, username), None)

    def _trim_locked(self, now: float) -> None:
        if len(self._states) <= self.max_keys:
            return
        for key, state in list(self._states.items()):
            self._prune_failures(state, now)
            if not state.failures and state.blocked_until <= now:
                self._states.pop(key, None)
        while len(self._states) > self.max_keys:
            self._states.pop(next(iter(self._states)), None)

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                "active_keys": len(self._states),
                "failure_count": self._failure_count,
                "blocked_count": self._blocked_count,
            }


__all__ = ["LoginThrottle"]
