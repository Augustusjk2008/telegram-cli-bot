"""OpenAI-compatible transfer bridge service."""

from __future__ import annotations

import json
import os
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

from aiohttp import ClientResponse, ClientSession, ClientTimeout

from bot.runtime_paths import get_transfer_config_path, get_transfer_trace_path
from bot.web.openai_compatible_client import (
    OpenAICompatibleClient,
    OpenAICompatibleClientError,
    build_openai_compatible_headers,
)

REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
UNSUPPORTED_RESPONSE_TOOLS = {
    "web_search",
    "web_search_preview",
    "web_search_call",
    "file_search",
    "file_search_call",
    "computer",
    "computer_use",
    "computer_use_preview",
    "local_shell",
    "local_shell_call",
    "apply_patch",
}
PROVIDER_REASONING_EFFORT_FALLBACKS = {
    ("max.jojocode.com", "gpt-5.5", "minimal"): "low",
}
TRACE_STRING_LIMIT = 500
TRACE_STRING_HEAD = 240


@dataclass
class TransferConfig:
    remote_base_url: str = ""
    remote_api_key: str = ""
    remote_model: str = ""
    request_stream_usage: bool = True
    retry_without_stream_options: bool = True
    reasoning_mode: str = "chat_reasoning_effort"
    downgrade_developer_to_system: bool = False
    use_legacy_max_tokens: bool = False
    unsupported_stream_options: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.remote_base_url and self.remote_api_key and self.remote_model)

    def to_file_dict(self) -> dict[str, Any]:
        return {
            "remote_base_url": self.remote_base_url,
            "remote_api_key": self.remote_api_key,
            "remote_model": self.remote_model,
            "request_stream_usage": self.request_stream_usage,
            "retry_without_stream_options": self.retry_without_stream_options,
            "reasoning_mode": self.reasoning_mode,
            "downgrade_developer_to_system": self.downgrade_developer_to_system,
            "use_legacy_max_tokens": self.use_legacy_max_tokens,
        }


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
    data: dict[str, Any] | None = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    stream: AsyncIterator[dict[str, Any]] | None = None
    content_type: str = "application/json"


