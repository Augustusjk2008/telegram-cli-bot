from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession
from bot.web.api_common import AuthContext, resolve_session_bot_id
from bot.web.auth_store import CAP_CHAT_SEND, CAP_VIEW_CHAT_TRACE
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import PROCESS_TRACE_RAW_TYPES, ChatStore
from bot.web.permission_store import BotPermissionStore
from bot.web.server import WebApiServer
from bot.web.trace_compaction import (
    REMAPPED_PROCESS_RAW_TYPES,
    TRACE_PAYLOAD_PREVIEW_CHARS,
    TRACE_SUMMARY_PREVIEW_CHARS,
    compact_trace_event,
)

BIG_OUTPUT = "".join(f"line {index}\n" for index in range(20_000))


def _begin(store: ChatStore, *, text: str = "hello", native_provider: str = "claude", bot_id: int = 1, user_id: int = 2):
    return store.begin_turn(
        bot_id=bot_id,
        bot_alias="main",
        user_id=user_id,
        agent_id="main",
        cli_type="claude",
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        user_text=text,
        native_provider=native_provider,
    )


def _is_preview_of(preview: str, full: str) -> bool:
    return 0 < len(preview) <= TRACE_PAYLOAD_PREVIEW_CHARS and full.startswith(preview)


def _tool_result(call_id: str, output: str, **extra) -> dict:
    return {
        "kind": "tool_result",
        "source": "native",
        "raw_type": "tool_result",
        "call_id": call_id,
        "summary": output.strip(),
        "payload": {"content": output, "is_error": False},
        **extra,
    }


def test_large_tool_result_keeps_head_shape_and_reports_original_sizes() -> None:
    event = _tool_result("toolu_1", BIG_OUTPUT)

    compact = compact_trace_event(event)

    assert compact is not event
    assert compact["content_truncated"] is True
    assert compact["summary"] == BIG_OUTPUT.strip()[:TRACE_SUMMARY_PREVIEW_CHARS]
    assert compact["summary_chars"] == len(BIG_OUTPUT.strip())
    assert _is_preview_of(compact["payload"]["content"], BIG_OUTPUT)
    assert len(compact["payload"]["content"]) > TRACE_PAYLOAD_PREVIEW_CHARS - 100
    assert compact["payload_chars"] > len(BIG_OUTPUT)
    assert len(json.dumps(compact, ensure_ascii=False)) < 3_000
    # The persisted event object is never mutated.
    assert event["payload"]["content"] == BIG_OUTPUT and "content_truncated" not in event


def test_small_or_unaddressable_events_are_returned_unchanged() -> None:
    small = {"kind": "tool_call", "call_id": "call_1", "summary": "ls", "payload": {"command": "ls"}}
    assert compact_trace_event(small) is small

    # Without a row id or a tool call_id the client could not read the full event later.
    unaddressable = {"kind": "tool_result", "summary": BIG_OUTPUT, "payload": {"content": BIG_OUTPUT}}
    assert compact_trace_event(unaddressable) is unaddressable
    live_unknown = {"kind": "unknown", "call_id": "call_2", "summary": "x", "payload": {"content": BIG_OUTPUT}}
    assert compact_trace_event(live_unknown) is live_unknown


def test_only_tool_events_with_a_call_id_get_a_capped_summary() -> None:
    # The transcript renders these summaries in full.
    for kind in ("commentary", "reasoning", "status", "error", "cancelled"):
        event = {"id": "trace_1", "kind": kind, "summary": "说明" * 2_000}
        assert compact_trace_event(event) is event

    # The client matches a streamed event (no row id) with its stored version by summary,
    # so the two forms must project the same summary.
    live = {"kind": "unknown", "summary": "s" * 5_000, "payload": {"detail": "p" * 9_000}}
    stored = {**live, "id": "trace_9"}
    assert compact_trace_event(live) is live
    projected = compact_trace_event(stored)
    assert projected["summary"] == live["summary"] and "summary_chars" not in projected
    assert projected["payload_chars"] > 9_000

    for raw_type in REMAPPED_PROCESS_RAW_TYPES:
        remapped = {"id": "trace_2", "kind": "tool_call", "call_id": "c1", "raw_type": raw_type, "summary": "s" * 5_000}
        assert compact_trace_event(remapped) is remapped
    # The store shows these raw types under another kind when it reads history.
    assert REMAPPED_PROCESS_RAW_TYPES == PROCESS_TRACE_RAW_TYPES


