from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.web.api_common import AuthContext
from bot.web.lan_chat_service import LanChatService
from bot.web.lan_chat_store import LanChatStore


def auth(account_id: str, username: str) -> AuthContext:
    return AuthContext(
        user_id=1001,
        token_used=True,
        account_id=account_id,
        username=username,
        role="member",
        capabilities={"chat_send"},
        allowed_bot_aliases=set(),
        owned_bot_aliases=set(),
        is_local_admin=False,
    )


@pytest.mark.asyncio
async def test_host_service_sends_group_and_dm_messages(tmp_path: Path) -> None:
    service = LanChatService(repo_root=tmp_path)
    config = service.update_config(
        {
            "mode": "host",
            "room_name": "工作室",
            "instance_name": "主机",
            "room_key": "tcbr_secret",
        }
    )
    assert config["mode"] == "host"

    alice = service.local_user(auth("member_1", "alice"))
    bob = service.register_remote_participant(
        {
            "account_id": "member_2",
            "username": "bob",
            "display_name": "Bob",
            "instance_id": "inst_b",
            "instance_name": "B-PC",
        }
    )

    group_message = await service.send_message(alice, "group:default", "群消息")
    dm = service.ensure_dm(alice.room_user_id, bob["room_user_id"])
    dm_message = await service.send_message(alice, dm["id"], "私聊消息")

    assert group_message["text"] == "群消息"
    assert dm_message["conversation_id"] == dm["id"]
    assert any(item["id"] == dm["id"] for item in service.list_conversations(alice))
    assert not any(
        item["id"] == dm["id"] for item in service.list_conversations(service.local_user(auth("member_3", "carol")))
    )


@pytest.mark.asyncio
async def test_join_mode_rejects_send_when_not_connected(tmp_path: Path) -> None:
    service = LanChatService(repo_root=tmp_path)
    service.update_config(
        {
            "mode": "join",
            "room_name": "工作室",
            "instance_name": "从机",
            "host_url": "http://192.168.1.2:8765",
            "room_key": "tcbr_secret",
        }
    )
    with pytest.raises(Exception) as exc:
        await service.send_message(service.local_user(auth("member_1", "alice")), "group:default", "hi")
    assert "主机未连接" in str(exc.value)


@pytest.mark.asyncio
async def test_join_service_proxies_send_to_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = LanChatService(repo_root=tmp_path)
    service.update_config(
        {
            "mode": "join",
            "host_url": "http://192.168.1.2:8765",
            "room_key": "tcbr_secret",
            "instance_name": "从机",
        }
    )
    service.set_join_connected_for_test(True)
    proxied = {
        "id": "msg_1",
        "seq": 1,
        "conversation_id": "group:default",
        "kind": "group",
        "sender": service.store.upsert_participant(service.local_user(auth("member_1", "alice")), online=True),
        "text": "代理消息",
        "created_at": "2026-05-18T12:00:00+08:00",
    }
    request = AsyncMock(return_value=proxied)
    monkeypatch.setattr(service, "_host_request", request)

    message = await service.send_message(service.local_user(auth("member_1", "alice")), "group:default", "代理消息")

    assert message == proxied
    request.assert_awaited_once()


def test_browser_socket_disconnect_marks_user_offline_after_last_socket(tmp_path: Path) -> None:
    service = LanChatService(repo_root=tmp_path)
    service.update_config({"mode": "host", "room_key": "tcbr_secret"})
    alice = service.local_user(auth("member_1", "alice"))
    participant = service.store.upsert_participant(alice, online=True)
    first_socket = object()
    second_socket = object()

    service.add_browser_socket(first_socket, participant["room_user_id"])  # type: ignore[arg-type]
    service.add_browser_socket(second_socket, participant["room_user_id"])  # type: ignore[arg-type]

    service.remove_browser_socket(first_socket)  # type: ignore[arg-type]
    assert service.store.list_participants()[0]["online"] is True

    service.remove_browser_socket(second_socket)  # type: ignore[arg-type]
    assert service.store.list_participants()[0]["online"] is False


def test_service_start_clears_stale_online_participants(tmp_path: Path) -> None:
    store = LanChatStore(
        config_path=tmp_path / ".web_lan_chat.json",
        messages_path=tmp_path / ".web_lan_chat_messages.json",
    )
    store.upsert_participant(
        LanChatService(repo_root=tmp_path).local_user(auth("member_1", "alice")),
        online=True,
    )

    service = LanChatService(repo_root=tmp_path)

    assert service.store.list_participants()[0]["online"] is False
