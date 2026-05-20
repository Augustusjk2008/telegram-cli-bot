from datetime import timezone
from pathlib import Path

from bot.web.lan_chat_store import LanChatStore
from bot.web import lan_chat_types
from bot.web.lan_chat_types import LAN_CHAT_GROUP_ID, LanChatUser, dm_conversation_id, room_user_id


def test_lan_chat_ids_are_stable() -> None:
    assert LAN_CHAT_GROUP_ID == "group:default"
    assert room_user_id("inst_a", "member_1") == "inst_a:member_1"
    left = dm_conversation_id("inst_b:member_2", "inst_a:member_1")
    right = dm_conversation_id("inst_a:member_1", "inst_b:member_2")
    assert left == right
    assert left.startswith("dm:")
    assert len(left) == len("dm:") + 16


def test_lan_chat_timezone_falls_back_to_china_offset_without_tzdb(monkeypatch) -> None:
    class MissingZoneInfo:
        def __init__(self, _key: str) -> None:
            raise lan_chat_types.ZoneInfoNotFoundError("missing tzdb")

    monkeypatch.setattr(lan_chat_types, "ZoneInfo", MissingZoneInfo)

    tz = lan_chat_types._load_lan_chat_timezone()

    assert tz.utcoffset(None).total_seconds() == 8 * 3600
    assert tz.tzname(None) == "Asia/Shanghai"
    assert tz is not timezone.utc


def test_lan_chat_store_creates_group_and_messages(tmp_path: Path) -> None:
    store = LanChatStore(
        config_path=tmp_path / ".web_lan_chat.json",
        messages_path=tmp_path / ".web_lan_chat_messages.json",
    )
    config = store.load_config()
    assert config["mode"] == "off"
    assert config["instance_id"].startswith("inst_")

    user = LanChatUser(
        account_id="member_1",
        username="alice",
        display_name="Alice",
        instance_id=config["instance_id"],
        instance_name="A-PC",
    )
    participant = store.upsert_participant(user, online=True)
    message = store.append_message(
        conversation_id=LAN_CHAT_GROUP_ID,
        kind="group",
        sender=participant,
        text="你好",
    )

    assert message["seq"] == 1
    assert message["conversation_id"] == LAN_CHAT_GROUP_ID
    assert store.list_messages(LAN_CHAT_GROUP_ID, after_seq=0, limit=20)[0]["text"] == "你好"
    assert store.list_conversations_for_user(user.room_user_id)[0]["id"] == LAN_CHAT_GROUP_ID


def test_lan_chat_store_private_conversation_visibility(tmp_path: Path) -> None:
    store = LanChatStore(
        config_path=tmp_path / ".web_lan_chat.json",
        messages_path=tmp_path / ".web_lan_chat_messages.json",
    )
    alice = LanChatUser("member_1", "alice", "Alice", "inst_a", "A-PC")
    bob = LanChatUser("member_2", "bob", "Bob", "inst_b", "B-PC")
    carol = LanChatUser("member_3", "carol", "Carol", "inst_c", "C-PC")
    alice_participant = store.upsert_participant(alice, online=True)
    store.upsert_participant(bob, online=True)
    store.upsert_participant(carol, online=True)

    conversation = store.ensure_dm_conversation(alice.room_user_id, bob.room_user_id)
    store.append_message(conversation["id"], "dm", alice_participant, "私聊内容")

    alice_conversations = {item["id"] for item in store.list_conversations_for_user(alice.room_user_id)}
    bob_conversations = {item["id"] for item in store.list_conversations_for_user(bob.room_user_id)}
    carol_conversations = {item["id"] for item in store.list_conversations_for_user(carol.room_user_id)}

    assert conversation["id"] in alice_conversations
    assert conversation["id"] in bob_conversations
    assert conversation["id"] not in carol_conversations
