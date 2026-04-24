from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bot.assistant_cron import AssistantCronService
from bot.assistant_cron_store import append_job_run_audit, load_job_runtime_state, read_job_run_audit, save_job_runtime_state
from bot.assistant_cron_types import AssistantCronJob, AssistantCronJobState
from bot.assistant_home import bootstrap_assistant_home


class _FakeAssistantRuntimeCoordinator:
    def __init__(self) -> None:
        self.requests = []
        self._known_run_ids: set[str] = set()

    async def submit_background(self, request):
        self.requests.append(request)
        self._known_run_ids.add(request.run_id)
        return {"run_id": request.run_id, "status": "queued"}

    async def wait_for_run(self, run_id: str):
        return {"run_id": run_id, "elapsed_seconds": 0}

    def has_run(self, run_id: str) -> bool:
        return run_id in self._known_run_ids


class _BlockingAssistantRuntimeCoordinator(_FakeAssistantRuntimeCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def wait_for_run(self, run_id: str):
        await self.release.wait()
        return {"run_id": run_id, "elapsed_seconds": 0}


def _build_assistant_cron_job(job_id: str, prompt: str, *, misfire_policy: str = "skip") -> AssistantCronJob:
    return AssistantCronJob.from_dict(
        {
            "id": job_id,
            "enabled": True,
            "title": "测试任务",
            "schedule": {
                "type": "daily",
                "time": "12:00",
                "timezone": "Asia/Shanghai",
                "misfire_policy": misfire_policy,
            },
            "task": {"prompt": prompt},
            "execution": {"timeout_seconds": 600},
        }
    )


@pytest.mark.asyncio
async def test_startup_recovers_orphaned_pending_run_once_policy(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _FakeAssistantRuntimeCoordinator()
    scheduled_at = datetime(2026, 4, 24, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = scheduled_at + timedelta(minutes=15)
    job = _build_assistant_cron_job("email_recvbox_check", "检查最新邮件并总结重点", misfire_policy="once")
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
        now_func=lambda: now,
    )
    await service.save_job(job)

    orphan_run_id = "run_orphaned"
    save_job_runtime_state(
        home,
        job.id,
        AssistantCronJobState.from_dict(
            {
                "next_run_at": (scheduled_at + timedelta(days=1)).isoformat(),
                "last_scheduled_at": scheduled_at.isoformat(),
                "last_enqueued_at": (scheduled_at + timedelta(seconds=1)).isoformat(),
                "last_status": "queued",
                "pending_run_id": orphan_run_id,
                "pending_scheduled_at": scheduled_at.isoformat(),
                "last_trigger_source": "schedule",
            }
        ),
    )
    append_job_run_audit(
        home,
        job.id,
        {
            "run_id": orphan_run_id,
            "job_id": job.id,
            "trigger_source": "schedule",
            "scheduled_at": scheduled_at.isoformat(),
            "enqueued_at": (scheduled_at + timedelta(seconds=1)).isoformat(),
            "started_at": "",
            "finished_at": "",
            "status": "queued",
            "elapsed_seconds": 0,
            "queue_wait_seconds": 0,
            "timed_out": False,
            "prompt_excerpt": "检查最新邮件并总结重点",
            "output_excerpt": "",
            "error": "",
        },
    )

    await service.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    state = load_job_runtime_state(home, job.id)
    records = read_job_run_audit(home, job.id)
    await service.stop()

    assert len(coordinator.requests) == 1
    request = coordinator.requests[0]
    assert request.scheduled_at == scheduled_at.isoformat()
    assert state.last_status == "success"
    assert state.pending_run_id == ""

    old_record = next(item for item in records if item["run_id"] == orphan_run_id)
    assert old_record["status"] == "error"
    assert "孤儿 cron run" in old_record["error"]

    replacement_record = next(item for item in records if item["run_id"] != orphan_run_id)
    assert replacement_record["trigger_source"] == "startup_misfire"
    assert replacement_record["status"] == "success"


@pytest.mark.asyncio
async def test_new_run_clears_previous_started_at_before_watch_updates(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _BlockingAssistantRuntimeCoordinator()
    previous_started_at = datetime(2026, 4, 23, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    enqueued_at = datetime(2026, 4, 24, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    finished_at = enqueued_at + timedelta(minutes=2, seconds=5)
    current = [enqueued_at]
    job = _build_assistant_cron_job("daily_digest", "汇总今天的重要动态")
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
        now_func=lambda: current[0],
    )
    await service.save_job(job)
    save_job_runtime_state(
        home,
        job.id,
        AssistantCronJobState.from_dict(
            {
                "last_started_at": previous_started_at.isoformat(),
                "last_finished_at": previous_started_at.isoformat(),
                "last_status": "success",
            }
        ),
    )

    result = await service.run_job_now(job.id)
    pending_state = load_job_runtime_state(home, job.id)
    assert result["status"] == "queued"
    assert pending_state.last_started_at == ""

    current[0] = finished_at
    coordinator.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    state = load_job_runtime_state(home, job.id)
    records = read_job_run_audit(home, job.id)
    await service.stop()

    assert state.last_started_at == enqueued_at.isoformat()
    assert records[-1]["started_at"] == enqueued_at.isoformat()
    assert records[-1]["elapsed_seconds"] == 125
