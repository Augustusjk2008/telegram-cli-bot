from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_MANAGE_BOTS, CAP_RUN_UNSAFE_CLI
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
            token="main_tok",
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
    with patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
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

    restored = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(manager.storage_file))
    assert restored.managed_profiles[alias].cli_params.get_param("codex", "yolo") is True
