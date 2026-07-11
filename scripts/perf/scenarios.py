from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import random
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Mapping

import psutil

from scripts.perf import FIXED_SEED


IdleProbe = Callable[[], Mapping[str, bool] | Awaitable[Mapping[str, bool]]]


@dataclass(frozen=True)
class ScenarioConfig:
    profile: str
    seed: int = FIXED_SEED
    scenario_timeout_seconds: float = 120.0
    git_command_timeout_seconds: float = 30.0


@dataclass
class ScenarioOutcome:
    name: str
    passed: bool
    duration_seconds: float
    coverage: str = "real"
    metrics: dict[str, object] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    idle_probe: IdleProbe | None = None
    observation_gaps: list[str] = field(default_factory=list)

    def to_dict(self, *, idle_checks: Mapping[str, bool] | None = None) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "coverage": self.coverage,
            "duration_seconds": self.duration_seconds,
            "metrics": self.metrics,
            "checks": self.checks,
            "idle_checks": dict(idle_checks or {}),
            "observation_gaps": self.observation_gaps,
        }


ScenarioFunction = Callable[[ScenarioConfig], Awaitable[ScenarioOutcome]]


def deterministic_chunks(*, seed: int, count: int, min_size: int = 8, max_size: int = 48) -> list[str]:
    rng = random.Random(seed)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return [
        "".join(rng.choice(alphabet) for _ in range(rng.randint(min_size, max_size)))
        for _ in range(count)
    ]


async def resolve_idle_probe(probe: IdleProbe | None) -> dict[str, bool]:
    if probe is None:
        return {"probe_available": False}
    result = probe()
    if inspect.isawaitable(result):
        result = await result
    return {str(name): bool(value) for name, value in result.items()}


async def run_pi_scenario(config: ScenarioConfig) -> ScenarioOutcome:
    from bot.native_agent.pi_turn_stream import PiTurnChannel

    started = time.monotonic()
    delta_count = 10_000 if config.profile == "stress" else 1_000
    chunks = deterministic_chunks(seed=config.seed, count=delta_count)

    async def producer():
        yield {"type": "meta", "native_session_id": "perf-session-1"}
        for index, chunk in enumerate(chunks):
            await asyncio.sleep(0)
            yield {"type": "delta", "event_id": f"delta-{index}", "text": chunk}
        yield {
            "type": "done",
            "turn_id": "perf-turn-1",
            "assistant_message_id": "perf-message-1",
        }

    channel = PiTurnChannel(producer())
    received: list[dict[str, object]] = []
    try:
        received = [event async for event in channel.events()]
        await channel.wait_finished()
    finally:
        await channel.close()

    received_chunks = [str(event.get("text") or "") for event in received if event.get("type") == "delta"]
    event_ids = [str(event.get("event_id") or "") for event in received if event.get("event_id")]
    sequences = [int(event.get("sequence") or 0) for event in received]
    expected_sha = hashlib.sha256("".join(chunks).encode()).hexdigest()
    actual_sha = hashlib.sha256("".join(received_chunks).encode()).hexdigest()
    checks = {
        "final_text_sha_matches": actual_sha == expected_sha,
        "delta_ids_exactly_once": len(event_ids) == delta_count and len(set(event_ids)) == delta_count,
        "sequences_contiguous": sequences == list(range(1, len(sequences) + 1)),
        "done_exactly_once": sum(event.get("type") == "done" for event in received) == 1,
        "turn_id_exactly_once": sum(event.get("turn_id") == "perf-turn-1" for event in received) == 1,
        "assistant_message_id_exactly_once": sum(
            event.get("assistant_message_id") == "perf-message-1" for event in received
        ) == 1,
        "no_gap": all(event.get("type") != "gap" for event in received),
    }

    def idle_probe() -> Mapping[str, bool]:
        diagnostics = channel.diagnostics()
        return {
            "pi_turn_finished": bool(diagnostics["finished"]),
            "pi_turn_no_consumers": int(diagnostics["active_consumers"]) == 0,
            "pi_turn_replay_bounded": (
                int(diagnostics["replay_events"]) <= int(diagnostics["replay_max_events"])
                and int(diagnostics["replay_bytes"]) <= int(diagnostics["replay_max_bytes"])
            ),
        }

    return ScenarioOutcome(
        name="pi",
        passed=all(checks.values()),
        coverage="boundary",
        duration_seconds=time.monotonic() - started,
        metrics={
            "seed": config.seed,
            "delta_count": delta_count,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "diagnostics": channel.diagnostics(),
            "public_boundary": "PiTurnChannel",
        },
        checks=checks,
        idle_probe=idle_probe,
    )


