import json
import sys
import asyncio
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
from bot.web.transfer_litellm_config import LiteLLMRouteConfig, LiteLLMTransferConfig, write_litellm_proxy_config
from bot.web.transfer_litellm_runtime import _PYTHON_LITELLM_ENTRYPOINT, _resolve_command
from bot.web.transfer_service import (
    TransferService,
    TransferServiceError,
    _CodexCompactionStreamAdapter,
    _SSEUsageParser,
)


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


class DelayedLiteLLMRuntime(FakeLiteLLMRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls = 0

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self.start_calls += 1
        await asyncio.sleep(0.02)
        await super().ensure_started(config)


class ControlledLiteLLMRuntime(FakeLiteLLMRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.start_entered = asyncio.Event()
        self.release_start = asyncio.Event()
        self.started_aliases: list[str] = []

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self.config = config
        self.started_aliases.append(config.model_alias)
        self.start_entered.set()
        await self.release_start.wait()
        self._running = True


class FailingControlledLiteLLMRuntime(FakeLiteLLMRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.start_entered = asyncio.Event()
        self.release_start = asyncio.Event()
        self.started_aliases: list[str] = []

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None:
        self.config = config
        self.started_aliases.append(config.model_alias)
        if len(self.started_aliases) == 1:
            self.start_entered.set()
            await self.release_start.wait()
            raise RuntimeError("stale generation failed")
        self._running = True


def test_sse_usage_parser_drops_oversized_line_and_recovers() -> None:
    parser = _SSEUsageParser(max_line_characters=128)

    parser.feed(b"x" * 256)
    assert len(parser._buffer) <= 128

    parser.feed(b"\n")
    parser.feed(b'data: {"model":"gpt-test","usage":{"input_tokens":3,"output_tokens":4}}\n')

    assert parser.model == "gpt-test"
    assert parser.usage == {"input_tokens": 3, "output_tokens": 4}


@pytest.mark.asyncio
async def test_transfer_config_defaults_disabled_and_hot_toggles_runtime(tmp_path: Path) -> None:
    runtime = FakeLiteLLMRuntime()
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=runtime)

    service.update_config(
        {
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "https://provider.test/v1",
            "provider_api_key": "sk-provider",
        }
    )

    status = service.get_status()
    assert status["configured"] is True
    assert status["enabled"] is False
    assert status["status"] == "disabled"
    assert status["litellm_running"] is False
    saved = json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))
    assert saved["enabled"] is False

    enabled_status = await service.update_config_async({"enabled": True})

    assert enabled_status["enabled"] is True
    assert enabled_status["configured"] is True
    assert enabled_status["status"] == "running"
    assert runtime.is_running is True

    disabled_status = await service.update_config_async({"enabled": False})

    assert disabled_status["enabled"] is False
    assert disabled_status["configured"] is True
    assert disabled_status["status"] == "disabled"
    assert runtime.is_running is False
    await service.close()


@pytest.mark.asyncio
async def test_config_update_restarts_with_latest_generation(tmp_path: Path) -> None:
    runtime = ControlledLiteLLMRuntime()
    service = _configured_service(runtime, tmp_path)
    start_task = asyncio.create_task(service.ensure_runtime())
    await runtime.start_entered.wait()

    update_task = asyncio.create_task(service.update_config_async({"model_alias": "latest-model"}))
    runtime.release_start.set()
    await asyncio.gather(start_task, update_task)

    assert runtime.started_aliases == ["codex-gpt-5", "latest-model"]
    assert runtime.config is not None
    assert runtime.config.model_alias == "latest-model"
    assert runtime.is_running is True
    await service.close()
    await service.close()


@pytest.mark.asyncio
async def test_stale_generation_failure_retries_latest_config(tmp_path: Path) -> None:
    runtime = FailingControlledLiteLLMRuntime()
    service = _configured_service(runtime, tmp_path)
    start_task = asyncio.create_task(service.ensure_runtime())
    await runtime.start_entered.wait()

    update_task = asyncio.create_task(service.update_config_async({"model_alias": "latest-model"}))
    runtime.release_start.set()
    await asyncio.gather(start_task, update_task)

    assert runtime.started_aliases == ["codex-gpt-5", "latest-model"]
    assert runtime.config is not None
    assert runtime.config.model_alias == "latest-model"
    assert runtime.is_running is True
    await service.close()


