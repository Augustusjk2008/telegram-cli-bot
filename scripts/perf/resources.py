from __future__ import annotations

import asyncio
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

import psutil


MIB = 1024 * 1024


@dataclass(frozen=True)
class ResourceSnapshot:
    timestamp: float
    rss_bytes: int
    thread_count: int
    child_process_count: int
    handle_count: int
    asyncio_task_count: int
    process_ids: tuple[int, ...]
    loop_lag_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceReturnPolicy:
    thread_allowance: int = 2
    handle_allowance: int = 16
    asyncio_task_allowance: int = 0
    rss_ratio: float = 1.15
    rss_allowance_bytes: int = 64 * MIB
    max_tail_rss_slope_bytes_per_minute: float = 2 * MIB
    loop_lag_p99_ms: float = 100.0
    loop_lag_spike_ms: float = 250.0
    max_consecutive_loop_lag_spikes: int = 2
    minimum_slope_window_seconds: float = 5.0
    slope_tail_seconds: float = 30.0


@dataclass(frozen=True)
class ResourceReturnReport:
    passed: bool
    thresholds_passed: bool
    conclusive: bool
    checks: dict[str, dict[str, object]]
    baseline: ResourceSnapshot
    final: ResourceSnapshot
    sample_count: int
    observed_process_ids: tuple[int, ...]
    remaining_new_process_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "thresholds_passed": self.thresholds_passed,
            "conclusive": self.conclusive,
            "checks": self.checks,
            "baseline": self.baseline.to_dict(),
            "final": self.final.to_dict(),
            "sample_count": self.sample_count,
            "observed_process_ids": list(self.observed_process_ids),
            "remaining_new_process_ids": list(self.remaining_new_process_ids),
        }


def capture_process_tree_snapshot(*, loop_lag_ms: float = 0.0) -> ResourceSnapshot:
    root = psutil.Process()
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    rss_bytes = 0
    thread_count = 0
    handle_count = 0
    live_process_ids: list[int] = []
    for process in processes:
        try:
            rss_bytes += int(process.memory_info().rss)
            thread_count += int(process.num_threads())
            live_process_ids.append(int(process.pid))
            num_handles = getattr(process, "num_handles", None)
            num_fds = getattr(process, "num_fds", None)
            if callable(num_handles):
                handle_count += int(num_handles())
            elif callable(num_fds):
                handle_count += int(num_fds())
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue

    try:
        task_count = len(asyncio.all_tasks())
    except RuntimeError:
        task_count = 0
    process_ids = tuple(sorted(set(live_process_ids)))
    return ResourceSnapshot(
        timestamp=time.monotonic(),
        rss_bytes=rss_bytes,
        thread_count=thread_count,
        child_process_count=max(0, len(process_ids) - int(root.pid in process_ids)),
        handle_count=handle_count,
        asyncio_task_count=task_count,
        process_ids=process_ids,
        loop_lag_ms=max(0.0, float(loop_lag_ms)),
    )


class ResourceMonitor:
    def __init__(self, *, interval_seconds: float = 0.1) -> None:
        self.interval_seconds = float(interval_seconds)
        self.samples: list[ResourceSnapshot] = []
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self.samples.append(capture_process_tree_snapshot())
        self._task = asyncio.create_task(self._run(), name="perf-resource-monitor")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stopping.set()
        await task
        self._task = None

    async def _run(self) -> None:
        expected = time.monotonic() + self.interval_seconds
        while not self._stopping.is_set():
            timeout = max(0.0, expected - time.monotonic())
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=timeout)
                break
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            self.samples.append(
                capture_process_tree_snapshot(loop_lag_ms=max(0.0, (now - expected) * 1000.0))
            )
            expected = max(expected + self.interval_seconds, now + self.interval_seconds)


