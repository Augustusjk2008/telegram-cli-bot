import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.runtime_paths import get_transfer_config_path, get_transfer_trace_path
from bot.web.transfer_service import ProtocolConverter, TransferService, TransferServiceError


@pytest.mark.asyncio
async def test_transfer_config_uses_runtime_paths_and_never_echoes_remote_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    service = TransferService(host="127.0.0.1", port=8765)

    assert get_transfer_config_path() == tmp_path / "transfer" / "config.json"
    assert get_transfer_trace_path() == tmp_path / "transfer" / "trace.jsonl"
    assert service.config_path == get_transfer_config_path()
    assert service.get_status()["status"] == "not_configured"

    service.update_config(
        {
            "remote_base_url": "http://example.test/v1",
            "remote_api_key": "sk-secret-value",
            "remote_model": "gpt-test",
        }
    )

    status = service.get_status()
    assert status["enabled"] is True
    assert status["is_running"] is False
    assert status["local_endpoint"] == "http://127.0.0.1:8765"
    assert status["local_host"] == "127.0.0.1"
    assert status["local_port"] == 8765
    assert status["uptime_seconds"] == 0
    assert status["remote_api_key_set"] is True
    assert "remote_api_key" not in status
    saved = json.loads(get_transfer_config_path().read_text(encoding="utf-8"))
    assert saved["remote_api_key"] == "sk-secret-value"


def test_transfer_config_empty_key_preserves_secret_and_clear_key_removes_it(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json")
    service.update_config(
        {
            "remote_base_url": "https://remote.test/v1",
            "remote_api_key": "sk-secret-value",
            "remote_model": "gpt-test",
        }
    )

    service.update_config({"remote_base_url": "https://other.test/v1", "remote_api_key": ""})

    assert service.config.remote_base_url == "https://other.test/v1"
    assert service.config.remote_api_key == "sk-secret-value"
    assert service.get_status()["remote_api_key_set"] is True

    service.update_config({"clear_remote_api_key": True})

    assert service.config.remote_api_key == ""
    assert service.get_status()["remote_api_key_set"] is False


def test_transfer_config_rejects_non_http_remote_base_url(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json")

    with pytest.raises(TransferServiceError) as exc_info:
        service.update_config({"remote_base_url": "file:///tmp/provider", "remote_model": "gpt-test"})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_remote_base_url"


def test_transfer_config_reports_restart_required_for_local_host_port(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json")

    status = service.update_config({"local_host": "0.0.0.0", "local_port": 9999})

    assert service.host == "127.0.0.1"
    assert service.port == 8765
    assert status["local_host"] == "127.0.0.1"
    assert status["local_port"] == 8765
    assert status["restart_required"] is True


@pytest.mark.asyncio
async def test_create_response_forwards_to_chat_completions_and_normalizes_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    captured: dict[str, object] = {}

    async def chat_completions(request: web.Request) -> web.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_1",
                "created": 123,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "bridge-ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.create_response(
                {
                    "model": "codex-client-model",
                    "input": "hello",
                    "max_output_tokens": 16,
                }
            )
        finally:
            await service.close()

    assert captured["authorization"] == "Bearer sk-remote"
    assert captured["body"] == {
        "model": "codex-client-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 16,
    }
    assert result.status == 200
    assert result.data["object"] == "response"
    assert result.data["output"][0]["content"][0]["text"] == "bridge-ok"
    assert result.data["usage"] == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    status = service.get_status()
    assert status["request_count"] == 1
    assert status["total_input_tokens"] == 7
    assert status["total_output_tokens"] == 3


@pytest.mark.asyncio
async def test_create_response_records_upstream_http_error_in_recent_traffic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))

    async def chat_completions(request: web.Request) -> web.Response:
        return web.json_response({"error": {"message": "rate limited"}}, status=429)

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            with pytest.raises(TransferServiceError) as exc_info:
                await service.create_response({"input": "hello"})
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
async def test_streaming_response_emits_completed_event_with_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        chunks = [
            {"choices": [{"delta": {"content": "hi"}}]},
            {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
        ]
        for chunk in chunks:
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.create_response({"input": "hello", "stream": True})
            events = [event async for event in result.stream]
        finally:
            await service.close()

    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["usage"]["input_tokens"] == 2
    assert events[-1]["response"]["usage"]["output_tokens"] == 1


@pytest.mark.asyncio
async def test_streaming_response_traces_missing_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSFER_TRACE", "1")

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    trace_path = tmp_path / "trace.jsonl"
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765, trace_path=trace_path)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.create_response({"input": "hello", "stream": True})
            events = [event async for event in result.stream]
        finally:
            await service.close()

    assert events[-1]["type"] == "response.completed"
    trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(line["payload"].get("message") == "usage_missing" for line in trace_lines)


