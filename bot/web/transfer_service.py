"""OpenAI-compatible transfer bridge backed by a LiteLLM proxy sidecar."""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Protocol

from aiohttp import ClientConnectionError, ClientResponse, ClientSession, ClientTimeout

from bot.runtime_paths import (
    get_transfer_config_path,
    get_transfer_litellm_config_path,
    get_transfer_litellm_log_path,
    get_transfer_trace_path,
)
from bot.web.transfer_litellm_config import (
    LiteLLMRouteConfig,
    LiteLLMTransferConfig,
    load_litellm_transfer_config,
    update_litellm_transfer_config,
)
from bot.web.transfer_litellm_runtime import LiteLLMProxyRuntime

TRACE_STRING_LIMIT = 500
TRACE_STRING_HEAD = 240


class TransferRuntime(Protocol):
    master_key: str

    @property
    def is_running(self) -> bool: ...

    @property
    def pid(self) -> int | None: ...

    @property
    def api_base_url(self) -> str: ...

    async def ensure_started(self, config: LiteLLMTransferConfig) -> None: ...

    async def close(self) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...

    def log_tail(self, max_lines: int = 80) -> list[str]: ...


@dataclass
class TrafficRecord:
    method: str
    endpoint: str
    status: int
    bytes_in: int
    bytes_out: int
    duration_ms: float
    model: str = ""
    error: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "method": self.method,
            "endpoint": self.endpoint,
            "status": self.status,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "duration_ms": round(self.duration_ms, 2),
            "model": self.model,
            "error": self.error,
        }


@dataclass
class TransferResult:
    data: Any | None = None
    raw_body: bytes | None = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    stream: AsyncIterator[bytes] | None = None
    content_type: str = "application/json"


class TransferServiceError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "transfer_error") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class _SSEUsageParser:
    def __init__(self) -> None:
        self._buffer = ""
        self.usage: dict[str, int] = {}
        self.model = ""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._process_line(line.rstrip("\r"))

    def _process_line(self, line: str) -> None:
        if not line.startswith("data:"):
            return
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            if payload.get("model"):
                self.model = str(payload.get("model") or "")
            usage = _extract_usage(payload)
            if usage:
                self.usage = usage


def _content_type_header(response: ClientResponse) -> str:
    value = response.headers.get("Content-Type", "application/json")
    return value.split(";", 1)[0].strip() or "application/json"


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _extract_error_message(status: int, raw_body: bytes) -> str:
    text = raw_body.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return f"LiteLLM proxy error ({status}): {text[:500]}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "").strip()
            if message:
                return f"LiteLLM proxy error ({status}): {message}"
        if payload.get("message"):
            return f"LiteLLM proxy error ({status}): {payload.get('message')}"
    return f"LiteLLM proxy error ({status}): {text[:500]}"


def _extract_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            usage = response.get("usage")
    if not isinstance(usage, dict):
        return {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _copy_response_headers(response: ClientResponse) -> dict[str, str]:
    allowed = {"cache-control", "x-accel-buffering"}
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in allowed
    }
    if response.content_type == "text/event-stream":
        headers.setdefault("Cache-Control", "no-cache")
        headers.setdefault("X-Accel-Buffering", "no")
    return headers


def _normalize_chat_usage_to_response_usage(usage: Any) -> dict[str, Any]:
    usage_data = usage if isinstance(usage, dict) else {}
    prompt_details = usage_data.get("prompt_tokens_details")
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    completion_details = usage_data.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    input_tokens = int(usage_data.get("input_tokens") or usage_data.get("prompt_tokens") or 0)
    output_tokens = int(usage_data.get("output_tokens") or usage_data.get("completion_tokens") or 0)
    total_tokens = int(usage_data.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_tokens_details": {
            "cached_tokens": int(prompt_details.get("cached_tokens") or 0),
        },
        "output_tokens_details": {
            "reasoning_tokens": int(completion_details.get("reasoning_tokens") or 0),
        },
    }


def _response_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    part_type = str(part.get("type") or "")
    if part_type in {"input_text", "output_text", "text"}:
        return str(part.get("text") or "")
    if part.get("text") is not None:
        return str(part.get("text") or "")
    return ""


def _response_content_to_chat_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_response_part_text(part) for part in content)
    if content is None:
        return ""
    return str(content)


