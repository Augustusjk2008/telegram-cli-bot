from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

import psutil


DiagnosticsProvider = Callable[[], Mapping[str, Any]]


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
