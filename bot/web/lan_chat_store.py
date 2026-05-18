from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from bot.web.lan_chat_types import (
    LAN_CHAT_GROUP_ID,
    LanChatConfig,
    LanChatConversation,
    LanChatConversationKind,
    LanChatError,
    LanChatMessage,
    LanChatParticipant,
    LanChatUser,
    dm_conversation_id,
    normalize_text,
    now_iso,
)


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(fallback)
    return loaded if isinstance(loaded, dict) else dict(fallback)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class LanChatStore:
    def __init__(self, *, config_path: Path, messages_path: Path) -> None:
        self.config_path = Path(config_path)
        self.messages_path = Path(messages_path)

    def load_config(self) -> LanChatConfig:
        raw = _read_json(self.config_path, {})
        config = self._normalize_config(raw)
        if raw != config:
            self._write_config(config)
        return config

    def save_config(self, config: LanChatConfig) -> LanChatConfig:
        current = self._normalize_config(_read_json(self.config_path, {}))
        merged = self._normalize_config({**current, **config})
        self._write_config(merged)
        return merged

    def load_state(self) -> dict[str, Any]:
        state = _read_json(self.messages_path, {})
        changed = False
        if not isinstance(state.get("next_seq"), int):
            state["next_seq"] = 1
            changed = True
        for key, default in (
            ("participants", {}),
            ("conversations", {}),
            ("messages", []),
            ("reads", {}),
        ):
            expected_type = list if key == "messages" else dict
            if not isinstance(state.get(key), expected_type):
                state[key] = default
                changed = True
        if self._ensure_group_conversation(state):
            changed = True
        if changed:
            self.save_state(state)
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        _write_json(self.messages_path, state)

    def upsert_participant(self, user: LanChatUser, *, online: bool) -> LanChatParticipant:
        state = self.load_state()
        participant = user.to_participant(online=online, last_seen_at=now_iso())
        state["participants"][user.room_user_id] = participant
        self.save_state(state)
        return participant

    def set_participant_online(self, room_user_id: str, *, online: bool) -> LanChatParticipant | None:
        state = self.load_state()
        participant = state.get("participants", {}).get(room_user_id)
        if not isinstance(participant, dict):
            return None
        participant["online"] = online
        participant["last_seen_at"] = now_iso()
        self.save_state(state)
        return participant

    def mark_all_participants_offline(self) -> None:
        state = self.load_state()
        changed = False
        timestamp = now_iso()
        for participant in state.get("participants", {}).values():
            if not isinstance(participant, dict) or not participant.get("online"):
                continue
            participant["online"] = False
            participant["last_seen_at"] = timestamp
            changed = True
        if changed:
            self.save_state(state)

    def list_participants(self) -> list[LanChatParticipant]:
        state = self.load_state()
        participants = state.get("participants", {})
        items = [item for item in participants.values() if isinstance(item, dict)]
        return sorted(items, key=lambda item: (not bool(item.get("online")), str(item.get("display_name") or "")))

    def ensure_dm_conversation(self, left_room_user_id: str, right_room_user_id: str) -> LanChatConversation:
        left_room_user_id = left_room_user_id.strip()
        right_room_user_id = right_room_user_id.strip()
        if not left_room_user_id or not right_room_user_id:
            raise LanChatError(400, "invalid_lan_chat_participant", "私聊用户无效")
        if left_room_user_id == right_room_user_id:
            raise LanChatError(400, "invalid_lan_chat_participant", "不能和自己私聊")

        state = self.load_state()
        conversation_id = dm_conversation_id(left_room_user_id, right_room_user_id)
        conversations = state["conversations"]
        if conversation_id not in conversations:
            participants = state.get("participants", {})
            left = participants.get(left_room_user_id, {})
            right = participants.get(right_room_user_id, {})
            conversations[conversation_id] = {
                "id": conversation_id,
                "kind": "dm",
                "title": self._dm_title(left_room_user_id, right_room_user_id, participants),
                "participant_ids": [left_room_user_id, right_room_user_id],
                "last_message": None,
                "updated_at": now_iso(),
            }
            if isinstance(left, dict) and isinstance(right, dict):
                conversations[conversation_id]["title"] = (
                    f"{left.get('display_name', left_room_user_id)} / {right.get('display_name', right_room_user_id)}"
                )
            self.save_state(state)
        return conversations[conversation_id]

    def append_message(
        self,
        conversation_id: str,
        kind: LanChatConversationKind,
        sender: LanChatParticipant,
        text: str,
    ) -> LanChatMessage:
        state = self.load_state()
        conversation_id = str(conversation_id or "").strip()
        if not conversation_id:
            raise LanChatError(400, "invalid_lan_chat_conversation", "会话无效")
        if kind == "dm" and conversation_id not in state["conversations"]:
            raise LanChatError(404, "lan_chat_conversation_not_found", "会话不存在")
        seq = int(state.get("next_seq") or 1)
        created_at = now_iso()
        message: LanChatMessage = {
            "id": f"msg_{created_at.replace('-', '').replace(':', '').replace('+', '_')}_{secrets.token_hex(4)}",
            "seq": seq,
            "conversation_id": conversation_id,
            "kind": kind,
            "sender": sender,
            "text": normalize_text(text),
            "created_at": created_at,
        }
        state["next_seq"] = seq + 1
        state["messages"].append(message)
        conversation = state["conversations"].setdefault(
            conversation_id,
            {
                "id": conversation_id,
                "kind": kind,
                "title": self.load_config().get("room_name", "工作室") if kind == "group" else conversation_id,
                "participant_ids": [] if kind == "group" else [sender["room_user_id"]],
                "last_message": None,
                "updated_at": created_at,
            },
        )
        conversation["last_message"] = message
        conversation["updated_at"] = created_at
        self.save_state(state)
        return message

    def list_messages(self, conversation_id: str, *, after_seq: int = 0, limit: int = 50) -> list[LanChatMessage]:
        state = self.load_state()
        bounded_limit = min(max(int(limit or 50), 1), 200)
        return [
            message
            for message in state["messages"]
            if message.get("conversation_id") == conversation_id and int(message.get("seq") or 0) > after_seq
        ][:bounded_limit]

    def list_conversations_for_user(self, room_user_id: str) -> list[dict[str, Any]]:
        state = self.load_state()
        reads = state.get("reads", {}).get(room_user_id, {})
        participants = state.get("participants", {})
        conversations: list[dict[str, Any]] = []
        for conversation in state["conversations"].values():
            if not isinstance(conversation, dict):
                continue
            conversation_id = str(conversation.get("id") or "")
            kind = conversation.get("kind")
            participant_ids = list(conversation.get("participant_ids") or [])
            if kind == "dm" and room_user_id not in participant_ids:
                continue
            item = dict(conversation)
            if kind == "dm":
                item["title"] = self._dm_title_for_user(room_user_id, participant_ids, participants)
            item["unread_count"] = self._unread_count(state, room_user_id, conversation_id, int(reads.get(conversation_id) or 0))
            conversations.append(item)
        return sorted(conversations, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def mark_read(self, room_user_id: str, conversation_id: str, seq: int) -> dict[str, Any]:
        state = self.load_state()
        if int(seq or 0) <= 0:
            seq = max(
                [
                    int(message.get("seq") or 0)
                    for message in state["messages"]
                    if message.get("conversation_id") == conversation_id
                ]
                or [0]
            )
        reads = state.setdefault("reads", {}).setdefault(room_user_id, {})
        reads[conversation_id] = int(seq or 0)
        self.save_state(state)
        return {"conversation_id": conversation_id, "seq": reads[conversation_id]}

    def conversation_participant_ids(self, conversation_id: str) -> list[str]:
        conversation = self.load_state().get("conversations", {}).get(conversation_id, {})
        if not isinstance(conversation, dict) or conversation.get("kind") == "group":
            return []
        return [str(item) for item in conversation.get("participant_ids") or []]

    def _write_config(self, config: LanChatConfig) -> None:
        _write_json(self.config_path, dict(config))

    def _normalize_config(self, raw: dict[str, Any]) -> LanChatConfig:
        mode = raw.get("mode") if raw.get("mode") in {"off", "host", "join"} else "off"
        return {
            "mode": mode,
            "room_name": str(raw.get("room_name") or "工作室"),
            "instance_id": str(raw.get("instance_id") or f"inst_{secrets.token_hex(8)}"),
            "instance_name": str(raw.get("instance_name") or "本机"),
            "host_url": str(raw.get("host_url") or ""),
            "room_key": str(raw.get("room_key") or ""),
            "lan_only": bool(raw.get("lan_only", True)),
            "auto_connect": bool(raw.get("auto_connect", True)),
        }

    def _ensure_group_conversation(self, state: dict[str, Any]) -> bool:
        conversations = state["conversations"]
        room_name = str(self.load_config().get("room_name") or "工作室")
        if LAN_CHAT_GROUP_ID not in conversations:
            conversations[LAN_CHAT_GROUP_ID] = {
                "id": LAN_CHAT_GROUP_ID,
                "kind": "group",
                "title": room_name,
                "participant_ids": [],
                "last_message": None,
                "updated_at": now_iso(),
            }
            return True
        if conversations[LAN_CHAT_GROUP_ID].get("title") != room_name:
            conversations[LAN_CHAT_GROUP_ID]["title"] = room_name
            return True
        return False

    def _dm_title_for_user(self, room_user_id: str, participant_ids: list[str], participants: dict[str, Any]) -> str:
        others = [item for item in participant_ids if item != room_user_id]
        target = others[0] if others else (participant_ids[0] if participant_ids else "")
        participant = participants.get(target, {})
        if isinstance(participant, dict):
            display = str(participant.get("display_name") or participant.get("username") or target)
            instance = str(participant.get("instance_name") or "")
            return f"{display} · {instance}" if instance else display
        return target

    def _dm_title(self, left: str, right: str, participants: dict[str, Any]) -> str:
        names: list[str] = []
        for item in (left, right):
            participant = participants.get(item, {})
            if isinstance(participant, dict):
                names.append(str(participant.get("display_name") or participant.get("username") or item))
            else:
                names.append(item)
        return " / ".join(names)

    def _unread_count(self, state: dict[str, Any], room_user_id: str, conversation_id: str, read_seq: int) -> int:
        count = 0
        for message in state["messages"]:
            if message.get("conversation_id") != conversation_id:
                continue
            if int(message.get("seq") or 0) <= read_seq:
                continue
            sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
            if sender.get("room_user_id") == room_user_id:
                continue
            count += 1
        return count
