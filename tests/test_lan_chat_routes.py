from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.server import WebApiServer


@pytest.fixture
def lan_chat_manager(tmp_path: Path) -> MultiBotManager:
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text('{"bots":[]}', encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(tmp_path),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


@pytest.mark.asyncio
async def test_lan_chat_admin_config_and_group_message(
    lan_chat_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server._REPO_ROOT", Path(lan_chat_manager.main_profile.working_dir))
    server = WebApiServer(lan_chat_manager)
    app = server._build_app()
    async with TestClient(TestServer(app)) as client:
        patch_resp = await client.patch(
            "/api/admin/lan-chat/config",
            json={
                "mode": "host",
                "room_name": "工作室",
                "instance_name": "主机",
                "room_key": "tcbr_secret",
            },
        )
        assert patch_resp.status == 200
        assert (await patch_resp.json())["data"]["mode"] == "host"

        send_resp = await client.post("/api/lan-chat/conversations/group:default/messages", json={"text": "大家好"})
        assert send_resp.status == 200
        sent = (await send_resp.json())["data"]
        assert sent["text"] == "大家好"

        list_resp = await client.get("/api/lan-chat/conversations")
        conversations = (await list_resp.json())["data"]["items"]
        assert conversations[0]["id"] == "group:default"


@pytest.mark.asyncio
async def test_lan_chat_private_conversation_route(
    lan_chat_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.server._REPO_ROOT", Path(lan_chat_manager.main_profile.working_dir))
    server = WebApiServer(lan_chat_manager)
    service = server.lan_chat_service
    service.update_config({"mode": "host", "room_key": "tcbr_secret"})
    remote = service.register_remote_participant(
        {
            "account_id": "member_2",
            "username": "bob",
            "display_name": "Bob",
            "instance_id": "inst_b",
            "instance_name": "B-PC",
        }
    )
    app = server._build_app()
    async with TestClient(TestServer(app)) as client:
        dm_resp = await client.post(
            "/api/lan-chat/private-conversations",
            json={"target_room_user_id": remote["room_user_id"]},
        )
        assert dm_resp.status == 200
        conversation = (await dm_resp.json())["data"]
        assert conversation["kind"] == "dm"

        send_resp = await client.post(
            f"/api/lan-chat/conversations/{conversation['id']}/messages",
            json={"text": "私聊"},
        )
        assert send_resp.status == 200
        assert (await send_resp.json())["data"]["text"] == "私聊"
