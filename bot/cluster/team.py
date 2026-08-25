from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


TEAM_FORMAT_VERSION = 1


@dataclass(frozen=True)
class TeamAssignment:
    agent_id: str
    name: str
    responsibility: str
    assignment_revision: int

    def __post_init__(self) -> None:
        agent_id = str(self.agent_id or "").strip()
        name = str(self.name or "").strip()
        responsibility = str(self.responsibility or "").strip()
        try:
            assignment_revision = int(self.assignment_revision)
        except (TypeError, ValueError) as exc:
            raise ValueError("assignment_revision 必须是正整数") from exc
        if not agent_id:
            raise ValueError("agent_id 不能为空")
        if not 1 <= len(name) <= 32:
            raise ValueError("角色名称长度必须为 1..32")
        if not 1 <= len(responsibility) <= 1000:
            raise ValueError("角色职责长度必须为 1..1000")
        if assignment_revision < 1:
            raise ValueError("assignment_revision 必须是正整数")
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "responsibility", responsibility)
        object.__setattr__(self, "assignment_revision", assignment_revision)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TeamAssignment":
        if not isinstance(value, dict):
            raise ValueError("编组 assignment 必须是对象")
        return cls(
            agent_id=value.get("agent_id", value.get("agentId", "")),
            name=value.get("name", ""),
            responsibility=value.get("responsibility", ""),
            assignment_revision=value.get(
                "assignment_revision",
                value.get("assignmentRevision", 0),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "responsibility": self.responsibility,
            "assignment_revision": self.assignment_revision,
        }


@dataclass(frozen=True)
class ConversationTeam:
    assignments: tuple[TeamAssignment, ...] = field(default_factory=tuple)
    version: int = TEAM_FORMAT_VERSION

    def __post_init__(self) -> None:
        if int(self.version) != TEAM_FORMAT_VERSION:
            raise ValueError(f"编组 version 必须为 {TEAM_FORMAT_VERSION}")
        assignments = tuple(self.assignments)
        names = [assignment.name for assignment in assignments]
        if len(names) != len(set(names)):
            raise ValueError("同一编组内角色名称必须唯一")
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "version", TEAM_FORMAT_VERSION)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ConversationTeam":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("编组必须是对象")
        version = value.get("version", TEAM_FORMAT_VERSION)
        raw_assignments = value.get("assignments", [])
        if not isinstance(raw_assignments, list):
            raise ValueError("编组 assignments 必须是数组")
        return cls(
            version=version,
            assignments=tuple(TeamAssignment.from_dict(item) for item in raw_assignments),
        )

    @classmethod
    def from_value(cls, value: "ConversationTeam | dict[str, Any] | None") -> "ConversationTeam":
        return value if isinstance(value, cls) else cls.from_dict(value)

    @classmethod
    def from_json(cls, value: str | None) -> "ConversationTeam":
        text = str(value or "").strip()
        if not text:
            return cls()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("编组 JSON 格式无效") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TEAM_FORMAT_VERSION,
            "assignments": [assignment.to_dict() for assignment in self.assignments],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ClusterSlotStatus:
    agent_id: str
    ordinal: int
    active: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": str(self.agent_id or "").strip(),
            "ordinal": max(1, int(self.ordinal)),
            "active": bool(self.active),
        }


class ClusterTeamChangedError(RuntimeError):
    code = "cluster_team_changed"

    def __init__(
        self,
        conversation_id: str,
        expected_revision: int,
        current_state: dict[str, Any],
    ) -> None:
        self.conversation_id = conversation_id
        self.expected_revision = expected_revision
        self.current_state = current_state
        self.data = {
            "conversation_id": conversation_id,
            "expected_revision": expected_revision,
            **current_state,
        }
        super().__init__("主会话编组已变化，请刷新后重试")


class ClusterSlotsLockedError(ValueError):
    code = "cluster_slots_locked"

    def __init__(self) -> None:
        super().__init__("集群已启用，不能通过模板接口修改物理槽位")


__all__ = [
    "ClusterSlotStatus",
    "ClusterSlotsLockedError",
    "ClusterTeamChangedError",
    "ConversationTeam",
    "TEAM_FORMAT_VERSION",
    "TeamAssignment",
]
