"""Host-side scheduler: opens a new conversation on a Bot and sends a fixed prompt.

Runs reuse the shared chat path used by the Weixin gateway
(``create_conversation`` followed by ``stream_chat``), so the transcript, SSE
events, ChatStore persistence, cluster mode and completion broadcasts behave
exactly like any other turn of the shared ``(bot, shared user, main)`` session.
Starting a run switches the Bot's active conversation; old history is kept.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from bot import config
from bot.chat_identity import chat_session_user_id
from bot.scheduler.store import RUN_ACTIVE_STATUSES, ScheduleStore, ScheduleStoreError
from bot.scheduler.triggers import (
    MIN_INTERVAL_MINUTES,
    TriggerError,
    detect_default_timezone,
    next_fire,
    normalize_trigger,
    parse_iso_datetime,
    resolve_timezone,
    to_utc_iso,
    utc_now,
)
from bot.web.api_common import WebApiError

logger = logging.getLogger(__name__)

SCHEDULE_SOURCE_CHANNEL = "schedule"
BUSY_POLICIES = ("wait", "skip")
MAX_NAME_CHARS = 80
MAX_PROMPT_CHARS = 20_000
MAX_WAIT_MINUTES = 120
MAX_MISFIRE_GRACE_MINUTES = 24 * 60
DEFAULT_MAX_WAIT_MINUTES = 15
DEFAULT_MISFIRE_GRACE_MINUTES = 10
DEFAULT_MAX_CONCURRENT_RUNS = 2
BUSY_RETRY_SECONDS = 30.0
MAX_LOOP_SLEEP_SECONDS = 30.0
PAUSED_LOOP_SLEEP_SECONDS = 5.0
PREVIEW_CHARS = 300

_BUSY_ERROR_CODES = frozenset({"session_busy", "conversation_switch_blocked", "cluster_team_busy"})
_PREEMPTED_ERROR_CODES = frozenset({"session_busy", "conversation_changed", "conversation_switch_blocked"})
_UNSAFE_SENSITIVE_FIELDS = ("prompt", "bot_alias", "allow_unsafe_cli")

CapabilityResolver = Callable[[str], "frozenset[str] | set[str] | None"]

_ACTIVE_SERVICE: "SchedulerService | None" = None


def get_active_scheduler_service() -> "SchedulerService | None":
    return _ACTIVE_SERVICE


def _store_error(exc: ScheduleStoreError) -> WebApiError:
    return WebApiError(exc.status, exc.code, exc.message)


def _invalid(message: str) -> WebApiError:
    return WebApiError(400, "invalid_schedule", message)


def _bounded_int(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        raise _invalid(f"{label}需为整数") from None
    if resolved < minimum or resolved > maximum:
        raise _invalid(f"{label}需在 {minimum} 到 {maximum} 之间")
    return resolved


def _serialize_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run["id"],
        "schedule_id": run["schedule_id"],
        "planned_at": run["planned_at"],
        "trigger": run["trigger"],
        "status": run["status"],
        "reason_code": run.get("reason_code") or "",
        "reason_message": run.get("reason_message") or "",
        "bot_alias": run.get("bot_alias") or "",
        "conversation_id": run.get("conversation_id") or "",
        "turn_id": run.get("turn_id") or "",
        "assistant_message_id": run.get("assistant_message_id") or "",
        "preview": run.get("preview") or "",
        "unsafe_downgraded": bool(run.get("unsafe_downgraded")),
        "created_at": run.get("created_at") or "",
        "started_at": run.get("started_at") or "",
        "finished_at": run.get("finished_at") or "",
    }


class SchedulerService:
    def __init__(
        self,
        manager: Any,
        store: ScheduleStore,
        *,
        capability_resolver: CapabilityResolver | None = None,
        max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS,
        busy_retry_seconds: float = BUSY_RETRY_SECONDS,
        clock: Callable[[], datetime] = utc_now,
        default_timezone: str | None = None,
    ) -> None:
        self.manager = manager
        self.store = store
        self._capability_resolver = capability_resolver
        self._busy_retry_seconds = max(0.0, float(busy_retry_seconds))
        self._clock = clock
        self.default_timezone = default_timezone or detect_default_timezone()
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent_runs)))
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._run_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_by_schedule: dict[str, str] = {}
        self._cancel_requested: set[str] = set()
        self._interrupt_reason = ("host_stopping", "宿主停止，运行已中断")
        self._paused_reason = ""
        self._stopping = False

    # Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        global _ACTIVE_SERVICE
        await asyncio.to_thread(self._recover)
        self._stopping = False
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler-loop")
        _ACTIVE_SERVICE = self

    async def stop(self) -> None:
        global _ACTIVE_SERVICE
        self._stopping = True
        if _ACTIVE_SERVICE is self:
            _ACTIVE_SERVICE = None
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        await self._cancel_all_runs("host_stopping", "宿主停止，运行已中断")

    async def pause(self, code: str, message: str) -> None:
        """Stop firing and interrupt in-flight runs (storage migration)."""
        self._paused_reason = code
        await self._cancel_all_runs(code, message)

    def wake(self) -> None:
        self._wake.set()

    def _recover(self) -> None:
        interrupted = self.store.mark_unfinished_runs("interrupted", "host_restarted", "宿主重启，运行已中断")
        if interrupted:
            logger.info("定时任务：%s 个未结束的运行已标记为中断", interrupted)
        now = self._clock()
        for schedule in self.store.list_schedules():
            if not schedule["enabled"] or schedule.get("next_run_at"):
                continue
            next_run_at = self._compute_next(schedule["trigger"], schedule["timezone"], now)
            if next_run_at is not None:
                self.store.update_schedule(schedule["id"], {"next_run_at": next_run_at}, bump_revision=False)

    async def _cancel_all_runs(self, code: str, message: str) -> None:
        tasks = list(self._run_tasks.values())
        if not tasks:
            return
        self._interrupt_reason = (code, message)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _is_paused(self) -> bool:
        return bool(
            self._paused_reason
            or getattr(config, "UPDATE_DRAINING", False)
            or getattr(config, "UPDATE_REQUESTED", False)
            or getattr(config, "RESTART_REQUESTED", False)
        )

    # Loop ----------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("定时任务调度失败")
            try:
                delay = await asyncio.to_thread(self._sleep_seconds)
            except Exception:
                logger.exception("定时任务读取下次时间失败")
                delay = MAX_LOOP_SLEEP_SECONDS
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def _sleep_seconds(self) -> float:
        if self._is_paused():
            return PAUSED_LOOP_SLEEP_SECONDS
        earliest = self.store.earliest_next_run_at()
        if not earliest:
            return MAX_LOOP_SLEEP_SECONDS
        try:
            remaining = (parse_iso_datetime(earliest) - self._clock()).total_seconds()
        except TriggerError:
            return MAX_LOOP_SLEEP_SECONDS
        return max(0.2, min(MAX_LOOP_SLEEP_SECONDS, remaining))

    async def _tick(self) -> None:
        if self._is_paused():
            return
        now = self._clock()
        due = await asyncio.to_thread(self.store.due_schedules, to_utc_iso(now))
        for schedule in due:
            active = schedule["id"] in self._active_by_schedule
            run = await asyncio.to_thread(self._fire_due, schedule, now, active)
            if run is not None:
                self._spawn(schedule["id"], run)

    def _fire_due(self, schedule: dict[str, Any], now: datetime, previous_active: bool) -> dict[str, Any] | None:
        planned_iso = schedule["next_run_at"]
        once = schedule["trigger"].get("type") == "once"
        try:
            planned = parse_iso_datetime(planned_iso)
            next_run_at = None if once else self._compute_next(schedule["trigger"], schedule["timezone"], now)
        except (TriggerError, WebApiError):
            self.store.update_schedule(
                schedule["id"],
                {"enabled": False, "next_run_at": None, "disabled_reason": "invalid_trigger"},
                expected_next_run_at=planned_iso,
            )
            return None
        changes: dict[str, Any] = {"next_run_at": next_run_at}
        if once:
            changes.update(enabled=False, disabled_reason="once_finished")
        # Advance first so a fire is never claimed twice, even across restarts.
        advanced = self.store.update_schedule(
            schedule["id"], changes, bump_revision=once, expected_next_run_at=planned_iso,
        )
        if advanced is None:
            return None
        claim = {"planned_at": to_utc_iso(planned), "trigger": "schedule", "bot_alias": schedule["bot_alias"]}
        lateness_minutes = (now - planned).total_seconds() / 60
        if lateness_minutes > schedule["misfire_grace_minutes"]:
            self.store.claim_run(
                schedule["id"], **claim, status="missed", reason_code="misfire",
                reason_message=f"宿主未在计划时间运行（延迟约 {int(lateness_minutes)} 分钟），已跳过",
            )
            return None
        if previous_active:
            self.store.claim_run(
                schedule["id"], **claim, status="skipped", reason_code="previous_run_active",
                reason_message="上一次运行尚未结束，已跳过",
            )
            return None
        return self.store.claim_run(schedule["id"], **claim)

    def _spawn(self, schedule_id: str, run: dict[str, Any]) -> None:
        run_id = run["id"]
        self._active_by_schedule[schedule_id] = run_id
        self._run_tasks[run_id] = asyncio.create_task(
            self._execute(schedule_id, run_id), name=f"scheduler-run-{run_id}",
        )

    # Execution -----------------------------------------------------------

    async def _execute(self, schedule_id: str, run_id: str) -> None:
        try:
            async with self._semaphore:
                await self._execute_run(schedule_id, run_id)
        except asyncio.CancelledError:
            if run_id in self._cancel_requested:
                self._finish(run_id, "cancelled", "cancelled_by_admin", "已由管理员取消")
            else:
                self._finish(run_id, "interrupted", *self._interrupt_reason)
            raise
        except WebApiError as exc:
            self._finish(run_id, "failed", exc.code, exc.message)
        except Exception:
            logger.exception("定时任务运行失败 run_id=%s", run_id)
            self._finish(run_id, "failed", "internal_error", "调度执行异常，请查看宿主日志")
        finally:
            self._run_tasks.pop(run_id, None)
            if self._active_by_schedule.get(schedule_id) == run_id:
                self._active_by_schedule.pop(schedule_id, None)
            self._cancel_requested.discard(run_id)

    def _finish(self, run_id: str, status: str, reason_code: str = "", reason_message: str = "", **extra: Any) -> None:
        current = self.store.get_run(run_id)
        if current is None or current["status"] not in RUN_ACTIVE_STATUSES:
            return
        self.store.update_run(
            run_id,
            status=status,
            reason_code=reason_code,
            reason_message=reason_message,
            finished_at=to_utc_iso(self._clock()),
            **extra,
        )

    def _target_aliases(self) -> set[str]:
        profiles = [self.manager.main_profile, *self.manager.managed_profiles.values()]
        return {profile.alias for profile in profiles if profile.enabled and not profile.archived}

    def _effective_unsafe(self, schedule: dict[str, Any]) -> tuple[bool, bool]:
        """Return ``(allow_unsafe_cli, downgraded)`` after re-checking the authorizer."""
        if not schedule.get("allow_unsafe_cli"):
            return False, False
        from bot.web.auth_store import CAP_RUN_UNSAFE_CLI

        account_id = str(schedule.get("unsafe_authorized_by") or "").strip()
        capabilities = None
        if account_id and self._capability_resolver is not None:
            try:
                capabilities = self._capability_resolver(account_id)
            except Exception:
                logger.warning("定时任务：无法读取授权账号能力 (%s)", account_id)
        if capabilities and CAP_RUN_UNSAFE_CLI in capabilities:
            return True, False
        return False, True

    async def _execute_run(self, schedule_id: str, run_id: str) -> None:
        from bot.web import api_service

        schedule = await asyncio.to_thread(self.store.get_schedule, schedule_id)
        if schedule is None:
            self._finish(run_id, "skipped", "schedule_deleted", "定时任务已删除")
            return
        alias = schedule["bot_alias"]
        if self._is_paused():
            self._finish(run_id, "skipped", "host_paused", "宿主正在更新、重启或迁移，已跳过本次运行")
            return
        if alias not in self._target_aliases():
            self._finish(run_id, "skipped", "target_unavailable", f"智能体 {alias} 不可用（已停用、归档或删除）")
            return
        allow_unsafe, downgraded = self._effective_unsafe(schedule)
        if downgraded:
            await asyncio.to_thread(self.store.update_run, run_id, unsafe_downgraded=True)

        user_id = chat_session_user_id(None)
        loop = asyncio.get_running_loop()
        wait_seconds = schedule["max_wait_minutes"] * 60 if schedule["busy_policy"] == "wait" else 0
        deadline = loop.time() + wait_seconds
        marked_waiting = False
        conversation_id = ""
        while True:
            if run_id in self._cancel_requested:
                self._finish(run_id, "cancelled", "cancelled_by_admin", "已由管理员取消")
                return
            if self._is_paused():
                self._finish(run_id, "skipped", "host_paused", "宿主正在更新、重启或迁移，已跳过本次运行")
                return
            snapshot = await api_service.get_conversation_control_snapshot(
                self.manager, alias, user_id, agent_id="main",
            )
            busy = snapshot.get("phase") != "idle"
            if not busy:
                try:
                    result = await api_service.create_conversation(
                        self.manager,
                        alias,
                        user_id,
                        title=self._conversation_title(schedule),
                        agent_id="main",
                        follow_current_conversation=True,
                    )
                    conversation_id = str(result["conversation"]["id"])
                    break
                except WebApiError as exc:
                    if exc.code not in _BUSY_ERROR_CODES:
                        self._finish(run_id, "failed", exc.code, exc.message)
                        return
                    busy = True
            remaining = deadline - loop.time()
            if remaining <= 0:
                message = "智能体忙碌，已跳过本次运行"
                if wait_seconds:
                    message = f"智能体忙碌，等待 {schedule['max_wait_minutes']} 分钟后仍未空闲，已跳过"
                self._finish(run_id, "skipped", "target_busy", message)
                return
            if not marked_waiting:
                await asyncio.to_thread(
                    self.store.update_run, run_id,
                    status="waiting", reason_code="target_busy", reason_message="智能体忙碌，等待空闲",
                )
                marked_waiting = True
            await asyncio.sleep(min(self._busy_retry_seconds, remaining))

        await asyncio.to_thread(
            self.store.update_run,
            run_id,
            status="running",
            reason_code="",
            reason_message="",
            conversation_id=conversation_id,
            started_at=to_utc_iso(self._clock()),
        )
        if run_id in self._cancel_requested:
            self._finish(run_id, "cancelled", "cancelled_by_admin", "已由管理员取消")
            return
        outcome = await self._stream(schedule, run_id, conversation_id, allow_unsafe)
        if outcome["status"] == "cancelled" and run_id in self._cancel_requested:
            outcome["reason_code"] = "cancelled_by_admin"
            outcome["reason_message"] = "已由管理员停止"
        self._finish(run_id, **outcome)

    def _conversation_title(self, schedule: dict[str, Any]) -> str:
        try:
            local = self._clock().astimezone(resolve_timezone(schedule["timezone"]))
        except TriggerError:
            local = self._clock()
        return f"⏰ {schedule['name']} · {local.strftime('%m-%d %H:%M')}"

    async def _stream(
        self, schedule: dict[str, Any], run_id: str, conversation_id: str, allow_unsafe: bool,
    ) -> dict[str, Any]:
        from bot.web import api_service

        events = api_service.stream_chat(
            self.manager,
            schedule["bot_alias"],
            chat_session_user_id(None),
            schedule["prompt"],
            agent_id="main",
            follow_current_conversation=True,
            expected_conversation_id=conversation_id,
            include_trace=False,
            actor={"account_id": f"schedule:{schedule['id']}", "username": f"定时任务 · {schedule['name']}"},
            source_channel=SCHEDULE_SOURCE_CHANNEL,
            source_external_id=schedule["id"],
            allow_unsafe_cli=allow_unsafe,
        )
        bindings: dict[str, str] = {"conversation_id": conversation_id}
        persisted: dict[str, str] = {}
        terminal: dict[str, Any] | None = None
        try:
            async for event in events:
                event_type = event.get("type")
                if event_type not in {"meta", "status", "done", "error"}:
                    continue
                message = event.get("message") if isinstance(event.get("message"), dict) else {}
                ids = {
                    "turn_id": str(event.get("turn_id") or message.get("turn_id") or ""),
                    "assistant_message_id": str(event.get("assistant_message_id") or message.get("id") or ""),
                    "conversation_id": str(event.get("conversation_id") or message.get("conversation_id") or ""),
                }
                if any(bindings.get(key) and ids[key] and bindings[key] != ids[key] for key in ids):
                    continue
                bindings.update({key: value for key, value in ids.items() if value})
                pending = {
                    key: bindings[key]
                    for key in ("turn_id", "assistant_message_id")
                    if bindings.get(key) and persisted.get(key) != bindings[key]
                }
                if pending:
                    await asyncio.to_thread(self.store.update_run, run_id, **pending)
                    persisted.update(pending)
                if event_type in {"done", "error"}:
                    terminal = event
        finally:
            await events.aclose()
        return self._classify_terminal(terminal)

    @staticmethod
    def _classify_terminal(terminal: dict[str, Any] | None) -> dict[str, Any]:
        if terminal is None:
            return {"status": "failed", "reason_code": "no_terminal_event",
                    "reason_message": "执行结束，但未收到最终结果，请在聊天记录中查看"}
        if terminal.get("type") == "error":
            code = str(terminal.get("code") or "agent_error")
            message = str(terminal.get("message") or "执行失败")
            if code in _PREEMPTED_ERROR_CODES:
                return {"status": "failed", "reason_code": "preempted",
                        "reason_message": f"会话在发送前被其他请求占用：{message}"}
            return {"status": "failed", "reason_code": code, "reason_message": message}
        message = terminal.get("message") if isinstance(terminal.get("message"), dict) else {}
        meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
        completion = str(meta.get("completion_state") or terminal.get("completion_state") or "")
        content = str(message.get("content") or terminal.get("output") or "")
        preview = content.strip()[:PREVIEW_CHARS]
        if completion in {"cancelled", "canceled"}:
            return {"status": "cancelled", "reason_code": "cancelled", "reason_message": "任务已停止", "preview": preview}
        failed = (
            completion in {"error", "failed"}
            or message.get("state") == "error"
            or terminal.get("returncode", 0) not in {0, None}
        )
        if failed:
            return {"status": "failed", "reason_code": "agent_error",
                    "reason_message": preview or "执行失败，请在聊天记录中查看", "preview": preview}
        return {"status": "completed", "preview": preview}

    # Admin API -----------------------------------------------------------

    def limits(self) -> dict[str, int]:
        return {
            "min_interval_minutes": MIN_INTERVAL_MINUTES,
            "max_prompt_chars": MAX_PROMPT_CHARS,
            "max_wait_minutes": MAX_WAIT_MINUTES,
            "max_misfire_grace_minutes": MAX_MISFIRE_GRACE_MINUTES,
        }

    def _targets(self) -> list[dict[str, str]]:
        profiles = [self.manager.main_profile, *self.manager.managed_profiles.values()]
        return sorted(
            ({"alias": profile.alias, "cli_type": profile.cli_type}
             for profile in profiles if profile.enabled and not profile.archived),
            key=lambda item: item["alias"],
        )

    def _serialize(self, schedule: dict[str, Any], last_run: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "id": schedule["id"],
            "name": schedule["name"],
            "enabled": schedule["enabled"],
            "revision": schedule["revision"],
            "bot_alias": schedule["bot_alias"],
            "agent_id": schedule["agent_id"],
            "prompt": schedule["prompt"],
            "trigger": schedule["trigger"],
            "timezone": schedule["timezone"],
            "busy_policy": schedule["busy_policy"],
            "max_wait_minutes": schedule["max_wait_minutes"],
            "misfire_grace_minutes": schedule["misfire_grace_minutes"],
            "allow_unsafe_cli": schedule["allow_unsafe_cli"],
            "next_run_at": schedule.get("next_run_at"),
            "disabled_reason": schedule.get("disabled_reason") or "",
            "created_by": {
                "account_id": schedule.get("created_by_account_id") or "",
                "username": schedule.get("created_by_username") or "",
            },
            "created_at": schedule["created_at"],
            "updated_at": schedule["updated_at"],
            "active_run_id": self._active_by_schedule.get(schedule["id"], ""),
            "last_run": _serialize_run(last_run),
        }

    def _serialize_one(self, schedule: dict[str, Any]) -> dict[str, Any]:
        runs = self.store.list_runs(schedule["id"], limit=1)
        return self._serialize(schedule, runs[0] if runs else None)

    async def overview(self, *, can_allow_unsafe_cli: bool) -> dict[str, Any]:
        def load() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
            return self.store.list_schedules(), self.store.latest_runs()

        schedules, latest = await asyncio.to_thread(load)
        return {
            "items": [self._serialize(item, latest.get(item["id"])) for item in schedules],
            "default_timezone": self.default_timezone,
            "can_allow_unsafe_cli": bool(can_allow_unsafe_cli),
            "targets": self._targets(),
            "limits": self.limits(),
        }

    def _compute_next(self, trigger: dict[str, Any], timezone_name: str, now: datetime) -> str | None:
        upcoming = next_fire(trigger, resolve_timezone(timezone_name), now)
        return to_utc_iso(upcoming) if upcoming is not None else None

    def _normalize_changes(
        self, payload: dict[str, Any], existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _invalid("请求体需为 JSON 对象")
        creating = existing is None
        changes: dict[str, Any] = {}
        if creating or "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name or len(name) > MAX_NAME_CHARS:
                raise _invalid(f"名称不能为空，且不超过 {MAX_NAME_CHARS} 个字符")
            changes["name"] = name
        if creating or "bot_alias" in payload:
            alias = str(payload.get("bot_alias") or "").strip()
            unchanged = existing is not None and alias == existing["bot_alias"]
            if not unchanged and alias not in self._target_aliases():
                raise WebApiError(400, "invalid_schedule", f"智能体 {alias or '(空)'} 不可用")
            changes["bot_alias"] = alias
        if creating or "prompt" in payload:
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise _invalid("指令不能为空")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise _invalid(f"指令不能超过 {MAX_PROMPT_CHARS} 个字符")
            changes["prompt"] = prompt
        if creating or "timezone" in payload:
            timezone_name = str(payload.get("timezone") or "").strip() or self.default_timezone
            try:
                resolve_timezone(timezone_name)
            except TriggerError as exc:
                raise _invalid(str(exc)) from None
            changes["timezone"] = timezone_name
        tz_name = changes.get("timezone") or (existing or {}).get("timezone") or self.default_timezone
        if creating or "trigger" in payload:
            try:
                changes["trigger"] = normalize_trigger(
                    payload.get("trigger"), resolve_timezone(tz_name), now=self._clock(),
                )
            except TriggerError as exc:
                raise _invalid(str(exc)) from None
        if creating or "busy_policy" in payload:
            policy = str(payload.get("busy_policy") or "wait").strip().lower()
            if policy not in BUSY_POLICIES:
                raise _invalid("忙碌策略需为 wait 或 skip")
            changes["busy_policy"] = policy
        if creating or "max_wait_minutes" in payload:
            changes["max_wait_minutes"] = _bounded_int(
                payload.get("max_wait_minutes", DEFAULT_MAX_WAIT_MINUTES),
                label="最长等待分钟数", minimum=1, maximum=MAX_WAIT_MINUTES,
            )
        if creating or "misfire_grace_minutes" in payload:
            changes["misfire_grace_minutes"] = _bounded_int(
                payload.get("misfire_grace_minutes", DEFAULT_MISFIRE_GRACE_MINUTES),
                label="错过补跑窗口", minimum=0, maximum=MAX_MISFIRE_GRACE_MINUTES,
            )
        if creating or "allow_unsafe_cli" in payload:
            changes["allow_unsafe_cli"] = bool(payload.get("allow_unsafe_cli", False))
        if creating or "enabled" in payload:
            changes["enabled"] = bool(payload.get("enabled", True))
        if existing is not None:
            changes = {key: value for key, value in changes.items() if existing.get(key) != value}
        return changes

    def _apply_unsafe_policy(
        self, changes: dict[str, Any], existing: dict[str, Any] | None, actor: dict[str, Any],
    ) -> None:
        unsafe_after = changes.get("allow_unsafe_cli", bool((existing or {}).get("allow_unsafe_cli")))
        if not unsafe_after:
            if existing is None or existing.get("unsafe_authorized_by"):
                changes["unsafe_authorized_by"] = ""
            return
        if not any(field in changes for field in _UNSAFE_SENSITIVE_FIELDS):
            return
        if not actor.get("can_allow_unsafe_cli"):
            raise WebApiError(
                403, "schedule_unsafe_forbidden",
                "当前账号没有运行不安全 CLI 参数的权限，不能开启或修改允许不安全参数的定时任务",
            )
        changes["unsafe_authorized_by"] = str(actor.get("account_id") or "")

    def _apply_next_run(self, changes: dict[str, Any], existing: dict[str, Any] | None) -> None:
        merged = {**(existing or {}), **changes}
        relevant = existing is None or any(key in changes for key in ("trigger", "timezone", "enabled"))
        if not relevant:
            return
        if not merged.get("enabled"):
            changes["next_run_at"] = None
            return
        next_run_at = self._compute_next(merged["trigger"], merged["timezone"], self._clock())
        if next_run_at is None:
            raise _invalid("一次性任务的执行时间已过，请修改执行时间")
        changes["next_run_at"] = next_run_at
        changes["disabled_reason"] = ""

    async def create(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            changes = self._normalize_changes(payload, None)
            self._apply_unsafe_policy(changes, None, actor)
            self._apply_next_run(changes, None)
            schedule = self.store.create_schedule({
                **changes,
                "agent_id": "main",
                "created_by_account_id": str(actor.get("account_id") or ""),
                "created_by_username": str(actor.get("username") or ""),
            })
            return self._serialize(schedule, None)

        result = await asyncio.to_thread(work)
        self.wake()
        return result

    async def update(self, schedule_id: str, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("revision") is None:
            raise _invalid("缺少 revision")
        try:
            revision = int(payload["revision"])
        except (TypeError, ValueError):
            raise _invalid("revision 需为整数") from None

        def work() -> dict[str, Any]:
            try:
                existing = self.store.require_schedule(schedule_id)
                if existing["revision"] != revision:
                    raise ScheduleStoreError(409, "schedule_conflict", "定时任务已在其他地方修改，请刷新后重试")
                changes = self._normalize_changes(
                    {key: value for key, value in payload.items() if key != "revision"}, existing,
                )
                self._apply_unsafe_policy(changes, existing, actor)
                self._apply_next_run(changes, existing)
                if not changes:
                    return self._serialize_one(existing)
                updated = self.store.update_schedule(schedule_id, changes, expected_revision=revision)
            except ScheduleStoreError as exc:
                raise _store_error(exc) from None
            return self._serialize_one(updated)

        result = await asyncio.to_thread(work)
        self.wake()
        return result

    async def delete(self, schedule_id: str) -> dict[str, Any]:
        if schedule_id in self._active_by_schedule:
            raise WebApiError(409, "schedule_run_active", "该定时任务正在运行，请先停止本次运行再删除")
        deleted = await asyncio.to_thread(self.store.delete_schedule, schedule_id)
        if not deleted:
            raise WebApiError(404, "schedule_not_found", "定时任务不存在")
        self.wake()
        return {"deleted": True, "id": schedule_id}

    async def run_now(self, schedule_id: str) -> dict[str, Any]:
        if self._stopping or self._is_paused():
            raise WebApiError(503, "scheduler_paused", "宿主正在更新、重启或迁移，暂不能运行定时任务")
        if schedule_id in self._active_by_schedule:
            raise WebApiError(409, "schedule_run_active", "该定时任务已有运行尚未结束")
        try:
            schedule = await asyncio.to_thread(self.store.require_schedule, schedule_id)
        except ScheduleStoreError as exc:
            raise _store_error(exc) from None
        run = await asyncio.to_thread(
            self.store.claim_run,
            schedule_id,
            # Wall clock with microseconds keeps manual runs unique per schedule.
            planned_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            trigger="manual",
            bot_alias=schedule["bot_alias"],
        )
        if run is None or schedule_id in self._active_by_schedule:
            if run is not None:
                self._finish(run["id"], "skipped", "previous_run_active", "上一次运行尚未结束，已跳过")
            raise WebApiError(409, "schedule_run_active", "该定时任务已有运行尚未结束")
        self._spawn(schedule_id, run)
        return {"run": _serialize_run(run)}

    async def list_runs(self, schedule_id: str, limit: int = 20) -> dict[str, Any]:
        def work() -> list[dict[str, Any]]:
            self.store.require_schedule(schedule_id)
            return self.store.list_runs(schedule_id, limit)

        try:
            runs = await asyncio.to_thread(work)
        except ScheduleStoreError as exc:
            raise _store_error(exc) from None
        return {"items": [_serialize_run(run) for run in runs]}

    async def cancel_run(self, schedule_id: str, run_id: str) -> dict[str, Any]:
        from bot.web import api_service

        run = await asyncio.to_thread(self.store.get_run, run_id)
        if run is None or run["schedule_id"] != schedule_id:
            raise WebApiError(404, "schedule_run_not_found", "运行记录不存在")
        if run["status"] not in RUN_ACTIVE_STATUSES:
            raise WebApiError(409, "schedule_run_finished", "该运行已结束")
        task = self._run_tasks.get(run_id)
        if task is None:
            self._finish(run_id, "cancelled", "cancelled_by_admin", "已由管理员取消")
        elif run["status"] == "running" and run.get("conversation_id"):
            self._cancel_requested.add(run_id)
            await api_service.kill_user_process(
                self.manager,
                run["bot_alias"],
                chat_session_user_id(None),
                agent_id="main",
                expected_conversation_id=run["conversation_id"],
            )
        else:
            self._cancel_requested.add(run_id)
            task.cancel()
            await asyncio.wait({task}, timeout=5)
        return {"run": _serialize_run(await asyncio.to_thread(self.store.get_run, run_id))}


async def start_scheduler_service(
    manager: Any,
    *,
    capability_resolver: CapabilityResolver | None = None,
) -> SchedulerService | None:
    from bot.runtime_paths import get_scheduler_db_path

    service = SchedulerService(
        manager, ScheduleStore(get_scheduler_db_path()), capability_resolver=capability_resolver,
    )
    await service.start()
    return service


__all__ = [
    "SCHEDULE_SOURCE_CHANNEL",
    "SchedulerService",
    "get_active_scheduler_service",
    "start_scheduler_service",
]
