from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import DiagramSource, PluginConfig


@dataclass(frozen=True)
class WorkerResult:
    ok: bool
    filename: str
    content: bytes = b""
    warnings: tuple[str, ...] = ()
    error: str = ""


def convert_with_worker(source: DiagramSource, config: PluginConfig, timeout_seconds: float) -> WorkerResult:
    worker = Path(__file__).resolve().parents[1] / "worker.py"
    payload = {
        "source": source.__dict__,
        "config": config.__dict__,
    }
    try:
        completed = subprocess.run(
            [sys.executable, str(worker)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=max(1.0, timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return WorkerResult(ok=False, filename=source.suggested_filename, error=f"转换超时: {int(timeout_seconds)}s")
    if completed.returncode != 0:
        return WorkerResult(ok=False, filename=source.suggested_filename, error=completed.stderr.strip() or "转换进程失败")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return WorkerResult(ok=False, filename=source.suggested_filename, error=f"转换结果无效: {exc}")
    if not data.get("ok"):
        return WorkerResult(ok=False, filename=source.suggested_filename, error=str(data.get("error") or "转换失败"))
    output_path = Path(str(data["outputPath"]))
    try:
        content = output_path.read_bytes()
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except TypeError:
            if output_path.exists():
                output_path.unlink()
    return WorkerResult(
        ok=True,
        filename=str(data.get("filename") or source.suggested_filename),
        content=content,
        warnings=tuple(str(item) for item in data.get("warnings") or []),
    )
