import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.runtime_paths import get_transfer_config_path, get_transfer_litellm_config_path, get_transfer_litellm_log_path
from bot.web.transfer_litellm_config import LiteLLMRouteConfig, LiteLLMTransferConfig, write_litellm_proxy_config
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
        return {"running": self._running, "pid": self.pid, "api_base_url": self._api_base_url,
                "config_path": "runtime-litellm.yaml", "log_path": "runtime-litellm.log", "log_tail": []}

    def log_tail(self, max_lines: int = 80) -> list[str]:
        return []


class BlockingLiteLLMRuntime(FakeLiteLLMRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started_models: list[str] = []
        self.close_count = 0
        self.first_start_entered = asyncio.Event()
        self.release_first_start = asyncio.Event()

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self.config = config
        self.started_models.append(config.model_alias)
        if len(self.started_models) == 1:
            self.first_start_entered.set()
            await self.release_first_start.wait()
        self._running = True

    async def close(self) -> None:
        self.close_count += 1
        await super().close()


def _configured_service(runtime: FakeLiteLLMRuntime, tmp_path: Path) -> TransferService:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=runtime)
    service.update_config({"enabled": True, "litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                           "provider_base_url": "https://provider.test/v1", "provider_api_key": "sk-provider"})
    return service


@pytest.mark.asyncio
async def test_transfer_config_defaults_disabled_and_hot_toggles_runtime(tmp_path: Path) -> None:
    runtime = FakeLiteLLMRuntime()
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=runtime)
    service.update_config({"litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                           "provider_base_url": "https://provider.test/v1", "provider_api_key": "sk-provider"})
    assert service.get_status()["status"] == "disabled"
    assert json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))["enabled"] is False

    enabled = await service.update_config_async({"enabled": True})
    assert enabled["status"] == "running" and runtime.is_running
    disabled = await service.update_config_async({"enabled": False})

    assert disabled["status"] == "disabled"
    await service.close()


@pytest.mark.asyncio
async def test_transfer_config_uses_runtime_paths_and_redacts_provider_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    service = TransferService(host="127.0.0.1", port=8765, runtime=FakeLiteLLMRuntime())
    assert service.config_path == get_transfer_config_path() == tmp_path / "transfer" / "config.json"
    assert get_transfer_litellm_config_path() == tmp_path / "transfer" / "litellm-config.yaml"
    assert get_transfer_litellm_log_path() == tmp_path / "transfer" / "litellm.log"

    service.update_config({"litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                           "provider_base_url": "http://example.test/v1", "provider_api_key": "sk-secret-value"})
    status = service.get_status()
    saved = json.loads(get_transfer_config_path().read_text(encoding="utf-8"))

    assert status["provider_api_key_set"] is True
    assert "provider_api_key" not in status and "sk-secret-value" not in json.dumps(status)
    assert saved["routes"][0]["provider_api_key"] == "sk-secret-value"


def test_transfer_routes_preserve_endpoint_modes_and_existing_secrets(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())
    routes = [
        {"id": "route-a", "endpoint_mode": "responses", "model_alias": "A", "litellm_model": "openai/A",
         "provider_base_url": "https://a.test/v1", "provider_api_key": "sk-a"},
        {"id": "route-b", "endpoint_mode": "chat_completions", "model_alias": "B", "litellm_model": "anthropic/B",
         "provider_base_url": "https://b.test/v1", "provider_api_key": "sk-b", "extra_litellm_params": {"rpm": 120}},
    ]
    service.update_config({"routes": routes, "drop_params": False})
    service.update_config({"routes": [{**routes[0], "litellm_model": "openai/A2", "provider_api_key": ""},
                                        {key: value for key, value in routes[1].items() if key != "provider_api_key"}]})

    status = service.get_status()
    saved = json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))
    assert [route.endpoint_mode for route in service.config.routes] == ["responses", "chat_completions"]
    assert [route.provider_api_key for route in service.config.routes] == ["sk-a", "sk-b"]
    assert status["route_count"] == 2 and "sk-a" not in json.dumps(status) and "sk-b" not in json.dumps(status)
    assert saved["routes"][0]["litellm_model"] == "openai/A2"
    assert saved["routes"][1]["extra_litellm_params"] == {"rpm": 120}


def test_transfer_config_explicitly_clears_provider_secret(tmp_path: Path) -> None:
    service = _configured_service(FakeLiteLLMRuntime(), tmp_path)

    service.update_config({"clear_provider_api_key": True})

    assert service.config.routes[0].provider_api_key == ""
    assert service.get_status()["provider_api_key_set"] is False
    assert json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))["routes"][0]["provider_api_key"] == ""