def _response_input_item_to_chat_message(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        return {"role": "user", "content": item}
    if not isinstance(item, dict):
        return {"role": "user", "content": str(item)}
    item_type = str(item.get("type") or "")
    if item_type == "function_call_output":
        message: dict[str, Any] = {
            "role": "tool",
            "content": _response_content_to_chat_content(item.get("output")),
        }
        call_id = str(item.get("call_id") or "").strip()
        if call_id:
            message["tool_call_id"] = call_id
        return message
    role = str(item.get("role") or "user")
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        role = "user"
    message = {
        "role": role,
        "content": _response_content_to_chat_content(item.get("content", item.get("text", ""))),
    }
    if role == "tool" and item.get("tool_call_id"):
        message["tool_call_id"] = str(item.get("tool_call_id"))
    return message


def _responses_input_to_chat_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    instructions = str(body.get("instructions") or "").strip()
    if instructions:
        messages.append({"role": "system", "content": instructions})
    raw_messages = body.get("messages")
    if isinstance(raw_messages, list):
        for item in raw_messages:
            message = _response_input_item_to_chat_message(item)
            if message is not None:
                messages.append(message)
        return messages or [{"role": "user", "content": ""}]
    raw_input = body.get("input", "")
    if isinstance(raw_input, list):
        for item in raw_input:
            message = _response_input_item_to_chat_message(item)
            if message is not None:
                messages.append(message)
    else:
        messages.append({"role": "user", "content": _response_content_to_chat_content(raw_input)})
    return messages or [{"role": "user", "content": ""}]


def _responses_tools_to_chat_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    chat_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            chat_tools.append(tool)
            continue
        if tool.get("type") in {"function", "custom"} and tool.get("name"):
            chat_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(tool.get("name")),
                        "description": str(tool.get("description") or ""),
                        "parameters": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object", "properties": {}},
                    },
                }
            )
    return chat_tools


def _responses_to_chat_completion_request(body: dict[str, Any]) -> dict[str, Any]:
    chat: dict[str, Any] = {
        "model": str(body.get("model") or ""),
        "messages": _responses_input_to_chat_messages(body),
    }
    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "stop", "user", "seed"):
        if key in body:
            chat[key] = body[key]
    if "max_output_tokens" in body:
        chat["max_completion_tokens"] = body["max_output_tokens"]
    elif "max_completion_tokens" in body:
        chat["max_completion_tokens"] = body["max_completion_tokens"]
    elif "max_tokens" in body:
        chat["max_tokens"] = body["max_tokens"]
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        chat["reasoning_effort"] = reasoning.get("effort")
    elif body.get("reasoning_effort"):
        chat["reasoning_effort"] = body.get("reasoning_effort")
    tools = _responses_tools_to_chat_tools(body.get("tools"))
    if tools:
        chat["tools"] = tools
    if "tool_choice" in body:
        chat["tool_choice"] = body["tool_choice"]
    if body.get("stream"):
        chat["stream"] = True
        stream_options = body.get("stream_options") if isinstance(body.get("stream_options"), dict) else {}
        chat["stream_options"] = {**stream_options, "include_usage": True}
    return {key: value for key, value in chat.items() if value is not None}


def _chat_message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_response_part_text(part) for part in content)
    return "" if content is None else str(content)


def _build_response_payload(
    *,
    response_id: str,
    model: str,
    created_at: int,
    text: str,
    usage: dict[str, Any],
    status: str = "completed",
    message_id: str | None = None,
) -> dict[str, Any]:
    message_id = message_id or f"msg_{uuid.uuid4().hex[:24]}"
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "model": model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": status,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": usage,
    }