class TransferServiceError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "transfer_error") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class ProtocolConverter:
    def __init__(self, service: "TransferService") -> None:
        self.service = service

    def response_to_chat_request(self, body: dict[str, Any]) -> dict[str, Any]:
        config = self.service.config
        chat_body: dict[str, Any] = {"model": body.get("model", config.remote_model)}
        messages: list[dict[str, Any]] = []
        if body.get("instructions"):
            messages.append({"role": "system", "content": body["instructions"]})
        input_data = body.get("input", "")
        if isinstance(input_data, str):
            messages.append({"role": "user", "content": input_data})
        elif isinstance(input_data, list):
            for item in input_data:
                if isinstance(item, dict):
                    message = self._convert_input_item(item)
                    if message:
                        messages.append(message)
        chat_body["messages"] = messages

        param_map = {
            "temperature": "temperature",
            "top_p": "top_p",
            "max_output_tokens": "max_completion_tokens",
            "frequency_penalty": "frequency_penalty",
            "presence_penalty": "presence_penalty",
            "stop": "stop",
            "seed": "seed",
            "parallel_tool_calls": "parallel_tool_calls",
            "stream": "stream",
            "n": "n",
            "logprobs": "logprobs",
            "top_logprobs": "top_logprobs",
        }
        for resp_key, chat_key in param_map.items():
            if resp_key in body:
                chat_body[chat_key] = body[resp_key]
        if config.use_legacy_max_tokens and "max_completion_tokens" in chat_body:
            chat_body["max_tokens"] = chat_body.pop("max_completion_tokens")

        text = body.get("text")
        if isinstance(text, dict) and text.get("format"):
            chat_body["response_format"] = text["format"]
        if body.get("tools"):
            chat_body["tools"] = self._convert_tools_to_chat(body["tools"])
        if "tool_choice" in body:
            chat_body["tool_choice"] = body["tool_choice"]

        explicit_effort = body.get("reasoning_effort")
        if explicit_effort in REASONING_EFFORTS:
            chat_body["reasoning_effort"] = self.service.apply_reasoning_effort_fallback(explicit_effort, chat_body["model"])
        elif isinstance(body.get("reasoning"), dict):
            effort = body["reasoning"].get("effort")
            if effort in REASONING_EFFORTS:
                chat_body["reasoning_effort"] = self.service.apply_reasoning_effort_fallback(effort, chat_body["model"])
        if "metadata" in body:
            chat_body["metadata"] = body["metadata"]
        if "user" in body:
            chat_body["user"] = body["user"]
        return chat_body

    def _convert_input_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        item_type = item.get("type", "message")
        config = self.service.config
        if item_type == "message":
            role = item.get("role", "user")
            if role == "developer" and config.downgrade_developer_to_system:
                role = "system"
            content = item.get("content", "")
            if isinstance(content, list):
                converted = [part for part in (self._convert_content_part(p) for p in content if isinstance(p, dict)) if part]
                return {"role": role, "content": converted}
            return {"role": role, "content": str(content)}
        if item_type == "input_text":
            return {"role": "user", "content": item.get("text", "")}
        if item_type == "input_image":
            image_url = item.get("image_url") or item.get("file_id") or ""
            return {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url, "detail": item.get("detail", "auto")}}]}
        if item_type == "input_file":
            ref = item.get("file_id") or item.get("filename") or item.get("file_url") or "unknown"
            return {"role": "user", "content": f"[File: {ref}]"}
        if item_type == "input_audio":
            audio_data = item.get("input_audio") or {}
            if not isinstance(audio_data, dict):
                audio_data = {}
            return {
                "role": "user",
                "content": [{"type": "input_audio", "input_audio": {"data": audio_data.get("data", ""), "format": audio_data.get("format", "mp3")}}],
            }
        if item_type == "function_call":
            return {
                "role": "assistant",
                "tool_calls": [{"id": item.get("call_id", ""), "type": "function", "function": {"name": item.get("name", ""), "arguments": item.get("arguments", "")}}],
            }
        if item_type == "function_call_output":
            return {"role": "tool", "tool_call_id": item.get("call_id", ""), "content": item.get("output", "")}
        if item_type == "reasoning":
            return {"role": "system", "content": f"[Previous reasoning context: {item.get('id', '')}]"}
        if item_type in ("custom_tool_call", "mcp_call", "web_search_call", "file_search_call", "code_interpreter_call", "local_shell_call", "image_generation_call"):
            return {"role": "assistant", "content": f"[{item_type}: {json.dumps(item, ensure_ascii=False)}]"}
        if item_type in ("custom_tool_call_output", "mcp_list_tools", "mcp_approval_request", "mcp_approval_response", "local_shell_call_output"):
            return {"role": "user", "content": f"[{item_type} result: {json.dumps(item, ensure_ascii=False)}]"}
        if item_type == "item_reference":
            return None
        return None

    @staticmethod
    def _convert_content_part(part: dict[str, Any]) -> dict[str, Any] | None:
        part_type = part.get("type", "input_text")
        if part_type == "input_text":
            return {"type": "text", "text": part.get("text", "")}
        if part_type == "input_image":
            image_url = part.get("image_url") or part.get("file_id") or ""
            return {"type": "image_url", "image_url": {"url": image_url, "detail": part.get("detail", "auto")}}
        if part_type == "input_file":
            ref = part.get("file_id") or part.get("filename") or "unknown"
            return {"type": "text", "text": f"[File: {ref}]"}
        if part_type == "input_audio":
            audio_data = part.get("input_audio") or {}
            if not isinstance(audio_data, dict):
                audio_data = {}
            return {"type": "input_audio", "input_audio": {"data": audio_data.get("data", ""), "format": audio_data.get("format", "mp3")}}
        if part_type == "output_text":
            return {"type": "text", "text": part.get("text", "")}
        if part_type == "refusal":
            return {"type": "text", "text": f"[Refused: {part.get('text', '')}]"}
        return {"type": "text", "text": str(part)}

    def _convert_tools_to_chat(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools:
            tool_type = tool.get("type", "")
            if tool_type == "function":
                converted.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.get("name", ""),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", {}),
                            "strict": tool.get("strict", False),
                        },
                    }
                )
            elif tool_type in UNSUPPORTED_RESPONSE_TOOLS:
                self.service.trace_event("warning", {"message": "unsupported_response_tool", "tool": tool})
            else:
                converted.append(tool)
        return converted

    @staticmethod
    def normalize_chat_usage_to_response_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
        usage = usage or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or (input_tokens + output_tokens)),
            "input_tokens_details": {"cached_tokens": int(prompt_details.get("cached_tokens") or 0)},
            "output_tokens_details": {"reasoning_tokens": int(completion_details.get("reasoning_tokens") or 0)},
        }

    def chat_response_to_response(self, chat_response: dict[str, Any], original_model: str) -> dict[str, Any]:
        choice = (chat_response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        output: list[dict[str, Any]] = []
        content = message.get("content", "")
        if content:
            if isinstance(content, str):
                output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]})
            elif isinstance(content, list):
                converted_parts = [part for part in (self._convert_chat_content_part_to_response(p) for p in content if isinstance(p, dict)) if part]
                if converted_parts:
                    output.append({"type": "message", "role": "assistant", "content": converted_parts})
        if message.get("refusal") and not any(item.get("type") == "message" for item in output):
            output.append({"type": "message", "role": "assistant", "content": [{"type": "refusal", "text": str(message.get("refusal") or "")}]})
        for tc in message.get("tool_calls") or []:
            if tc.get("type") == "function":
                func = tc.get("function") or {}
                output.append({"type": "function_call", "call_id": tc.get("id", f"call_{uuid.uuid4().hex[:24]}"), "name": func.get("name", ""), "arguments": func.get("arguments", "")})
            elif tc.get("type") == "computer_use":
                output.append({"type": "computer_call", "call_id": tc.get("id", ""), "action": tc.get("action", {})})
        reasoning = {"effort": None, "summary": None}
        reasoning_content = message.get("reasoning_content", "")
        if reasoning_content:
            reasoning = {"effort": "high", "summary": str(reasoning_content)}
        usage = self.normalize_chat_usage_to_response_usage(chat_response.get("usage"))
        response = {
            "id": chat_response.get("id", f"resp_{uuid.uuid4().hex[:24]}"),
            "object": "response",
            "created_at": chat_response.get("created", int(time.time())),
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "max_output_tokens": None,
            "model": original_model,
            "output": output,
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": reasoning,
            "store": True,
            "temperature": 1.0,
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": 1.0,
            "truncation": "disabled",
            "usage": usage,
            "user": None,
            "metadata": {},
        }
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            response["incomplete_details"] = {"reason": "max_output_tokens"}
            response["status"] = "incomplete"
        elif finish_reason == "content_filter":
            response["incomplete_details"] = {"reason": "content_filter"}
            response["status"] = "incomplete"
        return response

    @staticmethod
    def _convert_chat_content_part_to_response(part: dict[str, Any]) -> dict[str, Any] | None:
        part_type = part.get("type", "text")
        if part_type == "text":
            return {"type": "output_text", "text": part.get("text", "")}
        if part_type == "image_url":
            image = part.get("image_url") or {}
            image_url = image.get("url", "") if isinstance(image, dict) else str(image)
            return {"type": "output_image", "image_url": image_url}
        if part_type == "refusal":
            return {"type": "refusal", "text": part.get("text", "")}
        return {"type": "output_text", "text": str(part)}


