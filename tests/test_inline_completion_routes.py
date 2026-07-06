from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_INLINE_COMPLETION, CAP_READ_FILE_CONTENT
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


class FakeInlineCompletionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "requestId": kwargs["request"]["requestId"],
            "model": "coder",
            "items": [{"insertText": "print('ok')", "displayText": "print('ok')"}],
            "latencyMs": 1,
            "context": {"relatedFiles": [], "truncated": False},
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


def _build_server(manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch) -> WebApiServer:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
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
async def test_admin_inline_completion_config_masks_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)
    monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_ADMIN_OPS))

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.patch(
                "/api/admin/inline-completion/config",
                json={
                    "enabled": True,
                    "base_url": "https://provider.test/v1",
                    "api_key": "sk-secret",
                    "model": "coder",
                },
            )
            payload = await response.json()
            get_response = await client.get("/api/admin/inline-completion/config")
            get_payload = await get_response.json()

    assert response.status == 200, payload
    assert get_response.status == 200, get_payload
    assert payload["data"]["api_key_set"] is True
    assert "api_key" not in payload["data"]
    assert "sk-secret" not in json.dumps(get_payload)


@pytest.mark.asyncio
async def test_inline_completion_workspace_route_requires_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)
    fake_service = FakeInlineCompletionService()
    server.inline_completion_service = fake_service
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)

    body = {
        "requestId": "req-1",
        "editorId": "editor-1",
        "path": "app.py",
        "languageId": "python",
        "cursor": {"line": 1, "column": 1, "offset": 0},
        "prefix": "",
        "suffix": "",
        "trigger": "manual",
    }

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context())
            forbidden = await client.post("/api/bots/main/workspace/inline-completion", json=body)
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_INLINE_COMPLETION))
            missing_read = await client.post("/api/bots/main/workspace/inline-completion", json=body)
            config_missing_read = await client.get("/api/bots/main/workspace/inline-completion/config")
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context(CAP_INLINE_COMPLETION, CAP_READ_FILE_CONTENT))
            config_allowed = await client.get("/api/bots/main/workspace/inline-completion/config")
            allowed = await client.post("/api/bots/main/workspace/inline-completion", json=body)
            payload = await allowed.json()

    assert forbidden.status == 403
    assert missing_read.status == 403
    assert config_missing_read.status == 403
    assert config_allowed.status == 200
    assert allowed.status == 200, payload
    assert payload["data"]["items"][0]["insertText"] == "print('ok')"
    assert fake_service.calls[0]["workspace_root"] == tmp_path
