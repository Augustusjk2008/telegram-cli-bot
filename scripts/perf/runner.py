from __future__ import annotations

import asyncio
import importlib.metadata
import json
import math
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

from scripts.perf import FIXED_SEED, PERF_TOOL_VERSION
from scripts.perf.resources import (
    ResourceMonitor,
    ResourceReturnReport,
    capture_process_tree_snapshot,
    evaluate_resource_return,
)
from scripts.perf.scenarios import (
    SCENARIOS,
    ScenarioConfig,
    ScenarioFunction,
    resolve_idle_probe,
)


RunStatus = Literal["pass", "fail", "inconclusive"]
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class RunConfig:
    profile: str = "baseline"
    seed: int = FIXED_SEED
    workers: int = 1
    settle_seconds: float = 5.0
    sample_interval_seconds: float = 0.1
    scenario_timeout_seconds: float = 120.0
    git_command_timeout_seconds: float = 30.0

    def validate(self) -> None:
        if self.workers != 1:
            raise ValueError("性能场景只允许 --workers 1，以确保串行和可重复。")
        if self.profile not in {"baseline", "stress"}:
            raise ValueError("profile 必须为 baseline 或 stress")
        if self.seed != FIXED_SEED:
            raise ValueError(f"固定基线 seed 必须为 {FIXED_SEED}")
        if not math.isfinite(self.settle_seconds) or self.settle_seconds < 0:
            raise ValueError("settle 必须是有限的非负秒数")
        if self.profile == "stress" and self.settle_seconds < 30.0:
            raise ValueError("stress 的 settle 必须至少 30 秒")
        if (
            not math.isfinite(self.sample_interval_seconds)
            or self.sample_interval_seconds <= 0
            or self.sample_interval_seconds > 1.0
        ):
            raise ValueError("sample interval 必须是大于 0 且不超过 1 秒的有限值")
        for name, value in (
            ("scenario timeout", self.scenario_timeout_seconds),
            ("git timeout", self.git_command_timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是有限正数")


def validate_run_id(run_id: str) -> str:
    value = str(run_id or "")
    if value in {".", ".."} or not _RUN_ID_RE.fullmatch(value):
        raise ValueError("run-id 只能包含 1-64 个 ASCII 字母、数字、点、下划线和连字符")
    return value


def create_run_directory(root: Path, *, run_id: str | None = None) -> Path:
    normalized_run_id = validate_run_id(
        run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    target = root / normalized_run_id
    target.mkdir(parents=True, exist_ok=False)
    return target


def _run_git_metadata(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").rstrip("\r\n") if result.returncode == 0 else ""


def collect_provenance(command: Sequence[str]) -> dict[str, object]:
    dirty_output = _run_git_metadata("status", "--porcelain=v1", "--untracked-files=all")
    dependencies: dict[str, str] = {}
    for package in ("psutil", "pytest", "pytest-asyncio"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "not-installed"
    dirty_paths = [line[3:] for line in dirty_output.splitlines() if len(line) > 3]
    return {
        "tool_version": PERF_TOOL_VERSION,
        "git_commit": _run_git_metadata("rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(dirty_output),
        "git_dirty_paths": dirty_paths[:200],
        "git_dirty_paths_truncated": len(dirty_paths) > 200,
        "command": list(command),
        "dependency_versions": dependencies,
        "python": sys.version,
        "platform": platform.platform(),
    }


def classify_scenario_status(
    *,
    checks_passed: bool,
    resource_passed: bool,
    resource_conclusive: bool,
    observation_gaps: Sequence[str],
    coverage: str,
    require_real_coverage: bool,
    error: str,
) -> RunStatus:
    if error or not checks_passed or not resource_passed:
        return "fail"
    if not resource_conclusive or observation_gaps:
        return "inconclusive"
    if require_real_coverage and coverage != "real":
        return "inconclusive"
    return "pass"


def scenario_status_reasons(
    *,
    checks_passed: bool,
    resource_passed: bool,
    resource_conclusive: bool,
    observation_gaps: Sequence[str],
    coverage: str,
    require_real_coverage: bool,
    error: str,
) -> list[str]:
    reasons: list[str] = []
    if error:
        reasons.append(f"error:{error}")
    if not checks_passed:
        reasons.append("functional_checks_failed")
    if not resource_passed:
        reasons.append("resource_threshold_failed")
    if not resource_conclusive:
        reasons.append("resource_evaluation_incomplete")
    reasons.extend(f"observation_gap:{gap}" for gap in observation_gaps)
    if require_real_coverage and coverage != "real":
        reasons.append(f"stress_requires_real_coverage:{coverage}")
    return reasons


def exit_code_for_status(status: str) -> int:
    if status == "pass":
        return 0
    if status == "inconclusive":
        return 3
    return 1


def _combine_statuses(statuses: Iterable[str]) -> RunStatus:
    values = set(statuses)
    if "fail" in values:
        return "fail"
    if "inconclusive" in values:
        return "inconclusive"
    return "pass"


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_samples(path: Path, samples) -> None:
    path.write_text(
        "".join(json.dumps(sample.to_dict(), sort_keys=True) + "\n" for sample in samples),
        encoding="utf-8",
    )


async def run_serial(
    scenario_names: Iterable[str],
    *,
    config: RunConfig,
    artifact_dir: Path,
    scenarios: Mapping[str, ScenarioFunction] | None = None,
    command: Sequence[str] | None = None,
) -> dict[str, object]:
    config.validate()
    registry = dict(scenarios or SCENARIOS)
    names = list(scenario_names)
    unknown = [name for name in names if name not in registry]
    if unknown:
        raise ValueError(f"未知性能场景: {', '.join(unknown)}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    provenance = collect_provenance(command or sys.argv)
    overall_baseline = capture_process_tree_snapshot()
    all_samples = [overall_baseline]
    last_settle_samples = [overall_baseline]
    payload: dict[str, object] = {
        "schema_version": 2,
        "status": "inconclusive",
        "passed": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "config": asdict(config),
        "provenance": provenance,
        "serial_execution": True,
        "scenario_order": names,
        "results": [],
        "overall_resources": None,
        "status_reasons": ["run_in_progress"],
    }
    results: list[dict[str, object]] = []
    _write_json(artifact_dir / "results.json", payload)

    for name in names:
        baseline = capture_process_tree_snapshot()
        monitor = ResourceMonitor(interval_seconds=config.sample_interval_seconds)
        outcome = None
        error = ""
        error_code = ""
        idle_checks: dict[str, bool] = {}
        scenario_deadline = time.monotonic() + config.scenario_timeout_seconds
        await monitor.start()
        try:
            outcome = await asyncio.wait_for(
                registry[name](
                    ScenarioConfig(
                        profile=config.profile,
                        seed=config.seed,
                        scenario_timeout_seconds=config.scenario_timeout_seconds,
                        git_command_timeout_seconds=config.git_command_timeout_seconds,
                    )
                ),
                timeout=max(0.001, scenario_deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            error_code = "scenario_deadline_exceeded"
            error = f"scenario deadline exceeded after {config.scenario_timeout_seconds:.3f}s"
        except Exception as exc:
            error_code = "scenario_error"
            error = f"{type(exc).__name__}: {exc}"

        settle_started = capture_process_tree_snapshot()
        monitor.samples.append(settle_started)
        remaining_for_settle = scenario_deadline - time.monotonic()
        if not error and config.settle_seconds > remaining_for_settle:
            await asyncio.sleep(max(0.0, remaining_for_settle))
            error_code = "scenario_deadline_exceeded"
            error = f"scenario deadline exceeded after {config.scenario_timeout_seconds:.3f}s"
        elif not error:
            await asyncio.sleep(config.settle_seconds)
        if outcome is not None and not error:
            try:
                remaining_for_probe = scenario_deadline - time.monotonic()
                if remaining_for_probe <= 0:
                    raise asyncio.TimeoutError
                idle_checks = await asyncio.wait_for(
                    resolve_idle_probe(outcome.idle_probe),
                    timeout=min(5.0, remaining_for_probe),
                )
            except asyncio.TimeoutError:
                idle_checks = {"probe_completed": False}
                error_code = "scenario_deadline_exceeded"
                error = f"scenario deadline exceeded after {config.scenario_timeout_seconds:.3f}s"
            except Exception as exc:
                idle_checks = {"probe_completed": False}
                if not error:
                    error_code = "idle_probe_error"
                    error = f"{type(exc).__name__}: {exc}"
        else:
            idle_checks = {"scenario_completed": False}
        await monitor.stop()
        final = capture_process_tree_snapshot()
        settle_samples = [
            sample for sample in monitor.samples if sample.timestamp >= settle_started.timestamp
        ]
        settle_samples.append(final)
        resource_report = evaluate_resource_return(
            baseline,
            final,
            monitor.samples,
            slope_samples=settle_samples,
            idle_checks=idle_checks,
        )
        checks_passed = bool(
            outcome
            and outcome.passed
            and all(bool(value) for value in outcome.checks.values())
        )
        status = classify_scenario_status(
            checks_passed=checks_passed,
            resource_passed=resource_report.thresholds_passed,
            resource_conclusive=resource_report.conclusive,
            observation_gaps=outcome.observation_gaps if outcome else [],
            coverage=outcome.coverage if outcome else "none",
            require_real_coverage=config.profile == "stress",
            error=error,
        )
        status_reasons = scenario_status_reasons(
            checks_passed=checks_passed,
            resource_passed=resource_report.thresholds_passed,
            resource_conclusive=resource_report.conclusive,
            observation_gaps=outcome.observation_gaps if outcome else [],
            coverage=outcome.coverage if outcome else "none",
            require_real_coverage=config.profile == "stress",
            error=error,
        )
        scenario_payload: dict[str, object] = {
            "name": name,
            "status": status,
            "passed": status == "pass",
            "error": error,
            "error_code": error_code,
            "status_reasons": status_reasons,
            "outcome": outcome.to_dict(idle_checks=idle_checks) if outcome is not None else None,
            "resources": resource_report.to_dict(),
        }
        results.append(scenario_payload)
        all_samples.extend(monitor.samples)
        all_samples.append(final)
        last_settle_samples = settle_samples
        _write_samples(artifact_dir / f"{name}-samples.jsonl", monitor.samples)
        payload["results"] = results
        payload["status"] = _combine_statuses(str(item["status"]) for item in results)
        _write_json(artifact_dir / "results.json", payload)

    overall_final = capture_process_tree_snapshot()
    all_samples.append(overall_final)
    overall_resources: ResourceReturnReport = evaluate_resource_return(
        overall_baseline,
        overall_final,
        all_samples,
        slope_samples=[*last_settle_samples, overall_final],
    )
    resource_status: RunStatus
    if not overall_resources.thresholds_passed:
        resource_status = "fail"
    elif not overall_resources.conclusive:
        resource_status = "inconclusive"
    else:
        resource_status = "pass"
    status = _combine_statuses(
        [*(str(item["status"]) for item in results), resource_status]
    )
    status_reasons = [
        f"{item['name']}:{reason}"
        for item in results
        for reason in item.get("status_reasons", [])
    ]
    if not overall_resources.thresholds_passed:
        status_reasons.append("overall_resources:resource_threshold_failed")
    if not overall_resources.conclusive:
        status_reasons.append("overall_resources:resource_evaluation_incomplete")
    payload.update(
        {
            "status": status,
            "passed": status == "pass",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "overall_resources": overall_resources.to_dict(),
            "status_reasons": status_reasons,
        }
    )
    _write_json(artifact_dir / "results.json", payload)
    return payload
