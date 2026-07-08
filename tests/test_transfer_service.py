import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.runtime_paths import (
    get_transfer_config_path,
    get_transfer_litellm_config_path,
    get_transfer_litellm_log_path,
    get_transfer_trace_path,
)
from bot.web.transfer_litellm_config import LiteLLMTransferConfig, write_litellm_proxy_config
from bot.web.transfer_service import TransferService, TransferServiceError


class FakeLiteLLMRuntime:
    def __init__(self, api_base_url: str = "http://127.0.0.1:9999/v1") -> None:
        self.master_key = "sk-internal-master"
        self._api_base_url = api_base_url.rstrip("/")
        self._running = False
        self.pid = 4242
        self.config: LiteLLMTransferConfig | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self.config = config
        self._running = True

    async def close(self) -> None:
        self._running = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "pid": self.pid,
            "api_base_url": self._api_base_url,
            "config_path": "runtime-litellm.yaml",
            "log_path": "runtime-litellm.log",
            "log_tail": [],
        }

    def log_tail(self, max_lines: int = 80) -> list[str]:
        return []


def _configured_service(runtime: FakeLiteLLMRuntime, tmp_path: Path) -> TransferService:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=runtime)
    service.update_config(
        {
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "https://provider.test/v1",
            "provider_api_key": "sk-provider",
            "drop_params": True,
        }
    )
    return service


@pytest.mark.asyncio
async def test_transfer_config_uses_runtime_paths_and_never_echoes_provider_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    service = TransferService(host="127.0.0.1", port=8765, runtime=FakeLiteLLMRuntime())

    assert get_transfer_config_path() == tmp_path / "transfer" / "config.json"
    assert get_transfer_trace_path() == tmp_path / "transfer" / "trace.jsonl"
    assert get_transfer_litellm_config_path() == tmp_path / "transfer" / "litellm-config.yaml"
    assert get_transfer_litellm_log_path() == tmp_path / "transfer" / "litellm.log"
    assert service.config_path == get_transfer_config_path()
    assert service.get_status()["status"] == "not_configured"

    service.update_config(
        {
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "http://example.test/v1",
            "provider_api_key": "sk-secret-value",
        }
    )

    status = service.get_status()
    assert status["enabled"] is True
    assert status["litellm_running"] is False
    assert status["local_endpoint"] == "http://127.0.0.1:8765"
    assert status["local_host"] == "127.0.0.1"
    assert status["local_port"] == 8765
    assert status["provider_api_key_set"] is True
    assert "provider_api_key" not in status
    assert "sk-secret-value" not in json.dumps(status)
    saved = json.loads(get_transfer_config_path().read_text(encoding="utf-8"))
    assert saved == {
        "litellm_model": "openai/gpt-5",
        "model_alias": "codex-gpt-5",
        "provider_base_url": "http://example.test/v1",
        "provider_api_key": "sk-secret-value",
        "drop_params": True,
    }


def test_transfer_config_empty_key_preserves_secret_and_clear_key_removes_it(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())
    service.update_config(
        {
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "https://remote.test/v1",
            "provider_api_key": "sk-secret-value",
        }
    )

    service.update_config({"provider_base_url": "https://other.test/v1", "provider_api_key": ""})

    assert service.config.provider_base_url == "https://other.test/v1"
    assert service.config.provider_api_key == "sk-secret-value"
    assert service.get_status()["provider_api_key_set"] is True

    service.update_config({"clear_provider_api_key": True})

    assert service.config.provider_api_key == ""
    assert service.get_status()["provider_api_key_set"] is False


def test_transfer_config_rejects_non_http_provider_base_url(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())

    with pytest.raises(TransferServiceError) as exc_info:
        service.update_config({"provider_base_url": "file:///tmp/provider", "litellm_model": "openai/gpt-5"})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_provider_base_url"


def test_legacy_transfer_config_migrates_to_litellm_schema_and_drops_converter_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "transfer.json"
    config_path.write_text(
        json.dumps(
            {
                "remote_base_url": "https://legacy.test/v1",
                "remote_api_key": "sk-legacy",
                "remote_model": "gpt-legacy",
                "reasoning_mode": "drop",
                "downgrade_developer_to_system": True,
                "use_legacy_max_tokens": True,
            }
        ),
        encoding="utf-8",
    )

    service = TransferService(host="127.0.0.1", port=8765, config_path=config_path, runtime=FakeLiteLLMRuntime())

    assert service.config.provider_base_url == "https://legacy.test/v1"
    assert service.config.provider_api_key == "sk-legacy"
    assert service.config.litellm_model == "gpt-legacy"
    assert service.config.model_alias == "gpt-legacy"

    service.update_config({"drop_params": False})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved == {
        "litellm_model": "gpt-legacy",
        "model_alias": "gpt-legacy",
        "provider_base_url": "https://legacy.test/v1",
        "provider_api_key": "sk-legacy",
        "drop_params": False,
    }


