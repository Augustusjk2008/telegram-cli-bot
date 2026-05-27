from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bot.assistant.cron.service import AssistantCronService
from bot.assistant.cron.store import (
    append_job_run_audit,
    load_job_runtime_state,
    read_job_run_audit,
    save_job_runtime_state,
)
from bot.assistant.cron.types import AssistantCronJob, AssistantCronJobState
from bot.assistant.home import bootstrap_assistant_home


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


class _NeverFinishesAssistantRuntimeCoordinator(_FakeAssistantRuntimeCoordinator):
    async def wait_for_run(self, run_id: str):
        await asyncio.sleep(3600)
        return {"run_id": run_id}


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


def test_cron_job_rejects_unsafe_id_values():
    invalid_ids = [
        "../escape",
        "..\\escape",
        "nested/job",
        "nested\\job",
        "",
        " ",
        ".",
        "..",
        "job with spaces",
    ]

    for job_id in invalid_ids:
        with pytest.raises(ValueError, match="job.id"):
            AssistantCronJob.from_dict(
                {
                    "id": job_id,
                    "enabled": True,
                    "title": "bad",
                    "schedule": {"type": "daily", "time": "12:00"},
                    "task": {"prompt": "x"},
                    "execution": {"timeout_seconds": 60},
                }
            )


def test_cron_store_rejects_unsafe_runtime_ids(tmp_path: Path):
    from bot.assistant.cron.store import (
        append_job_run_audit,
        delete_job_definition,
        delete_job_run_audit,
        delete_job_runtime_state,
        load_job_runtime_state,
        read_job_definition,
        read_job_run_audit,
        save_job_runtime_state,
    )

    home = bootstrap_assistant_home(tmp_path)
    unsafe_id = "../escape_store"

    operations = [
        lambda: read_job_definition(home, unsafe_id),
        lambda: delete_job_definition(home, unsafe_id),
        lambda: save_job_runtime_state(home, unsafe_id, AssistantCronJobState()),
        lambda: load_job_runtime_state(home, unsafe_id),
        lambda: delete_job_runtime_state(home, unsafe_id),
        lambda: append_job_run_audit(home, unsafe_id, {"run_id": "run_1"}),
        lambda: read_job_run_audit(home, unsafe_id),
        lambda: delete_job_run_audit(home, unsafe_id),
    ]

    for operation in operations:
        with pytest.raises(ValueError, match="unsafe cron id"):
            operation()

    assert not (home.root / "automation" / "escape_store.yaml").exists()
    assert not (home.root / "state" / "escape_store.json").exists()
    assert not (home.root / "audit" / "escape_store.jsonl").exists()


def test_cron_schedule_rejects_invalid_interval_seconds():
    for value in [None, "", 0, -1, "0", "abc"]:
        payload = {
            "id": f"interval_bad_{str(value).replace('-', 'neg').replace(' ', '_') or 'none'}",
            "enabled": True,
            "title": "bad interval",
            "schedule": {"type": "interval", "every_seconds": value},
            "task": {"prompt": "x"},
            "execution": {"timeout_seconds": 60},
        }
        with pytest.raises(ValueError, match="every_seconds"):
            AssistantCronJob.from_dict(payload)


def test_cron_schedule_rejects_invalid_daily_time():
    for value in ["", "25:00", "23:60", "9:00", "09", "09:00:00", "aa:bb"]:
        payload = {
            "id": f"daily_bad_{len(value)}_{value.replace(':', '_') or 'empty'}",
            "enabled": True,
            "title": "bad daily",
            "schedule": {"type": "daily", "time": value},
            "task": {"prompt": "x"},
            "execution": {"timeout_seconds": 60},
        }
        with pytest.raises(ValueError, match="schedule.time"):
            AssistantCronJob.from_dict(payload)


def test_cron_schedule_accepts_valid_daily_and_interval():
    daily = AssistantCronJob.from_dict(
        {
            "id": "daily_valid",
            "enabled": True,
            "title": "daily",
            "schedule": {"type": "daily", "time": "09:30"},
            "task": {"prompt": "x"},
            "execution": {"timeout_seconds": 60},
        }
    )
    interval = AssistantCronJob.from_dict(
        {
            "id": "interval_valid",
            "enabled": True,
            "title": "interval",
            "schedule": {"type": "interval", "every_seconds": 60},
            "task": {"prompt": "x"},
            "execution": {"timeout_seconds": 60},
        }
    )

    assert daily.schedule.time == "09:30"
    assert interval.schedule.every_seconds == 60


