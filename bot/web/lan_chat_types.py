from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

LAN_CHAT_GROUP_ID = "group:default"
LAN_CHAT_TIMEZONE = ZoneInfo("Asia/Shanghai")

LanChatMode = Literal["off", "host", "join"]
LanChatConversationKind = Literal["group", "dm"]
LanChatEventType = Literal[
    "snapshot",
    "message_created",
    "conversation_updated",
    "presence_updated",
    "read_updated",
    "config_updated",
]


class LanChatError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class LanChatParticipant(TypedDict):
    room_user_id: str
    account_id: str
    username: str
    display_name: str
    instance_id: str
    instance_name: str
    online: bool
    last_seen_at: str


class LanChatMessage(TypedDict):
    id: str
    seq: int
    conversation_id: str
    kind: LanChatConversationKind
    sender: LanChatParticipant
    text: str
    created_at: str


class LanChatConversation(TypedDict, total=False):
    id: str
    kind: LanChatConversationKind
    title: str
    participant_ids: list[str]
    last_message: LanChatMessage | None
    unread_count: int
    updated_at: str


class LanChatConfig(TypedDict, total=False):
    mode: LanChatMode
    room_name: str
    instance_id: str
    instance_name: str
    host_url: str
    room_key: str
    lan_only: bool
    auto_connect: bool


@dataclass(frozen=True)
class LanChatUser:
    account_id: str
    username: str
    display_name: str
    instance_id: str
    instance_name: str

    @property
    def room_user_id(self) -> str:
        return room_user_id(self.instance_id, self.account_id)

    def to_participant(self, *, online: bool, last_seen_at: str) -> LanChatParticipant:
        return {
            "room_user_id": self.room_user_id,
            "account_id": self.account_id,
            "username": self.username,
            "display_name": self.display_name,
            "instance_id": self.instance_id,
            "instance_name": self.instance_name,
            "online": online,
            "last_seen_at": last_seen_at,
        }


def now_iso() -> str:
    return datetime.now(LAN_CHAT_TIMEZONE).isoformat(timespec="seconds")


def room_user_id(instance_id: str, account_id: str) -> str:
    return f"{instance_id.strip()}:{account_id.strip()}"


def dm_conversation_id(left_room_user_id: str, right_room_user_id: str) -> str:
    ordered = sorted([left_room_user_id.strip(), right_room_user_id.strip()])
    digest = hashlib.sha256("|".join(ordered).encode("utf-8")).hexdigest()[:16]
    return f"dm:{digest}"


def normalize_text(value: Any, *, max_length: int = 4000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise LanChatError(400, "empty_lan_chat_message", "消息不能为空")
    if len(text) > max_length:
        raise LanChatError(400, "lan_chat_message_too_long", f"消息不能超过 {max_length} 字")
    return text
