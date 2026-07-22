from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_READ_FILE_CONTENT
from bot.web.server import WebApiServer


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def stop(self) -> dict[str, object]:
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


def _build_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: True)
    return server


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
async def test_code_navigation_route_uses_new_contract_and_requires_read_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = "def greet():\n    return None\n\ngreet()\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")
    server = _build_server(tmp_path, monkeypatch)
    body = {
        "kind": "definition",
        "requestId": "route-nav-1",
        "document": {
            "path": "main.py",
            "languageId": "python",
            "version": 3,
            "content": content,
        },
        "position": {"line": 4, "column": 2},
    }

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context())
            forbidden = await client.post("/api/bots/main/workspace/code-navigation/resolve", json=body)
            monkeypatch.setattr(
                server,
                "_auth_context",
                lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
            )
            allowed = await client.post("/api/bots/main/workspace/code-navigation/resolve", json=body)
            payload = await allowed.json()

    assert forbidden.status == 403
    assert allowed.status == 200, payload
    assert payload["data"]["request_id"] == "route-nav-1"
    assert payload["data"]["items"][0]["selection_range"]["start"] == {"line": 1, "column": 5}


@pytest.mark.asyncio
async def test_legacy_definition_route_adapts_to_semantic_resolver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = "def greet():\n    return None\n\ngreet()\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")
    server = _build_server(tmp_path, monkeypatch)
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/workspace/resolve-definition",
                json={"path": "main.py", "line": 4, "column": 2, "symbol": "greet"},
            )
            payload = await response.json()

    assert response.status == 200, payload
    assert payload["data"]["items"] == [
        {
            "path": "main.py",
            "line": 1,
            "column": 5,
            "match_kind": "same_file",
            "confidence": 1.0,
        }
    ]