def _chat_completion_to_response(chat: dict[str, Any], request_body: dict[str, Any]) -> dict[str, Any]:
    choices = chat.get("choices") if isinstance(chat.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    text = _chat_message_text(message)
    return _build_response_payload(
        response_id=str(chat.get("id") or f"resp_{uuid.uuid4().hex[:24]}"),
        model=str(chat.get("model") or request_body.get("model") or ""),
        created_at=int(chat.get("created") or time.time()),
        text=text,
        usage=_normalize_chat_usage_to_response_usage(chat.get("usage")),
    )


def _sse_event(event_type: str, payload: dict[str, Any]) -> bytes:
    payload.setdefault("type", event_type)
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


class TransferService:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        config_path: Path | None = None,
        trace_path: Path | None = None,
        runtime: TransferRuntime | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.config_path = config_path or get_transfer_config_path()
        self.trace_path = trace_path or get_transfer_trace_path()
        self.config = LiteLLMTransferConfig()
        self.runtime: TransferRuntime = runtime or LiteLLMProxyRuntime(
            config_path=get_transfer_litellm_config_path(),
            log_path=get_transfer_litellm_log_path(),
            command=os.environ.get("TRANSFER_LITELLM_COMMAND"),
        )
        self.request_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_bytes_in = 0
        self.total_bytes_out = 0
        self.traffic_log: deque[dict[str, Any]] = deque(maxlen=50)
        self.started_at: datetime | None = None
        self.last_request_at: datetime | None = None
        self.last_error = ""
        self.is_running = False
        self._client: ClientSession | None = None
        self._runtime_dirty = False
        self.load_config()
        self.apply_env_config()

    async def start(self) -> None:
        if self._client is None or self._client.closed:
            self._client = ClientSession(timeout=ClientTimeout(total=300))
        self.is_running = True
        self.started_at = datetime.now()
        if self.config.enabled:
            try:
                await self.ensure_runtime()
            except TransferServiceError:
                pass

    async def close(self) -> None:
        await self.runtime.close()
        if self._client is not None and not self._client.closed:
            await self._client.close()
        self.is_running = False

    async def ensure_runtime(self) -> None:
        if self._client is None or self._client.closed:
            self._client = ClientSession(timeout=ClientTimeout(total=300))
        if not self.config.enabled:
            await self.runtime.close()
            raise TransferServiceError(503, "LiteLLM 网关尚未配置", code="transfer_not_configured")
        try:
            await self.runtime.ensure_started(self.config)
            self._runtime_dirty = False
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)[:500]
            self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
            raise TransferServiceError(503, f"LiteLLM 网关启动失败: {exc}", code="litellm_start_failed") from exc

    def load_config(self) -> None:
        self.config = load_litellm_transfer_config(self.config_path)

    def apply_env_config(self) -> None:
        data: dict[str, Any] = {}
        env_map = {
            "TRANSFER_LITELLM_MODEL": "litellm_model",
            "TRANSFER_MODEL_ALIAS": "model_alias",
            "TRANSFER_PROVIDER_BASE_URL": "provider_base_url",
            "TRANSFER_PROVIDER_API_KEY": "provider_api_key",
            "TRANSFER_REMOTE_BASE_URL": "remote_base_url",
            "TRANSFER_REMOTE_API_KEY": "remote_api_key",
            "TRANSFER_REMOTE_MODEL": "remote_model",
        }
        for env_key, data_key in env_map.items():
            if env_key in os.environ:
                data[data_key] = os.environ[env_key]
        if "TRANSFER_DROP_PARAMS" in os.environ:
            data["drop_params"] = os.environ["TRANSFER_DROP_PARAMS"].strip().lower() not in {"0", "false", "no", "off"}
        if data:
            update_litellm_transfer_config(self.config, data)

    def save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config.to_file_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def update_config(self, data: dict[str, Any], *, save: bool = True) -> dict[str, Any]:
        restart_required = False
        if any(key in data for key in ("local_host", "local_port")):
            restart_required = True
        try:
            update_litellm_transfer_config(self.config, data)
        except ValueError as exc:
            error_text = str(exc)
            code = "invalid_provider_base_url" if "provider_base_url" in error_text or "URL" in error_text else "invalid_transfer_config"
            raise TransferServiceError(400, error_text, code=code) from exc
        self._runtime_dirty = True
        if save:
            self.save_config()
        status = self.get_status()
        if restart_required:
            status["restart_required"] = True
            status["restart_required_reason"] = "local_endpoint_readonly"
        return status

    def reset_stats(self) -> dict[str, Any]:
        self.request_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_bytes_in = 0
        self.total_bytes_out = 0
        self.traffic_log.clear()
        self.last_error = ""
        self.last_request_at = None
        return self.get_status()

    def get_status(self, *, base_path: str = "") -> dict[str, Any]:
        enabled = self.config.enabled
        runtime_running = bool(self.runtime.is_running)
        status = "running" if enabled and runtime_running else "not_configured" if not enabled else "stopped"
        if self.last_error and enabled:
            status = "error"
        base = self._local_base_url(base_path)
        uptime_seconds = 0
        if self.started_at:
            uptime_seconds = max(0, int((datetime.now() - self.started_at).total_seconds()))
        runtime_snapshot = self.runtime.snapshot()
        routes = self.config.effective_routes()
        first_route = routes[0] if routes else None
        return {
            "enabled": enabled,
            "running": runtime_running,
            "is_running": bool(self.is_running),
            "status": status,
            "local_url": base,
            "local_endpoint": base,
            "local_host": self.host,
            "local_port": self.port,
            "bridge_page_url": f"{base_path}/api/transfer/page" if base_path else "/api/transfer/page",
            "responses_base_url": f"{base}/v1",
            "chat_completions_base_url": f"{base}/v1",
            "litellm_running": runtime_running,
            "litellm_pid": self.runtime.pid,
            "litellm_model": first_route.litellm_model if first_route else "",
            "model_alias": first_route.model_alias if first_route else "",
            "conversion_type": first_route.conversion_type if first_route else "model_api",
            "upstream_api": first_route.upstream_api if first_route else "responses",
            "provider_base_url": first_route.provider_base_url if first_route else "",
            "provider_api_key_set": bool(first_route.provider_api_key) if first_route else False,
            "routes": [route.to_status_dict() for route in routes],
            "route_count": len(routes),
            "configured_route_count": len(self.config.configured_routes()),
            "drop_params": self.config.drop_params,
            "litellm_proxy_base_url": runtime_snapshot.get("api_base_url", ""),
            "litellm_config_path": runtime_snapshot.get("config_path", ""),
            "litellm_log_path": runtime_snapshot.get("log_path", ""),
            "litellm_log_tail": runtime_snapshot.get("log_tail", []),
            "request_count": self.request_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_bytes_in": self.total_bytes_in,
            "total_bytes_out": self.total_bytes_out,
            "uptime_seconds": uptime_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
            "last_error": self.last_error,
            "recent_traffic": list(self.traffic_log),
        }

    def _local_base_url(self, base_path: str = "") -> str:
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return f"http://{host}:{self.port}{base_path}"

    async def create_response(self, body: dict[str, Any]) -> TransferResult:
        route = self._route_for_model(str(body.get("model") or ""))
        if route is not None and route.upstream_api == "chat_completions":
            return await self._proxy_response_via_chat_completions(body)
        return await self._proxy_post("responses", "/v1/responses", body)

    async def proxy_chat_completions(self, body: dict[str, Any]) -> TransferResult:
        return await self._proxy_post("chat/completions", "/v1/chat/completions", body)

    async def get_response(self, response_id: str) -> TransferResult:
        return await self._proxy_request("GET", f"responses/{response_id}", f"/v1/responses/{response_id}")

    async def delete_response(self, response_id: str) -> TransferResult:
        return await self._proxy_request("DELETE", f"responses/{response_id}", f"/v1/responses/{response_id}")

    def _route_for_model(self, model: str) -> LiteLLMRouteConfig | None:
        routes = self.config.effective_routes()
        normalized = str(model or "").strip()
        if normalized:
            for route in routes:
                if route.model_alias == normalized:
                    return route
        return routes[0] if routes else None

    async def _proxy_response_via_chat_completions(self, body: dict[str, Any]) -> TransferResult:
        chat_body = _responses_to_chat_completion_request(body)
        model = str(chat_body.get("model") or body.get("model") or self.config.model_alias or "")
        bytes_in = _json_size(body)
        if body.get("stream"):
            start_time = time.time()
            try:
                return await self._open_response_chat_stream(chat_body, model, bytes_in, start_time)
            except TransferServiceError as exc:
                self._record_failure("POST", "/v1/responses -> /v1/chat/completions", model, bytes_in, 0, start_time, exc.message, status=exc.status)
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
                self._record_failure("POST", "/v1/responses -> /v1/chat/completions", model, bytes_in, 0, start_time, str(exc), status=502)
                raise TransferServiceError(502, f"LiteLLM proxy request failed: {exc}", code="litellm_proxy_error") from exc
        result = await self._proxy_request(
            "POST",
            "chat/completions",
            "/v1/responses -> /v1/chat/completions",
            body=chat_body,
            model=model,
            bytes_in=bytes_in,
            transform_json=lambda data: _chat_completion_to_response(data, body),
        )
        return result

    async def _proxy_post(self, runtime_endpoint: str, traffic_endpoint: str, body: dict[str, Any]) -> TransferResult:
        method = "POST"
        model = str(body.get("model") or self.config.model_alias or "")
        bytes_in = _json_size(body)
        if body.get("stream"):
            start_time = time.time()
            try:
                return await self._open_stream(method, runtime_endpoint, traffic_endpoint, body, model, bytes_in, start_time)
            except TransferServiceError as exc:
                self._record_failure(method, traffic_endpoint, model, bytes_in, 0, start_time, exc.message, status=exc.status)
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
                self._record_failure(method, traffic_endpoint, model, bytes_in, 0, start_time, str(exc), status=502)
                raise TransferServiceError(502, f"LiteLLM proxy request failed: {exc}", code="litellm_proxy_error") from exc
        return await self._proxy_request(method, runtime_endpoint, traffic_endpoint, body=body, model=model, bytes_in=bytes_in)

    async def _proxy_request(
        self,
        method: str,
        runtime_endpoint: str,
        traffic_endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        model: str = "",
        bytes_in: int = 0,
        transform_json: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> TransferResult:
        await self.ensure_runtime()
        assert self._client is not None
        start_time = time.time()
        url = self._runtime_url(runtime_endpoint)
        try:
            async with self._client.request(method, url, json=body, headers=self._runtime_headers()) as response:
                raw = await response.read()
                if response.status >= 400:
                    message = _extract_error_message(response.status, raw)
                    self.last_error = message[:500]
                    self._record_failure(method, traffic_endpoint, model, bytes_in, len(raw), start_time, message, status=response.status)
                    raise TransferServiceError(response.status, message, code="litellm_proxy_error")
                content_type = _content_type_header(response)
                data: Any | None = None
                raw_body: bytes | None = raw
                usage: dict[str, int] = {}
                if content_type == "application/json" or not raw:
                    try:
                        data = json.loads(raw.decode("utf-8")) if raw else {}
                        raw_body = None
                        if isinstance(data, dict):
                            if transform_json is not None:
                                data = transform_json(data)
                            model = str(data.get("model") or model)
                            usage = _extract_usage(data)
                    except json.JSONDecodeError:
                        data = None
                        raw_body = raw
                self._record_success(method, traffic_endpoint, model, bytes_in, len(raw), start_time, usage, status=response.status)
                return TransferResult(
                    data=data,
                    raw_body=raw_body,
                    status=response.status,
                    headers=_copy_response_headers(response),
                    content_type=content_type,
                )
        except asyncio.TimeoutError as exc:
            self.last_error = "LiteLLM proxy request timed out"
            self._record_failure(method, traffic_endpoint, model, bytes_in, 0, start_time, self.last_error, status=504)
            raise TransferServiceError(504, self.last_error, code="litellm_timeout") from exc
        except ClientConnectionError as exc:
            self.last_error = str(exc)
            self._record_failure(method, traffic_endpoint, model, bytes_in, 0, start_time, self.last_error, status=502)
            raise TransferServiceError(502, f"LiteLLM proxy connection failed: {exc}", code="litellm_proxy_error") from exc

    async def _open_stream(
        self,
        method: str,
        runtime_endpoint: str,
        traffic_endpoint: str,
        body: dict[str, Any],
        model: str,
        bytes_in: int,
        start_time: float,
    ) -> TransferResult:
        await self.ensure_runtime()
        assert self._client is not None
        url = self._runtime_url(runtime_endpoint)
        response = await self._client.request(method, url, json=body, headers=self._runtime_headers())
        if response.status >= 400:
            raw = await response.read()
            response.release()
            raise TransferServiceError(response.status, _extract_error_message(response.status, raw), code="litellm_proxy_error")

        parser = _SSEUsageParser()
        total_out = 0
        failed = False

        async def stream() -> AsyncIterator[bytes]:
            nonlocal total_out, failed, model
            try:
                async for chunk in response.content.iter_any():
                    total_out += len(chunk)
                    parser.feed(chunk)
                    if parser.model:
                        model = parser.model
                    yield chunk
            except Exception as exc:
                failed = True
                self.last_error = str(exc)
                self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
                yield f'event: error\ndata: {json.dumps({"error": {"message": str(exc), "code": "stream_error"}}, ensure_ascii=False)}\n\n'.encode("utf-8")
            finally:
                response.release()
                if failed:
                    self._record_failure(method, f"{traffic_endpoint} (stream)", model, bytes_in, total_out, start_time, self.last_error)
                else:
                    if not parser.usage:
                        self.trace_event("warning", {"message": "usage_missing", "endpoint": f"{traffic_endpoint} (stream)", "model": model})
                    self._record_success(method, f"{traffic_endpoint} (stream)", model, bytes_in, total_out, start_time, parser.usage, status=response.status)

        return TransferResult(
            status=response.status,
            headers=_copy_response_headers(response),
            stream=stream(),
            content_type=_content_type_header(response),
        )

    async def _open_response_chat_stream(
        self,
        chat_body: dict[str, Any],
        model: str,
        bytes_in: int,
        start_time: float,
    ) -> TransferResult:
        await self.ensure_runtime()
        assert self._client is not None
        url = self._runtime_url("chat/completions")
        response = await self._client.request("POST", url, json=chat_body, headers=self._runtime_headers())
        if response.status >= 400:
            raw = await response.read()
            response.release()
            raise TransferServiceError(response.status, _extract_error_message(response.status, raw), code="litellm_proxy_error")

        response_id = f"resp_{uuid.uuid4().hex[:24]}"
        message_id = f"msg_{uuid.uuid4().hex[:24]}"
        created_at = int(time.time())
        full_text = ""
        usage = _normalize_chat_usage_to_response_usage(None)
        total_out = 0
        failed = False

        async def stream() -> AsyncIterator[bytes]:
            nonlocal full_text, usage, total_out, failed, model
            buffer = ""
            text_started = False
            try:
                yield _sse_event(
                    "response.created",
                    {
                        "response": _build_response_payload(
                            response_id=response_id,
                            model=model,
                            created_at=created_at,
                            text="",
                            usage=usage,
                            status="in_progress",
                            message_id=message_id,
                        )
                    },
                )
                yield _sse_event(
                    "response.in_progress",
                    {
                        "response": _build_response_payload(
                            response_id=response_id,
                            model=model,
                            created_at=created_at,
                            text="",
                            usage=usage,
                            status="in_progress",
                            message_id=message_id,
                        )
                    },
                )

                async for chunk in response.content.iter_any():
                    total_out += len(chunk)
                    buffer += chunk.decode("utf-8", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.rstrip("\r")
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        if data == "[DONE]":
                            continue
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("model"):
                            model = str(payload.get("model") or model)
                        if isinstance(payload.get("usage"), dict):
                            usage = _normalize_chat_usage_to_response_usage(payload.get("usage"))
                        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
                        for choice in choices:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                            content = delta.get("content")
                            if not content:
                                continue
                            text_delta = str(content)
                            if not text_started:
                                text_started = True
                                yield _sse_event(
                                    "response.output_item.added",
                                    {
                                        "output_index": 0,
                                        "item": {
                                            "id": message_id,
                                            "type": "message",
                                            "status": "in_progress",
                                            "role": "assistant",
                                            "content": [],
                                        },
                                    },
                                )
                                yield _sse_event(
                                    "response.content_part.added",
                                    {
                                        "item_id": message_id,
                                        "output_index": 0,
                                        "content_index": 0,
                                        "part": {"type": "output_text", "text": "", "annotations": []},
                                    },
                                )
                            full_text += text_delta
                            yield _sse_event(
                                "response.output_text.delta",
                                {
                                    "item_id": message_id,
                                    "output_index": 0,
                                    "content_index": 0,
                                    "delta": text_delta,
                                },
                            )
                if not text_started:
                    yield _sse_event(
                        "response.output_item.added",
                        {
                            "output_index": 0,
                            "item": {
                                "id": message_id,
                                "type": "message",
                                "status": "in_progress",
                                "role": "assistant",
                                "content": [],
                            },
                        },
                    )
                    yield _sse_event(
                        "response.content_part.added",
                        {
                            "item_id": message_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {"type": "output_text", "text": "", "annotations": []},
                        },
                    )
                yield _sse_event(
                    "response.output_text.done",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": full_text,
                    },
                )
                yield _sse_event(
                    "response.content_part.done",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": full_text, "annotations": []},
                    },
                )
                output_item = {
                    "id": message_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": full_text, "annotations": []}],
                }
                yield _sse_event(
                    "response.output_item.done",
                    {
                        "output_index": 0,
                        "item": output_item,
                    },
                )
                yield _sse_event(
                    "response.completed",
                    {
                        "response": _build_response_payload(
                            response_id=response_id,
                            model=model,
                            created_at=created_at,
                            text=full_text,
                            usage=usage,
                            status="completed",
                            message_id=message_id,
                        )
                    },
                )
            except Exception as exc:
                failed = True
                self.last_error = str(exc)
                self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
                yield _sse_event("error", {"error": {"message": str(exc), "code": "stream_error"}})
            finally:
                response.release()
                if failed:
                    self._record_failure("POST", "/v1/responses -> /v1/chat/completions (stream)", model, bytes_in, total_out, start_time, self.last_error)
                else:
                    if usage["total_tokens"] == 0:
                        self.trace_event("warning", {"message": "usage_missing", "endpoint": "/v1/responses -> /v1/chat/completions (stream)", "model": model})
                    self._record_success("POST", "/v1/responses -> /v1/chat/completions (stream)", model, bytes_in, total_out, start_time, usage, status=response.status)

        return TransferResult(
            status=response.status,
            headers=_copy_response_headers(response),
            stream=stream(),
            content_type="text/event-stream",
        )

    def _runtime_url(self, runtime_endpoint: str) -> str:
        base = self.runtime.api_base_url.rstrip("/")
        return f"{base}/{runtime_endpoint.lstrip('/')}"

    def _runtime_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.runtime.master_key}",
            "Content-Type": "application/json",
        }

    def _record_success(
        self,
        method: str,
        endpoint: str,
        model: str,
        bytes_in: int,
        bytes_out: int,
        start_time: float,
        usage: dict[str, Any],
        *,
        status: int = 200,
    ) -> None:
        duration = (time.time() - start_time) * 1000
        self.request_count += 1
        self.total_bytes_in += bytes_in
        self.total_bytes_out += bytes_out
        self.total_input_tokens += int(usage.get("input_tokens") or 0)
        self.total_output_tokens += int(usage.get("output_tokens") or 0)
        self.last_request_at = datetime.now()
        self.last_error = ""
        self.traffic_log.append(TrafficRecord(method, endpoint, status, bytes_in, bytes_out, duration, model=model).to_dict())

    def _record_failure(
        self,
        method: str,
        endpoint: str,
        model: str,
        bytes_in: int,
        bytes_out: int,
        start_time: float,
        error: str,
        *,
        status: int = 502,
    ) -> None:
        duration = (time.time() - start_time) * 1000
        self.last_request_at = datetime.now()
        self.last_error = error[:500]
        self.traffic_log.append(TrafficRecord(method, endpoint, status, bytes_in, bytes_out, duration, model=model, error=error[:200]).to_dict())

    def trace_event(self, kind: str, payload: Any) -> None:
        if os.environ.get("TRANSFER_TRACE") != "1":
            return
        record = {"ts": datetime.now().isoformat(timespec="milliseconds"), "kind": kind, "payload": self._redact(payload)}
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                lowered = str(key).lower()
                redacted[key] = cls._mask_secret(item) if any(word in lowered for word in ("key", "token", "authorization", "secret")) else cls._redact(item)
            return redacted
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        if isinstance(value, str) and len(value) > TRACE_STRING_LIMIT:
            return f"{value[:TRACE_STRING_HEAD]}...<truncated {len(value) - TRACE_STRING_HEAD} chars>"
        return value

    @staticmethod
    def _mask_secret(value: Any) -> Any:
        if not isinstance(value, str) or len(value) <= 10:
            return "***" if value else value
        return f"{value[:6]}...{value[-4:]}"
