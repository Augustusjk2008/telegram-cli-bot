from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import WEB_DEFAULT_USER_ID
from bot.assistant_cron_store import (
    append_job_run_audit,
    delete_job_definition,
    list_job_definitions,
    load_job_runtime_state,
    save_job_definition,
    upsert_job_run_audit,
    save_job_runtime_state,
)
from bot.assistant_cron_types import AssistantCronJob, AssistantCronJobState
from bot.assistant_home import AssistantHome
from bot.assistant_runtime import AssistantRunRequest


class AssistantCronService:
    def __init__(
        self,
        *,
        assistant_home: AssistantHome,
        bot_alias: str,
        coordinator,
        now_func: Callable[[], datetime] | None = None,
        web_user_id: int = WEB_DEFAULT_USER_ID,
        reload_interval_seconds: float = 30.0,
    ) -> None:
        self.assistant_home = assistant_home
        self.bot_alias = bot_alias
        self.coordinator = coordinator
        self.now_func = now_func or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self.web_user_id = web_user_id
        self._reload_interval_seconds = max(1.0, float(reload_interval_seconds))
        self._cached_jobs: list[AssistantCronJob] = []
        self._cached_states: dict[str, AssistantCronJobState] = {}
        self._jobs_loaded_at = 0.0
        self._states_loaded_at: dict[str, float] = {}
        self._jobs_dirty = True
        self._states_dirty: set[str] = set()
        self._watch_tasks: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._reload_event = asyncio.Event()

    def _loop_time(self) -> float:
        try:
            return asyncio.get_running_loop().time()
        except RuntimeError:
            return 0.0

    def _load_jobs_if_needed(self, *, force: bool = False) -> list[AssistantCronJob]:
        now = self._loop_time()
        if force or self._jobs_dirty or now - self._jobs_loaded_at >= self._reload_interval_seconds:
            self._cached_jobs = list_job_definitions(self.assistant_home)
            self._jobs_loaded_at = now
            self._jobs_dirty = False
        return self._cached_jobs

    def _load_state_if_needed(self, job_id: str, *, force: bool = False) -> AssistantCronJobState:
        now = self._loop_time()
        loaded_at = self._states_loaded_at.get(job_id, 0.0)
        if (
            force
            or job_id in self._states_dirty
            or job_id not in self._cached_states
            or now - loaded_at >= self._reload_interval_seconds
        ):
            self._cached_states[job_id] = load_job_runtime_state(self.assistant_home, job_id)
            self._states_loaded_at[job_id] = now
            self._states_dirty.discard(job_id)
        return self._cached_states[job_id]

    def _save_state(self, job_id: str, state: AssistantCronJobState) -> None:
        save_job_runtime_state(self.assistant_home, job_id, state)
        self._cached_states[job_id] = state
        self._states_loaded_at[job_id] = self._loop_time()
        self._states_dirty.discard(job_id)

    def list_jobs(self) -> list[AssistantCronJob]:
        return list(self._load_jobs_if_needed())

    def get_job_state(self, job_id: str) -> AssistantCronJobState:
        return self._load_state_if_needed(job_id)

    def _get_job_or_raise(self, job_id: str) -> AssistantCronJob:
        for job in self._load_jobs_if_needed():
            if job.id == job_id:
                return job
        raise FileNotFoundError(job_id)

    async def delete_job(self, job_id: str) -> bool:
        removed = delete_job_definition(self.assistant_home, job_id)
        if removed:
            self._jobs_dirty = True
            self._cached_jobs = [job for job in self._cached_jobs if job.id != job_id]
            self._cached_states.pop(job_id, None)
            self._states_loaded_at.pop(job_id, None)
            self._states_dirty.discard(job_id)
        return removed

    @staticmethod
    def _excerpt(text: str, *, limit: int = 160) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."

    def _build_synthetic_user_id(self, job_id: str) -> int:
        digest = hashlib.sha256(f"{self.assistant_home.assistant_id}:{job_id}".encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF
        return -max(1, value)

    @staticmethod
    def _elapsed_seconds(started_at: str, finished_at: str) -> int:
        if not started_at or not finished_at:
            return 0
        try:
            started = datetime.fromisoformat(started_at)
            finished = datetime.fromisoformat(finished_at)
        except ValueError:
            return 0
        return max(0, int((finished - started).total_seconds()))

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _coordinator_has_run(self, run_id: str) -> bool:
        checker = getattr(self.coordinator, "has_run", None)
        if not callable(checker):
            return False
        return bool(checker(run_id))

    def _schedule_watch_task(self, job_id: str, run_id: str, trigger_source: str) -> None:
        task = asyncio.create_task(
            self._watch_run(job_id, run_id, trigger_source),
            name=f"assistant-cron-watch-{job_id}",
        )
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)

    async def _recover_startup_state(self) -> None:
        now = self.now_func()
        for job in self._load_jobs_if_needed(force=True):
            state = self._load_state_if_needed(job.id, force=True)
            await self._recover_orphaned_run(job, state=state, now=now)

    async def _recover_orphaned_run(
        self,
        job: AssistantCronJob,
        *,
        state: AssistantCronJobState,
        now: datetime,
    ) -> AssistantCronJobState:
        run_id = state.pending_run_id or state.current_run_id
        if not run_id:
            return state

        if self._coordinator_has_run(run_id):
            self._schedule_watch_task(job.id, run_id, state.last_trigger_source or "schedule")
            return state

        finished_at = now.isoformat()
        started_at = state.last_started_at if state.current_run_id else ""
        elapsed_seconds = self._elapsed_seconds(started_at, finished_at)
        stale_error = f"检测到孤儿 cron run，已按启动恢复处理: {run_id}"
        scheduled_at_raw = state.pending_scheduled_at or state.last_scheduled_at

        self._save_state(
            job.id,
            AssistantCronJobState.from_dict(
                {
                    **state.to_dict(),
                    "pending_run_id": "",
                    "pending_scheduled_at": "",
                    "current_run_id": "",
                    "last_started_at": started_at,
                    "last_finished_at": finished_at,
                    "last_status": "error",
                    "last_error": stale_error,
                }
            ),
        )
        upsert_job_run_audit(
            self.assistant_home,
            job.id,
            {
                "run_id": run_id,
                "job_id": job.id,
                "trigger_source": state.last_trigger_source or "schedule",
                "scheduled_at": scheduled_at_raw,
                "enqueued_at": state.last_enqueued_at,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": "error",
                "elapsed_seconds": elapsed_seconds,
                "queue_wait_seconds": 0,
                "timed_out": False,
                "prompt_excerpt": self._excerpt(job.task.prompt),
                "output_excerpt": "",
                "error": stale_error,
            },
        )

        next_state = self._load_state_if_needed(job.id, force=True)
        scheduled_at = self._parse_timestamp(scheduled_at_raw)
        should_rerun = (
            job.enabled
            and job.schedule.misfire_policy == "once"
            and state.last_trigger_source in {"schedule", "startup_misfire"}
            and scheduled_at is not None
            and scheduled_at <= now
        )
        if not should_rerun:
            return next_state

        result = await self._enqueue_job(
            job,
            state=next_state,
            trigger_source="startup_misfire",
            scheduled_at=scheduled_at,
        )
        if result is None:
            return self._load_state_if_needed(job.id, force=True)
        return self._load_state_if_needed(job.id, force=True)

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        await self._recover_startup_state()
        self._loop_task = asyncio.create_task(self._run_loop(), name="assistant-cron-service")

    async def stop(self, *, cancel_watch_tasks: bool = True) -> None:
        loop_task = self._loop_task
        self._loop_task = None
        if loop_task is not None:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        watch_tasks = list(self._watch_tasks)
        self._watch_tasks.clear()
        if watch_tasks:
            if cancel_watch_tasks:
                for task in watch_tasks:
                    task.cancel()
            await asyncio.gather(*watch_tasks, return_exceptions=True)

    async def save_job(self, job: AssistantCronJob) -> AssistantCronJob:
        save_job_definition(self.assistant_home, job)
        self._jobs_dirty = True
        state = self._load_state_if_needed(job.id, force=True)
        if not state.next_run_at:
            now = self.now_func()
            next_run_at = self._compute_initial_next_run(job, now)
            self._save_state(
                job.id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "next_run_at": next_run_at.isoformat(),
                    }
                ),
            )
        self._states_dirty.add(job.id)
        self._reload_event.set()
        return job

    async def enqueue_due_jobs(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        now = self.now_func()
        for job in self._load_jobs_if_needed():
            if not job.enabled:
                continue
            state = self._load_state_if_needed(job.id)
            next_run_at = self._resolve_next_run_at(job, state, now)
            if next_run_at > now:
                if next_run_at.isoformat() != state.next_run_at:
                    self._save_state(
                        job.id,
                        AssistantCronJobState.from_dict(
                            {
                                **state.to_dict(),
                                "next_run_at": next_run_at.isoformat(),
                            }
                        ),
                    )
                continue
            result = await self._enqueue_job(job, state=state, trigger_source="schedule", scheduled_at=next_run_at)
            advanced_next = self._advance_next_run(job, next_run_at, now)
            next_state = self._load_state_if_needed(job.id, force=True)
            self._save_state(
                job.id,
                AssistantCronJobState.from_dict(
                    {
                        **next_state.to_dict(),
                        "next_run_at": advanced_next.isoformat(),
                    }
                ),
            )
            if result is not None:
                results.append(result)
        return results

    async def run_job_now(self, job_id: str) -> dict[str, str]:
        job = self._get_job_or_raise(job_id)
        state = self._load_state_if_needed(job.id)
        scheduled_at = self.now_func()
        result = await self._enqueue_job(job, state=state, trigger_source="manual", scheduled_at=scheduled_at)
        if result is None:
            updated_state = self._load_state_if_needed(job.id, force=True)
            return {
                "run_id": updated_state.pending_run_id or updated_state.current_run_id,
                "status": "queued",
                "task_mode": job.task.mode,
                "deliver_mode": job.task.deliver_mode,
            }
        return result

    async def _run_loop(self) -> None:
        while True:
            await self.enqueue_due_jobs()
            try:
                await asyncio.wait_for(self._reload_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._reload_event.clear()

    async def _enqueue_job(
        self,
        job: AssistantCronJob,
        *,
        state: AssistantCronJobState,
        trigger_source: str,
        scheduled_at: datetime,
    ) -> dict[str, str] | None:
        if state.pending_run_id or state.current_run_id:
            self._save_state(
                job.id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "coalesced_count": state.coalesced_count + 1,
                    }
                ),
            )
            return None

        runtime_user_id = self.web_user_id
        context_user_id = None
        if job.task.mode == "dream":
            runtime_user_id = self._build_synthetic_user_id(job.id)
            context_user_id = self.web_user_id

        request = AssistantRunRequest(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            source="manual" if trigger_source == "manual" else "cron",
            bot_alias=self.bot_alias,
            user_id=runtime_user_id,
            text=job.task.prompt,
            interactive=False,
            visible_text=job.task.prompt,
            context_user_id=context_user_id,
            task_mode=job.task.mode,
            task_payload=job.task.to_dict(),
            job_id=job.id,
            scheduled_at=scheduled_at.isoformat(),
            enqueued_at=self.now_func().isoformat(),
        )
        result = await self.coordinator.submit_background(request)
        next_state = AssistantCronJobState.from_dict(
            {
                **state.to_dict(),
                "pending_run_id": request.run_id,
                "pending_scheduled_at": scheduled_at.isoformat(),
                "last_scheduled_at": scheduled_at.isoformat(),
                "last_enqueued_at": request.enqueued_at or "",
                "last_started_at": "",
                "last_trigger_source": trigger_source,
                "last_status": result["status"],
                "last_error": "",
            }
        )
        self._save_state(job.id, next_state)
        append_job_run_audit(
            self.assistant_home,
            job.id,
            {
                "run_id": request.run_id,
                "job_id": job.id,
                "trigger_source": trigger_source,
                "scheduled_at": scheduled_at.isoformat(),
                "enqueued_at": request.enqueued_at or "",
                "started_at": "",
                "finished_at": "",
                "status": result["status"],
                "elapsed_seconds": 0,
                "queue_wait_seconds": 0,
                "timed_out": False,
                "prompt_excerpt": self._excerpt(job.task.prompt),
                "output_excerpt": "",
                "error": "",
            },
        )

        self._schedule_watch_task(job.id, request.run_id, trigger_source)
        return {
            **result,
            "task_mode": job.task.mode,
            "deliver_mode": job.task.deliver_mode,
        }

    async def _watch_run(self, job_id: str, run_id: str, trigger_source: str) -> None:
        try:
            result = await self.coordinator.wait_for_run(run_id)
            now = self.now_func().isoformat()
            state = self._load_state_if_needed(job_id, force=True)
            started_at = state.last_started_at or state.last_enqueued_at
            elapsed_seconds = int(result.get("elapsed_seconds") or self._elapsed_seconds(started_at, now))
            self._save_state(
                job_id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "pending_run_id": "",
                        "pending_scheduled_at": "",
                        "current_run_id": "",
                        "last_started_at": started_at,
                        "last_finished_at": now,
                        "last_success_at": now,
                        "last_status": "success",
                        "last_error": "",
                        "last_trigger_source": trigger_source,
                    }
                ),
            )
            upsert_job_run_audit(
                self.assistant_home,
                job_id,
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "trigger_source": trigger_source,
                    "scheduled_at": state.pending_scheduled_at or state.last_scheduled_at,
                    "enqueued_at": state.last_enqueued_at,
                    "started_at": started_at,
                    "finished_at": now,
                    "status": "success",
                    "elapsed_seconds": elapsed_seconds,
                    "queue_wait_seconds": 0,
                    "timed_out": bool(result.get("timed_out", False)),
                    "prompt_excerpt": self._excerpt(""),
                    "output_excerpt": self._excerpt(str(result.get("output") or "")),
                    "error": "",
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            now = self.now_func().isoformat()
            state = self._load_state_if_needed(job_id, force=True)
            started_at = state.last_started_at or state.last_enqueued_at
            elapsed_seconds = self._elapsed_seconds(started_at, now)
            self._save_state(
                job_id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "pending_run_id": "",
                        "pending_scheduled_at": "",
                        "current_run_id": "",
                        "last_started_at": started_at,
                        "last_finished_at": now,
                        "last_status": "error",
                        "last_error": str(exc),
                        "last_trigger_source": trigger_source,
                    }
                ),
            )
            upsert_job_run_audit(
                self.assistant_home,
                job_id,
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "trigger_source": trigger_source,
                    "scheduled_at": state.pending_scheduled_at or state.last_scheduled_at,
                    "enqueued_at": state.last_enqueued_at,
                    "started_at": started_at,
                    "finished_at": now,
                    "status": "error",
                    "elapsed_seconds": elapsed_seconds,
                    "queue_wait_seconds": 0,
                    "timed_out": False,
                    "prompt_excerpt": self._excerpt(""),
                    "output_excerpt": "",
                    "error": str(exc),
                },
            )

    def _resolve_next_run_at(self, job: AssistantCronJob, state: AssistantCronJobState, now: datetime) -> datetime:
        if state.next_run_at:
            return datetime.fromisoformat(state.next_run_at)
        return self._compute_initial_next_run(job, now)

    def _compute_initial_next_run(self, job: AssistantCronJob, now: datetime) -> datetime:
        if job.schedule.type == "interval":
            return now + timedelta(seconds=job.schedule.every_seconds or 0)
        tz = ZoneInfo(job.schedule.timezone or "Asia/Shanghai")
        current = now.astimezone(tz)
        hour, minute = [int(item) for item in (job.schedule.time or "00:00").split(":", maxsplit=1)]
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    def _advance_next_run(self, job: AssistantCronJob, last_run_at: datetime, now: datetime) -> datetime:
        if job.schedule.type == "interval":
            next_run = last_run_at + timedelta(seconds=job.schedule.every_seconds or 0)
            while next_run < now:
                next_run += timedelta(seconds=job.schedule.every_seconds or 0)
            return next_run
        next_run = last_run_at + timedelta(days=1)
        while next_run < now:
            next_run += timedelta(days=1)
        return next_run