def _configured_service(runtime: FakeLiteLLMRuntime, tmp_path: Path) -> TransferService:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=runtime)
    service.update_config(
        {
            "enabled": True,
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "https://provider.test/v1",
            "provider_api_key": "sk-provider",
            "drop_params": True,
        }
    )
    return service


@pytest.mark.asyncio
async def test_ensure_runtime_concurrent_requests_share_one_start(tmp_path: Path) -> None:
    runtime = DelayedLiteLLMRuntime()
    service = _configured_service(runtime, tmp_path)

    await asyncio.gather(*(service.ensure_runtime() for _ in range(20)))

    assert runtime.start_calls == 1


@pytest.mark.asyncio
async def test_disabling_runtime_prevents_stale_start_from_becoming_running(tmp_path: Path) -> None:
    runtime = ControlledLiteLLMRuntime()
    service = _configured_service(runtime, tmp_path)
    start_task = asyncio.create_task(service.ensure_runtime())
    await runtime.start_entered.wait()

    disabled_status = await service.update_config_async({"enabled": False})
    runtime.release_start.set()
    await start_task

    assert disabled_status["status"] == "disabled"
    assert runtime.is_running is False


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
    assert status["enabled"] is False
    assert status["configured"] is True
    assert status["status"] == "disabled"
    assert status["litellm_running"] is False
    assert status["local_endpoint"] == "http://127.0.0.1:8765"
    assert status["local_host"] == "127.0.0.1"
    assert status["local_port"] == 8765
    assert status["provider_api_key_set"] is True
    assert status["endpoint_mode"] == "auto"
    assert status["route_count"] == 1
    assert status["configured_route_count"] == 1
    assert status["routes"] == [
        {
            "id": "route-1",
            "name": "",
            "endpoint_mode": "auto",
            "litellm_model": "openai/gpt-5",
            "model_alias": "codex-gpt-5",
            "provider_base_url": "http://example.test/v1",
            "extra_litellm_params": {},
            "provider_api_key_set": True,
            "configured": True,
        }
    ]
    assert "provider_api_key" not in status
    assert "sk-secret-value" not in json.dumps(status)
    saved = json.loads(get_transfer_config_path().read_text(encoding="utf-8"))
    assert saved == {
        "enabled": False,
        "routes": [
            {
                "id": "route-1",
                "name": "",
                "endpoint_mode": "auto",
                "litellm_model": "openai/gpt-5",
                "model_alias": "codex-gpt-5",
                "provider_base_url": "http://example.test/v1",
                "extra_litellm_params": {},
                "provider_api_key": "sk-secret-value",
            }
        ],
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


def test_transfer_config_accepts_multiple_routes_and_preserves_route_secrets(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())

    service.update_config(
        {
            "routes": [
                {
                    "id": "route-ab",
                    "name": "AB 转",
                    "endpoint_mode": "auto",
                    "model_alias": "A",
                    "litellm_model": "openai/B",
                    "provider_base_url": "https://provider-ab.test/v1",
                    "provider_api_key": "sk-ab",
                },
                {
                    "id": "route-cd",
                    "name": "CD 转",
                    "endpoint_mode": "chat_completions",
                    "model_alias": "C",
                    "litellm_model": "anthropic/D",
                    "provider_base_url": "https://provider-cd.test/v1",
                    "provider_api_key": "sk-cd",
                    "extra_litellm_params": {"rpm": 120},
                },
            ],
            "drop_params": False,
        }
    )

    status = service.get_status()
    assert status["enabled"] is False
    assert status["configured"] is True
    assert status["status"] == "disabled"
    assert status["route_count"] == 2
    assert status["configured_route_count"] == 2
    assert [route["model_alias"] for route in status["routes"]] == ["A", "C"]
    assert status["routes"][1]["endpoint_mode"] == "chat_completions"
    assert status["routes"][1]["extra_litellm_params"] == {"rpm": 120}
    assert "sk-ab" not in json.dumps(status)
    assert "sk-cd" not in json.dumps(status)

    service.update_config(
        {
            "routes": [
                {
                    "id": "route-ab",
                    "name": "AB 转",
                    "endpoint_mode": "auto",
                    "model_alias": "A",
                    "litellm_model": "openai/B2",
                    "provider_base_url": "https://provider-ab.test/v2",
                },
                {
                    "id": "route-cd",
                    "name": "CD 转",
                    "endpoint_mode": "chat_completions",
                    "model_alias": "C",
                    "litellm_model": "anthropic/D",
                    "provider_base_url": "https://provider-cd.test/v1",
                },
            ]
        }
    )

    assert service.config.routes[0].provider_api_key == "sk-ab"
    assert service.config.routes[1].provider_api_key == "sk-cd"
    assert service.config.routes[1].endpoint_mode == "chat_completions"
    assert service.config.routes[1].extra_litellm_params == {"rpm": 120}
    saved = json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))
    assert saved["routes"][0]["litellm_model"] == "openai/B2"
    assert saved["routes"][0]["provider_api_key"] == "sk-ab"
    assert saved["routes"][1]["endpoint_mode"] == "chat_completions"
    assert saved["routes"][1]["extra_litellm_params"] == {"rpm": 120}
    assert "conversion_type" not in json.dumps(saved)
    assert "upstream_api" not in json.dumps(saved)


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
        "enabled": False,
        "routes": [
            {
                "id": "route-1",
                "name": "",
                "endpoint_mode": "auto",
                "litellm_model": "gpt-legacy",
                "model_alias": "gpt-legacy",
                "provider_base_url": "https://legacy.test/v1",
                "extra_litellm_params": {},
                "provider_api_key": "sk-legacy",
            }
        ],
        "drop_params": False,
    }