class ChatStreamAccumulator:
    def __init__(self, converter: ProtocolConverter, original_model: str, response_id: str | None = None) -> None:
        self.converter = converter
        self.original_model = original_model
        self.response_id = response_id or f"resp_{uuid.uuid4().hex[:24]}"
        self.created_at = int(time.time())
        self.message_id = f"msg_{uuid.uuid4().hex[:24]}"
        self.full_text = ""
        self.text_started = False
        self.text_done = False
        self.usage: dict[str, Any] | None = None
        self.message_output_index: int | None = None
        self.next_output_index = 0
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self.tool_items_added: set[int] = set()

    def initial_events(self) -> list[dict[str, Any]]:
        response = self._response_base("in_progress")
        return [{"type": "response.created", "response": response}, {"type": "response.in_progress", "response": response}]

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                events.extend(self._text_delta(str(content)))
            for tc in delta.get("tool_calls") or []:
                if isinstance(tc, dict):
                    events.extend(self._tool_delta(tc))
            if choice.get("finish_reason"):
                events.extend(self._finish_outputs())
        return events

    def finish(self) -> list[dict[str, Any]]:
        return self._finish_outputs() + [{"type": "response.completed", "response": self._response_base("completed")}]

    def _text_delta(self, content: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not self.text_started:
            self.message_output_index = self.next_output_index
            self.next_output_index += 1
            events.append({"type": "response.output_item.added", "output_index": self.message_output_index, "item": {"id": self.message_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}})
            events.append({"type": "response.content_part.added", "item_id": self.message_id, "output_index": self.message_output_index, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})
            self.text_started = True
        self.full_text += content
        events.append({"type": "response.output_text.delta", "item_id": self.message_id, "output_index": self.message_output_index, "content_index": 0, "delta": content})
        return events

    def _tool_delta(self, tc: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            index = int(tc.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        state = self.tool_calls.setdefault(
            index,
            {
                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "name": "",
                "arguments": "",
                "output_index": self.next_output_index,
            },
        )
        if tc.get("id"):
            state["id"] = tc["id"]
        func = tc.get("function") or {}
        if isinstance(func, dict) and func.get("name"):
            state["name"] = str(func["name"])
        args_delta = str(func.get("arguments") or "") if isinstance(func, dict) else ""
        events: list[dict[str, Any]] = []
        if index not in self.tool_items_added:
            self.tool_items_added.add(index)
            self.next_output_index = max(self.next_output_index, int(state["output_index"]) + 1)
            events.append(
                {
                    "type": "response.output_item.added",
                    "output_index": state["output_index"],
                    "item": {
                        "id": state["id"],
                        "type": "function_call",
                        "status": "in_progress",
                        "call_id": state["id"],
                        "name": state["name"],
                        "arguments": "",
                    },
                }
            )
        if args_delta:
            state["arguments"] += args_delta
            events.append(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": state["id"],
                    "output_index": state["output_index"],
                    "delta": args_delta,
                }
            )
        return events

    def _finish_outputs(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.text_started and not self.text_done:
            self.text_done = True
            events.extend(
                [
                    {"type": "response.output_text.done", "item_id": self.message_id, "output_index": self.message_output_index, "content_index": 0, "text": self.full_text},
                    {"type": "response.content_part.done", "item_id": self.message_id, "output_index": self.message_output_index, "content_index": 0, "part": {"type": "output_text", "text": self.full_text, "annotations": []}},
                    {"type": "response.output_item.done", "item_id": self.message_id, "output_index": self.message_output_index, "item": self._message_item()},
                ]
            )
        for index in sorted(self.tool_calls):
            state = self.tool_calls[index]
            if state.get("done"):
                continue
            state["done"] = True
            events.extend(
                [
                    {
                        "type": "response.function_call_arguments.done",
                        "item_id": state["id"],
                        "output_index": state["output_index"],
                        "arguments": state["arguments"],
                    },
                    {
                        "type": "response.output_item.done",
                        "item_id": state["id"],
                        "output_index": state["output_index"],
                        "item": self._function_item(state),
                    },
                ]
            )
        return events

    def _message_item(self) -> dict[str, Any]:
        return {"id": self.message_id, "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": self.full_text, "annotations": []}]}

    @staticmethod
    def _function_item(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": state["id"],
            "type": "function_call",
            "status": "completed",
            "call_id": state["id"],
            "name": state["name"],
            "arguments": state["arguments"],
        }

    def _response_base(self, status: str) -> dict[str, Any]:
        output = [self._message_item()] if self.text_started and (status == "completed" or self.text_done) else []
        for index in sorted(self.tool_calls):
            state = self.tool_calls[index]
            if status == "completed" or state.get("done"):
                output.append(self._function_item(state))
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "model": self.original_model,
            "output": output,
            "usage": ProtocolConverter.normalize_chat_usage_to_response_usage(self.usage),
        }