def test_cron_timezone_falls_back_to_china_offset_without_tzdb(monkeypatch: pytest.MonkeyPatch):
    from bot.assistant.cron import service

    class MissingZoneInfo:
        def __init__(self, _key: str) -> None:
            raise service.ZoneInfoNotFoundError("missing tzdb")

    monkeypatch.setattr(service, "ZoneInfo", MissingZoneInfo)

    tz = service._load_timezone("Asia/Shanghai")

    assert tz.utcoffset(None).total_seconds() == 8 * 3600
    assert tz.tzname(None) == "Asia/Shanghai"
    assert tz is not timezone.utc


@pytest.mark.asyncio
async def test_cron_service_caches_jobs_between_reload_windows(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        reload_interval_seconds=30,
    )
    job = _build_assistant_cron_job("cached_job", "hello")

    await service.save_job(job)
    first = service._load_jobs_if_needed(force=True)
    second = service._load_jobs_if_needed()

    assert first is second
    assert [item.id for item in second] == ["cached_job"]


@pytest.mark.asyncio
async def test_cron_service_caches_state_between_reload_windows(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        reload_interval_seconds=30,
    )
    job = _build_assistant_cron_job("state_job", "hello")

    await service.save_job(job)
    first = service._load_state_if_needed(job.id)
    save_job_runtime_state(home, job.id, AssistantCronJobState(next_run_at="external-change"))
    second = service._load_state_if_needed(job.id)
    forced = service._load_state_if_needed(job.id, force=True)

    assert second.next_run_at == first.next_run_at
    assert forced.next_run_at == "external-change"


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


@pytest.mark.asyncio
async def test_delete_job_removes_definition_state_and_audit(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
    )
    job = _build_assistant_cron_job("nightly", "hello")

    await service.save_job(job)
    await service.run_job_now(job.id)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    deleted = await service.delete_job(job.id)

    assert deleted is True
    assert not (home.root / "automation" / "jobs" / f"{job.id}.yaml").exists()
    assert not (home.root / "state" / "cron" / f"{job.id}.json").exists()
    assert not (home.root / "audit" / "cron" / f"{job.id}.jsonl").exists()
    await service.stop()


@pytest.mark.asyncio
async def test_deleted_running_job_does_not_recreate_state(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _BlockingAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
    )
    job = _build_assistant_cron_job("slow_job", "hello")

    await service.save_job(job)
    await service.run_job_now(job.id)
    await asyncio.sleep(0)
    deleted = await service.delete_job(job.id)
    coordinator.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert deleted is True
    assert not (home.root / "state" / "cron" / f"{job.id}.json").exists()
    assert not (home.root / "audit" / "cron" / f"{job.id}.jsonl").exists()
    await service.stop()


@pytest.mark.asyncio
async def test_cron_execution_timeout_marks_run_timed_out(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    coordinator = _NeverFinishesAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
    )
    job = AssistantCronJob.from_dict(
        {
            "id": "timeout_job",
            "enabled": True,
            "title": "测试任务",
            "schedule": {
                "type": "daily",
                "time": "12:00",
                "timezone": "Asia/Shanghai",
                "misfire_policy": "skip",
            },
            "task": {"prompt": "hello"},
            "execution": {"timeout_seconds": 1},
        }
    )

    await service.save_job(job)
    result = await service.run_job_now(job.id)
    assert result["status"] == "queued"

    await asyncio.sleep(1.2)
    await asyncio.sleep(0)

    state = load_job_runtime_state(home, job.id)
    records = read_job_run_audit(home, job.id)

    assert state.last_status == "error"
    assert "超时" in state.last_error
    assert records[-1]["timed_out"] is True
    assert "超时" in records[-1]["error"]
    await service.stop()


def test_upsert_job_run_audit_appends_and_reader_returns_latest(tmp_path: Path):
    from bot.assistant.cron.store import upsert_job_run_audit

    home = bootstrap_assistant_home(tmp_path)

    upsert_job_run_audit(home, "nightly", {"run_id": "r1", "status": "running"})
    upsert_job_run_audit(home, "nightly", {"run_id": "r1", "status": "completed"})

    raw_lines = (home.root / "audit" / "cron" / "nightly.jsonl").read_text(encoding="utf-8").splitlines()
    records = read_job_run_audit(home, "nightly")

    assert len(raw_lines) == 2
    assert records == [{"run_id": "r1", "status": "completed"}]


def test_read_job_run_audit_limit_reads_tail_only_and_keeps_latest(tmp_path: Path):
    from bot.assistant.cron.store import upsert_job_run_audit

    home = bootstrap_assistant_home(tmp_path)
    for index in range(10):
        upsert_job_run_audit(home, "nightly", {"run_id": f"r{index}", "status": "queued"})
    upsert_job_run_audit(home, "nightly", {"run_id": "r8", "status": "completed"})
    upsert_job_run_audit(home, "nightly", {"run_id": "r9", "status": "completed"})

    records = read_job_run_audit(home, "nightly", limit=2)

    assert records == [
        {"run_id": "r8", "status": "completed"},
        {"run_id": "r9", "status": "completed"},
    ]
