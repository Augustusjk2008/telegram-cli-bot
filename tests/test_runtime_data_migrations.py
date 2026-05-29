from __future__ import annotations

import json
from pathlib import Path

from bot.migrations.runner import MIGRATION_REPO_STATE_TO_USER_HOME, run_pending_migrations
from bot.web.auth_store import WebAuthStore


def test_repo_state_migration_moves_legacy_files_to_user_data_dir(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))

    secret = WebAuthStore(
        users_path=repo_root / ".web_users.json",
        register_codes_path=repo_root / ".web_register_codes.json",
        secret_path=repo_root / ".web_auth_secret.json",
    )
    (repo_root / ".web_register_codes.json").write_text(
        json.dumps(
            {
                "items": [
                    {"code": "INVITE-001", "disabled": False},
                    {"code": "INVITE-USED", "disabled": False, "created_by": "admin", "used_by": "alice"},
                ]
            }
        ),
        encoding="utf-8",
    )
    legacy_session = secret.register_member("alice", "pw-123", "INVITE-001")
    (repo_root / ".web_permissions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "users": {legacy_session.account.account_id: {"allowed_bots": ["main"], "updated_at": "t1"}},
                "bots": {"main": {"owner_account_id": legacy_session.account.account_id}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (repo_root / ".web_admin_settings.json").write_text(json.dumps({"update_channel": "beta"}), encoding="utf-8")
    (repo_root / ".session_store.json").write_text(json.dumps({"1:2": {"codex_session_id": "s1"}}), encoding="utf-8")
    (repo_root / ".web_announcements.json").write_text(
        json.dumps({"version": 1, "items": [], "reads": {"member": {"last_seen_id": "ann-1"}}}),
        encoding="utf-8",
    )
    (repo_root / ".web_lan_chat.json").write_text(json.dumps({"mode": "host"}), encoding="utf-8")
    (repo_root / ".web_lan_chat_messages.json").write_text(json.dumps({"messages": [{"text": "hi"}]}), encoding="utf-8")
    (repo_root / ".web_tunnel_state.json").write_text(json.dumps({"public_url": "https://old.example"}), encoding="utf-8")

    result = run_pending_migrations(repo_root=repo_root)

    assert result.completed == [MIGRATION_REPO_STATE_TO_USER_HOME]
    assert (data_root / "auth" / "secret.json").exists()
    assert (data_root / "auth" / "accounts" / f"{legacy_session.account.account_id}.json").exists()
    assert (data_root / "auth" / "username_index.json").exists()
    assert (data_root / "auth" / "register_codes.json").exists()
    assert (data_root / "permissions" / "accounts" / f"{legacy_session.account.account_id}.json").exists()
    assert (data_root / "permissions" / "bots.json").exists()
    assert json.loads((data_root / "config" / "app_settings.json").read_text(encoding="utf-8"))["update_channel"] == "beta"
    assert json.loads((data_root / "sessions" / "session_store.json").read_text(encoding="utf-8"))["1:2"]["codex_session_id"] == "s1"
    assert json.loads((data_root / "announcements" / "reads.json").read_text(encoding="utf-8"))["reads"]["member"]["last_seen_id"] == "ann-1"
    assert json.loads((data_root / "lan_chat" / "config.json").read_text(encoding="utf-8"))["mode"] == "host"
    assert json.loads((data_root / "lan_chat" / "messages.json").read_text(encoding="utf-8"))["messages"][0]["text"] == "hi"
    assert json.loads((data_root / "tunnel" / "state.json").read_text(encoding="utf-8"))["public_url"] == "https://old.example"
    assert (repo_root / ".migrated-to-tcb.json").exists()
    assert (data_root / "migrations" / "state.json").exists()

    users_text = "".join(path.read_text(encoding="utf-8") for path in (data_root / "auth" / "accounts").glob("*.json"))
    codes_text = (data_root / "auth" / "register_codes.json").read_text(encoding="utf-8")
    assert '"alice"' not in users_text
    assert "INVITE-001" not in codes_text
    assert "INVITE-USED" not in codes_text
    assert "admin" not in codes_text
    assert "alice" not in codes_text
    assert '"used_by"' not in codes_text
    assert '"created_by"' not in codes_text


def test_migrated_auth_store_can_login_and_register_with_preserved_secret(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    codes_path = repo_root / ".web_register_codes.json"
    codes_path.write_text(
        json.dumps(
            {
                "items": [
                    {"code": "INVITE-001", "disabled": False},
                    {"code": "INVITE-002", "disabled": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    legacy_store = WebAuthStore(
        users_path=repo_root / ".web_users.json",
        register_codes_path=codes_path,
        secret_path=repo_root / ".web_auth_secret.json",
    )
    legacy_store.register_member("alice", "pw-123", "INVITE-001")
    legacy_users_before = (repo_root / ".web_users.json").read_text(encoding="utf-8")
    legacy_codes_before = (repo_root / ".web_register_codes.json").read_text(encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)
    migrated_store = WebAuthStore(
        users_path=data_root / "auth" / "accounts",
        register_codes_path=data_root / "auth" / "register_codes.json",
        secret_path=data_root / "auth" / "secret.json",
    )

    login = migrated_store.login_member("alice", "pw-123")
    register = migrated_store.register_member("bob", "pw-456", "INVITE-002")

    assert login.account.username == "alice"
    assert register.account.username == "bob"
    assert [item["username"] for item in migrated_store.list_members()["items"]] == ["alice", "bob"]
    assert (repo_root / ".web_users.json").read_text(encoding="utf-8") == legacy_users_before
    assert (repo_root / ".web_register_codes.json").read_text(encoding="utf-8") == legacy_codes_before


def test_repo_state_migration_is_idempotent_and_does_not_overwrite_new_data(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    (repo_root / ".session_store.json").write_text(json.dumps({"1:2": {"codex_session_id": "legacy"}}), encoding="utf-8")
    target = data_root / "sessions" / "session_store.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"1:2": {"codex_session_id": "new"}}), encoding="utf-8")

    first = run_pending_migrations(repo_root=repo_root)
    second = run_pending_migrations(repo_root=repo_root)

    assert first.completed == [MIGRATION_REPO_STATE_TO_USER_HOME]
    assert second.completed == []
    assert json.loads(target.read_text(encoding="utf-8"))["1:2"]["codex_session_id"] == "new"


def test_repo_state_migration_repairs_polluted_main_settings_from_legacy(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))

    legacy_settings = {
        "main_bot_profile": {
            "cli_type": "codex",
            "cli_path": "codex",
            "working_dir": str(repo_root),
            "cli_params": {"codex": {"model": "gpt-5.5"}},
            "agents": [{"id": "backend-owner", "name": "后端"}],
        }
    }
    polluted_settings = {
        "main_bot_profile": {
            "cli_type": "claude",
            "cli_path": "claude",
            "working_dir": str(tmp_path / "pytest-of-user" / "test_main_bot_workdir_persists0" / "new"),
            "cli_params": {"codex": {"model": None}},
            "agents": [{"id": "tester", "name": "测试"}],
        }
    }
    (repo_root / ".web_admin_settings.json").write_text(json.dumps(legacy_settings), encoding="utf-8")
    target = data_root / "config" / "app_settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(polluted_settings), encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)

    migrated = json.loads(target.read_text(encoding="utf-8"))
    main = migrated["main_bot_profile"]
    assert main["cli_type"] == "codex"
    assert main["working_dir"] == str(repo_root)
    assert main["cli_params"]["codex"]["model"] == "gpt-5.5"
    assert [item["id"] for item in main["agents"]] == ["backend-owner"]


def test_repo_state_migration_repairs_empty_permission_bots_from_legacy(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    (repo_root / ".web_permissions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "users": {"member_1": {"allowed_bots": ["main"]}},
                "bots": {"team2": {"owner_account_id": "member_1"}},
            }
        ),
        encoding="utf-8",
    )
    target = data_root / "permissions" / "bots.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"version": 1, "bots": {}}), encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)

    repaired = json.loads(target.read_text(encoding="utf-8"))
    assert repaired["bots"]["team2"]["owner_account_id"] == "member_1"


def test_repo_state_migration_repairs_empty_lan_messages_from_legacy(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    legacy_messages = {
        "next_seq": 2,
        "participants": {},
        "conversations": {"group:default": {"id": "group:default", "kind": "group"}},
        "messages": [{"id": "msg_1", "seq": 1, "conversation_id": "group:default", "text": "hi"}],
        "reads": {},
    }
    (repo_root / ".web_lan_chat_messages.json").write_text(json.dumps(legacy_messages), encoding="utf-8")
    target = data_root / "lan_chat" / "messages.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"next_seq": 1, "participants": {}, "conversations": {}, "messages": [], "reads": {}}), encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)

    repaired = json.loads(target.read_text(encoding="utf-8"))
    assert repaired["messages"][0]["text"] == "hi"
    assert repaired["next_seq"] == 2


def test_repo_state_migration_does_not_repair_user_cleared_permission_bots_twice(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    (repo_root / ".web_permissions.json").write_text(
        json.dumps({"version": 1, "users": {}, "bots": {"team2": {"owner_account_id": "member_1"}}}),
        encoding="utf-8",
    )
    target = data_root / "permissions" / "bots.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"version": 1, "bots": {}}), encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)
    target.write_text(json.dumps({"version": 1, "bots": {}}), encoding="utf-8")
    run_pending_migrations(repo_root=repo_root)

    assert json.loads(target.read_text(encoding="utf-8"))["bots"] == {}


def test_repo_state_migration_respects_absolute_tunnel_env_override(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    explicit_state = tmp_path / "external" / "tunnel.json"
    repo_root.mkdir()
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    monkeypatch.setenv("WEB_TUNNEL_STATE_FILE", str(explicit_state))
    (repo_root / ".web_tunnel_state.json").write_text(json.dumps({"public_url": "https://old.example"}), encoding="utf-8")

    run_pending_migrations(repo_root=repo_root)

    assert not (data_root / "tunnel" / "state.json").exists()
