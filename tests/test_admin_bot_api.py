from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext, WebApiError, get_session_for_alias
from bot.web.api_service import list_bots, list_archived_bots
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_MANAGE_BOTS, CAP_MANAGE_REGISTER_CODES, CAP_RUN_UNSAFE_CLI, CAP_VIEW_BOTS
from bot.web.permission_store import BotPermissionStore
from bot.web.server import WebApiServer


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


def _build_manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )


def _build_server(
    manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> WebApiServer:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    return WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())


def _auth_context(*capabilities: str) -> AuthContext:
    return AuthContext(
        user_id=123,
        token_used=True,
        account_id="member-1",
        username="alice",
        capabilities=set(capabilities),
        is_local_admin=False,
    )


@pytest.mark.asyncio
async def test_admin_add_bot_rejects_bypass_without_unsafe_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch, tmp_path)

    async def manage_bots_only(_request, capability: str) -> AuthContext:
        assert capability == CAP_MANAGE_BOTS
        return _auth_context(CAP_MANAGE_BOTS)

    monkeypatch.setattr(server, "_with_capability", manage_bots_only)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/admin/bots",
                json={
                    "alias": "danger",
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(tmp_path),
                    "bypass_approval_and_sandbox": True,
                },
            )
            payload = await response.json()

    assert response.status == 403
    assert payload["error"]["code"] == "forbidden"
    assert "danger" not in manager.managed_profiles


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "extra_capability"),
    [
        ("bypass_approval_and_sandbox", CAP_RUN_UNSAFE_CLI),
        ("bypassApprovalAndSandbox", CAP_ADMIN_OPS),
    ],
)
async def test_admin_add_bot_persists_bypass_with_unsafe_or_admin_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field_name: str,
    extra_capability: str,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch, tmp_path)

    async def allowed(_request, capability: str) -> AuthContext:
        assert capability == CAP_MANAGE_BOTS
        return _auth_context(CAP_MANAGE_BOTS, extra_capability)

    monkeypatch.setattr(server, "_with_capability", allowed)
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda cli_path, _cwd=None: str(cli_path))

    alias = "unsafe" + extra_capability.replace("_", "")
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/admin/bots",
                json={
                    "alias": alias,
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(tmp_path),
                    field_name: True,
                },
            )
            payload = await response.json()

    assert response.status == 200
    assert payload["data"]["bot"]["alias"] == alias

    restored = MultiBotManager(BotProfile(alias="main"), str(manager.storage_file))
    assert restored.managed_profiles[alias].cli_params.get_param("codex", "yolo") is True


