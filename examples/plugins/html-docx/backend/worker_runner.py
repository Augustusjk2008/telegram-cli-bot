"""Run conversion stages with the remaining budget of a single operation."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULTS = {
    "maxSourceBytes": 2097152,
    "maxResourceBytes": 16777216,
    "maxImagePixels": 16000000,
    "maxElements": 10000,
    "maxTableCells": 10000,
    "conversionTimeoutSeconds": 45,
    "defaultFont": "Microsoft YaHei",
    "defaultFontSizePt": 11,
}
CAPS = {
    "maxSourceBytes": 2097152,
    "maxResourceBytes": 16777216,
    "maxImagePixels": 16000000,
    "maxElements": 10000,
    "maxTableCells": 10000,
    "conversionTimeoutSeconds": 55,
    "defaultFontSizePt": 72,
}


def bounded_config(config: dict | None = None) -> dict:
    current = config or {}
    result = dict(DEFAULTS)
    for key, cap in CAPS.items():
        try:
            result[key] = max(6 if key == "defaultFontSizePt" else 1, min(cap, int(current.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError, OverflowError):
            pass
    result["defaultFont"] = str(current.get("defaultFont") or DEFAULTS["defaultFont"])[:128]
    return result


def run_worker(operation: str, source: bytes, config: dict, *, deadline: float,
               resources: dict[str, bytes] | None = None,
               max_artifact_bytes: int = 33554432) -> dict[str, Any]:
    payload = {
        "operation": operation,
        "sourceBase64": base64.b64encode(source).decode("ascii"),
        "resources": None if resources is None else {
            name: base64.b64encode(content).decode("ascii") for name, content in resources.items()
        },
        "config": config,
        "maxArtifactBytes": max_artifact_bytes,
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    worker_dir = Path(__file__).resolve().parent
    worker_env = os.environ.copy()
    existing_python_path = worker_env.get("PYTHONPATH")
    worker_env["PYTHONPATH"] = os.pathsep.join(
        [str(worker_dir), existing_python_path] if existing_python_path else [str(worker_dir)]
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("转换预算已耗尽")
    try:
        # subprocess.run kills and reaps only this conversion worker on timeout.
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("worker.py"))],
            input=encoded, capture_output=True, env=worker_env, timeout=remaining, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("转换 worker 超时") from exc
    if time.monotonic() >= deadline:
        raise TimeoutError("转换预算已耗尽")
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr[:4096].decode("utf-8", errors="replace") or "转换进程失败"}
    if len(completed.stdout) > 4 * ((max_artifact_bytes + 2) // 3) + 2097152:
        return {"ok": False, "error": "转换结果超过产物限额"}
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict):
            raise ValueError("expected object")
        return result
    except (ValueError, UnicodeError) as exc:
        return {"ok": False, "error": f"转换结果无效: {exc}"}
