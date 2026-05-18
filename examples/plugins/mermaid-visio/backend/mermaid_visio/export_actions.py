from __future__ import annotations

import time
from collections.abc import Callable

from .models import DiagramSource, DiagramStatus, PluginConfig
from .worker_runner import WorkerResult, convert_with_worker


def export_selected(
    selected: list[DiagramStatus],
    config: PluginConfig,
    *,
    convert_one: Callable[[DiagramSource, PluginConfig, float], WorkerResult | None] = convert_with_worker,
    clock: Callable[[], float] = time.monotonic,
) -> list[WorkerResult]:
    started = clock()
    results: list[WorkerResult] = []
    for status in selected:
        remaining = config.conversion_timeout_seconds - (clock() - started) - 2
        if remaining <= 1:
            result = WorkerResult(ok=False, filename=status.source.suggested_filename, error="批量转换预算耗尽")
        else:
            converted = convert_one(status.source, config, remaining)
            result = converted if converted is not None else WorkerResult(ok=False, filename=status.source.suggested_filename, error="转换未返回结果")
        results.append(result)
        status.status = "done" if result.ok else "error"
        status.warnings = list(result.warnings)
        status.error = result.error
        status.artifact_filename = result.filename if result.ok else ""
    return results
