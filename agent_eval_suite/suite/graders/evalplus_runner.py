from __future__ import annotations

import json
import math
import sys
import traceback
from copy import deepcopy
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(json.dumps({"ok": False, "error": "payload path required"}))
        return 2
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    namespace: dict[str, object] = {}
    try:
        if payload.get("mode") == "call_tests":
            _run_call_tests(payload)
        else:
            exec(str(payload["solution"]), namespace)
            exec(str(payload["test_code"]), namespace)
    except BaseException as exc:  # noqa: BLE001 - report untrusted solution failures.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps({"ok": True}))
    return 0


def _run_call_tests(payload: dict[str, object]) -> None:
    entry_point = str(payload["entry_point"])
    inputs = payload["inputs"]
    if not isinstance(inputs, list):
        raise TypeError("inputs must be a list")
    atol = float(payload.get("atol", 0) or 0)
    reference_ns: dict[str, object] = {}
    solution_ns: dict[str, object] = {}
    prompt = str(payload.get("prompt", ""))
    exec(prompt + "\n" + str(payload["canonical_solution"]), reference_ns)
    exec(prompt + "\n" + str(payload["solution"]), solution_ns)
    reference_fn = reference_ns[entry_point]
    solution_fn = solution_ns[entry_point]
    for call_input in inputs:
        args = call_input if isinstance(call_input, list) else [call_input]
        expected = reference_fn(*deepcopy(args))
        actual = solution_fn(*deepcopy(args))
        if not _same_output(actual, expected, atol):
            raise AssertionError(f"expected {expected!r}, got {actual!r}")


def _same_output(actual: object, expected: object, atol: float) -> bool:
    if isinstance(actual, float) or isinstance(expected, float):
        return math.isclose(float(actual), float(expected), abs_tol=atol)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_output(a, e, atol) for a, e in zip(actual, expected)
        )
    if isinstance(actual, tuple) and isinstance(expected, tuple):
        return len(actual) == len(expected) and all(
            _same_output(a, e, atol) for a, e in zip(actual, expected)
        )
    return actual == expected


if __name__ == "__main__":
    raise SystemExit(main())
