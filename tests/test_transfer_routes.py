import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.web.auth_store import CAP_ADMIN_OPS, WebAuthStore
from bot.web.server import WebApiServer


class DummyTunnelService:
    def __init__(self) -> None:
        self._snapshot = {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }

    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return dict(self._snapshot)

    async def stop(self) -> dict[str, object]:
        return dict(self._snapshot)

    async def restart(self) -> dict[str, object]:
        return dict(self._snapshot)

    def preserve_for_restart(self) -> dict[str, object]:
        return dict(self._snapshot)

    def snapshot(self) -> dict[str, object]:
        return dict(self._snapshot)


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WebApiServer:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    return WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())


def _build_member_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth_store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=tmp_path / ".web_register_codes.json",
    )
    invite_code = auth_store.create_register_code(created_by="127.0.0.1")["code"]
    session = auth_store.register_member("alice", "pw-123456", invite_code)
    monkeypatch.setattr("bot.web.server._WEB_AUTH_STORE", auth_store)
    return session


@pytest.mark.asyncio
async def test_openai_compatible_responses_endpoint_ignores_project_authorization_and_uses_transfer_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRANSFER_ACCESS_TOKEN", "local-transfer-token")
    captured: dict[str, object] = {}

    async def chat_completions(request: web.Request) -> web.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_1",
                "created": 123,
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        server = _build_server(monkeypatch, tmp_path)
        server.transfer_service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        app = server._build_app()
        async with TestServer(app) as test_server:
            async with TestClient(test_server) as client:
                unauthorized = await client.post(
                    "/v1/responses",
                    json={"input": "hello"},
                    headers={"Authorization": "Bearer sk-client"},
                )
                authorized = await client.post(
                    "/v1/responses",
                    json={"input": "hello"},
                    headers={
                        "Authorization": "Bearer sk-client",
                        "X-TCB-Transfer-Token": "local-transfer-token",
                    },
                )
                payload = await authorized.json()

    assert unauthorized.status == 401
    assert authorized.status == 200
    assert payload["usage"]["total_tokens"] == 3
    assert captured["authorization"] == "Bearer sk-remote"


@pytest.mark.asyncio
async def test_transfer_status_requires_project_auth_and_does_not_echo_remote_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="8.8.8.8", port=8765, tunnel_service=DummyTunnelService())
    server.transfer_service.update_config(
        {
            "remote_base_url": "http://remote.test/v1",
            "remote_api_key": "sk-remote",
            "remote_model": "gpt-remote",
        }
    )
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            missing_auth = await client.get("/api/transfer/status", headers={"X-Forwarded-For": "203.0.113.9"})
            with_auth = await client.get("/api/transfer/status", headers={"X-API-Token": "project-token"})
            payload = await with_auth.json()

    assert missing_auth.status == 401
    assert with_auth.status == 200
    data = payload["data"]
    assert data["remote_api_key_set"] is True
    assert "remote_api_key" not in data
    assert "sk-remote" not in json.dumps(data)


@pytest.mark.asyncio
async def test_admin_transfer_status_requires_admin_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    member_session = _build_member_session(monkeypatch, tmp_path)
    assert CAP_ADMIN_OPS not in member_session.capabilities

    server = WebApiServer(object(), host="8.8.8.8", port=8765, tunnel_service=DummyTunnelService())
    server.transfer_service.update_config(
        {
            "remote_base_url": "http://remote.test/v1",
            "remote_api_key": "sk-remote",
            "remote_model": "gpt-remote",
        }
    )
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            member_response = await client.get(
                "/api/admin/transfer/status",
                headers={"Authorization": f"Bearer {member_session.token}", "X-Forwarded-For": "203.0.113.9"},
            )
            admin_response = await client.get("/api/admin/transfer/status", headers={"X-API-Token": "project-token"})
            payload = await admin_response.json()

    assert member_response.status == 403
    assert admin_response.status == 200
    data = payload["data"]
    assert data["remote_api_key_set"] is True
    assert data["remote_model"] == "gpt-remote"
    assert "sk-remote" not in json.dumps(data)


@pytest.mark.asyncio
async def test_admin_transfer_reset_and_config_require_admin_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="8.8.8.8", port=8765, tunnel_service=DummyTunnelService())
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            reset_no_auth = await client.post("/api/admin/transfer/reset", headers={"X-Forwarded-For": "203.0.113.9"})
            patch_no_auth = await client.patch(
                "/api/admin/transfer/config",
                json={"remote_model": "gpt"},
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
            reset_auth = await client.post("/api/admin/transfer/reset", headers={"X-API-Token": "project-token"})
            patch_auth = await client.patch(
                "/api/admin/transfer/config",
                json={"remote_base_url": "http://remote.test/v1", "remote_api_key": "sk", "remote_model": "gpt"},
                headers={"X-API-Token": "project-token"},
            )
            payload = await patch_auth.json()

    assert reset_no_auth.status == 401
    assert patch_no_auth.status == 401
    assert reset_auth.status == 200
    assert patch_auth.status == 200
    assert payload["data"]["remote_api_key_set"] is True


@pytest.mark.asyncio
async def test_admin_transfer_config_validation_error_returns_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.patch(
                "/api/admin/transfer/config",
                json={"remote_base_url": "file:///tmp/provider"},
                headers={"X-API-Token": "project-token"},
            )
            payload = await response.json()

    assert response.status == 400
    assert payload["error"]["code"] == "invalid_remote_base_url"


@pytest.mark.asyncio
async def test_transfer_page_is_served_as_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server = _build_server(monkeypatch, tmp_path)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/transfer/page")
            text = await response.text()

    assert response.status == 200
    assert response.content_type == "text/html"
    assert "Response ↔ Chat API 转接器" in text
    assert "/api/transfer/status" in text
    assert "/api/admin/transfer/config" in text
    assert "/api/admin/transfer/reset" in text
    assert "/api/transfer/health" in text
    assert "/api/config" not in text
    assert "/api/reset" not in text
    assert "window.location.pathname" in text
    assert "setInterval" in text
    assert "2000" in text


@pytest.mark.asyncio
async def test_chat_completions_streaming_proxy_emits_sse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TRANSFER_ACCESS_TOKEN", "local-transfer-token")

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"id":"chunk_1","choices":[{"delta":{"content":"ok"}}]}\n\n')
        await response.write(b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n')
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        server = _build_server(monkeypatch, tmp_path)
        server.transfer_service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        app = server._build_app()
        async with TestServer(app) as test_server:
            async with TestClient(test_server) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
                    headers={"X-TCB-Transfer-Token": "local-transfer-token"},
                )
                text = await response.text()

    assert response.status == 200
    assert response.content_type == "text/event-stream"
    assert 'data: {"id": "chunk_1"' in text
    assert "data: [DONE]" in text