def test_payload_preview_is_the_head_of_the_payload_in_document_order() -> None:
    command = compact_trace_event({
        "id": "trace_1",
        "kind": "tool_result",
        "summary": "ok",
        "payload": {"command": "make test", "aggregated_output": "o" * 50_000, "exit_code": 0, "status": "completed"},
    })
    assert list(command["payload"]) == ["command", "aggregated_output"]
    assert command["payload"]["command"] == "make test"
    assert _is_preview_of(command["payload"]["aggregated_output"], "o" * 50_000)
    assert "summary_chars" not in command

    # Many small values: whole leading items are kept instead of every item cut to nothing.
    blocks = compact_trace_event({
        "id": "trace_2",
        "kind": "tool_result",
        "summary": "ok",
        "payload": {"content": [{"type": "text", "text": "x" * 50} for _ in range(400)]},
    })["payload"]["content"]
    assert 10 <= len(blocks) < 60
    assert blocks[0] == {"type": "text", "text": "x" * 50}
    paths = [f"/src/module_{index}/file_{index}.py" for index in range(2_000)]
    files = compact_trace_event({"id": "trace_3", "kind": "tool_result", "summary": "ok", "payload": {"files": paths}})
    assert files["payload"]["files"][:20] == paths[:20]
    assert len(json.dumps(files["payload"])) <= TRACE_PAYLOAD_PREVIEW_CHARS * 2
    numbers = compact_trace_event({"id": "trace_4", "kind": "tool_result", "summary": "ok", "payload": list(range(100_000))})
    assert numbers["payload"][:5] == [0, 1, 2, 3, 4]
    assert len(json.dumps(numbers["payload"])) <= TRACE_PAYLOAD_PREVIEW_CHARS * 2


def test_unusual_payload_shapes_never_raise() -> None:
    nested: dict = {}
    cursor = nested
    for _ in range(5_000):
        cursor["child"] = {}
        cursor = cursor["child"]
    cursor["text"] = "x" * 5_000
    deep = {"id": "trace_1", "kind": "tool_result", "summary": "ok", "payload": {"pad": "y" * 3_000, "deep": nested}}
    projected = compact_trace_event(deep)
    assert projected["content_truncated"] is True and projected["payload"]["pad"] == "y" * 1_493

    for payload in ("z" * 9_000, ["z" * 9_000], 12345, True, None, {"n": 1}):
        event = {"id": "trace_2", "kind": "tool_result", "summary": 404, "payload": payload}
        compact_trace_event(event)
    assert compact_trace_event("not an event") == "not an event"


def test_store_serves_compact_snapshot_and_full_event_on_demand(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)
    store.append_trace_events(handle.turn_id, [
        {"kind": "commentary", "summary": "先看目录", "raw_type": "assistant.text"},
        {"kind": "tool_call", "call_id": "toolu_1", "tool_name": "Read", "title": "Read",
         "raw_type": "tool_use", "summary": "/tmp/big.log", "payload": {"file_path": "/tmp/big.log"}},
        _tool_result("toolu_1", BIG_OUTPUT),
    ])
    store.complete_turn(handle, content="完成", completion_state="completed")

    full = store.get_message_trace(handle.assistant_message_id)
    compact = store.get_message_trace(handle.assistant_message_id, compact=True)

    assert [item["kind"] for item in compact["trace"]] == ["commentary", "tool_call", "tool_result"]
    assert compact["trace_count"] == full["trace_count"] == 3
    assert full["trace"][2]["payload"]["content"] == BIG_OUTPUT
    assert "content_truncated" not in full["trace"][2]
    result = compact["trace"][2]
    assert result["content_truncated"] is True
    assert result["id"] == full["trace"][2]["id"]
    assert _is_preview_of(result["payload"]["content"], BIG_OUTPUT)
    assert "content_truncated" not in compact["trace"][0] and "content_truncated" not in compact["trace"][1]

    by_id = store.get_message_trace_event(handle.assistant_message_id, event_id=result["id"])
    assert by_id["event"]["payload"]["content"] == BIG_OUTPUT
    assert by_id["event"]["summary"] == BIG_OUTPUT.strip()
    assert by_id["native_provider"] == "claude"
    # Live events have no row id yet and are addressed by kind and call_id.
    by_call = store.get_message_trace_event(handle.assistant_message_id, kind="tool_result", call_id="toolu_1")
    assert by_call["event"] == by_id["event"]
    # A stale row id (trace replaced after recovery) falls back to the call reference.
    fallback = store.get_message_trace_event(
        handle.assistant_message_id, event_id="trace_missing", kind="tool_result", call_id="toolu_1",
    )
    assert fallback["event"] == by_id["event"]

    with pytest.raises(KeyError):
        store.get_message_trace_event(handle.assistant_message_id, event_id="trace_missing")
    with pytest.raises(KeyError):
        store.get_message_trace_event("msg_missing", event_id=result["id"])


