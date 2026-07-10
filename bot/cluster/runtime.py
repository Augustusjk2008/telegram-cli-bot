from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bot.models import BotProfile


@dataclass(frozen=True)
class ClusterRunRequest:
    bot_alias: str
    user_id: int
    profile: BotProfile
    execution_mode: str = "cli"
    mentions: list[dict[str, Any]] = field(default_factory=list)
    allow_unsafe_cli: bool = False


@dataclass(frozen=True)
class AskAgentRequest:
    agent_id: str
    message: str
    model_tier: str
    timeout_seconds: int
    allow_write: bool


@dataclass
class ClusterAgentTaskMessage:
    sequence: int
    task_id: str
    agent_id: str
    kind: str
    content: str
    created_at: str


@dataclass
class ClusterAgentTask:
    task_id: str
    agent_id: str
    message: str
    model_tier: str
    timeout_seconds: int
    allow_write: bool
    status: str
    created_at: str
    started_at: str = ""
    completed_at: str = ""
    output: str = ""
    error: str = ""
    messages: list[ClusterAgentTaskMessage] = field(default_factory=list)


@dataclass
class ClusterRun:
    run_id: str
    bot_alias: str
    user_id: int
    execution_mode: str
    status: str
    profile: BotProfile
    mentions: list[dict[str, Any]]
    allow_unsafe_cli: bool
    started_at: str
    updated_at: str
    events: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, ClusterAgentTask] = field(default_factory=dict)
    _next_message_sequence: int = 1
    _agent_message_read_sequence: int = 0
    message_condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class ClusterToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _bool(value: Any) -> bool:
    return bool(value)


