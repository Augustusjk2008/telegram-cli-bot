from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from bot.assistant.cron.types import AssistantCronJob, AssistantCronJobState, validate_cron_job_id
from bot.assistant.home import AssistantHome


def _jobs_dir(home: AssistantHome) -> Path:
    return home.root / "automation" / "jobs"


def _state_dir(home: AssistantHome) -> Path:
    return home.root / "state" / "cron"


def _audit_dir(home: AssistantHome) -> Path:
    return home.root / "audit" / "cron"


def _safe_item_path(base_dir: Path, item_id: str, suffix: str) -> Path:
    try:
        safe_id = validate_cron_job_id(item_id)
    except ValueError as exc:
        raise ValueError(f"unsafe cron id: {item_id}") from exc
    base = base_dir.resolve()
    path = (base_dir / f"{safe_id}{suffix}").resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"unsafe cron id: {item_id}") from exc
    return path


def _job_path(home: AssistantHome, job_id: str) -> Path:
    return _safe_item_path(_jobs_dir(home), job_id, ".yaml")


def _state_path(home: AssistantHome, job_id: str) -> Path:
    return _safe_item_path(_state_dir(home), job_id, ".json")


def _audit_path(home: AssistantHome, job_id: str) -> Path:
    return _safe_item_path(_audit_dir(home), job_id, ".jsonl")


def save_job_definition(home: AssistantHome, job: AssistantCronJob) -> None:
    path = _job_path(home, job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(job.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def read_job_definition(home: AssistantHome, job_id: str) -> AssistantCronJob:
    path = _job_path(home, job_id)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AssistantCronJob.from_dict(payload)


def list_job_definitions(home: AssistantHome) -> list[AssistantCronJob]:
    items: list[AssistantCronJob] = []
    for path in sorted(_jobs_dir(home).glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items.append(AssistantCronJob.from_dict(payload))
    return items


def delete_job_definition(home: AssistantHome, job_id: str) -> bool:
    path = _job_path(home, job_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def delete_job_runtime_state(home: AssistantHome, job_id: str) -> bool:
    path = _state_path(home, job_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def save_job_runtime_state(home: AssistantHome, job_id: str, state: AssistantCronJobState) -> None:
    path = _state_path(home, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_job_runtime_state(home: AssistantHome, job_id: str) -> AssistantCronJobState:
    path = _state_path(home, job_id)
    if not path.exists():
        return AssistantCronJobState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AssistantCronJobState.from_dict(payload)


def append_job_run_audit(home: AssistantHome, job_id: str, record: dict[str, Any]) -> None:
    path = _audit_path(home, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


def upsert_job_run_audit(home: AssistantHome, job_id: str, record: dict[str, Any]) -> None:
    run_id = str(record.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("audit record 缺少 run_id")

    path = _audit_path(home, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False))
        handle.write("\n")


def delete_job_run_audit(home: AssistantHome, job_id: str) -> bool:
    path = _audit_path(home, job_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def _read_text_chunks_reverse(path: Path, *, chunk_size: int = 64 * 1024):
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        pending = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            if not chunk:
                continue
            data = chunk + pending
            parts = data.split(b"\n")
            pending = parts[0]
            for line in reversed(parts[1:]):
                yield line
        if pending:
            yield pending


def read_job_run_audit(home: AssistantHome, job_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = _audit_path(home, job_id)
    if not path.exists():
        return []
    if limit is None:
        folded: dict[str, dict[str, Any]] = {}
        ordered_run_ids: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            run_id = str(record.get("run_id") or "").strip()
            if not run_id:
                continue
            if run_id not in folded:
                ordered_run_ids.append(run_id)
            folded[run_id] = record
        return [folded[run_id] for run_id in ordered_run_ids]
    folded: dict[str, dict[str, Any]] = {}
    unique_limit = max(1, int(limit)) if limit is not None else None
    for raw_line in _read_text_chunks_reverse(path):
        if not raw_line.strip():
            continue
        record = json.loads(raw_line.decode("utf-8"))
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            continue
        if run_id in folded:
            continue
        folded[run_id] = record
        if unique_limit is not None and len(folded) >= unique_limit:
            break
    records = list(reversed(list(folded.values())))
    return records