def test_duplicate_tool_results_resolve_to_the_event_shown_in_the_trace(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)
    # replace_trace_events keeps duplicates as separate rows; the normalized trace
    # shows the richer result under the first row's id.
    store.replace_trace_events(handle.turn_id, [
        _tool_result("toolu_1", "partial"),
        _tool_result("toolu_1", BIG_OUTPUT),
    ])

    shown = store.get_message_trace(handle.assistant_message_id)["trace"]
    assert len(shown) == 1 and shown[0]["payload"]["content"] == BIG_OUTPUT

    detail = store.get_message_trace_event(handle.assistant_message_id, event_id=shown[0]["id"])
    assert detail["event"]["payload"]["content"] == BIG_OUTPUT


def test_tool_call_rows_sharing_a_call_id_resolve_to_the_richest_version(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)
    started = {"kind": "tool_call", "call_id": "item_1", "raw_type": "command_execution", "tool_name": "command_execution",
               "summary": "make test", "payload": {"command": "make test", "aggregated_output": ""}}
    finished = {**started, "payload": {"command": "make test", "aggregated_output": BIG_OUTPUT}}
    store.append_trace_events(handle.turn_id, [started, finished])
    rows = store.get_message_trace(handle.assistant_message_id)["trace"]
    assert len(rows) == 2

    # The Web client merges both rows into one entry that keeps the richer payload,
    # whichever row id or call reference it asks with.
    for reference in ({"event_id": rows[0]["id"]}, {"event_id": rows[1]["id"]}, {"kind": "tool_call", "call_id": "item_1"}):
        detail = store.get_message_trace_event(handle.assistant_message_id, **reference)
        assert detail["event"]["payload"]["aggregated_output"] == BIG_OUTPUT


def test_single_event_read_applies_the_history_provider_filter(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)
    store.append_trace_events(handle.turn_id, [_tool_result("toolu_1", BIG_OUTPUT)])
    reference = {"kind": "tool_result", "call_id": "toolu_1"}

    session = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(store.workspace_dir))
    visible = ChatHistoryService(store).get_message_trace_event(None, session, handle.assistant_message_id, **reference)
    assert visible is not None and "native_provider" not in visible
    filtered = ChatHistoryService(store, native_provider_filter="codex")
    assert filtered.get_message_trace_event(None, session, handle.assistant_message_id, **reference) is None
    excluded = ChatHistoryService(store, native_provider_exclude="claude")
    assert excluded.get_message_trace_event(None, session, handle.assistant_message_id, **reference) is None
    assert ChatHistoryService(store).get_message_trace_event(None, session, "msg_missing", **reference) is None


class _DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    def snapshot(self) -> dict[str, object]:
        return {"mode": "disabled", "status": "stopped", "source": "disabled", "public_url": "",
                "local_url": "http://127.0.0.1:8765", "last_error": "", "pid": None}

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WebApiServer:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="claude", cli_path="claude", working_dir=str(tmp_path)),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=_DummyTunnelService())

    async def with_capability(_request, _capability: str) -> AuthContext:
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND, CAP_VIEW_CHAT_TRACE})

    monkeypatch.setattr(server, "_with_capability", with_capability)
    monkeypatch.setattr(server, "_schedule_chat_terminal_event", lambda **_kwargs: None)
    return server