@pytest.mark.asyncio
async def test_streaming_response_retries_without_stream_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    seen_bodies: list[dict[str, object]] = []

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        seen_bodies.append(body)
        if "stream_options" in body:
            return web.json_response({"error": "stream_options is unsupported"}, status=400)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n')
        await response.write(b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\n')
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.create_response({"input": "hello", "stream": True})
            events = [event async for event in result.stream]
        finally:
            await service.close()

    assert len(seen_bodies) == 2
    assert "stream_options" in seen_bodies[0]
    assert "stream_options" not in seen_bodies[1]
    assert service.config.unsupported_stream_options is True
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["usage"]["input_tokens"] == 4


@pytest.mark.asyncio
async def test_chat_completions_streaming_retries_without_stream_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    seen_bodies: list[dict[str, object]] = []

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        seen_bodies.append(body)
        if "stream_options" in body:
            return web.json_response({"error": "include_usage is unsupported"}, status=400)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"id":"chunk_1","choices":[{"delta":{"content":"ok"}}]}\n\n')
        await response.write(b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\n')
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.proxy_chat_completions(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            )
            chunks = [chunk async for chunk in result.stream]
        finally:
            await service.close()

    assert len(seen_bodies) == 2
    assert "stream_options" in seen_bodies[0]
    assert "stream_options" not in seen_bodies[1]
    assert service.config.unsupported_stream_options is True
    assert chunks[-1]["type"] == "__done__"
    assert service.get_status()["request_count"] == 1


@pytest.mark.asyncio
async def test_streaming_response_converts_tool_call_deltas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))

    async def chat_completions(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"q"'},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ':"x"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
        ]
        for chunk in chunks:
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat_completions)
    async with TestServer(upstream) as upstream_server:
        service = TransferService(host="127.0.0.1", port=8765)
        service.update_config(
            {
                "remote_base_url": str(upstream_server.make_url("/v1")),
                "remote_api_key": "sk-remote",
                "remote_model": "gpt-remote",
            }
        )
        await service.start()
        try:
            result = await service.create_response(
                {
                    "input": "hello",
                    "stream": True,
                    "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
                }
            )
            events = [event async for event in result.stream]
        finally:
            await service.close()

    event_types = [event["type"] for event in events]
    assert "response.function_call_arguments.delta" in event_types
    assert "response.function_call_arguments.done" in event_types
    completed = events[-1]["response"]
    function_call = completed["output"][0]
    assert function_call["type"] == "function_call"
    assert function_call["name"] == "lookup"
    assert function_call["arguments"] == '{"q":"x"}'
    assert completed["usage"]["input_tokens"] == 5


def test_response_to_chat_request_converts_audio_refusal_and_tool_replay(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json")
    body = {
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "listen"},
                    {"type": "input_audio", "input_audio": {"data": "abc123", "format": "wav"}},
                    {"type": "refusal", "text": "blocked"},
                ],
            },
            {"type": "custom_tool_call", "name": "custom", "input": {"value": 1}},
            {"type": "mcp_call", "name": "tool", "arguments": "{}"},
            {"type": "web_search_call", "query": "docs"},
            {"type": "file_search_call", "query": "file"},
            {"type": "code_interpreter_call", "code": "print(1)"},
            {"type": "local_shell_call", "action": "pwd"},
            {"type": "image_generation_call", "prompt": "icon"},
            {"type": "custom_tool_call_output", "output": "done"},
            {"type": "mcp_list_tools", "tools": []},
            {"type": "mcp_approval_request", "id": "approval"},
            {"type": "mcp_approval_response", "approve": True},
            {"type": "local_shell_call_output", "output": "cwd"},
            {"type": "item_reference", "id": "ignored"},
        ],
    }

    chat = service.converter.response_to_chat_request(body)

    assert chat["messages"][0] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "listen"},
            {"type": "input_audio", "input_audio": {"data": "abc123", "format": "wav"}},
            {"type": "text", "text": "[Refused: blocked]"},
        ],
    }
    assistant_replays = [message for message in chat["messages"] if message["role"] == "assistant"]
    user_results = [message for message in chat["messages"] if message["role"] == "user" and isinstance(message["content"], str)]
    assert len(assistant_replays) == 7
    assert all(message["content"].startswith("[") for message in assistant_replays)
    assert len(user_results) == 5
    assert all(" result: " in message["content"] for message in user_results)


def test_chat_response_to_response_converts_list_content_refusal_image_computer_and_reasoning(tmp_path: Path) -> None:
    service = TransferService(host="127.0.0.1", port=8765, config_path=tmp_path / "transfer.json")

    response = service.converter.chat_response_to_response(
        {
            "id": "chatcmpl_1",
            "created": 123,
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "hello"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                            {"type": "refusal", "text": "cannot"},
                        ],
                        "tool_calls": [
                            {"id": "call_fn", "type": "function", "function": {"name": "lookup", "arguments": "{}"}},
                            {"id": "call_pc", "type": "computer_use", "action": {"type": "click"}},
                        ],
                        "reasoning_content": "thought summary",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        "client-model",
    )

    assert response["output"][0]["content"] == [
        {"type": "output_text", "text": "hello"},
        {"type": "output_image", "image_url": "data:image/png;base64,abc"},
        {"type": "refusal", "text": "cannot"},
    ]
    assert response["output"][1]["type"] == "function_call"
    assert response["output"][2] == {"type": "computer_call", "call_id": "call_pc", "action": {"type": "click"}}
    assert response["reasoning"] == {"effort": "high", "summary": "thought summary"}
