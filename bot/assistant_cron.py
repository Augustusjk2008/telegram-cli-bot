from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import WEB_DEFAULT_USER_ID
from bot.assistant_cron_store import (
    append_job_run_audit,
    list_job_definitions,
    load_job_runtime_state,
    read_job_definition,
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
    ) -> None:
        self.assistant_home = assistant_home
        self.bot_alias = bot_alias
        self.coordinator = coordinator
        self.now_func = now_func or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self.web_user_id = web_user_id
        self._watch_tasks: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._reload_event = asyncio.Event()

    @staticmethod
    def _excerpt(text: str, *, limit: int = 160) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run_loop(), name="assistant-cron-service")

    async def stop(self) -> None:
        loop_task = self._loop_task
        self._loop_task = None
        if loop_task is not None:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        watch_tasks = list(self._watch_tasks)
        self._watch_tasks.clear()
        for task in watch_tasks:
            task.cancel()
        if watch_tasks:
            await asyncio.gather(*watch_tasks, return_exceptions=True)

    async def save_job(self, job: AssistantCronJob) -> AssistantCronJob:
        save_job_definition(self.assistant_home, job)
        state = load_job_runtime_state(self.assistant_home, job.id)
        if not state.next_run_at:
            now = self.now_func()
            next_run_at = self._compute_initial_next_run(job, now)
            save_job_runtime_state(
                self.assistant_home,
                job.id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "next_run_at": next_run_at.isoformat(),
                    }
                ),
            )
        self._reload_event.set()
        return job

    async def enqueue_due_jobs(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        now = self.now_func()
        for job in list_job_definitions(self.assistant_home):
            if not job.enabled:
                continue
            state = load_job_runtime_state(self.assistant_home, job.id)
            next_run_at = self._resolve_next_run_at(job, state, now)
            if next_run_at > now:
                if next_run_at.isoformat() != state.next_run_at:
                    save_job_runtime_state(
                        self.assistant_home,
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
            next_state = load_job_runtime_state(self.assistant_home, job.id)
            save_job_runtime_state(
                self.assistant_home,
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
        job = read_job_definition(self.assistant_home, job_id)
        state = load_job_runtime_state(self.assistant_home, job.id)
        scheduled_at = self.now_func()
        result = await self._enqueue_job(job, state=state, trigger_source="manual", scheduled_at=scheduled_at)
        if result is None:
            updated_state = load_job_runtime_state(self.assistant_home, job.id)
            return {
                "run_id": updated_state.pending_run_id or updated_state.current_run_id,
                "status": "queued",
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
            save_job_runtime_state(
                self.assistant_home,
                job.id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "coalesced_count": state.coalesced_count + 1,
                    }
                ),
            )
            return None

        request = AssistantRunRequest(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            source="manual" if trigger_source == "manual" else "cron",
            bot_alias=self.bot_alias,
            user_id=self.web_user_id,
            text=job.task.prompt,
            interactive=False,
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
                "last_trigger_source": trigger_source,
                "last_status": result["status"],
            }
        )
        save_job_runtime_state(self.assistant_home, job.id, next_state)
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

        task = asyncio.create_task(
            self._watch_run(job.id, request.run_id, trigger_source),
            name=f"assistant-cron-watch-{job.id}",
        )
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)
        return result

    async def _watch_run(self, job_id: str, run_id: str, trigger_source: str) -> None:
        try:
            result = await self.coordinator.wait_for_run(run_id)
            now = self.now_func().isoformat()
            state = load_job_runtime_state(self.assistant_home, job_id)
            started_at = state.last_started_at or state.last_enqueued_at
            save_job_runtime_state(
                self.assistant_home,
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
                    "elapsed_seconds": int(result.get("elapsed_seconds") or 0),
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
            state = load_job_runtime_state(self.assistant_home, job_id)
            save_job_runtime_state(
                self.assistant_home,
                job_id,
                AssistantCronJobState.from_dict(
                    {
                        **state.to_dict(),
                        "pending_run_id": "",
                        "pending_scheduled_at": "",
                        "current_run_id": "",
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
                    "started_at": state.last_started_at or state.last_enqueued_at,
                    "finished_at": now,
                    "status": "error",
                    "elapsed_seconds": 0,
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