def test_litellm_runtime_config_yaml_contains_model_and_master_key_only(tmp_path: Path) -> None:
    config = LiteLLMTransferConfig(
        litellm_model="openai/gpt-5",
        model_alias="codex-gpt-5",
        provider_base_url="https://provider.test/v1",
        provider_api_key="sk-provider",
        drop_params=True,
    )

    path = tmp_path / "litellm.yaml"
    write_litellm_proxy_config(path, config, "sk-master")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["model_list"][0]["model_name"] == "codex-gpt-5"
    assert payload["model_list"][0]["litellm_params"] == {
        "model": "openai/gpt-5",
        "api_key": "sk-provider",
        "api_base": "https://provider.test/v1",
    }
    assert payload["litellm_settings"]["drop_params"] is True
    assert payload["general_settings"]["master_key"] == "sk-master"


@pytest.mark.asyncio
async def test_create_response_proxies_raw_body_and_preserves_response_tools(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "resp_1",
                "object": "response",
                "model": "codex-gpt-5",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            }
        )

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            result = await service.create_response(
                {
                    "model": "codex-gpt-5",
                    "input": "hello",
                    "tools": [
                        {"type": "custom", "name": "run_shell", "description": "custom tool"},
                        {"type": "namespace", "name": "codegraph", "tools": [{"name": "search"}]},
                    ],
                    "reasoning": {"effort": "high"},
                }
            )
        finally:
            await service.close()

    assert captured["authorization"] == "Bearer sk-internal-master"
    assert captured["body"] == {
        "model": "codex-gpt-5",
        "input": "hello",
        "tools": [
            {"type": "custom", "name": "run_shell", "description": "custom tool"},
            {"type": "namespace", "name": "codegraph", "tools": [{"name": "search"}]},
        ],
        "reasoning": {"effort": "high"},
    }
    assert result.data["object"] == "response"
    assert result.data["output"][0]["content"][0]["text"] == "ok"
    status = service.get_status()
    assert status["request_count"] == 1
    assert status["total_input_tokens"] == 7
    assert status["total_output_tokens"] == 3


@pytest.mark.asyncio
async def test_chat_completions_non_stream_proxies_raw_body(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def chat_completions(request: web.Request) -> web.Response:
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_1",
                "model": "codex-gpt-5",
                "choices": [{"message": {"role": "assistant", "content": "chat-ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
            }
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            body = {"model": "codex-gpt-5", "messages": [{"role": "user", "content": "hello"}]}
            result = await service.proxy_chat_completions(body)
        finally:
            await service.close()

    assert captured["body"] == body
    assert result.data["choices"][0]["message"]["content"] == "chat-ok"
    assert service.get_status()["total_input_tokens"] == 2
    assert service.get_status()["total_output_tokens"] == 4


@pytest.mark.asyncio
async def test_chat_completions_streaming_proxies_sse_bytes_and_records_usage(tmp_path: Path) -> None:
    chunks = [
        b'data: {"id":"chunk_1","model":"codex-gpt-5","choices":[{"delta":{"content":"ok"}}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\n',
        b"data: [DONE]\n\n",
    ]

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for chunk in chunks:
            await response.write(chunk)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            result = await service.proxy_chat_completions(
                {"model": "codex-gpt-5", "messages": [{"role": "user", "content": "hello"}], "stream": True}
            )
            text = b"".join([chunk async for chunk in result.stream]).decode("utf-8")
        finally:
            await service.close()

    assert text == b"".join(chunks).decode("utf-8")
    status = service.get_status()
    assert status["request_count"] == 1
    assert status["total_input_tokens"] == 4
    assert status["total_output_tokens"] == 2
    assert status["recent_traffic"][0]["endpoint"] == "/v1/chat/completions (stream)"


@pytest.mark.asyncio
async def test_create_response_records_litellm_http_error_in_recent_traffic(tmp_path: Path) -> None:
    async def responses(request: web.Request) -> web.Response:
        return web.json_response({"error": {"message": "rate limited"}}, status=429)

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            with pytest.raises(TransferServiceError) as exc_info:
                await service.create_response({"model": "codex-gpt-5", "input": "hello"})
        finally:
            await service.close()

    assert exc_info.value.status == 429
    status = service.get_status()
    assert status["request_count"] == 0
    traffic = status["recent_traffic"]
    assert len(traffic) == 1
    assert traffic[0]["endpoint"] == "/v1/responses"
    assert traffic[0]["status"] == 429
    assert "rate limited" in traffic[0]["error"]


@pytest.mark.asyncio
async def test_get_and_delete_response_proxy_to_litellm(tmp_path: Path) -> None:
    async def get_response(request: web.Request) -> web.Response:
        return web.json_response({"id": request.match_info["response_id"], "object": "response"})

    async def delete_response(request: web.Request) -> web.Response:
        return web.json_response({"id": request.match_info["response_id"], "object": "response.deleted", "deleted": True})

    app = web.Application()
    app.router.add_get("/v1/responses/{response_id}", get_response)
    app.router.add_delete("/v1/responses/{response_id}", delete_response)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            fetched = await service.get_response("resp_1")
            deleted = await service.delete_response("resp_1")
        finally:
            await service.close()

    assert fetched.data == {"id": "resp_1", "object": "response"}
    assert deleted.data == {"id": "resp_1", "object": "response.deleted", "deleted": True}