def test_transfer_config_rejects_unsafe_provider_url_and_reserved_params(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())
    with pytest.raises(TransferServiceError, match="http/https"):
        service.update_config({"provider_base_url": "file:///tmp/provider"})
    with pytest.raises(TransferServiceError, match="extra_litellm_params"):
        service.update_config({"litellm_model": "openai/gpt-5", "extra_litellm_params": {"api_key": "override"}})


def test_legacy_route_endpoint_mode_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "transfer.json"
    path.write_text(json.dumps({"routes": [{"id": "route-chat", "upstream_api": "chat_completions",
                                               "litellm_model": "openai/gpt-5", "model_alias": "codex-gpt-5",
                                               "provider_api_key": "sk-provider"}]}), encoding="utf-8")
    service = TransferService(host="127.0.0.1", port=8765, config_path=path, runtime=FakeLiteLLMRuntime())
    service.update_config({"drop_params": False})
    route = json.loads(path.read_text(encoding="utf-8"))["routes"][0]
    assert route["endpoint_mode"] == "chat_completions" and "upstream_api" not in route


def test_litellm_proxy_config_keeps_routes_and_endpoint_specific_options(tmp_path: Path) -> None:
    config = LiteLLMTransferConfig(drop_params=False, routes=[
        LiteLLMRouteConfig(id="chat", endpoint_mode="chat_completions", model_alias="chat", litellm_model="anthropic/test",
                            provider_base_url="https://chat.test/v1", provider_api_key="sk-chat", extra_litellm_params={"rpm": 120}),
        LiteLLMRouteConfig(id="responses", endpoint_mode="responses", model_alias="responses", litellm_model="openai/gpt-5",
                            provider_api_key="sk-responses"),
    ])
    path = tmp_path / "litellm.yaml"
    write_litellm_proxy_config(path, config, "sk-master")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert payload["general_settings"]["master_key"] == "sk-master"
    assert payload["litellm_settings"]["drop_params"] is False
    assert payload["model_list"][0]["litellm_params"]["use_chat_completions_api"] is True
    assert payload["model_list"][0]["litellm_params"]["rpm"] == 120
    assert payload["model_list"][1]["litellm_params"]["model"] == "openai/responses/gpt-5"


