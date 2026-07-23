from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

from bot.language_server.jsonrpc import (
    LspJsonRpcClient,
    LspJsonRpcClosedError,
    LspJsonRpcProtocolError,
    LspJsonRpcTimeoutError,
)


async def _start_fake_lsp(script: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


class _GatedWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.first_drain_started = asyncio.Event()
        self.release_first_drain = asyncio.Event()
        self.active_drains = 0
        self.max_active_drains = 0
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def drain(self) -> None:
        self.active_drains += 1
        self.max_active_drains = max(self.max_active_drains, self.active_drains)
        try:
            if len(self.frames) == 1:
                self.first_drain_started.set()
                await self.release_first_drain.wait()
        finally:
            self.active_drains -= 1

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, writer: Any) -> None:
        self.stdin = writer
        self.stdout = asyncio.StreamReader()
        self.returncode: int | None = None


class _CancelBlockingWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.cancel_written = asyncio.Event()
        self.cancel_drain_started = asyncio.Event()
        self.release_cancel_drain = asyncio.Event()
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)
        if b"$/cancelRequest" in frame:
            self.cancel_written.set()

    async def drain(self) -> None:
        if self.frames and b"$/cancelRequest" in self.frames[-1]:
            self.cancel_drain_started.set()
            await self.release_cancel_drain.wait()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _BrokenSecondWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.first_frame_written = asyncio.Event()
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)
        if len(self.frames) == 1:
            self.first_frame_written.set()

    async def drain(self) -> None:
        if len(self.frames) == 2:
            raise BrokenPipeError("fake LSP stdin closed")

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _CloseBlockingWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.drain_started = asyncio.Event()
        self.release_drain = asyncio.Event()
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def drain(self) -> None:
        self.drain_started.set()
        await self.release_drain.wait()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _WaitClosedBlockingWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.closed = False

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        await asyncio.Event().wait()


def _frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload


def _decode_frame(frame: bytes) -> dict[str, Any]:
    _headers, payload = frame.split(b"\r\n\r\n", 1)
    return json.loads(payload.decode("utf-8"))


@pytest.mark.asyncio
async def test_client_frames_fragmented_messages_and_matches_multiple_responses() -> None:
    process = await _start_fake_lsp(
        r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(0)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def send(message, fragment_at=7):
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    frame = b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload
    for offset in range(0, len(frame), fragment_at):
        sys.stdout.buffer.write(frame[offset:offset + fragment_at])
        sys.stdout.buffer.flush()


first = read_message()
second = read_message()
send({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "就绪🙂"}}, 3)
for request in (second, first):
    send({"jsonrpc": "2.0", "id": request["id"], "result": {"method": request["method"]}}, 5)
shutdown = read_message()
assert shutdown["method"] == "shutdown"
send({"jsonrpc": "2.0", "id": shutdown["id"], "result": None}, 2)
exit_message = read_message()
assert exit_message["method"] == "exit"
'''
    )
    received_notifications: list[tuple[str, Any]] = []
    notification_seen = asyncio.Event()

    async def on_notification(method: str, params: Any) -> None:
        received_notifications.append((method, params))
        notification_seen.set()

    client = LspJsonRpcClient(process, notification_handler=on_notification)
    first, second = await asyncio.gather(
        client.request("first", {"value": 1}),
        client.request("second", {"value": 2}),
    )

    assert first == {"method": "first"}
    assert second == {"method": "second"}
    await asyncio.wait_for(notification_seen.wait(), timeout=1)
    assert received_notifications == [("window/logMessage", {"message": "就绪🙂"})]

    await client.shutdown(timeout_seconds=1)
    await client.close()
    assert await asyncio.wait_for(process.wait(), timeout=1) == 0


@pytest.mark.asyncio
async def test_timeout_sends_cancel_request_and_cleans_pending_future() -> None:
    process = await _start_fake_lsp(
        r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(1)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def send(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload)
    sys.stdout.buffer.flush()


request = read_message()
cancel = read_message()
assert cancel == {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request["id"]}}
send({"jsonrpc": "2.0", "id": request["id"], "result": "late"})
'''
    )
    client = LspJsonRpcClient(process, request_timeout_seconds=0.05)

    with pytest.raises(LspJsonRpcTimeoutError):
        await client.request("slow")

    assert client.pending_count == 0
    assert await asyncio.wait_for(process.wait(), timeout=1) == 0
    await client.close()


