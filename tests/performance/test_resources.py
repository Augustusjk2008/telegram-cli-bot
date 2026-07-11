from __future__ import annotations

import pytest

from scripts.perf.resources import (
    MIB,
    ResourceReturnPolicy,
    ResourceSnapshot,
    evaluate_resource_return,
    max_consecutive_above,
    percentile,
    tail_rss_slope_bytes_per_minute,
)


def _snapshot(
    timestamp: float,
    rss_mib: float,
    *,
    threads: int = 4,
    children: int = 0,
    lag_ms: float = 0.0,
    handles: int = 10,
    tasks: int = 1,
    pids: tuple[int, ...] = (100,),
) -> ResourceSnapshot:
    return ResourceSnapshot(
        timestamp=timestamp,
        rss_bytes=int(rss_mib * MIB),
        thread_count=threads,
        child_process_count=children,
        handle_count=handles,
        asyncio_task_count=tasks,
        process_ids=pids,
        loop_lag_ms=lag_ms,
    )


def test_resource_return_accepts_plan_limits_and_idle_state() -> None:
    baseline = _snapshot(0, 100)
    samples = [_snapshot(float(index), 110 + index * 0.01, lag_ms=20) for index in range(31)]
    final = _snapshot(31, 114, threads=6)

    report = evaluate_resource_return(baseline, final, samples, idle_checks={"queue": True})

    assert report.passed is True
    assert report.checks["rss_returned"]["limit"] == 164 * MIB
    assert report.checks["idle:queue"]["passed"] is True


def test_resource_return_rejects_leaks_growth_and_loop_lag_bursts() -> None:
    baseline = _snapshot(0, 100, threads=4, children=0)
    samples = [
        _snapshot(float(index), 100 + index, lag_ms=300 if 10 <= index <= 12 else 150)
        for index in range(31)
    ]
    final = _snapshot(31, 170, threads=7, children=1)

    report = evaluate_resource_return(
        baseline,
        final,
        samples,
        idle_checks={"queue": False},
        policy=ResourceReturnPolicy(),
    )

    assert report.passed is False
    assert report.checks["child_processes_returned"]["passed"] is False
    assert report.checks["threads_returned"]["passed"] is False
    assert report.checks["rss_returned"]["passed"] is False
    assert report.checks["rss_tail_slope"]["passed"] is False
    assert report.checks["loop_lag_p99"]["passed"] is False
    assert report.checks["loop_lag_consecutive_spikes"]["passed"] is False
    assert report.checks["idle:queue"]["passed"] is False


def test_resource_math_is_deterministic() -> None:
    samples = [_snapshot(float(index), 100 + index / 60) for index in range(31)]

    assert percentile([0, 10, 20, 30], 99) == pytest.approx(29.7)
    assert max_consecutive_above([0, 251, 260, 1, 300], 250) == 2
    slope = tail_rss_slope_bytes_per_minute(samples)
    assert slope is not None
    assert abs(slope - MIB) < 1


def test_short_sample_window_reports_slope_as_not_evaluated() -> None:
    baseline = _snapshot(0, 100)
    samples = [_snapshot(0, 100), _snapshot(1, 140)]

    report = evaluate_resource_return(baseline, _snapshot(1, 140), samples)

    assert report.checks["rss_tail_slope"]["evaluated"] is False
    assert report.checks["rss_tail_slope"]["passed"] is False
    assert report.conclusive is False
    assert report.passed is False


def test_slope_can_be_limited_to_post_workload_samples() -> None:
    baseline = _snapshot(0, 100)
    workload_samples = [_snapshot(0, 100), _snapshot(10, 150)]
    settle_samples = [_snapshot(10, 150), _snapshot(20, 150)]

    report = evaluate_resource_return(
        baseline,
        _snapshot(20, 150),
        [*workload_samples, *settle_samples],
        slope_samples=settle_samples,
    )

    assert report.checks["rss_tail_slope"]["passed"] is True
    assert report.checks["rss_tail_slope"]["actual"] == 0


def test_resource_return_checks_handles_tasks_and_exact_pid_set() -> None:
    baseline = _snapshot(0, 100, handles=20, tasks=1, pids=(100,))
    samples = [
        _snapshot(0, 100, handles=20, tasks=1, pids=(100,)),
        _snapshot(10, 101, handles=21, tasks=1, pids=(100, 200)),
    ]
    final = _snapshot(10, 101, handles=40, tasks=2, pids=(100, 200))

    report = evaluate_resource_return(baseline, final, samples)

    assert report.passed is False
    assert report.checks["handles_returned"]["passed"] is False
    assert report.checks["asyncio_tasks_returned"]["passed"] is False
    assert report.checks["process_ids_returned"]["passed"] is False
    assert report.observed_process_ids == (100, 200)
    assert report.remaining_new_process_ids == (200,)
