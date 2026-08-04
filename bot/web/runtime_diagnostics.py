from __future__ import annotations

import asyncio
import math
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

import psutil


DiagnosticsProvider = Callable[[], Mapping[str, Any]]


class EventLoopStallWatchdog:
    """Detect a missing event-loop heartbeat from an independent thread."""

    def __init__(
        self,
        *,
        threshold_ms: float,
        poll_interval_ms: float,
        on_stall: Callable[[dict[str, object]], None],
        enabled: Callable[[], bool] | None = None,
        max_stack_frames: int = 16,
    ) -> None:
        self._threshold_ms = max(1.0, float(threshold_ms))
        self._poll_interval_seconds = max(0.001, float(poll_interval_ms) / 1000.0)
        self._on_stall = on_stall
        self._enabled = enabled or (lambda: True)
        self._max_stack_frames = max(1, int(max_stack_frames))
        self._lock = threading.Lock()
        self._workers: dict[threading.Thread, threading.Event] = {}
        self._running = False
        self._run_token = 0
        self._loop_thread_id = 0
        self._last_beat_at = 0.0
        self._beat_generation = 0
        self._reported_generation = -1
        self._report_count = 0
        self._last_stall_ms = 0.0
        self._last_reported_at_unix_ms = 0

    def _is_enabled(self) -> bool:
        try:
            return bool(self._enabled())
        except Exception:
            return False

    def start(self, *, loop_thread_id: int) -> None:
        if not self._is_enabled():
            return
        with self._lock:
            if self._running:
                return
            self._run_token += 1
            run_token = self._run_token
            self._running = True
            self._loop_thread_id = int(loop_thread_id)
            self._last_beat_at = time.monotonic()
            self._beat_generation += 1
            self._reported_generation = -1
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(run_token, stop_event),
                name="event-loop-stall-watchdog",
                daemon=True,
            )
            self._workers[thread] = stop_event
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._workers.pop(thread, None)
                if self._run_token == run_token:
                    self._running = False
            raise

    def beat(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._last_beat_at = time.monotonic()
            self._beat_generation += 1

    def stop(self) -> None:
        with self._lock:
            self._running = False
            stop_events = list(self._workers.values())
        for stop_event in stop_events:
            stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        with self._lock:
            threads = list(self._workers)
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        current_thread = threading.current_thread()
        for thread in threads:
            if thread is current_thread:
                continue
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
        with self._lock:
            for thread in list(self._workers):
                if not thread.is_alive():
                    self._workers.pop(thread, None)

    def diagnostics(self) -> dict[str, int | float | bool]:
        with self._lock:
            return {
                "running": self._running,
                "threshold_ms": self._threshold_ms,
                "poll_interval_ms": round(self._poll_interval_seconds * 1000, 3),
                "report_count": self._report_count,
                "last_stall_ms": round(self._last_stall_ms, 3),
                "last_reported_at_unix_ms": self._last_reported_at_unix_ms,
                "active_thread_count": sum(1 for thread in self._workers if thread.is_alive()),
            }

    def _format_stack(self, frame: Any) -> str:
        frames: list[str] = []
        current = frame
        while current is not None and len(frames) < self._max_stack_frames:
            code = current.f_code
            frames.append(f"{os.path.basename(code.co_filename)}:{current.f_lineno}:{code.co_name}")
            current = current.f_back
        return "|".join(frames)

    def _run(self, run_token: int, stop_event: threading.Event) -> None:
        threshold_seconds = self._threshold_ms / 1000.0
        current_thread = threading.current_thread()
        try:
            while not stop_event.wait(self._poll_interval_seconds):
                if not self._is_enabled():
                    continue
                now = time.monotonic()
                with self._lock:
                    if not self._running or self._run_token != run_token:
                        return
                    generation = self._beat_generation
                    stall_seconds = now - self._last_beat_at
                    if stall_seconds < threshold_seconds or self._reported_generation == generation:
                        continue
                    self._reported_generation = generation
                    loop_thread_id = self._loop_thread_id

                frame = sys._current_frames().get(loop_thread_id)
                stack = self._format_stack(frame) if frame is not None else ""
                stall_ms = max(0.0, stall_seconds * 1000.0)
                detected_at_unix_ms = int(time.time() * 1000)
                report: dict[str, object] = {
                    "stall_ms": round(stall_ms, 3),
                    "threshold_ms": self._threshold_ms,
                    "detected_at_unix_ms": detected_at_unix_ms,
                    "stack_available": bool(stack),
                    "stack": stack,
                }

                with self._lock:
                    if (
                        not self._running
                        or stop_event.is_set()
                        or self._run_token != run_token
                        or self._beat_generation != generation
                    ):
                        continue
                    self._report_count += 1
                    self._last_stall_ms = stall_ms
                    self._last_reported_at_unix_ms = detected_at_unix_ms
                try:
                    self._on_stall(report)
                except Exception:
                    continue
        finally:
            with self._lock:
                self._workers.pop(current_thread, None)
                if self._running and self._run_token == run_token and not stop_event.is_set():
                    self._running = False


class LoopLagTracker:
    def __init__(self, *, max_samples: int = 600, threshold_ms: float = 100.0) -> None:
        self._samples: deque[float] = deque(maxlen=max(1, int(max_samples)))
        self._threshold_ms = max(0.0, float(threshold_ms))
        self._max_ms = 0.0
        self._over_threshold_count = 0
        self._lock = threading.Lock()

    def observe(self, lag_ms: float) -> None:
        value = max(0.0, float(lag_ms))
        with self._lock:
            self._samples.append(value)
            self._max_ms = max(self._max_ms, value)
            if value >= self._threshold_ms:
                self._over_threshold_count += 1

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
        return round(ordered[index], 3)

    def diagnostics(self) -> dict[str, int | float]:
        with self._lock:
            samples = list(self._samples)
            maximum = self._max_ms
            over_threshold = self._over_threshold_count
        return {
            "sample_count": len(samples),
            "sample_capacity": self._samples.maxlen or 0,
            "current_ms": round(samples[-1], 3) if samples else 0.0,
            "max_ms": round(maximum, 3),
            "p50_ms": self._percentile(samples, 0.50),
            "p95_ms": self._percentile(samples, 0.95),
            "p99_ms": self._percentile(samples, 0.99),
            "threshold_ms": self._threshold_ms,
            "over_threshold_count": over_threshold,
        }


class RuntimeDiagnosticsRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, DiagnosticsProvider] = {}
        self._lock = threading.RLock()
        self._started_at = time.monotonic()

    def register(self, name: str, provider: DiagnosticsProvider) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("diagnostics provider 名称不能为空")
        with self._lock:
            self._providers[normalized] = provider

    def unregister(self, name: str) -> None:
        with self._lock:
            self._providers.pop(str(name or "").strip(), None)

    def _process_snapshot(self) -> dict[str, Any]:
        process = psutil.Process(os.getpid())
        children = process.children(recursive=True)
        rss = process.memory_info().rss
        child_rss = 0
        alive_children = 0
        for child in children:
            try:
                child_rss += int(child.memory_info().rss)
                alive_children += int(child.is_running())
            except (psutil.Error, OSError):
                continue
        try:
            handle_count = int(process.num_handles())
        except (AttributeError, psutil.Error, OSError):
            try:
                handle_count = int(process.num_fds())
            except (AttributeError, psutil.Error, OSError):
                handle_count = 0
        try:
            loop = asyncio.get_running_loop()
            task_count = sum(1 for task in asyncio.all_tasks(loop) if not task.done())
        except RuntimeError:
            task_count = 0
        return {
            "pid": process.pid,
            "rss_bytes": int(rss),
            "process_tree_rss_bytes": int(rss + child_rss),
            "threads": int(process.num_threads()),
            "handles": handle_count,
            "asyncio_tasks": task_count,
            "child_processes": alive_children,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            providers = list(self._providers.items())
        components: dict[str, Any] = {}
        for name, provider in providers:
            try:
                value = provider()
                components[name] = dict(value)
            except Exception as exc:
                components[name] = {
                    "available": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                }
        try:
            process = self._process_snapshot()
        except Exception as exc:
            process = {
                "available": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            }
        return {
            "schema_version": 1,
            "sampled_at_unix_ms": int(time.time() * 1000),
            "uptime_seconds": round(max(0.0, time.monotonic() - self._started_at), 3),
            "process": process,
            "components": components,
        }