@pytest.mark.asyncio
async def test_bot_archive_persists_and_preserves_main_constraint(
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    manager.managed_profiles["worker"] = BotProfile(
        alias="worker",
        working_dir=str(tmp_path),
        enabled=True,
    )
    manager._save_profiles()

    await manager.archive_bot("worker")

    assert "worker" not in manager.managed_profiles
    summaries = list_bots(manager)
    assert [item["alias"] for item in summaries] == ["main"]
    assert list_archived_bots(manager)[0]["archived"] is True
    with pytest.raises(WebApiError):
        get_session_for_alias(manager, "worker", 123)

    restored = MultiBotManager(BotProfile(alias="main"), str(manager.storage_file))
    assert "worker" not in restored.managed_profiles
    assert restored.load_archived_profiles()["worker"].enabled is False
    restored._save_profiles()
    assert "worker" in restored.load_archived_profiles()

    with pytest.raises(ValueError, match="主 Bot"):
        await manager.archive_bot("main")

    loaded_archived = BotProfile.from_dict({"alias": "legacy", "enabled": True, "archived": True})
    assert loaded_archived.enabled is False

    await manager.unarchive_bot("worker")
    assert manager.managed_profiles["worker"].archived is False
    assert manager.managed_profiles["worker"].enabled is False


@pytest.mark.asyncio
async def test_admin_archive_routes_only_expose_archive_in_management(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    manager.managed_profiles["worker"] = BotProfile(alias="worker", working_dir=str(tmp_path))
    manager._save_profiles()
    server = _build_server(manager, monkeypatch, tmp_path)

    async def admin_auth(_request, capability: str) -> AuthContext:
        assert capability in {CAP_ADMIN_OPS, CAP_MANAGE_BOTS, CAP_VIEW_BOTS}
        return AuthContext(
            user_id=123,
            token_used=True,
            account_id="admin-1",
            username="admin",
            capabilities={CAP_ADMIN_OPS, CAP_MANAGE_BOTS, CAP_VIEW_BOTS},
            is_local_admin=True,
        )

    monkeypatch.setattr(server, "_with_capability", admin_auth)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            archive_response = await client.post("/api/admin/bots/worker/archive")
            archive_payload = await archive_response.json()
            main_list_response = await client.get("/api/bots")
            main_list_payload = await main_list_response.json()
            admin_list_response = await client.get("/api/admin/bots")
            admin_list_payload = await admin_list_response.json()
            unarchive_response = await client.post("/api/admin/bots/worker/unarchive")
            unarchive_payload = await unarchive_response.json()

    assert archive_response.status == 200, archive_payload
    assert archive_payload["data"]["bot"]["archived"] is True
    assert archive_payload["data"]["bot"]["enabled"] is False
    assert main_list_response.status == 200, main_list_payload
    assert [item["alias"] for item in main_list_payload["data"]] == ["main"]
    assert admin_list_response.status == 200, admin_list_payload
    worker = next(item for item in admin_list_payload["data"] if item["alias"] == "worker")
    assert worker["archived"] is True
    assert unarchive_response.status == 200, unarchive_payload
    assert unarchive_payload["data"]["bot"]["archived"] is False
    assert unarchive_payload["data"]["bot"]["enabled"] is False


@pytest.mark.asyncio
async def test_archive_unloads_sessions_preserves_bindings_and_reads_only_on_management(tmp_path, monkeypatch):
    from bot.sessions import get_bot_sessions

    manager = _build_manager(tmp_path)
    manager.managed_profiles["worker"] = BotProfile(alias="worker", working_dir=str(tmp_path))
    manager._save_profiles()
    session = get_session_for_alias(manager, "worker", 123)
    session.codex_session_id = "saved-session"
    await manager.archive_bot("worker")
    assert get_bot_sessions("worker") == []

    with monkeypatch.context() as scoped:
        scoped.setattr(manager, "load_archived_profiles", lambda: pytest.fail("ordinary lists must not read archives"))
        assert [item["alias"] for item in list_bots(manager, 123)] == ["main"]
    with monkeypatch.context() as scoped:
        scoped.setattr("bot.web.api_service.get_session_for_alias", lambda *args: pytest.fail("archive created a session"))
        scoped.setattr("bot.web.api_service.ChatStore", lambda *args: pytest.fail("archive opened chat runtime storage"))
        assert list_archived_bots(manager)[0]["working_dir"] == str(tmp_path)

    # Archived aliases remain reserved and survive updates to other profiles.
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda *args: "codex")
    with pytest.raises(ValueError, match="已存在"):
        await manager.add_bot("worker", working_dir=str(tmp_path))
    await manager.add_bot("other", working_dir=str(tmp_path))
    with pytest.raises(ValueError, match="已存在"):
        await manager.rename_bot("other", "worker")
    await manager.unarchive_bot("worker")
    assert get_session_for_alias(manager, "worker", 123).codex_session_id == "saved-session"
    await manager.archive_bot("worker")
    await manager.remove_bot("worker")
    assert manager.load_archived_profiles() == {}


@pytest.mark.asyncio
async def test_archive_rejects_busy_sessions_and_rolls_back_shutdown_failure(tmp_path, monkeypatch):
    manager = _build_manager(tmp_path)
    manager.managed_profiles["worker"] = BotProfile(alias="worker", working_dir=str(tmp_path))
    manager._save_profiles()
    session = get_session_for_alias(manager, "worker", 123)
    session.is_processing = True
    with pytest.raises(ValueError, match="任务运行中"):
        await manager.archive_bot("worker")
    assert manager.managed_profiles["worker"].enabled

    session.is_processing = False
    from bot.native_agent.service import get_native_agent_service
    service = get_native_agent_service()
    async def fail_close(alias):
        assert alias not in manager.managed_profiles
        with pytest.raises(WebApiError):
            get_session_for_alias(manager, alias, 123)
        raise RuntimeError("shutdown failed")
    monkeypatch.setattr(service, "close_bot_runtimes", fail_close)
    with pytest.raises(RuntimeError, match="shutdown failed"):
        await manager.archive_bot("worker")
    assert manager.managed_profiles["worker"].enabled
    assert not manager.managed_profiles["worker"].archived
    assert not manager.load_archived_profiles()

    monkeypatch.setattr(service, "close_bot_runtimes", AsyncMock())
    monkeypatch.setattr("bot.manager.save_managed_profiles", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        await manager.archive_bot("worker")
    assert manager.managed_profiles["worker"].enabled
    assert not manager.load_archived_profiles()


@pytest.mark.asyncio
async def test_archive_revokes_grants_blocks_direct_access_and_owner_can_restore(tmp_path, monkeypatch):
    import bot.web.server as server_module
    manager = _build_manager(tmp_path)
    manager.managed_profiles["worker"] = BotProfile(alias="worker", working_dir=str(tmp_path))
    manager._save_profiles()
    server = _build_server(manager, monkeypatch, tmp_path)
    permissions = server_module._BOT_PERMISSION_STORE
    permissions.set_bot_owner("worker", "member-1", grant_owner=True)
    permissions.grant_bot_to_account("member-2", "worker")
    monkeypatch.setattr(server, "_auth_context", lambda request: _auth_context(
        CAP_ADMIN_OPS, CAP_MANAGE_BOTS, CAP_VIEW_BOTS, CAP_MANAGE_REGISTER_CODES,
    ))
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.post("/api/admin/bots/worker/archive")
        assert response.status == 200, await response.text()
        assert not permissions.allowed_bots_for_account("member-1")
        assert not permissions.allowed_bots_for_account("member-2")
        assert permissions.bot_owner("worker") == "member-1"
        assert (await client.get("/api/bots/worker")).status == 403
        assert (await client.post("/api/admin/bots/worker/start")).status == 403
        assert (await client.patch("/api/admin/users/member-2/permissions", json={"allowed_bots": ["worker"]})).status == 400
        payload = await (await client.get("/api/admin/bots")).json()
        assert [item["alias"] for item in payload["data"]] == ["worker"]
        assert payload["data"][0]["can_operate"] is False
        response = await client.post("/api/admin/bots/worker/unarchive")
        assert response.status == 200, await response.text()
        assert permissions.allowed_bots_for_account("member-1") == {"worker"}
        assert not permissions.allowed_bots_for_account("member-2")


@pytest.mark.asyncio
async def test_legacy_archive_stays_cold_and_keeps_unknown_disk_fields(tmp_path):
    manager = _build_manager(tmp_path)
    manager.storage_file.write_text(json.dumps({"bots": [{
        "alias": "old", "enabled": True, "archived": True, "future_field": {"value": 1},
    }]}), encoding="utf-8")
    manager._load_profiles()
    assert manager.managed_profiles == {}
    manager._save_profiles()
    saved = json.loads(manager.storage_file.read_text(encoding="utf-8"))["bots"][0]
    assert saved["future_field"] == {"value": 1}
    await manager.unarchive_bot("old")
    assert manager.managed_profiles["old"].enabled is False
