from __future__ import annotations

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
    mentions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AskAgentRequest:
    agent_id: str
    message: str
    model_tier: str
    timeout_seconds: int
    allow_write: bool


@dataclass
class ClusterRun:
    run_id: str
    bot_alias: str
    user_id: int
    status: str
    profile: BotProfile
    mentions: list[dict[str, Any]]
    started_at: str
    updated_at: str
    events: list[dict[str, Any]] = field(default_factory=list)


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
        now = self._now_iso()
        run = ClusterRun(
            run_id=f"clr_{uuid.uuid4().hex[:12]}",
            bot_alias=request.bot_alias,
            user_id=request.user_id,
            status="running",
            profile=request.profile,
            mentions=[dict(item) for item in request.mentions],
            started_at=now,
            updated_at=now,
            events=[{"kind": "run_started", "created_at": now}],
        )
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> ClusterRun | None:
        return self._runs.get(str(run_id or "").strip())

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        run = self._runs[str(run_id)]
        item = {"created_at": self._now_iso(), **dict(event)}
        run.events.append(item)
        run.updated_at = item["created_at"]

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        run = self._runs.get(str(run_id or "").strip())
        if run is None:
            return
        now = self._now_iso()
        run.status = status
        run.updated_at = now
        run.events.append({"kind": "run_finished", "status": status, "created_at": now})
        self._runs.pop(run.run_id, None)

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
            })
        return {
            "run_id": run.run_id,
            "bot_alias": run.bot_alias,
            "status": run.status,
            "agents": agents,
            "events": list(run.events),
        }

    def validate_ask_agent(self, run_id: str, payload: dict[str, Any]) -> AskAgentRequest:
        run = self._runs[str(run_id)]
        agent_id = str(payload.get("agent_id") or payload.get("agentId") or "").strip().lower()
        message = str(payload.get("message") or "").strip()
        allow_write = _bool(payload.get("allow_write", payload.get("allowWrite")))
        model_tier = _model_tier(payload.get("model_tier", payload.get("modelTier")))
        timeout_seconds = _int(
            payload.get("timeout_seconds", payload.get("timeoutSeconds")),
            run.profile.cluster.default_timeout_seconds,
            minimum=60,
            maximum=3600,
        )
        if not message:
            raise ClusterToolError("cluster_empty_message", "子 agent 消息不能为空")
        if agent_id == "main":
            raise ClusterToolError("cluster_tool_forbidden", "不能通过 ask_agent 调用主 agent")
        try:
            agent = run.profile.get_agent(agent_id)
        except KeyError as exc:
            raise ClusterToolError("cluster_agent_not_found", "未找到子 agent") from exc
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
