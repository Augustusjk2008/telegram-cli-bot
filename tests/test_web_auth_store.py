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
    data = json.loads(codes_path.read_text(encoding="utf-8"))
    assert data["items"][0]["used_by"] == "alice"


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
        store.login_member("alice", "wrong")

    assert exc_info.value.code == "invalid_credentials"