class TransferService:
    def __init__(self, *, host: str, port: int, config_path: Path | None = None, trace_path: Path | None = None) -> None:
        self.host = host
        self.port = port
        self.config_path = config_path or get_transfer_config_path()
        self.trace_path = trace_path or get_transfer_trace_path()
        self.config = TransferConfig()
        self.request_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_bytes_in = 0
        self.total_bytes_out = 0
        self.traffic_log: deque[dict[str, Any]] = deque(maxlen=200)
        self.is_running = False
        self.started_at: datetime | None = None
        self.last_request_at: datetime | None = None
        self.last_error = ""
        self._client: ClientSession | None = None
        self.converter = ProtocolConverter(self)
        self.load_config()
        self.apply_env_config()

    async def start(self) -> None:
        if self._client is None or self._client.closed:
            self._client = ClientSession(timeout=ClientTimeout(total=300))
        self.is_running = True
        self.started_at = datetime.now()

    async def close(self) -> None:
        if self._client is not None and not self._client.closed:
            await self._client.close()
        self.is_running = False

    def load_config(self) -> None:
        if not self.config_path.exists():
            return
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            self.update_config(data, save=False)

    def apply_env_config(self) -> None:
        env_map: dict[str, tuple[str, Callable[[str], Any]]] = {
            "TRANSFER_REMOTE_BASE_URL": ("remote_base_url", str),
            "TRANSFER_REMOTE_API_KEY": ("remote_api_key", str),
            "TRANSFER_REMOTE_MODEL": ("remote_model", str),
        }
        for env_key, (attr, caster) in env_map.items():
            if env_key in os.environ:
                setattr(self.config, attr, caster(os.environ[env_key]))

    def save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config.to_file_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def update_config(self, data: dict[str, Any], *, save: bool = True) -> dict[str, Any]:
        restart_required = False
        if any(key in data for key in ("local_host", "local_port")):
            restart_required = True
        if "remote_base_url" in data:
            remote_base_url = str(data.get("remote_base_url") or "").strip()
            if remote_base_url:
                parsed = urlparse(remote_base_url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise TransferServiceError(400, "remote_base_url 仅支持 http/https URL", code="invalid_remote_base_url")
            self.config.remote_base_url = remote_base_url
        if data.get("clear_remote_api_key") is True:
            self.config.remote_api_key = ""
        elif "remote_api_key" in data:
            remote_api_key = data.get("remote_api_key")
            if remote_api_key is not None and str(remote_api_key) != "":
                self.config.remote_api_key = str(remote_api_key)
        for key in self.config.to_file_dict():
            if key in {"remote_base_url", "remote_api_key"}:
                continue
            if key in data:
                setattr(self.config, key, data[key])
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
        status = "running" if enabled and self.is_running else "not_configured" if not enabled else "stopped"
        if self.last_error:
            status = "error"
        base = self._local_base_url(base_path)
        uptime_seconds = 0
        if self.started_at:
            uptime_seconds = max(0, int((datetime.now() - self.started_at).total_seconds()))
        return {
            "enabled": enabled,
            "running": bool(self.is_running and enabled),
            "is_running": bool(self.is_running),
            "status": status,
            "local_url": base,
            "local_endpoint": base,
            "local_host": self.host,
            "local_port": self.port,
            "bridge_page_url": f"{base_path}/api/transfer/page" if base_path else "/api/transfer/page",
            "responses_base_url": f"{base}/v1",
            "chat_completions_base_url": f"{base}/v1",
            "remote_base_url": self.config.remote_base_url,
            "remote_model": self.config.remote_model,
            "remote_api_key_set": bool(self.config.remote_api_key),
            "request_stream_usage": self.config.request_stream_usage,
            "retry_without_stream_options": self.config.retry_without_stream_options,
            "reasoning_mode": self.config.reasoning_mode,
            "downgrade_developer_to_system": self.config.downgrade_developer_to_system,
            "use_legacy_max_tokens": self.config.use_legacy_max_tokens,
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

    def _remote_chat_url(self) -> str:
        if not self.config.enabled:
            raise TransferServiceError(503, "Transfer bridge is not configured", code="transfer_not_configured")
        return f"{self.config.remote_base_url.rstrip('/')}/chat/completions"

    def build_remote_headers(self) -> dict[str, str]:
        return build_openai_compatible_headers(self.config.remote_api_key)

    def apply_reasoning_effort_fallback(self, effort: str, model: str) -> str:
        host = urlparse(self.config.remote_base_url).netloc.lower()
        model = (model or self.config.remote_model).lower()
        fallback = PROVIDER_REASONING_EFFORT_FALLBACKS.get((host, model, effort))
        if fallback:
            self.trace_event("warning", {"message": "reasoning_effort_fallback", "provider": host, "model": model, "from": effort, "to": fallback})
            return fallback
        return effort

    async def create_response(self, body: dict[str, Any]) -> TransferResult:
        if self._client is None or self._client.closed:
            await self.start()
        start_time = time.time()
        bytes_in = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        chat_body = self.converter.response_to_chat_request(body)
        original_model = str(body.get("model") or self.config.remote_model)
        if body.get("stream"):
            stream = self._stream_response(chat_body, original_model, bytes_in, start_time)
            return TransferResult(stream=stream, content_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        try:
            data = await self._post_json(self._remote_chat_url(), chat_body)
        except TransferServiceError as exc:
            self._record_failure("/v1/responses", original_model, bytes_in, 0, start_time, exc.message, status=exc.status)
            raise
        except Exception as exc:
            self.last_error = str(exc)
            self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
            self._record_failure("/v1/responses", original_model, bytes_in, 0, start_time, str(exc), status=502)
            raise
        converted = self.converter.chat_response_to_response(data, original_model)
        bytes_out = len(json.dumps(converted, ensure_ascii=False).encode("utf-8"))
        self._record_success("/v1/responses", original_model, bytes_in, bytes_out, start_time, converted.get("usage") or {})
        return TransferResult(data=converted)

    async def proxy_chat_completions(self, body: dict[str, Any]) -> TransferResult:
        if self._client is None or self._client.closed:
            await self.start()
        start_time = time.time()
        bytes_in = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if body.get("stream"):
            stream = self._stream_chat_completions(body, bytes_in, start_time)
            return TransferResult(
                stream=stream,
                content_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        model = str(body.get("model") or "")
        try:
            data = await self._post_json(self._remote_chat_url(), body)
        except TransferServiceError as exc:
            self._record_failure("/v1/chat/completions", model, bytes_in, 0, start_time, exc.message, status=exc.status)
            raise
        except Exception as exc:
            self.last_error = str(exc)
            self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
            self._record_failure("/v1/chat/completions", model, bytes_in, 0, start_time, str(exc), status=502)
            raise
        bytes_out = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        usage = data.get("usage") or {}
        self._record_success(
            "/v1/chat/completions",
            str(data.get("model") or body.get("model") or ""),
            bytes_in,
            bytes_out,
            start_time,
            {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
        )
        return TransferResult(data=data)

    async def _stream_chat_completions(self, body: dict[str, Any], bytes_in: int, start_time: float) -> AsyncIterator[dict[str, Any]]:
        total_out = 0
        usage: dict[str, Any] = {}
        model = str(body.get("model") or "")
        failed = False
        try:
            async for chunk in self._iter_raw_remote_sse_chunks(body):
                if isinstance(chunk, dict):
                    model = str(chunk.get("model") or model)
                    if chunk.get("usage"):
                        raw_usage = chunk.get("usage") or {}
                        usage = {"input_tokens": raw_usage.get("prompt_tokens", 0), "output_tokens": raw_usage.get("completion_tokens", 0)}
                total_out += len(json.dumps(chunk, ensure_ascii=False).encode("utf-8"))
                yield chunk
        except Exception as exc:
            failed = True
            self.last_error = str(exc)
            self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
            yield {"type": "error", "code": "stream_error", "message": str(exc)}
        finally:
            if failed:
                self._record_failure("/v1/chat/completions (stream)", model, bytes_in, total_out, start_time, self.last_error)
            else:
                if not usage:
                    self.trace_event("warning", {"message": "usage_missing", "endpoint": "/v1/chat/completions (stream)", "model": model})
                self._record_success("/v1/chat/completions (stream)", model, bytes_in, total_out, start_time, usage)

    async def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None
        client = OpenAICompatibleClient(self._client)
        try:
            return await client.post_json(url=url, api_key=self.config.remote_api_key, body=body)
        except OpenAICompatibleClientError as exc:
            self.last_error = exc.message[:500]
            raise TransferServiceError(exc.status, exc.message, code=exc.code) from exc

    async def _stream_response(self, chat_body: dict[str, Any], original_model: str, bytes_in: int, start_time: float) -> AsyncIterator[dict[str, Any]]:
        assert self._client is not None
        response_id = f"resp_{uuid.uuid4().hex[:24]}"
        stream_body = json.loads(json.dumps(chat_body))
        if self.config.request_stream_usage and not self.config.unsupported_stream_options:
            stream_body.setdefault("stream_options", {})["include_usage"] = True
        accumulator = ChatStreamAccumulator(self.converter, original_model, response_id=response_id)
        total_out = 0
        failed = False
        try:
            for event in accumulator.initial_events():
                total_out += len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
                yield event
            async for event in self._iter_remote_sse_events(stream_body, accumulator):
                total_out += len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
                yield event
        except Exception as exc:
            failed = True
            self.last_error = str(exc)
            self.trace_event("error", {"detail": str(exc), "stack": traceback.format_exc()})
            yield {"type": "error", "code": "stream_error", "message": str(exc)}
        finally:
            usage = accumulator._response_base("completed").get("usage") or {}
            if failed:
                self._record_failure("/v1/responses (stream)", original_model, bytes_in, total_out, start_time, self.last_error)
            else:
                if accumulator.usage is None:
                    self.trace_event("warning", {"message": "usage_missing", "endpoint": "/v1/responses (stream)", "model": original_model})
                self._record_success("/v1/responses (stream)", original_model, bytes_in, total_out, start_time, usage)

    async def _iter_remote_sse_events(self, body: dict[str, Any], accumulator: ChatStreamAccumulator) -> AsyncIterator[dict[str, Any]]:
        assert self._client is not None
        async with self._client.post(self._remote_chat_url(), json=body, headers=self.build_remote_headers()) as response:
            if (
                response.status == 400
                and self.config.retry_without_stream_options
                and "stream_options" in body
                and await self._remote_rejects_stream_options(response)
            ):
                fallback_body = json.loads(json.dumps(body))
                fallback_body.pop("stream_options", None)
                async for event in self._iter_remote_sse_events(fallback_body, accumulator):
                    yield event
                return
            await self._raise_for_status(response)
            async for raw_line in response.content:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    for event in accumulator.finish():
                        yield event
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for event in accumulator.process_chunk(chunk):
                    yield event

    async def _iter_raw_remote_sse_chunks(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        assert self._client is not None
        async with self._client.post(self._remote_chat_url(), json=body, headers=self.build_remote_headers()) as response:
            if (
                response.status == 400
                and self.config.retry_without_stream_options
                and "stream_options" in body
                and await self._remote_rejects_stream_options(response)
            ):
                fallback_body = json.loads(json.dumps(body))
                fallback_body.pop("stream_options", None)
                async for chunk in self._iter_raw_remote_sse_chunks(fallback_body):
                    yield chunk
                return
            await self._raise_for_status(response)
            async for raw_line in response.content:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    yield {"type": "__done__"}
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict):
                    yield chunk

    async def _remote_rejects_stream_options(self, response: ClientResponse) -> bool:
        text = await response.text()
        if "stream_options" not in text and "include_usage" not in text:
            self.last_error = text[:500]
            return False
        self.config.unsupported_stream_options = True
        self.trace_event("warning", {"message": "retry_without_stream_options", "error": text[:500]})
        return True

    async def _raise_for_status(self, response: ClientResponse) -> None:
        if response.status < 400:
            return
        text = await response.text()
        self.last_error = text[:500]
        raise TransferServiceError(response.status, f"Remote API error: {text[:500]}", code="remote_api_error")

    def _record_success(self, endpoint: str, model: str, bytes_in: int, bytes_out: int, start_time: float, usage: dict[str, Any]) -> None:
        duration = (time.time() - start_time) * 1000
        self.request_count += 1
        self.total_bytes_in += bytes_in
        self.total_bytes_out += bytes_out
        self.total_input_tokens += int(usage.get("input_tokens") or 0)
        self.total_output_tokens += int(usage.get("output_tokens") or 0)
        self.last_request_at = datetime.now()
        self.last_error = ""
        self.traffic_log.append(TrafficRecord("POST", endpoint, 200, bytes_in, bytes_out, duration, model=model).to_dict())

    def _record_failure(self, endpoint: str, model: str, bytes_in: int, bytes_out: int, start_time: float, error: str, *, status: int = 502) -> None:
        duration = (time.time() - start_time) * 1000
        self.last_request_at = datetime.now()
        self.last_error = error[:500]
        self.traffic_log.append(TrafficRecord("POST", endpoint, status, bytes_in, bytes_out, duration, model=model, error=error[:200]).to_dict())

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
