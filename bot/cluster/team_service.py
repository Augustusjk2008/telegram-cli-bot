from __future__ import annotations

import asyncio
from typing import Any

from bot.cluster.runtime import ClusterRuntime, ClusterToolError
from bot.models import BotProfile


def _normalize_roles(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ClusterToolError("cluster_team_invalid", "roles 必须是数组")
    roles: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ClusterToolError("cluster_team_invalid", "角色必须是对象")
        name = str(item.get("name") or "").strip()
        responsibility = str(item.get("responsibility") or "").strip()
        if not 1 <= len(name) <= 32:
            raise ClusterToolError("cluster_team_invalid", "角色名称长度必须为 1-32 字符")
        if not 1 <= len(responsibility) <= 1000:
            raise ClusterToolError("cluster_team_invalid", "角色职责长度必须为 1-1000 字符")
        if name in names:
            raise ClusterToolError("cluster_team_invalid", "同一编组内角色名称必须唯一")
        names.add(name)
        roles.append({"name": name, "responsibility": responsibility})
    return roles


class ClusterTeamService:
    def __init__(self) -> None:
        self._bot_locks: dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Lock] = {}
        self._locks: dict[tuple[asyncio.AbstractEventLoop, str, int, str], asyncio.Lock] = {}

    def bot_lock(self, bot_alias: str) -> asyncio.Lock:
        alias = str(bot_alias or "").strip().lower()
        key = (asyncio.get_running_loop(), alias)
        return self._bot_locks.setdefault(key, asyncio.Lock())

    def conversation_lock(
        self,
        bot_alias: str,
        user_id: int,
        parent_conversation_id: str,
    ) -> asyncio.Lock:
        key = (
            asyncio.get_running_loop(),
            str(bot_alias or "").strip().lower(),
            int(user_id),
            str(parent_conversation_id or "").strip(),
        )
        return self._locks.setdefault(key, asyncio.Lock())

    async def configure(
        self,
        *,
        runtime: ClusterRuntime,
        store: Any,
        run_id: str,
        payload: dict[str, Any],
        current_profile: BotProfile | None = None,
    ) -> dict[str, Any]:
        run = runtime.get_run(run_id)
        if run is None or not run.main_conversation_id:
            raise ClusterToolError("cluster_run_not_found", "未找到主会话集群任务")
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"extend", "replace"}:
            raise ClusterToolError("cluster_team_invalid", "mode 必须是 extend 或 replace")
        roles = _normalize_roles(payload.get("roles"))
        lock = self.conversation_lock(run.bot_alias, run.user_id, run.main_conversation_id)
        async with self.bot_lock(run.bot_alias), lock:
            live_run = runtime.get_run(run_id)
            if live_run is None:
                raise ClusterToolError("cluster_run_not_found", "未找到集群任务")
            state = store.get_conversation_team(live_run.main_conversation_id)
            current_revision = max(0, int(state.get("cluster_team_revision") or 0))
            if current_revision != live_run.team_revision:
                raise ClusterToolError("cluster_team_changed", "编组已被另一轮更新，请重新读取后重试")
            current_team = state.get("cluster_team") if isinstance(state.get("cluster_team"), dict) else {}
            current_assignments = [
                dict(item)
                for item in list(current_team.get("assignments") or [])
                if isinstance(item, dict)
            ]
            capacity_profile = current_profile or live_run.profile
            capacity = max(1, int(capacity_profile.cluster.max_parallel_agents or 1))
            active_slot_ids = [
                agent.id
                for agent in capacity_profile.normalized_agents()
                if agent.id != "main"
            ][:capacity]
            if len(active_slot_ids) < capacity:
                raise ClusterToolError("cluster_slots_unavailable", "物理槽位数量不足，请先保存集群配置")

            if mode == "extend":
                if len(current_assignments) + len(roles) > capacity:
                    raise ClusterToolError("cluster_team_full", "没有足够的空闲槽位")
                existing_names = {str(item.get("name") or "").strip() for item in current_assignments}
                if any(role["name"] in existing_names for role in roles):
                    raise ClusterToolError("cluster_team_invalid", "同一编组内角色名称必须唯一")
                occupied = {str(item.get("agent_id") or "").strip() for item in current_assignments}
                free_slots = [agent_id for agent_id in active_slot_ids if agent_id not in occupied]
                next_assignments = list(current_assignments)
                for role, agent_id in zip(roles, free_slots, strict=False):
                    next_assignments.append({
                        "agent_id": agent_id,
                        **role,
                        "assignment_revision": current_revision + 1,
                    })
            else:
                if runtime.has_pending_tasks(
                    bot_alias=live_run.bot_alias,
                    user_id=live_run.user_id,
                    main_conversation_id=live_run.main_conversation_id,
                ):
                    raise ClusterToolError("cluster_team_busy", "当前主会话仍有子任务运行，暂不能重新编组")
                if len(roles) > capacity:
                    raise ClusterToolError("cluster_team_full", "角色数量超过集群规模")
                current_by_slot = {
                    str(item.get("agent_id") or "").strip(): item for item in current_assignments
                }
                next_assignments = []
                for role, agent_id in zip(roles, active_slot_ids, strict=False):
                    previous = current_by_slot.get(agent_id)
                    unchanged = bool(
                        previous
                        and str(previous.get("name") or "").strip() == role["name"]
                        and str(previous.get("responsibility") or "").strip() == role["responsibility"]
                    )
                    next_assignments.append({
                        "agent_id": agent_id,
                        **role,
                        "assignment_revision": (
                            max(1, int(previous.get("assignment_revision") or 1))
                            if unchanged
                            else current_revision + 1
                        ),
                    })

            next_team = {"version": 1, "assignments": next_assignments}
            try:
                updated = store.update_conversation_team(
                    live_run.main_conversation_id,
                    next_team,
                    expected_revision=current_revision,
                )
            except Exception as exc:
                if getattr(exc, "code", "") == "cluster_team_changed":
                    raise ClusterToolError("cluster_team_changed", "编组已被另一轮更新，请重新读取后重试") from exc
                raise
            updated_team = updated.get("cluster_team") if isinstance(updated.get("cluster_team"), dict) else next_team
            updated_revision = max(0, int(updated.get("cluster_team_revision") or current_revision + 1))
            try:
                runtime.update_run_team(run_id, updated_team, updated_revision)
            except Exception as exc:  # pragma: no cover - defensive recovery
                reloaded = store.get_conversation_team(live_run.main_conversation_id)
                runtime.update_run_team(
                    run_id,
                    reloaded.get("cluster_team") or {"version": 1, "assignments": []},
                    int(reloaded.get("cluster_team_revision") or 0),
                )
                raise ClusterToolError("cluster_team_sync_failed", "编组已保存，但运行态同步失败，请重试") from exc
            runtime.append_event(
                run_id,
                {
                    "kind": "team_configured",
                    "mode": mode,
                    "team_revision": updated_revision,
                    "role_count": len(updated_team.get("assignments") or []),
                },
            )
            assignments = [dict(item) for item in list(updated_team.get("assignments") or []) if isinstance(item, dict)]
            return {
                "team_revision": updated_revision,
                "capacity": capacity,
                "assignments": assignments,
                "free_slots": max(0, capacity - len(assignments)),
            }
