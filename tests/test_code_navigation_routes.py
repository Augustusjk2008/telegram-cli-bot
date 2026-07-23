from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.language_server.manager import LanguageServerUnavailableError
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


class FakeLanguageServerRuntimeManager:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []
        self.prewarm_calls: list[dict[str, object]] = []
        self.cancel_calls: list[dict[str, object]] = []
        self.shutdown_calls = 0

    async def resolve_code_navigation(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.result

    def diagnostics(self) -> dict[str, object]:
        return {"runtime_count": 0, "provider_counts": {}}

    async def prewarm(self, **kwargs) -> bool:
        self.prewarm_calls.append(kwargs)
        return True

    async def cancel_code_navigation(self, **kwargs) -> bool:
        self.cancel_calls.append(kwargs)
        return True

    def runtime_status(self, **_kwargs) -> dict[str, object]:
        return {
            "state": "ready",
            "pending_count": 0,
            "open_document_count": 0,
            "implementation_supported": False,
        }

    async def shutdown(self) -> dict[str, int]:
        self.shutdown_calls += 1
        return {"requested": 0, "closed": 0, "failed": 0}


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


@pytest.mark.asyncio
async def test_code_navigation_route_uses_isolated_language_server_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = "from helper import greet\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")
    manager = FakeLanguageServerRuntimeManager(
        {
            "request_id": "route-lsp-1",
            "items": [{"provider": "pyright", "path": "helper.py"}],
            "message": "",
        }
    )
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )
    body = {
        "kind": "definition",
        "requestId": "route-lsp-1",
        "document": {
            "path": "main.py",
            "languageId": "python",
            "version": 9,
            "content": content,
        },
        "position": {"line": 1, "column": 20},
    }

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post("/api/bots/main/workspace/code-navigation/resolve", json=body)
            payload = await response.json()

    assert response.status == 200, payload
    assert payload["data"]["items"] == [{"provider": "pyright", "path": "helper.py"}]
    assert manager.calls == [
        {
            "bot_alias": "main",
            "user_id": server._chat_user_id(_auth_context(CAP_READ_FILE_CONTENT)),
            "workspace_root": str(tmp_path),
            "request": body,
        }
    ]


@pytest.mark.asyncio
async def test_code_navigation_cancel_route_requires_read_capability_and_preserves_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = FakeLanguageServerRuntimeManager(
        {"request_id": "unused", "items": [], "message": ""}
    )
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            monkeypatch.setattr(server, "_auth_context", lambda _request: _auth_context())
            forbidden = await client.post(
                "/api/bots/main/workspace/code-navigation/cancel",
                json={"requestId": "route-nav-1"},
            )
            monkeypatch.setattr(
                server,
                "_auth_context",
                lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
            )
            allowed = await client.post(
                "/api/bots/main/workspace/code-navigation/cancel",
                json={"requestId": "route-nav-1"},
            )
            payload = await allowed.json()

    assert forbidden.status == 403
    assert allowed.status == 200, payload
    assert payload["data"] == {"cancelled": True}
    assert manager.cancel_calls == [
        {
            "bot_alias": "main",
            "user_id": server._chat_user_id(_auth_context(CAP_READ_FILE_CONTENT)),
            "workspace_root": str(tmp_path),
            "request_id": "route-nav-1",
        }
    ]


@pytest.mark.asyncio
async def test_legacy_definition_route_uses_language_server_definition_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = "from helper import greet\n"
    (tmp_path / "main.py").write_text(content, encoding="utf-8")
    manager = FakeLanguageServerRuntimeManager(
        {
            "request_id": "legacy-definition",
            "items": [
                {
                    "target_type": "workspace",
                    "path": "helper.py",
                    "provider": "pyright",
                    "range": {
                        "start": {"line": 3, "column": 1},
                        "end": {"line": 4, "column": 1},
                    },
                    "selection_range": {
                        "start": {"line": 3, "column": 5},
                        "end": {"line": 3, "column": 10},
                    },
                }
            ],
            "message": "",
        }
    )
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
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
                json={"path": "main.py", "line": 1, "column": 20, "symbol": "greet"},
            )
            payload = await response.json()

    assert response.status == 200, payload
    assert payload["data"]["items"] == [
        {
            "path": "helper.py",
            "line": 3,
            "column": 5,
            "match_kind": "import",
            "confidence": 1.0,
        }
    ]
    assert manager.calls[0]["request"]["kind"] == "definition"
    assert manager.calls[0]["request"]["requestId"] == "legacy-definition"
    assert manager.calls[0]["request"]["document"]["content"] == content


@pytest.mark.asyncio
async def test_workspace_language_server_status_prewarms_selected_python_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = FakeLanguageServerRuntimeManager({"request_id": "unused", "items": [], "message": ""})
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )
    monkeypatch.setattr(
        server.language_server_catalog,
        "api_snapshot",
        lambda: {
            "providers": [
                {
                    "id": "pyright",
                    "status": "available",
                    "available": True,
                    "source": "path",
                    "message": "使用 PATH 中的命令",
                }
            ],
            "canRefresh": True,
        },
    )

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(
                "/api/bots/main/workspace/language-servers?provider=pyright&prewarm=1"
            )
            payload = await response.json()

    assert response.status == 200, payload
    assert manager.prewarm_calls == [
        {
            "bot_alias": "main",
            "user_id": server._chat_user_id(_auth_context(CAP_READ_FILE_CONTENT)),
            "workspace_root": str(tmp_path),
            "provider_id": "pyright",
        }
    ]
    assert payload["data"]["providers"][0]["runtimeState"] == "ready"
    assert payload["data"]["providers"][0]["runtimeMessage"] == "Python 语言服务已就绪"
    assert payload["data"]["providers"][0]["implementationSupported"] is False