def evaluate_resource_return(
    baseline: ResourceSnapshot,
    final: ResourceSnapshot,
    samples: Iterable[ResourceSnapshot],
    *,
    slope_samples: Iterable[ResourceSnapshot] | None = None,
    idle_checks: Mapping[str, bool] | None = None,
    policy: ResourceReturnPolicy | None = None,
) -> ResourceReturnReport:
    effective = policy or ResourceReturnPolicy()
    sample_list = list(samples)
    checks: dict[str, dict[str, object]] = {}

    def record(
        name: str,
        passed: bool,
        actual: object,
        limit: object,
        *,
        evaluated: bool = True,
    ) -> None:
        checks[name] = {
            "passed": bool(passed),
            "actual": actual,
            "limit": limit,
            "evaluated": evaluated,
        }

    record(
        "child_processes_returned",
        final.child_process_count <= baseline.child_process_count,
        final.child_process_count,
        baseline.child_process_count,
    )
    record(
        "threads_returned",
        final.thread_count <= baseline.thread_count + effective.thread_allowance,
        final.thread_count,
        baseline.thread_count + effective.thread_allowance,
    )
    record(
        "handles_returned",
        final.handle_count <= baseline.handle_count + effective.handle_allowance,
        final.handle_count,
        baseline.handle_count + effective.handle_allowance,
    )
    record(
        "asyncio_tasks_returned",
        final.asyncio_task_count <= baseline.asyncio_task_count + effective.asyncio_task_allowance,
        final.asyncio_task_count,
        baseline.asyncio_task_count + effective.asyncio_task_allowance,
    )
    observed_process_ids = tuple(
        sorted(
            {
                pid
                for snapshot in (baseline, *sample_list, final)
                for pid in snapshot.process_ids
            }
        )
    )
    remaining_new_process_ids = tuple(sorted(set(final.process_ids) - set(baseline.process_ids)))
    record(
        "process_ids_returned",
        not remaining_new_process_ids,
        list(remaining_new_process_ids),
        [],
    )
    rss_limit = max(
        int(baseline.rss_bytes * effective.rss_ratio),
        baseline.rss_bytes + effective.rss_allowance_bytes,
    )
    record("rss_returned", final.rss_bytes <= rss_limit, final.rss_bytes, rss_limit)

    slope_sample_list = list(slope_samples) if slope_samples is not None else sample_list
    slope = tail_rss_slope_bytes_per_minute(
        slope_sample_list,
        tail_seconds=effective.slope_tail_seconds,
        minimum_window_seconds=effective.minimum_slope_window_seconds,
    )
    if slope is None:
        record(
            "rss_tail_slope",
            False,
            None,
            effective.max_tail_rss_slope_bytes_per_minute,
            evaluated=False,
        )
    else:
        record(
            "rss_tail_slope",
            slope <= effective.max_tail_rss_slope_bytes_per_minute,
            slope,
            effective.max_tail_rss_slope_bytes_per_minute,
        )

    lag_values = [sample.loop_lag_ms for sample in sample_list]
    if lag_values:
        lag_p99 = percentile(lag_values, 99.0)
        record("loop_lag_p99", lag_p99 <= effective.loop_lag_p99_ms, lag_p99, effective.loop_lag_p99_ms)
        consecutive_spikes = max_consecutive_above(lag_values, effective.loop_lag_spike_ms)
        record(
            "loop_lag_consecutive_spikes",
            consecutive_spikes <= effective.max_consecutive_loop_lag_spikes,
            consecutive_spikes,
            effective.max_consecutive_loop_lag_spikes,
        )
    else:
        record("loop_lag_p99", False, None, effective.loop_lag_p99_ms, evaluated=False)
        record(
            "loop_lag_consecutive_spikes",
            False,
            None,
            effective.max_consecutive_loop_lag_spikes,
            evaluated=False,
        )
    for name, idle in sorted((idle_checks or {}).items()):
        record(f"idle:{name}", bool(idle), bool(idle), True)

    conclusive = all(bool(check["evaluated"]) for check in checks.values())
    thresholds_passed = all(
        bool(check["passed"])
        for check in checks.values()
        if bool(check["evaluated"])
    )
    return ResourceReturnReport(
        passed=conclusive and thresholds_passed,
        thresholds_passed=thresholds_passed,
        conclusive=conclusive,
        checks=checks,
        baseline=baseline,
        final=final,
        sample_count=len(sample_list),
        observed_process_ids=observed_process_ids,
        remaining_new_process_ids=remaining_new_process_ids,
    )


def percentile(values: Iterable[float], percentile_value: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    rank = max(0.0, min(100.0, float(percentile_value))) / 100.0 * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def max_consecutive_above(values: Iterable[float], threshold: float) -> int:
    longest = 0
    current = 0
    for value in values:
        if float(value) > threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def tail_rss_slope_bytes_per_minute(
    samples: Iterable[ResourceSnapshot],
    *,
    tail_seconds: float = 30.0,
    minimum_window_seconds: float = 5.0,
) -> float | None:
    ordered = sorted(samples, key=lambda item: item.timestamp)
    if len(ordered) < 2:
        return None
    cutoff = ordered[-1].timestamp - max(0.0, float(tail_seconds))
    tail = [item for item in ordered if item.timestamp >= cutoff]
    if len(tail) < 2 or tail[-1].timestamp - tail[0].timestamp < minimum_window_seconds:
        return None
    x_values = [item.timestamp - tail[0].timestamp for item in tail]
    y_values = [float(item.rss_bytes) for item in tail]
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return 0.0
    bytes_per_second = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    ) / denominator
    return bytes_per_second * 60.0