def _int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _model_tier(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in {"low", "medium", "high"} else "medium"


class ClusterRuntime:
    def __init__(self) -> None:
        self._runs: dict[str, ClusterRun] = {}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat()

    def start_run(self, request: ClusterRunRequest) -> ClusterRun:
        self.cleanup_finished_runs()
        now = self._now_iso()
        run = ClusterRun(
            run_id=f"clr_{uuid.uuid4().hex[:12]}",
            bot_alias=request.bot_alias,
            user_id=request.user_id,
            execution_mode=str(request.execution_mode or "cli").strip().lower() or "cli",
            status="running",
            profile=request.profile,
            mentions=[dict(item) for item in request.mentions],
            allow_unsafe_cli=bool(request.allow_unsafe_cli),
            started_at=now,
            updated_at=now,
            events=[{"kind": "run_started", "created_at": now}],
        )
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> ClusterRun | None:
        return self._runs.get(str(run_id or "").strip())

    def find_active_run(self, bot_alias: str, user_id: int) -> ClusterRun | None:
        self.cleanup_finished_runs()
        alias = str(bot_alias or "").strip()
        active_runs = [
            run
            for run in self._runs.values()
            if run.bot_alias == alias
            and run.user_id == user_id
            and (
                run.status == "running"
                or any(task.status in {"queued", "running"} for task in run.tasks.values())
            )
        ]
        active_runs.sort(key=lambda item: item.updated_at or item.started_at, reverse=True)
        return active_runs[0] if active_runs else None

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        run = self._runs[str(run_id)]
        item = {"created_at": self._now_iso(), **dict(event)}
        run.events.append(item)
        run.updated_at = item["created_at"]

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        run = self._runs.get(str(run_id or "").strip())
        if run is None:
            return
        if run.status == "cancelled" and status != "cancelled":
            return
        now = self._now_iso()
        run.status = status
        run.updated_at = now
        run.events.append({"kind": "run_finished", "status": status, "created_at": now})

    def cleanup_finished_runs(self, *, keep_latest: int = 50) -> None:
        finished = [
            run
            for run in self._runs.values()
            if run.status in {"completed", "failed", "error", "cancelled"}
            and all(task.status in {"completed", "failed", "cancelled"} for task in run.tasks.values())
        ]
        finished.sort(key=lambda item: item.updated_at, reverse=True)
        for run in finished[keep_latest:]:
            self._runs.pop(run.run_id, None)

    def create_agent_task(self, run_id: str, request: AskAgentRequest) -> ClusterAgentTask:
        run = self._runs[str(run_id)]
        now = self._now_iso()
        task = ClusterAgentTask(
            task_id=f"clt_{uuid.uuid4().hex[:12]}",
            agent_id=request.agent_id,
            message=request.message,
            model_tier=request.model_tier,
            timeout_seconds=request.timeout_seconds,
            allow_write=request.allow_write,
            status="queued",
            created_at=now,
        )
        run.tasks[task.task_id] = task
        run.events.append({
            "kind": "agent_task_created",
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "model_tier": task.model_tier,
            "message_preview": task.message[:120],
            "created_at": now,
        })
        run.updated_at = now
        return task

    def mark_agent_task_running(self, run_id: str, task_id: str) -> ClusterAgentTask:
        task = self._runs[str(run_id)].tasks[str(task_id)]
        now = self._now_iso()
        task.status = "running"
        task.started_at = now
        self.append_event(run_id, {"kind": "agent_task_started", "task_id": task.task_id, "agent_id": task.agent_id})
        return task

    def append_agent_task_message(
        self,
        run_id: str,
        task_id: str,
        *,
        kind: str,
        content: str,
    ) -> ClusterAgentTaskMessage | None:
        run = self._runs[str(run_id)]
        task = run.tasks[str(task_id)]
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"progress", "final"}:
            return None
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return None
        if (
            task.messages
            and task.messages[-1].kind == normalized_kind
            and task.messages[-1].content == normalized_content
        ):
            return None
        if normalized_kind == "final" and any(message.kind == "final" for message in task.messages):
            return None
        now = self._now_iso()
        message = ClusterAgentTaskMessage(
            sequence=run._next_message_sequence,
            task_id=task.task_id,
            agent_id=task.agent_id,
            kind=normalized_kind,
            content=normalized_content[:4000],
            created_at=now,
        )
        run._next_message_sequence += 1
        task.messages.append(message)
        if len(task.messages) > 100:
            del task.messages[: len(task.messages) - 100]
        self.append_event(
            run_id,
            {
                "kind": "agent_task_message",
                "task_id": task.task_id,
                "agent_id": task.agent_id,
                "message_kind": message.kind,
                "sequence": message.sequence,
                "summary": message.content[:200],
            },
        )
        return message

    async def notify_agent_task_message(self, run_id: str) -> None:
        run = self._runs.get(str(run_id))
        if run is None:
            return
        async with run.message_condition:
            run.message_condition.notify_all()

    async def wait_for_task_change(self, run_id: str, task_ids: list[str] | None, wait_seconds: float) -> None:
        run = self._runs[str(run_id)]
        deadline = asyncio.get_running_loop().time() + max(0.0, wait_seconds)
        while True:
            if self.build_task_status(run_id, task_ids, include_output=False)["pending_count"] <= 0:
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            async with run.message_condition:
                if self.build_task_status(run_id, task_ids, include_output=False)["pending_count"] <= 0:
                    return
                try:
                    await asyncio.wait_for(run.message_condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return

    def complete_agent_task(self, run_id: str, task_id: str, output: str) -> ClusterAgentTask:
        task = self._runs[str(run_id)].tasks[str(task_id)]
        if task.status == "cancelled":
            return task
        now = self._now_iso()
        task.status = "completed"
        task.completed_at = now
        task.output = str(output or "")
        task.error = ""
        self.append_agent_task_message(run_id, task_id, kind="final", content=task.output)
        self.append_event(
            run_id,
            {"kind": "agent_task_completed", "task_id": task.task_id, "agent_id": task.agent_id, "summary": task.output[:200]},
        )
        return task

    def fail_agent_task(self, run_id: str, task_id: str, error: str) -> ClusterAgentTask:
        task = self._runs[str(run_id)].tasks[str(task_id)]
        if task.status == "cancelled":
            return task
        now = self._now_iso()
        task.status = "failed"
        task.completed_at = now
        task.error = str(error or "")
        self.append_agent_task_message(run_id, task_id, kind="final", content=task.error)
        self.append_event(
            run_id,
            {"kind": "agent_task_failed", "task_id": task.task_id, "agent_id": task.agent_id, "error": task.error[:200]},
        )
        return task

    def cancel_run_tasks(self, run_id: str, message: str = "已取消") -> list[ClusterAgentTask]:
        run = self._runs.get(str(run_id or "").strip())
        if run is None:
            return []
        now = self._now_iso()
        cancelled: list[ClusterAgentTask] = []
        for task in run.tasks.values():
            if task.status not in {"queued", "running"}:
                continue
            task.status = "cancelled"
            task.completed_at = now
            task.error = str(message or "已取消")
            self.append_agent_task_message(run_id, task.task_id, kind="final", content=task.error)
            self.append_event(
                run_id,
                {"kind": "agent_task_cancelled", "task_id": task.task_id, "agent_id": task.agent_id, "error": task.error[:200]},
            )
            cancelled.append(task)
        return cancelled

    def _task_deadline_exceeded(self, task: ClusterAgentTask) -> bool:
        if task.status != "running" or not task.started_at:
            return False
        if task.timeout_seconds <= 0:
            return True
        try:
            started_at = datetime.fromisoformat(task.started_at)
        except ValueError:
            return False
        elapsed_seconds = (datetime.now().astimezone() - started_at).total_seconds()
        return elapsed_seconds >= task.timeout_seconds

    def _serialize_task_message(self, message: ClusterAgentTaskMessage) -> dict[str, Any]:
        return {
            "sequence": message.sequence,
            "task_id": message.task_id,
            "agent_id": message.agent_id,
            "kind": message.kind,
            "content": message.content,
            "created_at": message.created_at,
        }

    def _serialize_task(
        self,
        task: ClusterAgentTask,
        *,
        include_output: bool,
        include_messages: bool = False,
        message_limit: int = 20,
    ) -> dict[str, Any]:
        item = {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "status": task.status,
            "model_tier": task.model_tier,
            "timeout_seconds": task.timeout_seconds,
            "deadline_exceeded": self._task_deadline_exceeded(task),
            "allow_write": task.allow_write,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "error": task.error,
            "message_count": len(task.messages),
            "latest_message_sequence": task.messages[-1].sequence if task.messages else 0,
        }
        if include_output:
            item["output"] = task.output
        if include_messages:
            limit = max(1, min(100, int(message_limit or 20)))
            item["messages"] = [self._serialize_task_message(message) for message in task.messages[-limit:]]
        return item

    def build_task_status(
        self,
        run_id: str,
        task_ids: list[str] | None = None,
        *,
        include_output: bool = True,
        include_messages: bool = False,
        message_limit: int = 20,
    ) -> dict[str, Any]:
        run = self._runs[str(run_id)]
        selected_ids = {str(item) for item in task_ids or [] if str(item).strip()}
        tasks = [
            task
            for task in run.tasks.values()
            if not selected_ids or task.task_id in selected_ids
        ]
        return {
            "tasks": [
                self._serialize_task(
                    task,
                    include_output=include_output,
                    include_messages=include_messages,
                    message_limit=message_limit,
                )
                for task in tasks
            ],
            "queued_count": sum(1 for task in tasks if task.status == "queued"),
            "running_count": sum(1 for task in tasks if task.status == "running"),
            "completed_count": sum(1 for task in tasks if task.status == "completed"),
            "failed_count": sum(1 for task in tasks if task.status == "failed"),
            "pending_count": sum(1 for task in tasks if task.status in {"queued", "running"}),
        }

    def build_agent_messages(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        include_progress: bool = True,
        include_final: bool = True,
        message_limit: int = 20,
    ) -> dict[str, Any]:
        run = self._runs[str(run_id)]
        allowed_kinds: set[str] = set()
        if include_progress:
            allowed_kinds.add("progress")
        if include_final:
            allowed_kinds.add("final")
        if not allowed_kinds:
            allowed_kinds = {"progress", "final"}
        limit = max(1, min(100, int(message_limit or 20)))
        messages = [
            message
            for task in run.tasks.values()
            for message in task.messages
            if message.sequence > after_sequence and message.kind in allowed_kinds
        ]
        messages.sort(key=lambda item: item.sequence)
        limited = messages[:limit]
        cursor = limited[-1].sequence if limited else max(0, run._next_message_sequence - 1)
        return {
            "timed_out": False,
            "cursor": cursor,
            "messages": [self._serialize_task_message(message) for message in limited],
        }

    def agent_message_read_sequence(self, run_id: str) -> int:
        run = self._runs.get(str(run_id))
        if run is None:
            return 0
        return max(0, int(getattr(run, "_agent_message_read_sequence", 0)))

    def mark_agent_messages_read(self, run_id: str, cursor: int) -> None:
        run = self._runs.get(str(run_id))
        if run is None:
            return
        run._agent_message_read_sequence = max(
            run._agent_message_read_sequence,
            max(0, int(cursor or 0)),
        )

    async def wait_agent_messages(
        self,
        run_id: str,
        *,
        after_sequence: int,
        wait_seconds: float,
        include_progress: bool = True,
        include_final: bool = True,
        message_limit: int = 20,
    ) -> dict[str, Any]:
        run = self._runs[str(run_id)]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1.0, min(300.0, float(wait_seconds or 60.0)))
        while True:
            result = self.build_agent_messages(
                run_id,
                after_sequence=after_sequence,
                include_progress=include_progress,
                include_final=include_final,
                message_limit=message_limit,
            )
            if result["messages"]:
                return result
            remaining = deadline - loop.time()
            if remaining <= 0:
                result["timed_out"] = True
                return result
            async with run.message_condition:
                result = self.build_agent_messages(
                    run_id,
                    after_sequence=after_sequence,
                    include_progress=include_progress,
                    include_final=include_final,
                    message_limit=message_limit,
                )
                if result["messages"]:
                    return result
                try:
                    await asyncio.wait_for(run.message_condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    result = self.build_agent_messages(
                        run_id,
                        after_sequence=after_sequence,
                        include_progress=include_progress,
                        include_final=include_final,
                        message_limit=message_limit,
                    )
                    result["timed_out"] = not bool(result["messages"])
                    return result

    def build_status(self, run_id: str) -> dict[str, Any]:
        run = self._runs[str(run_id)]
        agents = []
        for agent in run.profile.normalized_agents():
            if agent.id == "main":
                continue
            agents.append({
                "id": agent.id,
                "name": agent.name,
                "enabled": agent.enabled,
                "allow_cluster": agent.cluster.allow_cluster,
                "allow_write": agent.cluster.allow_write,
                "session_policy": agent.cluster.session_policy,
                "timeout_seconds": agent.cluster.timeout_seconds,
            })
        return {
            "run_id": run.run_id,
            "bot_alias": run.bot_alias,
            "execution_mode": run.execution_mode,
            "status": run.status,
            "agents": agents,
            "events": list(run.events),
            "tasks": self.build_task_status(run_id, include_output=False),
        }

    def validate_ask_agent(self, run_id: str, payload: dict[str, Any]) -> AskAgentRequest:
        run = self._runs[str(run_id)]
        agent_id = str(payload.get("agent_id") or payload.get("agentId") or "").strip().lower()
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ClusterToolError("cluster_empty_message", "子 agent 消息不能为空")
        if not agent_id:
            raise ClusterToolError("cluster_agent_not_found", "未找到子 agent")
        if agent_id == "main":
            raise ClusterToolError("cluster_tool_forbidden", "不能通过 ask_agent 调用主 agent")
        try:
            agent = run.profile.get_agent(agent_id)
        except KeyError as exc:
            raise ClusterToolError("cluster_agent_not_found", "未找到子 agent") from exc
        allow_write = _bool(payload.get("allow_write", payload.get("allowWrite")))
        model_tier = _model_tier(payload.get("model_tier", payload.get("modelTier")))
        if "timeout_seconds" in payload:
            timeout_source = payload.get("timeout_seconds")
        elif "timeoutSeconds" in payload:
            timeout_source = payload.get("timeoutSeconds")
        else:
            timeout_source = agent.cluster.timeout_seconds
        timeout_seconds = _int(
            timeout_source,
            run.profile.cluster.default_timeout_seconds,
            minimum=60,
            maximum=3600,
        )
        if not agent.enabled or not agent.cluster.allow_cluster:
            raise ClusterToolError("cluster_agent_disabled", "子 agent 未启用集群调用")
        if allow_write and run.profile.cluster.write_policy == "main_only":
            raise ClusterToolError("cluster_tool_forbidden", "当前策略不允许子 agent 写文件")
        if allow_write and not agent.cluster.allow_write and run.profile.cluster.write_policy != "all_agents":
            raise ClusterToolError("cluster_tool_forbidden", "该子 agent 未允许写文件")
        return AskAgentRequest(
            agent_id=agent_id,
            message=message,
            model_tier=model_tier,
            timeout_seconds=timeout_seconds,
            allow_write=allow_write,
        )
