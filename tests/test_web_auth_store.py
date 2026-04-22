from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.web.auth_store import AuthStoreError, WebAuthStore


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
    assert data["items"][0]["used_count"] == 1
    assert data["items"][0]["usage"][0]["used_by_enc"].startswith("v1:")


def test_guest_account_is_builtin_and_never_requires_register_code(tmp_path: Path):
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=tmp_path / ".web_register_codes.json",
    )

    session = store.create_guest_session()

    assert session.account.role == "guest"
    assert session.account.username == "guest"


def test_login_rejects_wrong_password(tmp_path: Path):
    codes_path = tmp_path / ".web_register_codes.json"
    codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=codes_path,
    )
    store.register_member("alice", "pw-123", "INVITE-001")

    with pytest.raises(AuthStoreError) as exc_info:
        store.login_member("alice", "wrong-1")

    assert exc_info.value.code == "invalid_credentials"


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
