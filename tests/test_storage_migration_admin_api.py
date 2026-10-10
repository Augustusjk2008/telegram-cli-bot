from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.routes import admin_routes
from bot.web.server import WebApiServer
from bot.web.storage_migration_api import StorageMigrationApi, StorageMigrationApiError


class FakeStorageMigrationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def snapshot(self) -> dict[str, object]:
        return {
            "state": "completed",
            "current_root": "C:/old",
            "sources": [{"id": "history", "label": "聊天历史", "path": "C:/history", "exists": True, "size_bytes": 12}],
            "total_bytes": 12,
        }

    def preview(self, target: str) -> dict[str, object]:
        self.calls.append(("preview", target))
        return {
            "plan_id": "plan-1",
            "target_root": target,
            "state": "verifying",
            "sources": [{"id": "history", "size_bytes": 12}],
            "total_bytes": 12,
        }

    def begin(self, plan_id: str) -> dict[str, object]:
        self.calls.append(("begin", plan_id))
        return {"plan_id": plan_id, "state": "copying", "progress": 0.1}

    def execute(self, plan_id: str) -> dict[str, object]:
        self.calls.append(("execute", plan_id))
        return {"plan_id": plan_id, "state": "verifying", "progress": 0.9}

    def finalize(self, plan_id: str) -> dict[str, object]:
        self.calls.append(("finalize", plan_id))
        return {"plan_id": plan_id, "state": "completed", "progress": 1}

    def retry_cleanup(self) -> dict[str, object]:
        self.calls.append(("retry_cleanup", ""))
        return {"state": "completed"}


async def _wait_for_preview(api: StorageMigrationApi) -> dict[str, object]:
    for _ in range(20):
        status = await api.snapshot()
        if status.get("planId"):
            return status
        await asyncio.sleep(0)
    raise AssertionError("preview did not complete")


@pytest.mark.asyncio
async def test_preview_binds_server_side_plan_and_migration_stops_all_agents() -> None:
    service = FakeStorageMigrationService()
    stop_all_agents = AsyncMock(return_value={"ready": True})
    api = StorageMigrationApi(service, stop_all_agents=stop_all_agents)

    preview = await api.preview("C:/new")
    assert preview["jobId"]
    assert "planId" not in preview
    preview_status = await _wait_for_preview(api)
    assert preview_status["planId"] == "plan-1"

    status = await api.begin("plan-1", confirm_stop_all_agents=True)
    assert status["state"] == "copying"
    await asyncio.wait_for(api._task, timeout=1)  # type: ignore[arg-type]

    assert stop_all_agents.await_count == 1
    assert service.calls == [
        ("preview", "C:/new"),
        ("begin", "plan-1"),
        ("execute", "plan-1"),
        ("finalize", "plan-1"),
    ]
    assert (await api.snapshot())["state"] == "completed"


@pytest.mark.asyncio
async def test_preview_returns_job_immediately_and_exposes_live_progress() -> None:
    class DelayedStorageMigrationService:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def preview(self, _target: str) -> dict[str, object]:
            self.started.set()
            await self.release.wait()
            return {
                "id": "plan-live",
                "state": "preparing",
                "previewReady": True,
                "totalBytes": 100,
                "completedBytes": 100,
                "totalFiles": 2,
                "completedFiles": 2,
            }

        async def status(self) -> dict[str, object]:
            return {
                "state": "preparing",
                "phase": "preparing",
                "completedBytes": 40,
                "totalBytes": 100,
                "completedFiles": 1,
                "totalFiles": 2,
                "currentItem": "chat-history/chat.sqlite",
                "message": "正在计算文件校验",
            }

        def snapshot(self) -> dict[str, object]:
            return {
                "state": "preparing",
                "totalBytes": 100,
                "completedBytes": 100,
                "totalFiles": 2,
                "completedFiles": 2,
            }

    service = DelayedStorageMigrationService()
    api = StorageMigrationApi(service)
    initial = await api.preview("C:/new")
    assert initial["jobId"]
    assert "planId" not in initial

    await service.started.wait()
    progress = await api.snapshot()
    assert progress["jobId"] == initial["jobId"]
    assert progress["completedBytes"] == 40
    assert progress["currentItem"] == "chat-history/chat.sqlite"

    service.release.set()
    ready = await _wait_for_preview(api)
    assert ready["planId"] == "plan-live"


