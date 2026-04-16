from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from bot.assistant_cron_types import AssistantCronJob, AssistantCronJobState
from bot.assistant_home import AssistantHome


def _jobs_dir(home: AssistantHome) -> Path:
    return home.root / "automation" / "jobs"


def _state_dir(home: AssistantHome) -> Path:
    return home.root / "state" / "cron"


def _audit_dir(home: AssistantHome) -> Path:
    return home.root / "audit" / "cron"


def _job_path(home: AssistantHome, job_id: str) -> Path:
    return _jobs_dir(home) / f"{job_id}.yaml"


def _state_path(home: AssistantHome, job_id: str) -> Path:
    return _state_dir(home) / f"{job_id}.json"


def _audit_path(home: AssistantHome, job_id: str) -> Path:
    return _audit_dir(home) / f"{job_id}.jsonl"


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

    records = read_job_run_audit(home, job_id)
    replaced = False
    for index, existing in enumerate(records):
        if str(existing.get("run_id") or "").strip() == run_id:
            records[index] = dict(record)
            replaced = True
            break
    if not replaced:
        records.append(dict(record))

    path = _audit_path(home, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in records:
            handle.write(json.dumps(item, ensure_ascii=False))
            handle.write("\n")


def delete_job_run_audit(home: AssistantHome, job_id: str) -> bool:
    path = _audit_path(home, job_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def read_job_run_audit(home: AssistantHome, job_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = _audit_path(home, job_id)
    if not path.exists():
        return []
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit is not None:
        return records[-limit:]
    return records