def test_old_route_upstream_api_migrates_to_endpoint_mode_and_saves_new_schema(tmp_path: Path) -> None:
    config_path = tmp_path / "transfer.json"
    config_path.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "id": "route-chat",
                        "name": "旧配置",
                        "conversion_type": "api",
                        "upstream_api": "chat_completions",
                        "litellm_model": "openai/gpt-5",
                        "model_alias": "codex-gpt-5",
                        "provider_base_url": "https://provider.test/v1",
                        "provider_api_key": "sk-provider",
                    }
                ],
                "drop_params": True,
            }
        ),
        encoding="utf-8",
    )

    service = TransferService(host="127.0.0.1", port=8765, config_path=config_path, runtime=FakeLiteLLMRuntime())

    assert service.config.routes[0].endpoint_mode == "chat_completions"

    service.update_config({"drop_params": False})

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["routes"][0]["endpoint_mode"] == "chat_completions"
    assert "conversion_type" not in saved["routes"][0]
    assert "upstream_api" not in saved["routes"][0]


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
    assert payload["general_settings"]["always_include_stream_usage"] is True


def test_litellm_runtime_config_yaml_contains_multiple_routes(tmp_path: Path) -> None:
    config = LiteLLMTransferConfig(drop_params=False)
    config.routes = [
        LiteLLMRouteConfig(
            id="route-ab",
            endpoint_mode="auto",
            model_alias="A",
            litellm_model="openai/B",
            provider_base_url="https://provider-ab.test/v1",
            provider_api_key="sk-ab",
        ),
        LiteLLMRouteConfig(
            id="route-cd",
            endpoint_mode="chat_completions",
            model_alias="C",
            litellm_model="anthropic/D",
            provider_base_url="https://provider-cd.test/v1",
            provider_api_key="sk-cd",
            extra_litellm_params={"rpm": 120},
        ),
    ]

    path = tmp_path / "litellm.yaml"
    write_litellm_proxy_config(path, config, "sk-master")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [item["model_name"] for item in payload["model_list"]] == ["A", "C"]
    assert payload["model_list"][0]["litellm_params"] == {
        "model": "openai/B",
        "api_key": "sk-ab",
        "api_base": "https://provider-ab.test/v1",
    }
    assert payload["model_list"][1]["litellm_params"] == {
        "model": "anthropic/D",
        "api_key": "sk-cd",
        "api_base": "https://provider-cd.test/v1",
        "rpm": 120,
        "use_chat_completions_api": True,
    }
    assert payload["litellm_settings"]["drop_params"] is False