@pytest.mark.asyncio
async def test_default_server_request_handlers_reply_without_blocking_stdout_reader() -> None:
    process = await _start_fake_lsp(
        r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(1)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def send(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload)
    sys.stdout.buffer.flush()


send({"jsonrpc": "2.0", "id": "configuration", "method": "workspace/configuration", "params": {"items": [{}, {}]}})
send({"jsonrpc": "2.0", "id": 2, "method": "window/workDoneProgress/create", "params": {"token": "index"}})
send({"jsonrpc": "2.0", "id": "unsupported", "method": "workspace/unsupported"})
responses = {str(message["id"]): message for message in (read_message(), read_message(), read_message())}
assert responses["configuration"] == {"jsonrpc": "2.0", "id": "configuration", "result": [None, None]}
assert responses["2"] == {"jsonrpc": "2.0", "id": 2, "result": None}
assert responses["unsupported"]["error"]["code"] == -32601
'''
    )
    client = LspJsonRpcClient(process)

    await client.start()

    assert await asyncio.wait_for(process.wait(), timeout=1) == 0
    await client.close()


@pytest.mark.asyncio
async def test_oversized_inbound_frame_fails_pending_request_without_reading_body() -> None:
    process = await _start_fake_lsp(
        r'''
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(1)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    sys.stdin.buffer.read(int(headers["content-length"]))


read_message()
sys.stdout.buffer.write(b"Content-Length: 257\r\n\r\n")
sys.stdout.buffer.flush()
sys.stdin.buffer.read()
'''
    )
    client = LspJsonRpcClient(process, max_message_bytes=256)

    with pytest.raises(LspJsonRpcProtocolError, match="超过 256 字节限制"):
        await client.request("small")

    assert client.pending_count == 0
    await client.close()
    assert await asyncio.wait_for(process.wait(), timeout=1) == 0


@pytest.mark.asyncio
async def test_close_fails_pending_request_and_releases_the_fake_lsp_process() -> None:
    process = await _start_fake_lsp(
        r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(1)
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def send(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload)
    sys.stdout.buffer.flush()


read_message()
send({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "request received"}})
sys.stdin.buffer.read()
'''
    )
    request_received = asyncio.Event()

    async def on_notification(method: str, params: Any) -> None:
        if method == "window/logMessage" and params == {"message": "request received"}:
            request_received.set()

    client = LspJsonRpcClient(process, notification_handler=on_notification)
    pending_request = asyncio.create_task(client.request("wait-forever", timeout_seconds=5))
    await asyncio.wait_for(request_received.wait(), timeout=1)

    await client.close()

    with pytest.raises(LspJsonRpcClosedError):
        await pending_request
    assert client.pending_count == 0
    await client.close()
    assert await asyncio.wait_for(process.wait(), timeout=1) == 0


@pytest.mark.asyncio
async def test_writer_lock_keeps_a_second_frame_outside_the_first_drain() -> None:
    writer = _GatedWriter()
    client = LspJsonRpcClient(_FakeProcess(writer))

    first = asyncio.create_task(client.notify("first"))
    await asyncio.wait_for(writer.first_drain_started.wait(), timeout=1)
    second = asyncio.create_task(client.notify("second"))
    await asyncio.sleep(0)

    assert len(writer.frames) == 1
    assert writer.max_active_drains == 1

    writer.release_first_drain.set()
    await asyncio.gather(first, second)
    assert len(writer.frames) == 2
    assert writer.max_active_drains == 1

    await client.close()
    assert writer.closed is True


@pytest.mark.asyncio
async def test_outbound_message_limit_rejects_before_writing_a_frame() -> None:
    writer = _GatedWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), max_message_bytes=64)

    with pytest.raises(LspJsonRpcProtocolError, match="超过 64 字节限制"):
        await client.notify("too-large", {"content": "x" * 128})

    assert writer.frames == []
    await client.close()


@pytest.mark.asyncio
async def test_timeout_returns_without_waiting_for_a_blocked_cancel_drain() -> None:
    writer = _CancelBlockingWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), request_timeout_seconds=0.01)

    with pytest.raises(LspJsonRpcTimeoutError):
        await asyncio.wait_for(client.request("slow"), timeout=0.1)

    await asyncio.wait_for(writer.cancel_written.wait(), timeout=1)
    await asyncio.wait_for(writer.cancel_drain_started.wait(), timeout=1)
    assert len(writer.frames) == 2

    await client.close()
    assert writer.closed is True


