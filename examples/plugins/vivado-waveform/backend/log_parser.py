from __future__ import annotations

import re
from typing import Any


_NUMBER = r"\d+(?:\.\d+)?"
_EXPLICIT_TIME_RE = re.compile(
    rf"(?:sim(?:ulation)?[_ ]?time|at\s+time|time)\s*[:=]?\s*({_NUMBER})",
    re.IGNORECASE,
)
_FINISH_RE = re.compile(rf"\$finish\s+called\s+at\s+time\s+({_NUMBER})", re.IGNORECASE)
_ELAPSED_RE = re.compile(rf"elapsed\s*[:=]?\s*({_NUMBER})", re.IGNORECASE)
_RUN_TIME_RE = re.compile(rf"run\s*:\s*time\s*[:=]?\s*({_NUMBER})\s+elapsed", re.IGNORECASE)


def _number(value: str) -> int | float:
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _event_time(line: str) -> int | float | None:
    match = _EXPLICIT_TIME_RE.search(line)
    return _number(match.group(1)) if match else None


def _tags(line: str) -> list[str]:
    tags: list[str] = []
    for match in re.findall(r"\[([^\]]+)\]", line):
        tags.extend(item for item in re.split(r"[\s,]+", match.strip()) if item)
    match = re.search(r"\btags?\s*[:=]\s*([^;]+)", line, re.IGNORECASE)
    if match:
        tags.extend(item for item in re.split(r"[\s,]+", match.group(1).strip()) if item)
    return list(dict.fromkeys(tags))


def _missing_signal(line: str) -> str | None:
    match = re.search(r"VCD\s+pattern\s+not\s+found\s*[:=]?\s*(\S+)", line, re.IGNORECASE)
    if match:
        return match.group(1).strip("'\".,;:")
    match = re.search(r"missing\s+signal\s*[:=]\s*(\S+)", line, re.IGNORECASE)
    return match.group(1).strip("'\".,;:") if match else None


def parse_vivado_log(text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    missing_signals: list[str] = []
    warnings: list[str] = []
    test_status = "unknown"
    test_name: str | None = None
    finish_time: int | float | None = None
    elapsed: int | float | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        kind: str | None = None
        if "TEST_FAIL" in upper or re.search(r"\bERROR\s*:", upper):
            kind = "fail" if "TEST_FAIL" in upper else "error"
            test_status = "fail"
            match = re.search(r"TEST_FAIL\s*(?:[:=]\s*|\s+)?([^;]+)?", line, re.IGNORECASE)
            if match and match.group(1):
                candidate = match.group(1).strip()
                if candidate and not candidate.lower().startswith("errors"):
                    test_name = candidate
        elif "TEST_PASS" in upper or re.search(r"\bPASS\s*:", upper):
            kind = "pass"
            if test_status != "fail":
                test_status = "pass"
            match = re.search(r"TEST_PASS\s*(?:[:=]\s*|\s+)?([^;]+)?", line, re.IGNORECASE)
            if match and match.group(1):
                candidate = match.group(1).strip()
                if candidate:
                    test_name = candidate
        elif re.search(r"\bWARNING\s*:", upper):
            kind = "warning"
            warnings.append(line)
        elif "$FINISH" in upper:
            kind = "finish"
            match = _FINISH_RE.search(line)
            if match:
                finish_time = _number(match.group(1))
        elif upper.startswith("RUN:"):
            kind = "run"
            match = _ELAPSED_RE.search(line) or _RUN_TIME_RE.search(line)
            if match:
                elapsed = _number(match.group(1))
        elif "THEORY:" in upper:
            kind = "theory"

        missing = _missing_signal(line)
        if missing and missing not in missing_signals:
            missing_signals.append(missing)
            if line not in warnings:
                warnings.append(line)

        if kind is None:
            continue
        sim_time = None if kind == "run" else (finish_time if kind == "finish" and finish_time is not None else _event_time(line))
        events.append(
            {
                "id": f"line-{line_number}",
                "kind": kind,
                "message": line,
                "line": line_number,
                "simTime": sim_time,
                "tags": _tags(line),
            }
        )

    return {
        "testStatus": test_status,
        "testName": test_name,
        "finishTime": finish_time,
        "elapsed": elapsed,
        "events": events,
        "missingSignals": missing_signals,
        "warnings": warnings,
    }
