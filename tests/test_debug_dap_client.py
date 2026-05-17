from __future__ import annotations

import asyncio
import json

import pytest

from bot.debug.providers.dap_client import DapClient


class _FakeWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _packet(payload: dict[str, object]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


@pytest.mark.asyncio
async def test_dap_client_sends_request_and_receives_response() -> None:
    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    client = DapClient(reader, writer)
    await client.start()
    pending = asyncio.create_task(client.request("initialize", {"clientID": "pytest"}))

    await asyncio.sleep(0)
    request_body = writer.buffer.decode("utf-8")
    assert "initialize" in request_body

    reader.feed_data(_packet({"type": "response", "request_seq": 1, "success": True, "command": "initialize", "body": {"supportsEvaluateForHovers": True}}))
    result = await asyncio.wait_for(pending, timeout=1)
    await client.close()

    assert result["supportsEvaluateForHovers"] is True
    assert writer.closed is True


@pytest.mark.asyncio
async def test_dap_client_queues_events() -> None:
    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    client = DapClient(reader, writer)
    await client.start()

    reader.feed_data(_packet({"type": "event", "event": "stopped", "body": {"reason": "breakpoint"}}))
    event = await asyncio.wait_for(client.events().__anext__(), timeout=1)
    await client.close()

    assert event["event"] == "stopped"
    assert event["body"]["reason"] == "breakpoint"