@pytest.mark.asyncio
async def test_create_response_uses_responses_even_for_chat_route(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.Response:
        captured["path"] = request.path
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = await request.json()
        return web.json_response({"id": "resp_1", "object": "response", "usage": {"input_tokens": 7, "output_tokens": 3}})

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream:
        service = _configured_service(FakeLiteLLMRuntime(str(upstream.make_url("/v1"))), tmp_path)
        service.update_config({"routes": [{"id": "route-chat", "endpoint_mode": "chat_completions", "model_alias": "codex-gpt-5",
                                            "litellm_model": "openai/gpt-5", "provider_base_url": "https://provider.test/v1"}]})
        try:
            result = await service.create_response({"model": "codex-gpt-5", "input": "hello", "max_output_tokens": 64})
        finally:
            await service.close()

    assert captured == {"path": "/v1/responses", "authorization": "Bearer sk-internal-master",
                        "body": {"model": "codex-gpt-5", "input": "hello", "max_output_tokens": 64}}
    assert result.data["id"] == "resp_1"


@pytest.mark.asyncio
async def test_create_response_streaming_converts_codex_compaction(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.StreamResponse:
        captured["body"] = await request.json()
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'event: response.output_text.delta\ndata: {"delta":"summary ","model":"codex-gpt-5"}\n\n')
        await response.write(b'event: response.output_text.delta\ndata: {"delta":"text"}\n\n')
        await response.write(b'event: response.completed\ndata: {"response":{"usage":{"input_tokens":9,"output_tokens":2}}}\n\n')
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream:
        service = _configured_service(FakeLiteLLMRuntime(str(upstream.make_url("/v1"))), tmp_path)
        try:
            result = await service.create_response({"model": "codex-gpt-5", "input": [{"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "before compact"}]}, {"type": "compaction_trigger"}],
                "tools": [{"type": "function", "name": "run_shell"}], "parallel_tool_calls": True, "stream": True})
            text = b"".join([chunk async for chunk in result.stream]).decode("utf-8")
        finally:
            await service.close()

    body = captured["body"]
    assert isinstance(body, dict) and "compaction_trigger" not in json.dumps(body) and "tools" not in body
    events = [json.loads(line.removeprefix("data: ")) for line in text.splitlines() if line.startswith("data: ")]
    assert events[0] == {"type": "response.output_item.done",
                         "item": {"type": "compaction", "encrypted_content": "summary text"}}
    assert "event: response.completed\n" in text
    assert events[-1]["response"]["usage"] == {"input_tokens": 9, "output_tokens": 2}
    assert "response.output_text.delta" not in text


@pytest.mark.asyncio
async def test_runtime_start_singleflight_retries_with_latest_generation(tmp_path: Path) -> None:
    runtime = BlockingLiteLLMRuntime()
    service = _configured_service(runtime, tmp_path)
    first = asyncio.create_task(service.ensure_runtime())
    await runtime.first_start_entered.wait()
    second = asyncio.create_task(service.ensure_runtime())
    await asyncio.sleep(0)
    assert runtime.started_models == ["codex-gpt-5"]
    service.update_config({"model_alias": "new-codex"})
    runtime.release_first_start.set()
    await asyncio.gather(first, second)

    assert runtime.started_models == ["codex-gpt-5", "new-codex"]
    assert runtime.close_count == 1
    await service.close()


@pytest.mark.asyncio
async def test_chat_completions_streaming_proxies_sse_and_usage(tmp_path: Path) -> None:
    chunks = [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
              b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n', b"data: [DONE]\n\n"]

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for chunk in chunks:
            await response.write(chunk)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(app) as upstream:
        service = _configured_service(FakeLiteLLMRuntime(str(upstream.make_url("/v1"))), tmp_path)
        try:
            result = await service.proxy_chat_completions({"model": "codex-gpt-5", "messages": [], "stream": True})
            text = b"".join([chunk async for chunk in result.stream]).decode("utf-8")
        finally:
            await service.close()

    assert text == b"".join(chunks).decode("utf-8")
    assert service.get_status()["total_input_tokens"] == 4 and service.get_status()["total_output_tokens"] == 2


@pytest.mark.asyncio
async def test_create_response_records_upstream_http_error(tmp_path: Path) -> None:
    async def responses(request: web.Request) -> web.Response:
        return web.json_response({"error": {"message": "rate limited"}}, status=429)

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream:
        service = _configured_service(FakeLiteLLMRuntime(str(upstream.make_url("/v1"))), tmp_path)
        try:
            with pytest.raises(TransferServiceError, match="rate limited"):
                await service.create_response({"model": "codex-gpt-5", "input": "hello"})
        finally:
            await service.close()

    traffic = service.get_status()["recent_traffic"]
    assert traffic[0]["endpoint"] == "/v1/responses" and traffic[0]["status"] == 429
