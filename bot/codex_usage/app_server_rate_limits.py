"""Best-effort one-shot Codex app-server account rate-limit lookup."""

from __future__ import annotations

import json
import math
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import (
    KNOWN_CODEX_RATE_LIMIT_IDS,
    SECONDARY_CODEX_RATE_LIMIT_ID,
    CodexRateLimitSample,
    SQLITE_INT64_MAX,
)


_APP_SERVER_TIMEOUT_SECONDS = 5.0


def _sample_from_snapshot(
    snapshot: object,
    *,
    limit_id: str,
) -> CodexRateLimitSample | None:
    if not isinstance(snapshot, Mapping):
        return None
    window_name = "secondary" if limit_id == SECONDARY_CODEX_RATE_LIMIT_ID else "primary"
    window = snapshot.get(window_name)
    if not isinstance(window, Mapping):
        return None
    used_percent = window.get("usedPercent")
    window_minutes = window.get("windowDurationMins")
    resets_at = window.get("resetsAt")
    if (
        isinstance(used_percent, bool)
        or not isinstance(used_percent, (int, float))
        or (isinstance(used_percent, float) and not math.isfinite(used_percent))
        or not 0 <= used_percent <= 100
    ):
        return None
    if (
        isinstance(window_minutes, bool)
        or not isinstance(window_minutes, int)
        or window_minutes <= 0
        or window_minutes > SQLITE_INT64_MAX
    ):
        return None
    if isinstance(resets_at, bool) or not isinstance(resets_at, int) or resets_at < 0:
        return None
    plan_type = snapshot.get("planType")
    if plan_type is not None and not isinstance(plan_type, str):
        return None
    try:
        return CodexRateLimitSample(
            sampled_at=datetime.now(timezone.utc),
            used_percent=float(used_percent),
            window_minutes=window_minutes,
            resets_at=datetime.fromtimestamp(resets_at, timezone.utc),
            plan_type=plan_type,
            limit_id=limit_id,
        )
    except (OSError, OverflowError, ValueError):
        return None


def _response_for_request(
    lines: queue.Queue[object],
    request_id: int,
    deadline: float,
) -> Mapping[str, Any] | None:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return None
        if line is None:
            return None
        try:
            message = json.loads(str(line))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(message, Mapping) or message.get("id") != request_id:
            continue
        if not isinstance(message.get("result"), Mapping):
            return None
        return message["result"]


def _read_stdout(stream: Any, lines: queue.Queue[object]) -> None:
    try:
        for line in stream:
            lines.put(line)
    finally:
        lines.put(None)


def _write_payload(stream: Any, payload: Mapping[str, Any]) -> None:
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def resolve_account_rate_limits(
    *,
    executable: str,
    env: Mapping[str, str] | None,
) -> tuple[CodexRateLimitSample, ...]:
    """Read known account buckets through one short-lived Codex app-server process."""

    executable_text = str(executable or "").strip()
    if not executable_text:
        return ()
    process = None
    reader: threading.Thread | None = None
    lines: queue.Queue[object] = queue.Queue()
    deadline = time.monotonic() + _APP_SERVER_TIMEOUT_SECONDS
    try:
        process = subprocess.Popen(
            [executable_text, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env) if env is not None else None,
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.stdin is None or process.stdout is None:
            return ()
        reader = threading.Thread(
            target=_read_stdout,
            args=(process.stdout, lines),
            daemon=True,
        )
        reader.start()
        payloads = (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "orbit-safe-claw", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"jsonrpc": "2.0", "method": "initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "account/rateLimits/read",
                "params": None,
            },
        )
        _write_payload(process.stdin, payloads[0])
        if _response_for_request(lines, 1, deadline) is None:
            return ()
        _write_payload(process.stdin, payloads[1])
        _write_payload(process.stdin, payloads[2])
        result = _response_for_request(lines, 2, deadline)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    finally:
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.terminate()
                process.wait(timeout=0.5)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=0.5)
                except (OSError, subprocess.SubprocessError):
                    pass
    if result is None:
        return ()
    buckets = result.get("rateLimitsByLimitId")
    if not isinstance(buckets, Mapping):
        return ()
    samples = (
        _sample_from_snapshot(buckets.get(limit_id), limit_id=limit_id)
        for limit_id in KNOWN_CODEX_RATE_LIMIT_IDS
    )
    return tuple(sample for sample in samples if sample is not None)


def resolve_account_rate_limit(
    *,
    executable: str,
    env: Mapping[str, str] | None,
    limit_id: str = "codex",
) -> CodexRateLimitSample | None:
    """Compatibility wrapper returning one requested account bucket."""

    normalized_limit_id = str(limit_id or "").strip()
    return next(
        (
            sample
            for sample in resolve_account_rate_limits(executable=executable, env=env)
            if sample.limit_id == normalized_limit_id
        ),
        None,
    )


__all__ = ["resolve_account_rate_limit", "resolve_account_rate_limits"]