def evaluate_terminal_timing(
    *,
    produced_bytes: int,
    elapsed_seconds: float,
    target_duration_seconds: float,
    target_rate_bytes_per_second: float,
    deadline_seconds: float,
) -> tuple[dict[str, bool], dict[str, float]]:
    actual_rate = produced_bytes / max(elapsed_seconds, 1e-9)
    checks = {
        "minimum_wall_duration": elapsed_seconds >= target_duration_seconds * 0.99,
        "deadline_honored": elapsed_seconds <= deadline_seconds,
        "minimum_sustained_rate": actual_rate >= target_rate_bytes_per_second * 0.99,
    }
    return checks, {
        "actual_wall_seconds": elapsed_seconds,
        "actual_bytes_per_second": actual_rate,
        "target_duration_seconds": target_duration_seconds,
        "target_rate_bytes_per_second": target_rate_bytes_per_second,
        "deadline_seconds": deadline_seconds,
    }


async def run_terminal_scenario(config: ScenarioConfig) -> ScenarioOutcome:
    from bot.web.terminal_manager import (
        TERMINAL_CLIENT_EOF,
        TerminalClientQueue,
        TerminalDelivery,
    )

    target_duration = 60.0 if config.profile == "stress" else 1.0
    target_rate = float(10 * 1024 * 1024 if config.profile == "stress" else 4 * 1024 * 1024)
    minimum_bytes = int(target_duration * target_rate)
    target_bytes = int(minimum_bytes * 1.02)
    pacing_rate = target_bytes / target_duration
    wall_deadline = target_duration + max(2.0, target_duration * 0.1)
    chunk_bytes = 64 * 1024
    stream_id = "perf-terminal-stream"
    normal = TerminalClientQueue(protocol_version=2)
    slow = TerminalClientQueue(protocol_version=2)
    normal_hasher = hashlib.sha256()
    expected_hasher = hashlib.sha256()
    received_sequences: list[int] = []
    eof_count = 0

    async def consume() -> None:
        nonlocal eof_count
        while True:
            item = await normal.get()
            if item is TERMINAL_CLIENT_EOF:
                eof_count += 1
                return
            if isinstance(item, TerminalDelivery) and item.kind == "output":
                received_sequences.append(item.sequence)
                normal_hasher.update(item.payload)

    consumer = asyncio.create_task(consume(), name="perf-terminal-consumer")
    rng = random.Random(config.seed)
    payload_template = rng.randbytes(chunk_bytes)
    slow_disconnected = False
    slow_gap_seen = False
    produced = 0
    sequence = 0
    wall_started = time.monotonic()
    while produced < target_bytes:
        size = min(chunk_bytes, target_bytes - produced)
        payload = payload_template[:size]
        sequence += 1
        delivery = TerminalDelivery(
            stream_id=stream_id,
            kind="output",
            sequence=sequence,
            payload=payload,
        )
        expected_hasher.update(payload)
        if not normal.put_delivery(delivery):
            break
        if not slow_disconnected and not slow.put_delivery(delivery):
            slow_disconnected = True
        produced += size
        due = wall_started + produced / pacing_rate
        if due > time.monotonic():
            await asyncio.sleep(due - time.monotonic())
        else:
            await asyncio.sleep(0)
        if time.monotonic() - wall_started > wall_deadline:
            break
    remaining = wall_started + target_duration - time.monotonic()
    if remaining > 0:
        await asyncio.sleep(remaining)
    elapsed = time.monotonic() - wall_started
    normal.put_eof()
    await consumer
    if slow_disconnected:
        while True:
            item = await slow.get()
            if item is TERMINAL_CLIENT_EOF:
                break
            if isinstance(item, TerminalDelivery) and item.kind == "gap":
                slow_gap_seen = item.snapshot_required and item.reason == "slow_client"
    slow.clear()

    expected_sha = expected_hasher.hexdigest()
    actual_sha = normal_hasher.hexdigest()
    timing_checks, timing_metrics = evaluate_terminal_timing(
        produced_bytes=produced,
        elapsed_seconds=elapsed,
        target_duration_seconds=target_duration,
        target_rate_bytes_per_second=target_rate,
        deadline_seconds=wall_deadline,
    )
    checks = {
        **timing_checks,
        "normal_client_sha_matches": actual_sha == expected_sha,
        "normal_client_eof_exactly_once": eof_count == 1,
        "delivery_sequences_contiguous": received_sequences == list(range(1, sequence + 1)),
        "slow_client_disconnected": slow_disconnected,
        "slow_client_gap_reported": slow_gap_seen,
        "produced_target_bytes": produced == target_bytes,
    }

    def idle_probe() -> Mapping[str, bool]:
        return {
            "normal_queue_empty": normal.queued_bytes == 0,
            "slow_queue_released": slow.queued_bytes == 0,
            "terminal_consumer_finished": consumer.done(),
        }

    return ScenarioOutcome(
        name="terminal",
        passed=all(checks.values()),
        coverage="boundary",
        duration_seconds=time.monotonic() - wall_started,
        metrics={
            "seed": config.seed,
            "target_bytes": target_bytes,
            "minimum_bytes": minimum_bytes,
            "produced_bytes": produced,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "public_boundary": "TerminalDelivery/TerminalClientQueue-v2",
            **timing_metrics,
        },
        checks=checks,
        idle_probe=idle_probe,
    )


