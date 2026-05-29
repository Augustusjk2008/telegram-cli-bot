from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web

from bot.web.api_common import AuthContext
from bot.web.lan_chat_store import LanChatStore
from bot.web.lan_chat_types import (
    LAN_CHAT_GROUP_ID,
    LanChatConfig,
    LanChatError,
    LanChatMessage,
    LanChatParticipant,
    LanChatUser,
    normalize_text,
    now_iso,
)


class LanChatService:
    def __init__(
        self,
        *,
        repo_root: Path,
        config_path: Path | None = None,
        messages_path: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.store = LanChatStore(
            config_path=config_path or self.repo_root / ".web_lan_chat.json",
            messages_path=messages_path or self.repo_root / ".web_lan_chat_messages.json",
        )
        self._browser_sockets: dict[web.WebSocketResponse, str] = {}
        self._node_sockets: dict[str, web.WebSocketResponse] = {}
        self._last_error = ""
        self._join_connected = False
        self._lock = asyncio.Lock()
        self.store.mark_all_participants_offline()

    def config(self) -> LanChatConfig:
        return self.store.load_config()

    def update_config(self, input_payload: dict[str, Any]) -> LanChatConfig:
        current = self.config()
        mode = str(input_payload.get("mode", current.get("mode", "off"))).strip()
        if mode not in {"off", "host", "join"}:
            raise LanChatError(400, "invalid_lan_chat_mode", "联机聊天模式无效")
        room_key = str(input_payload.get("room_key", current.get("room_key", ""))).strip()
        if mode in {"host", "join"} and not room_key:
            room_key = f"tcbr_{secrets.token_urlsafe(24)}"
        config = self.store.save_config(
            {
                "mode": mode,
                "room_name": str(input_payload.get("room_name", current.get("room_name", "工作室"))).strip() or "工作室",
                "instance_id": str(current.get("instance_id")),
                "instance_name": str(input_payload.get("instance_name", current.get("instance_name", "本机"))).strip()
                or "本机",
                "host_url": str(input_payload.get("host_url", current.get("host_url", ""))).strip().rstrip("/"),
                "room_key": room_key,
                "lan_only": bool(input_payload.get("lan_only", current.get("lan_only", True))),
                "auto_connect": bool(input_payload.get("auto_connect", current.get("auto_connect", True))),
            }
        )
        self._join_connected = False if config["mode"] != "join" else self._join_connected
        self._last_error = ""
        return config

    def public_config(self) -> dict[str, Any]:
        config = self.config()
        room_key = str(config.get("room_key") or "")
        return {
            **{key: value for key, value in config.items() if key != "room_key"},
            "room_key_preview": f"{room_key[:8]}...{room_key[-4:]}" if room_key else "",
        }

    def local_user(self, auth: AuthContext) -> LanChatUser:
        config = self.config()
        username = auth.username or auth.account_id
        return LanChatUser(
            account_id=auth.account_id,
            username=username,
            display_name=username,
            instance_id=str(config["instance_id"]),
            instance_name=str(config.get("instance_name") or "本机"),
        )

    def register_remote_participant(self, payload: dict[str, Any]) -> LanChatParticipant:
        user = LanChatUser(
            account_id=str(payload["account_id"]),
            username=str(payload["username"]),
            display_name=str(payload.get("display_name") or payload["username"]),
            instance_id=str(payload["instance_id"]),
            instance_name=str(payload.get("instance_name") or payload["instance_id"]),
        )
        return self.store.upsert_participant(user, online=True)

    def list_participants(self) -> list[LanChatParticipant]:
        return self.store.list_participants()

    def ensure_dm(self, left_room_user_id: str, right_room_user_id: str) -> dict[str, Any]:
        return self.store.ensure_dm_conversation(left_room_user_id, right_room_user_id)

    def list_conversations(self, user: LanChatUser) -> list[dict[str, Any]]:
        self.store.upsert_participant(user, online=True)
        return self.store.list_conversations_for_user(user.room_user_id)

    def list_messages(
        self,
        user: LanChatUser,
        conversation_id: str,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> list[LanChatMessage]:
        self._assert_user_can_view_conversation(user.room_user_id, conversation_id)
        return self.store.list_messages(conversation_id, after_seq=after_seq, limit=limit)

    async def send_message(self, user: LanChatUser, conversation_id: str, text: str) -> LanChatMessage:
        config = self.config()
        if config["mode"] == "off":
            raise LanChatError(400, "lan_chat_disabled", "联机聊天未启用")
        if config["mode"] == "join":
            if not self._join_connected:
                raise LanChatError(503, "lan_chat_host_disconnected", "联机聊天主机未连接")
            return await self._host_request(
                "POST",
                f"/api/internal/lan-chat/node/conversations/{conversation_id}/messages",
                {
                    "sender": user.to_participant(online=True, last_seen_at=now_iso()),
                    "text": normalize_text(text),
                },
            )
        normalized = normalize_text(text)
        async with self._lock:
            sender = self.store.upsert_participant(user, online=True)
            self._assert_user_can_view_conversation(user.room_user_id, conversation_id)
            kind = "group" if conversation_id == LAN_CHAT_GROUP_ID else "dm"
            message = self.store.append_message(conversation_id, kind, sender, normalized)
        await self.broadcast_event({"type": "message_created", "message": message})
        return message

    def append_node_message(self, conversation_id: str, sender_payload: dict[str, Any], text: Any) -> LanChatMessage:
        config = self.config()
        if config["mode"] != "host":
            raise LanChatError(400, "lan_chat_not_host", "当前实例不是联机聊天主机")
        sender = self.register_remote_participant(sender_payload)
        kind = "group" if conversation_id == LAN_CHAT_GROUP_ID else "dm"
        if kind == "dm":
            self._assert_user_can_view_conversation(sender["room_user_id"], conversation_id)
        return self.store.append_message(conversation_id, kind, sender, normalize_text(text))

    def mark_read(self, user: LanChatUser, conversation_id: str, seq: int) -> dict[str, Any]:
        self._assert_user_can_view_conversation(user.room_user_id, conversation_id)
        result = self.store.mark_read(user.room_user_id, conversation_id, seq)
        return result

    def status_for_user(self, auth: AuthContext) -> dict[str, Any]:
        user = self.local_user(auth)
        self.store.upsert_participant(user, online=True)
        config = self.config()
        return {
            "mode": config["mode"],
            "connected": config["mode"] == "host" or self._join_connected,
            "room_name": config["room_name"],
            "self": self.store.upsert_participant(user, online=True),
            "online_users": self.list_participants(),
            "online_nodes": [{"instance_id": key, "connected": True} for key in self._node_sockets],
            "last_error": self._last_error,
        }

    def set_join_connected_for_test(self, connected: bool) -> None:
        self._join_connected = connected

    async def _host_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        config = self.config()
        host_url = str(config.get("host_url") or "").rstrip("/")
        room_key = str(config.get("room_key") or "")
        if not host_url or not room_key:
            raise LanChatError(400, "lan_chat_join_not_configured", "主机地址或房间密钥未配置")
        headers = {
            "Authorization": f"Bearer {room_key}",
            "X-Lan-Chat-Instance-Id": str(config["instance_id"]),
            "X-Lan-Chat-Instance-Name": str(config.get("instance_name") or "本机"),
        }
        async with ClientSession(headers=headers) as session:
            async with session.request(method, f"{host_url}{path}", json=payload) as response:
                data = await response.json()
                if response.status >= 400 or not data.get("ok", False):
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    raise LanChatError(
                        response.status,
                        str(error.get("code") or "lan_chat_host_error"),
                        str(error.get("message") or "主机请求失败"),
                    )
                return data.get("data")

    def add_browser_socket(self, ws: web.WebSocketResponse, room_user_id: str = "") -> None:
        self._browser_sockets[ws] = room_user_id

    def remove_browser_socket(self, ws: web.WebSocketResponse) -> str:
        room_user_id = self._browser_sockets.pop(ws, "")
        if not room_user_id:
            return ""
        if any(active_room_user_id == room_user_id for active_room_user_id in self._browser_sockets.values()):
            return ""
        self.store.set_participant_online(room_user_id, online=False)
        return room_user_id

    def add_node_socket(self, instance_id: str, ws: web.WebSocketResponse) -> None:
        self._node_sockets[instance_id] = ws

    def remove_node_socket(self, instance_id: str, ws: web.WebSocketResponse) -> None:
        if self._node_sockets.get(instance_id) is ws:
            self._node_sockets.pop(instance_id, None)

    async def broadcast_event(self, event: dict[str, Any]) -> None:
        stale_browsers: list[web.WebSocketResponse] = []
        for ws, room_user_id in list(self._browser_sockets.items()):
            if not self._should_send_event_to_room_user(event, room_user_id):
                continue
            try:
                await ws.send_json(event)
            except (ConnectionError, RuntimeError):
                stale_browsers.append(ws)
        for ws in stale_browsers:
            self.remove_browser_socket(ws)

        stale_nodes: list[str] = []
        for instance_id, ws in list(self._node_sockets.items()):
            if not self._should_send_event_to_node(event, instance_id):
                continue
            try:
                await ws.send_json(event)
            except (ConnectionError, RuntimeError):
                stale_nodes.append(instance_id)
        for instance_id in stale_nodes:
            self._node_sockets.pop(instance_id, None)

    async def close(self) -> None:
        sockets = [*self._browser_sockets.keys(), *self._node_sockets.values()]
        self._browser_sockets.clear()
        self._node_sockets.clear()
        for ws in sockets:
            await ws.close()

    def _assert_user_can_view_conversation(self, room_user_id: str, conversation_id: str) -> None:
        if conversation_id == LAN_CHAT_GROUP_ID:
            return
        if room_user_id in self.store.conversation_participant_ids(conversation_id):
            return
        raise LanChatError(403, "lan_chat_conversation_forbidden", "无权访问此私聊")

    def _should_send_event_to_room_user(self, event: dict[str, Any], room_user_id: str) -> bool:
        if event.get("type") != "message_created":
            return True
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        conversation_id = str(message.get("conversation_id") or "")
        if conversation_id == LAN_CHAT_GROUP_ID or not room_user_id:
            return True
        return room_user_id in self.store.conversation_participant_ids(conversation_id)

    def _should_send_event_to_node(self, event: dict[str, Any], instance_id: str) -> bool:
        if event.get("type") != "message_created":
            return True
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        conversation_id = str(message.get("conversation_id") or "")
        if conversation_id == LAN_CHAT_GROUP_ID:
            return True
        participant_ids = self.store.conversation_participant_ids(conversation_id)
        participants = {item["room_user_id"]: item for item in self.store.list_participants()}
        return any(participants.get(room_user_id, {}).get("instance_id") == instance_id for room_user_id in participant_ids)