@pytest.mark.asyncio
async def test_cancelling_request_sends_cancel_request_for_the_matching_lsp_id() -> None:
    writer = _CancelBlockingWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), request_timeout_seconds=5)
    request_task = asyncio.create_task(client.request("textDocument/definition"))
    while not writer.frames:
        await asyncio.sleep(0)

    request_task.cancel()
    result = await asyncio.gather(request_task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    await asyncio.wait_for(writer.cancel_written.wait(), timeout=1)
    assert _decode_frame(writer.frames[1]) == {
        "jsonrpc": "2.0",
        "method": "$/cancelRequest",
        "params": {"id": 1},
    }

    writer.release_cancel_drain.set()
    await client.close()


@pytest.mark.asyncio
async def test_shutdown_rejects_new_work_but_allows_the_required_exit_notification() -> None:
    writer = _GatedWriter()
    writer.release_first_drain.set()
    process = _FakeProcess(writer)
    client = LspJsonRpcClient(process)
    shutdown_request = asyncio.create_task(client.request("shutdown"))
    await asyncio.wait_for(writer.first_drain_started.wait(), timeout=1)
    process.stdout.feed_data(_frame({"jsonrpc": "2.0", "id": 1, "result": None}))
    await shutdown_request

    with pytest.raises(LspJsonRpcClosedError):
        await client.notify("after-shutdown")

    await client.notify("exit")

    with pytest.raises(LspJsonRpcClosedError):
        await client.request("after-exit")
    assert [_decode_frame(frame)["method"] for frame in writer.frames] == ["shutdown", "exit"]

    await client.close()


@pytest.mark.asyncio
async def test_stdin_write_failure_fails_every_pending_request_immediately() -> None:
    writer = _BrokenSecondWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), request_timeout_seconds=5)
    first_request = asyncio.create_task(client.request("first"))
    await asyncio.wait_for(writer.first_frame_written.wait(), timeout=1)

    with pytest.raises(LspJsonRpcClosedError, match="stdin 写入失败"):
        await client.request("second")
    with pytest.raises(LspJsonRpcClosedError, match="stdin 写入失败"):
        await asyncio.wait_for(first_request, timeout=0.1)
    assert client.pending_count == 0

    await client.close()
    assert writer.closed is True


@pytest.mark.asyncio
async def test_close_unblocks_a_caller_waiting_in_writer_drain() -> None:
    writer = _CloseBlockingWriter()
    client = LspJsonRpcClient(_FakeProcess(writer))
    blocked_notification = asyncio.create_task(client.notify("blocked"))
    await asyncio.wait_for(writer.drain_started.wait(), timeout=1)

    await asyncio.wait_for(client.close(), timeout=0.1)

    with pytest.raises(LspJsonRpcClosedError):
        await asyncio.wait_for(blocked_notification, timeout=0.1)
    assert writer.closed is True


@pytest.mark.asyncio
async def test_notification_write_uses_the_client_deadline_when_drain_stalls() -> None:
    writer = _CloseBlockingWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), request_timeout_seconds=0.01)

    with pytest.raises(LspJsonRpcTimeoutError, match="写入超时"):
        await asyncio.wait_for(client.notify("blocked"), timeout=0.1)

    await asyncio.wait_for(client.close(), timeout=0.1)
    assert writer.closed is True


@pytest.mark.asyncio
async def test_close_bounds_writer_wait_closed() -> None:
    writer = _WaitClosedBlockingWriter()
    client = LspJsonRpcClient(_FakeProcess(writer), request_timeout_seconds=0.01)

    await asyncio.wait_for(client.close(timeout_seconds=0.01), timeout=0.1)

    assert writer.closed is True


@pytest.mark.asyncio
async def test_close_unblocks_a_waiter_for_the_next_notification() -> None:
    client = LspJsonRpcClient(_FakeProcess(_GatedWriter()))
    notification_waiter = asyncio.create_task(client.next_notification())
    await asyncio.sleep(0)

    await client.close()

    with pytest.raises(LspJsonRpcClosedError):
        await asyncio.wait_for(notification_waiter, timeout=0.1)


@pytest.mark.asyncio
async def test_notification_callback_task_limit_drops_backlogged_callbacks() -> None:
    writer = _GatedWriter()
    process = _FakeProcess(writer)
    callback_started = asyncio.Event()
    allow_callback = asyncio.Event()
    callback_messages: list[str] = []

    async def on_notification(method: str, params: Any) -> None:
        callback_messages.append(f"{method}:{params['message']}")
        callback_started.set()
        await allow_callback.wait()

    client = LspJsonRpcClient(
        process,
        notification_handler=on_notification,
        max_notification_handler_tasks=1,
    )
    await client.start()
    process.stdout.feed_data(
        _frame({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "first"}})
        + _frame({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "second"}})
    )
    await asyncio.wait_for(callback_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert callback_messages == ["window/logMessage:first"]

    allow_callback.set()
    await asyncio.sleep(0)
    await client.close()


@pytest.mark.asyncio
async def test_callback_handled_notification_is_not_duplicated_in_the_pull_queue() -> None:
    writer = _GatedWriter()
    process = _FakeProcess(writer)
    callback_received = asyncio.Event()

    async def on_notification(_method: str, _params: Any) -> None:
        callback_received.set()

    client = LspJsonRpcClient(process, notification_handler=on_notification)
    await client.start()
    process.stdout.feed_data(
        _frame({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "ready"}})
    )

    await asyncio.wait_for(callback_received.wait(), timeout=1)
    assert client._notifications.qsize() == 0
    await client.close()