_PLUGIN_DRIVER = r'''from __future__ import annotations
import json
import os
import sys

for line in sys.stdin.buffer:
    request = json.loads(line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if method == "plugin.shutdown":
        result = {"ok": True}
    elif method == "plugin.render_view":
        payload = dict(params.get("input") or {})
        oversize = int(payload.get("oversizeBytes") or 0)
        if oversize:
            block = b"x" * (64 * 1024)
            remaining = oversize
            while remaining > 0:
                part = block[:min(len(block), remaining)]
                os.write(sys.stdout.fileno(), part)
                remaining -= len(part)
            continue
        result = {"kind": "document", "requestIndex": int(payload.get("requestIndex") or 0)}
    else:
        result = {"ok": True}
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
'''


async def run_plugin_scenario(config: ScenarioConfig) -> ScenarioOutcome:
    from bot.plugins.models import PluginManifest, PluginRuntimeSpec, PluginViewSpec
    from bot.plugins.runtime import PLUGIN_MAX_FRAME_BYTES, PluginRuntime

    started = time.monotonic()
    request_count = 1_000 if config.profile == "stress" else 25
    oversize_bytes = 100 * 1024 * 1024 if config.profile == "stress" else PLUGIN_MAX_FRAME_BYTES + 1024
    runtime: PluginRuntime | None = None
    with tempfile.TemporaryDirectory(prefix="tcb-perf-plugin-") as temp_dir:
        root = Path(temp_dir)
        (root / "main.py").write_text(_PLUGIN_DRIVER, encoding="utf-8")
        manifest = PluginManifest(
            root=root,
            plugin_id="perf-plugin",
            schema_version=2,
            name="Perf Plugin",
            version="1.0.0",
            description="",
            enabled=True,
            config={},
            runtime=PluginRuntimeSpec(runtime_type="python", entry="main.py", protocol="jsonrpc-stdio"),
            views=(PluginViewSpec(id="main", title="Main", renderer="document"),),
            file_handlers=(),
        )
        runtime = PluginRuntime(workspace_root_for=lambda _alias: root, call_timeout_seconds=20)
        response_indexes: list[int] = []
        protocol_error = ""
        try:
            for index in range(request_count):
                response = await runtime.render_view("perf", manifest, "main", {"requestIndex": index})
                response_indexes.append(int(response.get("requestIndex", -1)))
            try:
                await runtime.render_view("perf", manifest, "main", {"oversizeBytes": oversize_bytes})
            except RuntimeError as exc:
                protocol_error = str(exc)
        finally:
            await runtime.shutdown()

    assert runtime is not None
    checks = {
        "responses_exactly_once_and_ordered": response_indexes == list(range(request_count)),
        "oversize_frame_rejected": "协议帧超过" in protocol_error,
        "plugin_processes_released": runtime.active_process_count() == 0,
    }
    return ScenarioOutcome(
        name="plugin",
        passed=all(checks.values()),
        coverage="real",
        duration_seconds=time.monotonic() - started,
        metrics={
            "seed": config.seed,
            "request_count": request_count,
            "oversize_frame_bytes": oversize_bytes,
            "protocol_error": protocol_error,
            "active_process_count": runtime.active_process_count(),
        },
        checks=checks,
        idle_probe=lambda: {"plugin_processes_zero": runtime.active_process_count() == 0},
    )


