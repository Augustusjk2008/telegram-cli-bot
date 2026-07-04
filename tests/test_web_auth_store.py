from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.web.auth_store import (
    CAPABILITIES_SCHEMA_VERSION,
    CAP_CHAT_SEND,
    CAP_MANAGE_BOTS,
    CAP_RUN_UNSAFE_CLI,
    CAP_TERMINAL_EXEC,
    MEMBER_CAPABILITIES,
    WebAuthStore,
)
from bot.web.permission_store import BotPermissionStore


def test_register_member_consumes_register_code(tmp_path: Path):
    users_path = tmp_path / ".web_users.json"
    codes_path = tmp_path / ".web_register_codes.json"
    codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )

    store = WebAuthStore(users_path=users_path, register_codes_path=codes_path)
    session = store.register_member("alice", "pw-123", "INVITE-001")

    assert session.account.username == "alice"
    users_text = users_path.read_text(encoding="utf-8")
    codes_text = codes_path.read_text(encoding="utf-8")
    assert '"alice"' not in users_text
    assert '"INVITE-001"' not in codes_text
    data = json.loads(codes_path.read_text(encoding="utf-8"))
    users_data = json.loads(users_text)
    assert isinstance(users_data["items"][0]["session_user_id"], int)
    assert users_data["items"][0]["capabilities_schema_version"] == CAPABILITIES_SCHEMA_VERSION
    assert set(users_data["items"][0]["capabilities"]) == set(MEMBER_CAPABILITIES)
    assert CAP_CHAT_SEND not in MEMBER_CAPABILITIES
    assert CAP_MANAGE_BOTS not in MEMBER_CAPABILITIES
    assert CAP_RUN_UNSAFE_CLI not in MEMBER_CAPABILITIES
    assert data["items"][0]["used_count"] == 1
    assert data["items"][0]["usage"][0]["used_by_enc"].startswith("v1:")


def test_legacy_member_capabilities_migrate_to_safe_schema_v2(tmp_path: Path):
    users_path = tmp_path / ".web_users.json"
    codes_path = tmp_path / ".web_register_codes.json"
    store = WebAuthStore(users_path=users_path, register_codes_path=codes_path)
    legacy_item = {
        "account_id": "member_legacy",
        "username": "alice",
        "role": "member",
        "disabled": False,
        "capabilities_schema_version": 1,
        "capabilities": [
            CAP_CHAT_SEND,
            CAP_MANAGE_BOTS,
            CAP_RUN_UNSAFE_CLI,
            CAP_TERMINAL_EXEC,
            *MEMBER_CAPABILITIES,
        ],
        "password_salt": "00" * 16,
        "password_hash": store._hash_password("pw-123", bytes.fromhex("00" * 16), 120_000),
        "password_iterations": 120_000,
    }
    users_path.write_text(json.dumps({"items": [legacy_item]}), encoding="utf-8")

    session = store.login_member("alice", "pw-123")
    data = json.loads(users_path.read_text(encoding="utf-8"))

    assert set(session.capabilities) == set(MEMBER_CAPABILITIES)
    assert data["items"][0]["capabilities_schema_version"] == CAPABILITIES_SCHEMA_VERSION
    assert set(data["items"][0]["capabilities"]) == set(MEMBER_CAPABILITIES)


def test_admin_capability_update_marks_legacy_account_schema_v2(tmp_path: Path):
    users_path = tmp_path / ".web_users.json"
    codes_path = tmp_path / ".web_register_codes.json"
    store = WebAuthStore(users_path=users_path, register_codes_path=codes_path)
    legacy_item = {
        "account_id": "member_legacy",
        "username": "alice",
        "role": "member",
        "disabled": False,
        "capabilities_schema_version": 1,
        "capabilities": [
            CAP_CHAT_SEND,
            CAP_MANAGE_BOTS,
            CAP_RUN_UNSAFE_CLI,
            CAP_TERMINAL_EXEC,
            *MEMBER_CAPABILITIES,
        ],
        "password_salt": "00" * 16,
        "password_hash": store._hash_password("pw-123", bytes.fromhex("00" * 16), 120_000),
        "password_iterations": 120_000,
    }
    users_path.write_text(json.dumps({"items": [legacy_item]}), encoding="utf-8")

    updated = store.update_member(
        "member_legacy",
        capabilities=[*MEMBER_CAPABILITIES, CAP_CHAT_SEND],
    )
    session = store.login_member("alice", "pw-123")
    data = json.loads(users_path.read_text(encoding="utf-8"))

    assert CAP_CHAT_SEND in updated["capabilities"]
    assert CAP_CHAT_SEND in session.capabilities
    assert data["items"][0]["capabilities_schema_version"] == CAPABILITIES_SCHEMA_VERSION


def test_guest_account_is_builtin_and_never_requires_register_code(tmp_path: Path):
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=tmp_path / ".web_register_codes.json",
    )

    session = store.create_guest_session()

    assert session.account.role == "guest"
    assert session.account.username == "guest"


def test_register_code_management_round_trip(tmp_path: Path):
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=tmp_path / ".web_register_codes.json",
    )

    created = store.create_register_code(created_by="127.0.0.1", max_uses=2)

    assert created["code"].startswith("INV-")
    assert created["max_uses"] == 2
    listed = store.list_register_codes()
    assert listed["items"][0]["code_preview"] == created["code_preview"]

    updated = store.update_register_code(created["code_id"], max_uses_delta=3, disabled=True)
    assert updated["max_uses"] == 5
    assert updated["disabled"] is True

    store.delete_register_code(created["code_id"])
    assert store.list_register_codes()["items"] == []


def test_permission_store_grants_allowed_bots(tmp_path: Path):
    store = BotPermissionStore(tmp_path / ".web_permissions.json")

    updated = store.set_allowed_bots("member_1", ["main", "team2"])

    assert updated["account_id"] == "member_1"
    assert updated["allowed_bots"] == ["main", "team2"]
    assert store.can_operate_bot("member_1", "main") is True
    assert store.can_operate_bot("member_1", "missing") is False


def test_permission_store_tracks_bot_owners_and_quota(tmp_path: Path):
    store = BotPermissionStore(tmp_path / ".web_permissions.json")

    for index in range(BotPermissionStore.MEMBER_BOT_LIMIT):
        store.set_bot_owner(f"bot-{index}", "member_1", grant_owner=True)

    expected_aliases = {f"bot-{index}" for index in range(BotPermissionStore.MEMBER_BOT_LIMIT)}
    assert store.owned_bot_aliases("member_1") == expected_aliases
    assert store.count_owned_bots("member_1") == BotPermissionStore.MEMBER_BOT_LIMIT
    assert store.allowed_bots_for_account("member_1") == expected_aliases
    with pytest.raises(ValueError, match=f"最多只能创建 {BotPermissionStore.MEMBER_BOT_LIMIT} 个 Bot"):
        store.assert_can_create_bot("member_1", is_local_admin=False)
    store.assert_can_create_bot("local-admin", is_local_admin=True)
