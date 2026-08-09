import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.web.auth_store import CAP_ADMIN_OPS, WebAuthStore
from bot.web.server import WebApiServer
from bot.web.transfer_litellm_config import LiteLLMTransferConfig


class DummyTunnelService:
    def __init__(self) -> None:
        self._snapshot = {"mode": "disabled", "status": "stopped", "source": "disabled", "public_url": "",
                          "local_url": "http://127.0.0.1:8765", "last_error": "", "pid": None}

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


class FakeLiteLLMRuntime:
    def __init__(self, api_base_url: str = "http://127.0.0.1:9999/v1") -> None:
        self.master_key, self._api_base_url, self._running, self.pid = "sk-internal-master", api_base_url.rstrip("/"), False, 4242

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self._running = True

    async def close(self) -> None:
        self._running = False

    def snapshot(self) -> dict[str, Any]:
        return {"running": self._running, "pid": self.pid, "api_base_url": self._api_base_url,
                "config_path": "runtime-litellm.yaml", "log_path": "runtime-litellm.log", "log_tail": []}

    def log_tail(self, max_lines: int = 80) -> list[str]:
        return []


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, host: str = "127.0.0.1") -> WebApiServer:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    return WebApiServer(object(), host=host, port=8765, tunnel_service=DummyTunnelService())


def _configure_transfer(server: WebApiServer, runtime: FakeLiteLLMRuntime) -> None:
    server.transfer_service.runtime = runtime
    server.transfer_service.update_config({"enabled": True, "litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                                           "provider_base_url": "https://provider.test/v1", "provider_api_key": "sk-provider"})


def _member_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = WebAuthStore(users_path=tmp_path / ".web_users.json", register_codes_path=tmp_path / ".web_register_codes.json")
    session = store.register_member("alice", "pw-123456", store.create_register_code(created_by="127.0.0.1")["code"])
    monkeypatch.setattr("bot.web.server._WEB_AUTH_STORE", store)
    return session


@pytest.mark.asyncio
async def test_openai_responses_requires_transfer_token_and_uses_internal_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRANSFER_ACCESS_TOKEN", "local-transfer-token")
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.Response:
        captured["authorization"], captured["body"] = request.headers.get("Authorization"), await request.json()
        return web.json_response({"id": "resp_1", "object": "response", "usage": {"input_tokens": 1, "output_tokens": 2}})

    upstream = web.Application()
    upstream.router.add_post("/v1/responses", responses)
    async with TestServer(upstream) as upstream_server:
        server = _build_server(monkeypatch, tmp_path)
        _configure_transfer(server, FakeLiteLLMRuntime(str(upstream_server.make_url("/v1"))))
        try:
            async with TestServer(server._build_app()) as test_server:
                async with TestClient(test_server) as client:
                    denied = await client.post("/v1/responses", json={"input": "hello"})
                    allowed = await client.post("/v1/responses", json={"input": "hello", "tools": [{"type": "custom", "name": "shell"}]},
                                                headers={"X-TCB-Transfer-Token": "local-transfer-token"})
                    payload = await allowed.json()
        finally:
            await server.transfer_service.close()

    assert denied.status == 401 and allowed.status == 200 and payload["usage"]["input_tokens"] == 1
    assert captured == {"authorization": "Bearer sk-internal-master",
                        "body": {"input": "hello", "tools": [{"type": "custom", "name": "shell"}]}}


@pytest.mark.asyncio
async def test_transfer_status_requires_project_auth_and_redacts_provider_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="8.8.8.8", port=8765, tunnel_service=DummyTunnelService())
    server.transfer_service.update_config({"litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                                           "provider_base_url": "http://remote.test/v1", "provider_api_key": "sk-remote"})
    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            denied = await client.get("/api/transfer/status", headers={"X-Forwarded-For": "203.0.113.9"})
            allowed = await client.get("/api/transfer/status", headers={"X-API-Token": "project-token"})
            data = (await allowed.json())["data"]

    assert denied.status == 401 and allowed.status == 200 and data["provider_api_key_set"] is True
    assert "provider_api_key" not in data and "sk-remote" not in json.dumps(data)


@pytest.mark.asyncio
async def test_admin_transfer_config_requires_capability_and_keeps_endpoint_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    member = _member_session(monkeypatch, tmp_path)
    assert CAP_ADMIN_OPS not in member.capabilities
    server = WebApiServer(object(), host="8.8.8.8", port=8765, tunnel_service=DummyTunnelService())
    config = {"litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5", "endpoint_mode": "responses",
              "provider_base_url": "http://remote.test/v1", "provider_api_key": "sk", "extra_litellm_params": {"rpm": 120}}
    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            denied = await client.patch("/api/admin/transfer/config", json=config, headers={"Authorization": f"Bearer {member.token}"})
            reset_denied = await client.post("/api/admin/transfer/reset", headers={"X-Forwarded-For": "203.0.113.9"})
            allowed = await client.patch("/api/admin/transfer/config", json=config, headers={"X-API-Token": "project-token"})
            data = (await allowed.json())["data"]

    assert denied.status == 403 and reset_denied.status == 401 and allowed.status == 200
    assert data["endpoint_mode"] == "responses" and data["extra_litellm_params"] == {"rpm": 120}
    assert "sk" not in json.dumps(data)


@pytest.mark.asyncio
async def test_admin_transfer_config_hot_starts_and_stops_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    runtime = FakeLiteLLMRuntime()
    server.transfer_service.runtime = runtime
    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            enabled = await client.patch("/api/admin/transfer/config", json={"enabled": True, "litellm_model": "openai/gpt-5",
                "model_alias": "codex-gpt-5", "provider_base_url": "http://remote.test/v1", "provider_api_key": "sk"},
                headers={"X-API-Token": "project-token"})
            disabled = await client.patch("/api/admin/transfer/config", json={"enabled": False}, headers={"X-API-Token": "project-token"})

    assert enabled.status == 200 and disabled.status == 200 and runtime.is_running is False


@pytest.mark.asyncio
async def test_admin_transfer_config_returns_json_for_invalid_extra_params(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "project-token")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            response = await client.patch("/api/admin/transfer/config", json={"litellm_model": "openai/gpt-5",
                "provider_api_key": "sk", "extra_litellm_params": {"api_key": "override"}}, headers={"X-API-Token": "project-token"})
            payload = await response.json()
            unsafe = await client.patch("/api/admin/transfer/config", json={"provider_base_url": "file:///tmp/provider"},
                                        headers={"X-API-Token": "project-token"})
            unsafe_payload = await unsafe.json()

    assert response.status == 400 and payload["error"]["code"] == "invalid_transfer_config"
    assert unsafe.status == 400 and unsafe_payload["error"]["code"] == "invalid_provider_base_url"