async def run_search_scenario(config: ScenarioConfig) -> ScenarioOutcome:
    from bot.web.workspace_search_service import search_workspace_text

    started = time.monotonic()
    hit_count = 100_000 if config.profile == "stress" else 2_000
    limit = 100
    needle = "PERF_FIXED_NEEDLE"

    def create_search_and_remove() -> tuple[dict[str, object], float]:
        with tempfile.TemporaryDirectory(prefix="tcb-perf-search-") as temp_dir:
            root = Path(temp_dir)
            per_file = 1_000
            for file_index in range((hit_count + per_file - 1) // per_file):
                lines = min(per_file, hit_count - file_index * per_file)
                content = "".join(f"{needle} {file_index:05d} {line:05d}\n" for line in range(lines))
                (root / f"matches-{file_index:05d}.txt").write_text(content, encoding="utf-8")
            search_started = time.monotonic()
            result = search_workspace_text(root, needle, limit=limit)
            return result, time.monotonic() - search_started

    result, search_seconds = await asyncio.to_thread(create_search_and_remove)
    items = list(result.get("items") or [])
    checks = {
        "result_limit_honored": len(items) == limit,
        "all_results_match": all(needle in str(item.get("preview") or "") for item in items),
        "truncation_explicit": result.get("truncated") is True,
        "truncation_reason_limit": result.get("reason") == "limit",
        "backend_reported": result.get("backend") in {"rg", "python"},
    }
    return ScenarioOutcome(
        name="search",
        passed=all(checks.values()),
        coverage="real",
        duration_seconds=time.monotonic() - started,
        metrics={
            "seed": config.seed,
            "fixture_hit_count": hit_count,
            "returned_count": len(items),
            "search_seconds": search_seconds,
            "truncated": result.get("truncated"),
            "reason": result.get("reason"),
            "backend": result.get("backend"),
        },
        checks=checks,
        idle_probe=lambda: {"search_call_completed": True},
    )


async def _terminate_subprocess_tree(process: asyncio.subprocess.Process) -> None:
    try:
        root = psutil.Process(process.pid)
        children = root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for child in reversed(children):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if process.returncode is None:
        process.kill()
    await process.communicate()


async def run_bounded_subprocess(
    command: list[str],
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        await _terminate_subprocess_tree(process)
        raise TimeoutError(f"subprocess deadline exceeded after {timeout_seconds:.3f}s") from exc
    return int(process.returncode or 0), stdout, stderr


async def run_git_scenario(config: ScenarioConfig) -> ScenarioOutcome:
    if not shutil.which("git"):
        return ScenarioOutcome(
            name="git",
            passed=False,
            duration_seconds=0.0,
            checks={"git_available": False},
            observation_gaps=["git executable unavailable"],
        )
    started = time.monotonic()
    untracked_count = 10_000 if config.profile == "stress" else 100
    total_files = 100_000 if config.profile == "stress" else 1_000
    worker = Path(__file__).with_name("git_worker.py")
    command = [
        sys.executable,
        str(worker),
        "--total-files",
        str(total_files),
        "--untracked-files",
        str(untracked_count),
        "--git-timeout",
        str(config.git_command_timeout_seconds),
    ]
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [repo_root, env.get("PYTHONPATH", "")]))
    returncode, stdout, stderr = await run_bounded_subprocess(
        command,
        timeout_seconds=config.git_command_timeout_seconds,
        cwd=Path(repo_root),
        env=env,
    )
    if returncode != 0:
        raise RuntimeError(
            f"git worker failed ({returncode}): {stderr.decode('utf-8', errors='replace')[-2000:]}"
        )
    payload = json.loads(stdout.decode("utf-8"))
    overview = dict(payload.get("overview") or {})
    changed_files = list(overview.get("changed_files") or [])
    if untracked_count > 2_000:
        truncation_checks = {
            "untracked_truncation_reported": overview.get("untracked_files_truncated") is True,
            "count_marked_inexact": overview.get("count_exact") is False,
            "truncation_reason_reported": bool(overview.get("truncation_reason")),
            "changed_files_bounded": len(changed_files) <= 2_000,
        }
    else:
        truncation_checks = {
            "untracked_count_exact": overview.get("count_exact") is True,
            "changed_files_count_exact": len(changed_files) == untracked_count,
        }
    checks = {
        "repo_found": overview.get("repo_found") is True,
        **truncation_checks,
    }
    return ScenarioOutcome(
        name="git",
        passed=all(checks.values()),
        coverage="real",
        duration_seconds=time.monotonic() - started,
        metrics={
            "seed": config.seed,
            "total_files": total_files,
            "untracked_files": untracked_count,
            "worker_seconds": payload.get("duration_seconds"),
            "changed_files_count": len(changed_files),
            "status_truncated": overview.get("status_truncated"),
            "count_lower_bound": overview.get("count_lower_bound"),
            "count_exact": overview.get("count_exact"),
            "truncation_reason": overview.get("truncation_reason"),
        },
        checks=checks,
        idle_probe=lambda: {"git_worker_completed": True},
    )


SCENARIOS: dict[str, ScenarioFunction] = {
    "pi": run_pi_scenario,
    "terminal": run_terminal_scenario,
    "plugin": run_plugin_scenario,
    "search": run_search_scenario,
    "git": run_git_scenario,
}
SCENARIO_ORDER = tuple(SCENARIOS)
