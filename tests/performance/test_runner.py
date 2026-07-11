from __future__ import annotations

import asyncio
import json
import math
import sys
import time

import pytest

from scripts.perf import FIXED_SEED
from scripts.perf import runner as perf_runner
from scripts.perf import scenarios as perf_scenarios
from scripts.perf.runner import RunConfig, create_run_directory, run_serial
from scripts.perf.scenarios import ScenarioConfig, ScenarioOutcome, deterministic_chunks


def test_fixed_seed_fixture_is_repeatable() -> None:
    first = deterministic_chunks(seed=FIXED_SEED, count=20)
    second = deterministic_chunks(seed=FIXED_SEED, count=20)

    assert first == second
    assert first != deterministic_chunks(seed=FIXED_SEED + 1, count=20)


def test_run_config_enforces_fixed_seed_and_single_worker() -> None:
    RunConfig().validate()

    with pytest.raises(ValueError, match="workers 1"):
        RunConfig(workers=2).validate()
    with pytest.raises(ValueError, match=str(FIXED_SEED)):
        RunConfig(seed=1).validate()


def test_stress_requires_30_second_settle_and_finite_positive_sampling() -> None:
    with pytest.raises(ValueError, match="至少 30"):
        RunConfig(profile="stress", settle_seconds=29.999).validate()
    for value in (0.0, -0.1, math.inf, math.nan, 1.01):
        with pytest.raises(ValueError, match="sample"):
            RunConfig(sample_interval_seconds=value).validate()


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", ".", "..", " space", "x" * 65])
def test_run_id_rejects_unsafe_directory_names(tmp_path, run_id: str) -> None:
    with pytest.raises(ValueError, match="run-id"):
        create_run_directory(tmp_path, run_id=run_id)


def test_create_run_directory_rejects_duplicate_run_id(tmp_path) -> None:
    first = create_run_directory(tmp_path, run_id="fixed")

    assert first == tmp_path / "fixed"
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, run_id="fixed")


@pytest.mark.asyncio
async def test_runner_executes_scenarios_serially_and_writes_artifacts(tmp_path) -> None:
    active = 0
    max_active = 0
    order: list[str] = []

    def scenario(name: str):
        async def run(_config: ScenarioConfig) -> ScenarioOutcome:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            order.append(name)
            active -= 1
            return ScenarioOutcome(
                name=name,
                passed=True,
                duration_seconds=0.0,
                idle_probe=lambda: {"done": True},
            )

        return run

    payload = await run_serial(
        ["one", "two"],
        config=RunConfig(settle_seconds=0.02, sample_interval_seconds=0.01),
        artifact_dir=tmp_path,
        scenarios={"one": scenario("one"), "two": scenario("two")},
    )

    assert payload["status"] in {"fail", "inconclusive"}
    assert payload["passed"] is False
    assert payload["serial_execution"] is True
    assert order == ["one", "two"]
    assert max_active == 1
    stored = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert stored["scenario_order"] == ["one", "two"]
    assert (tmp_path / "one-samples.jsonl").is_file()
    assert (tmp_path / "two-samples.jsonl").is_file()


@pytest.mark.asyncio
async def test_runner_persists_scenario_failure(tmp_path) -> None:
    async def failing(_config: ScenarioConfig) -> ScenarioOutcome:
        raise RuntimeError("boom")

    payload = await run_serial(
        ["failure"],
        config=RunConfig(settle_seconds=0.02, sample_interval_seconds=0.01),
        artifact_dir=tmp_path,
        scenarios={"failure": failing},
    )

    assert payload["passed"] is False
    assert payload["results"][0]["error"] == "RuntimeError: boom"


def test_observation_gaps_and_stress_boundary_coverage_are_inconclusive() -> None:
    assert perf_runner.classify_scenario_status(
        checks_passed=True,
        resource_passed=True,
        resource_conclusive=True,
        observation_gaps=["missing diagnostics"],
        coverage="real",
        require_real_coverage=False,
        error="",
    ) == "inconclusive"
    assert perf_runner.classify_scenario_status(
        checks_passed=True,
        resource_passed=True,
        resource_conclusive=True,
        observation_gaps=[],
        coverage="boundary",
        require_real_coverage=True,
        error="",
    ) == "inconclusive"
    assert perf_runner.exit_code_for_status("inconclusive") != 0
    reasons = perf_runner.scenario_status_reasons(
        checks_passed=True,
        resource_passed=True,
        resource_conclusive=True,
        observation_gaps=[],
        coverage="boundary",
        require_real_coverage=True,
        error="",
    )
    assert "stress_requires_real_coverage:boundary" in reasons