def _sse_events(body: str, event_type: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        lines = block.split("\n")
        if f"event: {event_type}" in lines:
            data = next(line for line in lines if line.startswith("data: "))
            events.append(json.loads(data[len("data: "):]))
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_fields", "expect_compact"),
    [({}, False), ({"trace_payload": "compact"}, True), ({"tracePayload": "compact"}, True), ({"trace_payload": "full"}, False)],
)
async def test_chat_stream_compacts_trace_events_only_when_the_client_asks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request_fields: dict[str, object],
    expect_compact: bool,
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    source_event = _tool_result("toolu_1", BIG_OUTPUT)

    async def event_source():
        yield {"type": "trace", "turn_id": "turn_1", "assistant_message_id": "msg_1", "event": source_event}
        yield {"type": "done", "output": "ok", "elapsed_seconds": 0}

    monkeypatch.setattr("bot.web.server.stream_chat", lambda *_args, **_kwargs: event_source())

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post("/api/bots/main/chat/stream", json={"message": "hello", **request_fields})
            body = await response.text()

    (trace,) = _sse_events(body, "trace")
    assert trace["turn_id"] == "turn_1" and trace["assistant_message_id"] == "msg_1"
    if expect_compact:
        assert trace["event"]["content_truncated"] is True
        assert _is_preview_of(trace["event"]["payload"]["content"], BIG_OUTPUT)
        assert len(body) < 5_000
    else:
        assert trace["event"] == source_event
    # The generator's event object (also queued for persistence) stays intact.
    assert source_event["payload"]["content"] == BIG_OUTPUT


@pytest.mark.asyncio
async def test_trace_endpoints_serve_compact_snapshot_and_single_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = _build_server(monkeypatch, tmp_path)
    store = ChatStore(tmp_path)
    handle = _begin(store, bot_id=resolve_session_bot_id(server.manager, "main"), user_id=chat_session_user_id())
    store.append_trace_events(handle.turn_id, [_tool_result("toolu_1", BIG_OUTPUT)])
    store.complete_turn(handle, content="完成", completion_state="completed")
    trace_path = f"/api/bots/main/history/{handle.assistant_message_id}/trace"

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            full = (await (await client.get(trace_path)).json())["data"]
            compact = (await (await client.get(f"{trace_path}?payload=compact")).json())["data"]
            event_id = compact["trace"][0]["id"]
            by_id = await client.get(f"{trace_path}/event", params={"id": event_id})
            by_call = await client.get(f"{trace_path}/event", params={"kind": "tool_result", "call_id": "toolu_1"})
            missing = await client.get(f"{trace_path}/event", params={"id": "trace_missing"})
            no_ref = await client.get(f"{trace_path}/event")
            by_id_payload = await by_id.json()
            by_call_payload = await by_call.json()
            missing_payload = await missing.json()
            no_ref_payload = await no_ref.json()

    # Without the query parameter the endpoint keeps returning full payloads.
    assert full["trace"][0]["payload"]["content"] == BIG_OUTPUT
    assert compact["trace"][0]["content_truncated"] is True
    assert by_id.status == 200 and by_id_payload["data"]["event"]["payload"]["content"] == BIG_OUTPUT
    assert "native_provider" not in by_id_payload["data"]
    assert by_call.status == 200 and by_call_payload["data"]["event"]["id"] == event_id
    assert missing.status == 404 and missing_payload["error"]["code"] == "trace_event_not_found"
    assert no_ref.status == 400 and no_ref_payload["error"]["code"] == "missing_trace_event_ref"


@pytest.mark.asyncio
async def test_single_event_endpoint_requires_the_trace_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="claude", cli_path="claude", working_dir=str(tmp_path)),
        str(storage),
    )
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    # The test client connects from loopback, which the server otherwise treats as the local admin.
    monkeypatch.setattr("bot.web.server._is_loopback_auto_auth_allowed", lambda _request: False)
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=_DummyTunnelService())
    store = ChatStore(tmp_path)
    handle = _begin(store)
    store.append_trace_events(handle.turn_id, [_tool_result("toolu_1", BIG_OUTPUT)])
    path = f"/api/bots/main/history/{handle.assistant_message_id}/trace/event"

    async with TestServer(server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            anonymous = await client.get(path, params={"kind": "tool_result", "call_id": "toolu_1"})
            login = await (await client.post("/api/auth/guest")).json()
            guest = await client.get(path, params={"kind": "tool_result", "call_id": "toolu_1"})
            guest_trace = await client.get(path.removesuffix("/event"))
            guest_body = await guest.text()

    # Guests can read chat history but not the execution trace; the new endpoint follows the
    # existing trace endpoint.
    assert CAP_VIEW_CHAT_TRACE not in login["data"]["capabilities"]
    assert anonymous.status in {401, 403}
    assert guest.status == guest_trace.status == 403
    assert BIG_OUTPUT[:100] not in guest_body
