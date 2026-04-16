from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ScheduleType = Literal["daily", "interval"]
MisfirePolicy = Literal["skip", "once"]


@dataclass(frozen=True)
class AssistantCronSchedule:
    type: ScheduleType
    time: str | None = None
    timezone: str = "Asia/Shanghai"
    every_seconds: int | None = None
    misfire_policy: MisfirePolicy = "skip"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AssistantCronSchedule":
        data = dict(payload or {})
        schedule_type = str(data.get("type") or "").strip().lower()
        if schedule_type not in {"daily", "interval"}:
            raise ValueError("schedule.type 仅支持 daily 或 interval")
        misfire_policy = str(data.get("misfire_policy") or "skip").strip().lower()
        if misfire_policy not in {"skip", "once"}:
            raise ValueError("misfire_policy 仅支持 skip 或 once")
        time_value = str(data.get("time") or "").strip() or None
        every_seconds = data.get("every_seconds")
        if every_seconds is not None:
            every_seconds = int(every_seconds)
        return cls(
            type=schedule_type,
            time=time_value,
            timezone=str(data.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai",
            every_seconds=every_seconds,
            misfire_policy=misfire_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssistantCronTask:
    prompt: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AssistantCronTask":
        prompt = str((payload or {}).get("prompt") or "").strip()
        if not prompt:
            raise ValueError("task.prompt 不能为空")
        return cls(prompt=prompt)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssistantCronExecution:
    timeout_seconds: int = 1800

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AssistantCronExecution":
        value = int((payload or {}).get("timeout_seconds") or 1800)
        if value <= 0:
            raise ValueError("execution.timeout_seconds 必须大于 0")
        return cls(timeout_seconds=value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssistantCronJob:
    id: str
    enabled: bool
    title: str
    schedule: AssistantCronSchedule
    task: AssistantCronTask
    execution: AssistantCronExecution

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AssistantCronJob":
        data = dict(payload or {})
        job_id = str(data.get("id") or "").strip()
        if not job_id:
            raise ValueError("job.id 不能为空")
        return cls(
            id=job_id,
            enabled=bool(data.get("enabled", True)),
            title=str(data.get("title") or job_id).strip() or job_id,
            schedule=AssistantCronSchedule.from_dict(data.get("schedule") or {}),
            task=AssistantCronTask.from_dict(data.get("task") or {}),
            execution=AssistantCronExecution.from_dict(data.get("execution") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "enabled": self.enabled,
            "title": self.title,
            "schedule": self.schedule.to_dict(),
            "task": self.task.to_dict(),
            "execution": self.execution.to_dict(),
        }


@dataclass(frozen=True)
class AssistantCronJobState:
    next_run_at: str = ""
    last_scheduled_at: str = ""
    last_enqueued_at: str = ""
    last_started_at: str = ""
    last_finished_at: str = ""
    last_success_at: str = ""
    last_status: str = ""
    last_error: str = ""
    current_run_id: str = ""
    pending_run_id: str = ""
    pending_scheduled_at: str = ""
    coalesced_count: int = 0
    last_trigger_source: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AssistantCronJobState":
        data = dict(payload or {})
        return cls(
            next_run_at=str(data.get("next_run_at") or ""),
            last_scheduled_at=str(data.get("last_scheduled_at") or ""),
            last_enqueued_at=str(data.get("last_enqueued_at") or ""),
            last_started_at=str(data.get("last_started_at") or ""),
            last_finished_at=str(data.get("last_finished_at") or ""),
            last_success_at=str(data.get("last_success_at") or ""),
            last_status=str(data.get("last_status") or ""),
            last_error=str(data.get("last_error") or ""),
            current_run_id=str(data.get("current_run_id") or ""),
            pending_run_id=str(data.get("pending_run_id") or ""),
            pending_scheduled_at=str(data.get("pending_scheduled_at") or ""),
            coalesced_count=int(data.get("coalesced_count") or 0),
            last_trigger_source=str(data.get("last_trigger_source") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