def test_terminal_timing_uses_actual_wall_clock_and_enforces_rate_and_deadline() -> None:
    checks, metrics = perf_scenarios.evaluate_terminal_timing(
        produced_bytes=600 * 1024 * 1024,
        elapsed_seconds=61.0,
        target_duration_seconds=60.0,
        target_rate_bytes_per_second=10 * 1024 * 1024,
        deadline_seconds=66.0,
    )
    assert checks["minimum_wall_duration"] is True
    assert checks["deadline_honored"] is True
    assert checks["minimum_sustained_rate"] is False
    assert metrics["actual_wall_seconds"] == 61.0
    assert metrics["actual_bytes_per_second"] == pytest.approx(600 * 1024 * 1024 / 61.0)


@pytest.mark.asyncio
async def test_idle_probe_runs_after_settle_instead_of_using_stale_outcome(tmp_path) -> None:
    state = {"idle": False, "probed_at": 0.0}

    async def scenario(_config: ScenarioConfig) -> ScenarioOutcome:
        async def become_idle() -> None:
            await asyncio.sleep(0.01)
            state["idle"] = True

        asyncio.create_task(become_idle())

        def probe():
            state["probed_at"] = time.monotonic()
            return {"dynamic": state["idle"]}

        return ScenarioOutcome(name="dynamic", passed=True, duration_seconds=0, idle_probe=probe)

    started = time.monotonic()
    payload = await run_serial(
        ["dynamic"],
        config=RunConfig(settle_seconds=0.03, sample_interval_seconds=0.01),
        artifact_dir=tmp_path,
        scenarios={"dynamic": scenario},
    )

    assert state["probed_at"] - started >= 0.02
    assert payload["results"][0]["outcome"]["idle_checks"]["dynamic"] is True


@pytest.mark.asyncio
async def test_scenario_deadline_returns_failure_and_persists_artifact(tmp_path) -> None:
    async def hanging(_config: ScenarioConfig) -> ScenarioOutcome:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    payload = await run_serial(
        ["hanging"],
        config=RunConfig(
            settle_seconds=0.02,
            sample_interval_seconds=0.01,
            scenario_timeout_seconds=0.02,
        ),
        artifact_dir=tmp_path,
        scenarios={"hanging": hanging},
    )

    assert payload["status"] == "fail"
    assert payload["results"][0]["error_code"] == "scenario_deadline_exceeded"
    stored = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert stored["status"] == "fail"


@pytest.mark.asyncio
async def test_scenario_deadline_includes_settle_and_probe_time(tmp_path) -> None:
    async def quick(_config: ScenarioConfig) -> ScenarioOutcome:
        return ScenarioOutcome(
            name="quick",
            passed=True,
            duration_seconds=0,
            idle_probe=lambda: {"idle": True},
        )

    payload = await run_serial(
        ["quick"],
        config=RunConfig(
            settle_seconds=0.05,
            sample_interval_seconds=0.01,
            scenario_timeout_seconds=0.02,
        ),
        artifact_dir=tmp_path,
        scenarios={"quick": quick},
    )

    result = payload["results"][0]
    assert result["status"] == "fail"
    assert result["error_code"] == "scenario_deadline_exceeded"


@pytest.mark.asyncio
async def test_bounded_subprocess_enforces_timeout() -> None:
    with pytest.raises(TimeoutError, match="deadline"):
        await perf_scenarios.run_bounded_subprocess(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout_seconds=0.05,
        )


def test_provenance_contains_commit_dirty_command_dependencies_and_tool_version() -> None:
    provenance = perf_runner.collect_provenance(["python", "scripts/perf/run.py", "--scenario", "all"])

    assert provenance["git_commit"]
    assert isinstance(provenance["git_dirty"], bool)
    assert provenance["command"] == ["python", "scripts/perf/run.py", "--scenario", "all"]
    assert provenance["tool_version"]
    assert provenance["dependency_versions"]["psutil"]


@pytest.mark.asyncio
async def test_run_has_initial_to_final_resource_gate(tmp_path) -> None:
    async def scenario(_config: ScenarioConfig) -> ScenarioOutcome:
        return ScenarioOutcome(
            name="global",
            passed=True,
            duration_seconds=0,
            idle_probe=lambda: {"idle": True},
        )

    payload = await run_serial(
        ["global"],
        config=RunConfig(settle_seconds=0.02, sample_interval_seconds=0.01),
        artifact_dir=tmp_path,
        scenarios={"global": scenario},
    )

    resources = payload["overall_resources"]
    assert resources["baseline"]["process_ids"]
    assert "handles_returned" in resources["checks"]
    assert "asyncio_tasks_returned" in resources["checks"]
    assert "process_ids_returned" in resources["checks"]