@pytest.mark.asyncio
async def test_migration_rejects_unknown_plan_and_unready_stop_hook() -> None:
    service = FakeStorageMigrationService()
    api = StorageMigrationApi(service, stop_all_agents=AsyncMock(return_value=False))
    await api.preview("C:/new")
    await _wait_for_preview(api)

    with pytest.raises(StorageMigrationApiError) as unknown:
        await api.begin("other", confirm_stop_all_agents=True)
    assert unknown.value.status == 409
    assert unknown.value.code == "storage_migration_plan_invalid"

    with pytest.raises(StorageMigrationApiError) as unready:
        await api.begin("plan-1", confirm_stop_all_agents=True)
    assert unready.value.status == 409
    assert unready.value.code == "agent_stop_not_ready"
    assert unready.value.data["state"] == "stopping"


def test_admin_routes_register_storage_endpoints() -> None:
    server = SimpleNamespace(
        admin_bots=AsyncMock(),
        admin_cli_error_stats=AsyncMock(),
        admin_processing=AsyncMock(),
        admin_add_bot=AsyncMock(),
        admin_single_bot=AsyncMock(),
        admin_remove_bot=AsyncMock(),
        admin_start_bot=AsyncMock(),
        admin_stop_bot=AsyncMock(),
        admin_archive_bot=AsyncMock(),
        admin_unarchive_bot=AsyncMock(),
        admin_update_cli=AsyncMock(),
        admin_update_execution=AsyncMock(),
        admin_rename_bot=AsyncMock(),
        admin_update_workdir=AsyncMock(),
        admin_update_prompt_presets=AsyncMock(),
        admin_update_global_prompt_presets=AsyncMock(),
        admin_get_update=AsyncMock(),
        admin_patch_update=AsyncMock(),
        admin_update_check=AsyncMock(),
        admin_update_download=AsyncMock(),
        admin_update_download_stream=AsyncMock(),
        admin_update_offline_packages=AsyncMock(),
        admin_update_offline_prepare=AsyncMock(),
        admin_update_offline_prepare_stream=AsyncMock(),
        admin_env_get=AsyncMock(),
        admin_inline_completion_config_get=AsyncMock(),
        admin_inline_completion_config_patch=AsyncMock(),
        admin_native_agent_config_get=AsyncMock(),
        admin_native_agent_preflight_get=AsyncMock(),
        admin_native_agent_config_patch=AsyncMock(),
        admin_language_server_install=AsyncMock(),
        admin_language_server_update=AsyncMock(),
        admin_language_servers_redetect=AsyncMock(),
        admin_runtime_diagnostics=AsyncMock(),
        admin_env_patch=AsyncMock(),
        admin_env_reload_preview=AsyncMock(),
        admin_env_reload=AsyncMock(),
        admin_env_reload_system=AsyncMock(),
        admin_restart=AsyncMock(),
        admin_tunnel=AsyncMock(),
        admin_tunnel_start=AsyncMock(),
        admin_tunnel_stop=AsyncMock(),
        admin_tunnel_restart=AsyncMock(),
        admin_storage=AsyncMock(),
        admin_storage_preview=AsyncMock(),
        admin_storage_migrate=AsyncMock(),
        admin_storage_cleanup_retry=AsyncMock(),
    )
    app = web.Application()
    admin_routes.register(app, server)
    paths = {route.resource.canonical for route in app.router.routes()}
    assert {
        "/api/admin/storage",
        "/api/admin/storage/preview",
        "/api/admin/storage/migrate",
        "/api/admin/storage/cleanup/retry",
    } <= paths


@pytest.mark.asyncio
async def test_storage_handlers_require_admin_and_ignore_client_source_list() -> None:
    service = FakeStorageMigrationService()
    server = WebApiServer(SimpleNamespace(), storage_migration_service=service, storage_migration_stop_all_agents=AsyncMock(return_value=True))
    server._with_capability = AsyncMock(return_value=AuthContext(user_id=1, token_used=True, capabilities={CAP_ADMIN_OPS}))  # type: ignore[method-assign]
    server._parse_json = AsyncMock(return_value={"targetRoot": "C:/new", "sources": ["C:/attacker"]})  # type: ignore[method-assign]
    request = make_mocked_request("POST", "/api/admin/storage/preview")

    response = await server.admin_storage_preview(request)
    assert response.status == 202
    assert service.calls == []
    await asyncio.sleep(0)
    assert service.calls == [("preview", "C:/new")]
    server._with_capability.assert_awaited_once_with(request, CAP_ADMIN_OPS)

    server._parse_json.return_value = {"planId": "plan-1", "confirmStopAllAgents": False}
    with pytest.raises(WebApiError) as caught:
        await server.admin_storage_migrate(request)
    assert caught.value.status == 409
    assert caught.value.code == "confirm_stop_all_agents_required"