@pytest.mark.asyncio
async def test_workspace_language_server_status_prewarms_selected_typescript_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = FakeLanguageServerRuntimeManager({"request_id": "unused", "items": [], "message": ""})
    manager.runtime_status = lambda **_kwargs: {
        "state": "ready",
        "pending_count": 0,
        "open_document_count": 0,
        "implementation_supported": True,
    }
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )
    monkeypatch.setattr(
        server.language_server_catalog,
        "api_snapshot",
        lambda: {
            "providers": [
                {
                    "id": "typescript",
                    "status": "available",
                    "available": True,
                    "source": "managed",
                    "message": "使用托管版本",
                }
            ],
            "canRefresh": True,
        },
    )

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(
                "/api/bots/main/workspace/language-servers?provider=typescript&prewarm=1"
            )
            payload = await response.json()

    assert response.status == 200, payload
    assert manager.prewarm_calls == [
        {
            "bot_alias": "main",
            "user_id": server._chat_user_id(_auth_context(CAP_READ_FILE_CONTENT)),
            "workspace_root": str(tmp_path),
            "provider_id": "typescript",
        }
    ]
    provider = payload["data"]["providers"][0]
    assert provider["runtimeState"] == "ready"
    assert provider["runtimeMessage"] == "TypeScript / JavaScript 语言服务已就绪"
    assert provider["implementationSupported"] is True


@pytest.mark.asyncio
async def test_code_navigation_ast_fallback_validation_error_is_a_structured_400(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = _build_server(tmp_path, monkeypatch)
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )

    async def unavailable(**_kwargs) -> dict[str, object]:
        raise LanguageServerUnavailableError("disabled")

    monkeypatch.setattr(server.language_server_manager, "resolve_code_navigation", unavailable)
    app = server._build_app()
    body = {
        "kind": "definition",
        "requestId": "invalid-fallback",
        "document": {"path": "main.py", "languageId": "python", "content": "name()"},
    }

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/workspace/code-navigation/resolve",
                json=body,
            )
            payload = await response.json()

    assert response.status == 400, payload
    assert payload["error"]["code"] == "invalid_code_navigation_request"
    assert payload["error"]["message"] == "代码导航请求格式无效"


@pytest.mark.asyncio
async def test_code_navigation_runtime_error_is_logged_and_returns_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = _build_server(tmp_path, monkeypatch)
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )

    async def fail(**_kwargs) -> dict[str, object]:
        raise RuntimeError(r"secret C:\\workspace\\private.py")

    monkeypatch.setattr(server.language_server_manager, "resolve_code_navigation", fail)
    app = server._build_app()
    body = {
        "kind": "definition",
        "requestId": "runtime-failure",
        "document": {
            "path": "main.py",
            "languageId": "python",
            "version": 1,
            "content": "name()",
        },
        "position": {"line": 1, "column": 1},
    }

    with caplog.at_level("ERROR", logger="bot.web.server"):
        async with TestServer(app) as test_server:
            async with TestClient(test_server) as client:
                response = await client.post(
                    "/api/bots/main/workspace/code-navigation/resolve",
                    json=body,
                )
                payload = await response.json()

    assert response.status == 503, payload
    assert payload["error"] == {
        "code": "language_server_failed",
        "message": "语言服务请求失败，请稍后重试",
        "data": {},
    }
    assert "secret" not in json.dumps(payload, ensure_ascii=False)
    assert "secret" in caplog.text


@pytest.mark.asyncio
async def test_language_server_prewarm_error_uses_a_sanitized_status_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = FakeLanguageServerRuntimeManager({"request_id": "unused", "items": [], "message": ""})
    server = _build_server(tmp_path, monkeypatch)
    server.language_server_manager = manager
    monkeypatch.setattr(
        server,
        "_auth_context",
        lambda _request: _auth_context(CAP_READ_FILE_CONTENT),
    )
    monkeypatch.setattr(
        server.language_server_catalog,
        "api_snapshot",
        lambda: {
            "providers": [{"id": "pyright", "status": "available", "source": "path"}],
            "canRefresh": True,
        },
    )

    async def fail_prewarm(**_kwargs) -> bool:
        raise RuntimeError(r"secret C:\\workspace\\private.py")

    monkeypatch.setattr(manager, "prewarm", fail_prewarm)
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(
                "/api/bots/main/workspace/language-servers?provider=pyright&prewarm=1"
            )
            payload = await response.json()

    assert response.status == 200, payload
    provider = payload["data"]["providers"][0]
    assert provider["runtimeState"] == "error"
    assert provider["runtimeMessage"] == "Python 语言服务启动失败"
    assert "secret" not in json.dumps(payload, ensure_ascii=False)