def test_litellm_runtime_config_yaml_normalizes_openai_responses_model(tmp_path: Path) -> None:
    config = LiteLLMTransferConfig(drop_params=True)
    config.routes = [
        LiteLLMRouteConfig(
            id="route-responses",
            endpoint_mode="responses",
            model_alias="gpt-5",
            litellm_model="openai/gpt-5",
            provider_api_key="sk-provider",
        )
    ]

    path = tmp_path / "litellm.yaml"
    write_litellm_proxy_config(path, config, "sk-master")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["model_list"][0]["litellm_params"]["model"] == "openai/responses/gpt-5"


def test_litellm_extra_params_reject_core_field_overrides(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json", runtime=FakeLiteLLMRuntime())

    with pytest.raises(TransferServiceError) as exc_info:
        service.update_config(
            {
                "routes": [
                    {
                        "id": "route-1",
                        "endpoint_mode": "auto",
                        "litellm_model": "openai/gpt-5",
                        "model_alias": "gpt-5",
                        "provider_api_key": "sk-provider",
                        "extra_litellm_params": {"api_key": "sk-override"},
                    }
                ]
            }
        )

    assert exc_info.value.status == 400
    assert "extra_litellm_params" in exc_info.value.message


def test_litellm_runtime_default_command_uses_current_python_module_when_script_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.web.transfer_litellm_runtime.shutil.which", lambda command: None)
    monkeypatch.setattr("bot.web.transfer_litellm_runtime.importlib.util.find_spec", lambda name: object() if name == "litellm" else None)

    assert _resolve_command(None) == [sys.executable, "-c", _PYTHON_LITELLM_ENTRYPOINT]


def test_litellm_runtime_default_command_explains_install_when_litellm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.web.transfer_litellm_runtime.shutil.which", lambda command: None)
    monkeypatch.setattr("bot.web.transfer_litellm_runtime.importlib.util.find_spec", lambda name: None)

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_command(None)

    assert "python -m pip install -r requirements.txt" in str(exc_info.value)


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
async def test_create_response_ignores_endpoint_mode_and_proxies_to_responses(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.Response:
        captured["path"] = request.path
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
        service.update_config(
            {
                "routes": [
                    {
                        "id": "route-chat",
                        "endpoint_mode": "chat_completions",
                        "model_alias": "codex-gpt-5",
                        "litellm_model": "openai/gpt-5",
                        "provider_base_url": "https://provider.test/v1",
                    }
                ]
            }
        )
        try:
            result = await service.create_response(
                {
                    "model": "codex-gpt-5",
                    "instructions": "You are concise.",
                    "input": "hello",
                    "reasoning": {"effort": "minimal"},
                    "max_output_tokens": 64,
                }
            )
        finally:
            await service.close()

    assert captured["path"] == "/v1/responses"
    assert captured["authorization"] == "Bearer sk-internal-master"
    assert captured["body"] == {
        "model": "codex-gpt-5",
        "instructions": "You are concise.",
        "input": "hello",
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 64,
    }
    assert result.data["object"] == "response"
    assert result.data["id"] == "resp_1"
    status = service.get_status()
    assert status["recent_traffic"][0]["endpoint"] == "/v1/responses"
    assert status["total_input_tokens"] == 7
    assert status["total_output_tokens"] == 3


@pytest.mark.asyncio
async def test_create_response_streaming_proxies_raw_sse_bytes(tmp_path: Path) -> None:
    chunks = [
        b'event: response.output_text.delta\ndata: {"delta":"he","model":"codex-gpt-5"}\n\n',
        b'event: response.output_text.delta\ndata: {"delta":"llo","model":"codex-gpt-5"}\n\n',
        b'event: response.completed\ndata: {"response":{"usage":{"input_tokens":5,"output_tokens":2,"total_tokens":7}}}\n\n',
        b"data: [DONE]\n\n",
    ]

    async def responses(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        assert body["stream"] is True
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for chunk in chunks:
            await response.write(chunk)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        service.update_config(
            {
                "routes": [
                    {
                        "id": "route-chat",
                        "endpoint_mode": "chat_completions",
                        "model_alias": "codex-gpt-5",
                        "litellm_model": "openai/gpt-5",
                        "provider_base_url": "https://provider.test/v1",
                    }
                ]
            }
        )
        try:
            result = await service.create_response({"model": "codex-gpt-5", "input": "hello", "stream": True})
            text = b"".join([chunk async for chunk in result.stream]).decode("utf-8")
        finally:
            await service.close()

    assert text == b"".join(chunks).decode("utf-8")
    status = service.get_status()
    assert status["recent_traffic"][0]["endpoint"] == "/v1/responses (stream)"
    assert status["total_input_tokens"] == 5
    assert status["total_output_tokens"] == 2


@pytest.mark.asyncio
async def test_create_response_streaming_wraps_codex_compaction_for_litellm(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def responses(request: web.Request) -> web.StreamResponse:
        captured["body"] = await request.json()
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'event: response.output_text.delta\ndata: {"delta":"summary ","model":"codex-gpt-5"}\n\n')
        await response.write(b'event: response.output_text.delta\ndata: {"delta":"text"}\n\n')
        await response.write(
            b'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp-compact","usage":{"input_tokens":9,"output_tokens":2,"total_tokens":11}}}\n\n'
        )
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/v1/responses", responses)
    async with TestServer(app) as upstream_server:
        runtime = FakeLiteLLMRuntime(str(upstream_server.make_url("/v1")))
        service = _configured_service(runtime, tmp_path)
        try:
            result = await service.create_response(
                {
                    "model": "codex-gpt-5",
                    "instructions": "Original coding agent instructions.",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "hello before compact"}],
                        },
                        {"type": "compaction_trigger"},
                    ],
                    "tools": [{"type": "function", "name": "run_shell"}],
                    "parallel_tool_calls": True,
                    "stream": True,
                }
            )
            text = b"".join([chunk async for chunk in result.stream]).decode("utf-8")
        finally:
            await service.close()

    upstream_body = captured["body"]
    assert isinstance(upstream_body, dict)
    assert upstream_body["stream"] is True
    assert upstream_body["model"] == "codex-gpt-5"
    assert "tools" not in upstream_body
    assert "parallel_tool_calls" not in upstream_body
    assert "compaction_trigger" not in json.dumps(upstream_body)
    assert "hello before compact" in json.dumps(upstream_body)

    data_events = [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert data_events[0] == {
        "type": "response.output_item.done",
        "item": {"type": "compaction", "encrypted_content": "summary text"},
    }
    assert data_events[1]["type"] == "response.completed"
    assert "response.output_text.delta" not in text

    status = service.get_status()
    assert status["recent_traffic"][0]["endpoint"] == "/v1/responses (stream)"
    assert status["total_input_tokens"] == 9
    assert status["total_output_tokens"] == 2


def test_codex_compaction_adapter_spools_raw_and_summary_without_changing_bytes() -> None:
    adapter = _CodexCompactionStreamAdapter(
        memory_limit_bytes=32,
        max_response_bytes=4096,
        max_summary_bytes=1024,
    )
    chunks = [
        b'event: response.output_text.delta\ndata: {"delta":"summary "}\n\n',
        b'event: response.output_text.delta\ndata: {"delta":"text"}\n\n',
        b'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":{"type":"compaction","encrypted_content":"summary text"}}\n\n',
    ]

    for chunk in chunks:
        adapter.feed(chunk)

    diagnostics = adapter.diagnostics()
    assert diagnostics["raw_spooled"] is True
    assert diagnostics["summary_spooled"] is False
    assert b"".join(adapter.passthrough_chunks()) == b"".join(chunks)
    assert adapter.summary_text() == "summary text"
    adapter.close()


def test_codex_compaction_adapter_rejects_oversized_summary() -> None:
    adapter = _CodexCompactionStreamAdapter(
        memory_limit_bytes=16,
        max_response_bytes=4096,
        max_summary_bytes=8,
    )

    with pytest.raises(TransferServiceError, match="compact summary exceeds"):
        adapter.feed(
            b'event: response.output_text.delta\ndata: {"delta":"summary text"}\n\n'
        )

    adapter.close()


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
