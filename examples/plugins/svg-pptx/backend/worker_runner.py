"""Run one conversion in an independent, time-limited Python process."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULTS = {
    "maxSourceBytes": 2 * 1024 * 1024,
    "conversionTimeoutSeconds": 45,
    "maxTextBoxes": 500,
    "maxLayers": 100,
    "renderMaxSide": 4096,
}
CAPS = {
    "maxSourceBytes": 32 * 1024 * 1024,
    "conversionTimeoutSeconds": 55,
    "maxTextBoxes": 500,
    "maxLayers": 100,
    "renderMaxSide": 4096,
}


def bounded_config(config: dict[str, Any] | None = None) -> dict[str, int]:
    current = config or {}
    return {
        key: max(1, min(CAPS[key], int(current.get(key, default))))
        for key, default in DEFAULTS.items()
    }


def run_worker(
    operation: str,
    source: bytes,
    config: dict[str, Any] | None = None,
    *,
    max_artifact_bytes: int = 32 * 1024 * 1024,
) -> dict[str, Any]:
    limits = bounded_config(config)
    if len(source) > limits["maxSourceBytes"]:
        return {"ok": False, "error": f"SVG 文件超过限制: {limits['maxSourceBytes']} bytes"}
    timeout = limits["conversionTimeoutSeconds"]
    payload = {
        "operation": operation,
        "sourceBase64": base64.b64encode(source).decode("ascii"),
        "config": limits,
        "maxArtifactBytes": max_artifact_bytes,
    }
    worker_dir = Path(__file__).resolve().parent
    worker_env = os.environ.copy()
    existing_python_path = worker_env.get("PYTHONPATH")
    worker_env["PYTHONPATH"] = os.pathsep.join(
        [str(worker_dir), existing_python_path] if existing_python_path else [str(worker_dir)]
    )
    try:
        # subprocess.run kills and reaps only this child on timeout.
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().with_name("worker.py"))],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True, env=worker_env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"SVG 转换超时: {timeout}s"}
    if completed.returncode != 0:
        error = completed.stderr[:4096].decode("utf-8", errors="replace").strip()
        return {"ok": False, "error": error or "SVG 转换进程失败"}
    # Allow bounded report metadata in addition to the base64 artifact.
    if len(completed.stdout) > 4 * ((max_artifact_bytes + 2) // 3) + 1024 * 1024:
        return {"ok": False, "error": "SVG 转换结果超过产物限额"}
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict):
            raise ValueError("expected an object")
        return result
    except (ValueError, UnicodeError) as exc:
        return {"ok": False, "error": f"SVG 转换结果无效: {exc}"}
