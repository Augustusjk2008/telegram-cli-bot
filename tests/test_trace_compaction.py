from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import uuid
import zlib
from contextlib import closing
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession
from bot.web import trace_previews
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


def test_single_event_read_applies_the_history_provider_filter(tmp_path: Path, monkeypatch) -> None:
    store = ChatStore(tmp_path / f"workspace-{uuid.uuid4().hex}")
    handle = _begin(store)
    store.append_trace_events(handle.turn_id, [_tool_result("toolu_1", BIG_OUTPUT)])
    reference = {"kind": "tool_result", "call_id": "toolu_1"}

    session = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(store.workspace_dir))
    visible = ChatHistoryService(store).get_message_trace_event(None, session, handle.assistant_message_id, **reference)
    assert visible is not None and "native_provider" not in visible
    monkeypatch.setattr(trace_previews, "read_body", lambda *args: pytest.fail("filtered body was read"))
    for other_owner in ((7, 2, "main"), (1, 8, "main"), (1, 2, "@ses_other")):
        with pytest.raises(KeyError):
            store.get_message_trace_event(handle.assistant_message_id, owner=other_owner, **reference)
    filtered = ChatHistoryService(store, native_provider_filter="codex")
    assert filtered.get_message_trace_event(None, session, handle.assistant_message_id, **reference) is None
    excluded = ChatHistoryService(store, native_provider_exclude="claude")
    assert excluded.get_message_trace_event(None, session, handle.assistant_message_id, **reference) is None
    assert ChatHistoryService(store).get_message_trace_event(None, session, "msg_missing", **reference) is None


def test_ready_preview_and_missing_stats_read_no_bodies_and_detail_reads_one(tmp_path, monkeypatch):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    mid = handle.assistant_message_id
    # The terminal state and the commentary IDs fall beyond the payload preview.
    events = [
        _tool_result("r", BIG_OUTPUT, payload={"output": BIG_OUTPUT, "state": "running"}),
        _tool_result("r", "winner" * 400, payload={"output": "winner" * 400, "state": "completed"}),
        _tool_result("r", BIG_OUTPUT + "later", payload={"output": BIG_OUTPUT + "later", "state": "running"}),
        {"kind": "tool_call", "call_id": "c"},
        *[{"kind": "commentary", "raw_type": "message.text.reclassified", "call_id": "c",
           "summary": "working", "payload": {"padding": BIG_OUTPUT, "messageID": identity, "reason": reason}}
          for identity, reason in (("msg_1", "assistant-message-switched"), ("native-id", "normal"))],
        {"kind": "tool_call", "call_id": "f", "raw_type": "file.edited",
         "summary": BIG_OUTPUT, "payload": {"output": BIG_OUTPUT}},
        {"kind": "reasoning", "summary": "final "},
    ]
    store.replace_trace_events(handle.turn_id, events)
    store.complete_turn(handle, content="final answer", completion_state="completed")
    full = store.get_message_trace(mid)
    expected = {**full, "trace": [compact_trace_event(e) for e in full["trace"]]}
    original_connect = store._connect

    def preview_only(*, create):
        conn = original_connect(create=create)

        def authorize(action, table, column, *_):
            if action == sqlite3.SQLITE_READ and table == "trace_events" and column in ("summary", "payload_json"):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        return conn

    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("DELETE FROM trace_stats WHERE turn_id=?", (handle.turn_id,))
    with monkeypatch.context() as patch:
        patch.setattr(store, "_connect", preview_only)
        assert store.get_message_trace(mid, compact=True) == expected
        counts = store.get_trace_recovery_context(mid)
        assert {k: counts[k] for k in ("trace_count", "tool_call_count", "process_count")} == {
            k: full[k] for k in ("trace_count", "tool_call_count", "process_count")
        }
        patch.setattr("bot.web.chat_history_service.resolve_native_trace_for_turn",
                      lambda *args, **kwargs: {"trace_count": 1, "tool_call_count": 0})
        assert not ChatHistoryService(store).reconcile_turn_trace(
            handle, profile=BotProfile(alias="main", cli_type="claude", working_dir=str(tmp_path)),
            session=UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(tmp_path)),
            user_text="hello", assistant_text="final answer", native_session_id="fixture",
        )
    reads = []
    original_body = trace_previews.read_body

    def record(conn, turn_id, event_id):
        reads.append(event_id)
        return original_body(conn, turn_id, event_id)

    monkeypatch.setattr(trace_previews, "read_body", record)
    detail = store.get_message_trace_event(mid, event_id=full["trace"][0]["id"])["event"]
    assert reads == [detail["id"]]
    assert detail["payload"]["state"] == "completed"
    assert detail["summary"] == "winner" * 400


def test_lazy_backfill_rereads_the_current_turn_and_final_text_after_legacy_write(tmp_path, monkeypatch):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    other = _begin(store, text="unopened turn")
    store.append_trace_events(handle.turn_id, [_tool_result("r", "original"), {"kind": "reasoning", "summary": "reply"}])
    store.append_trace_events(other.turn_id, [_tool_result("other", BIG_OUTPUT)])
    mid = handle.assistant_message_id
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE trace_event_previews SET version=0")
    original_rows = trace_previews._rows
    changed = False

    def read_then_update(*args, **kwargs):
        nonlocal changed
        rows = original_rows(*args, **kwargs)
        if not changed:
            changed = True
            with closing(sqlite3.connect(store.db_path)) as writer, writer:
                writer.execute("UPDATE trace_events SET summary=?,payload_json=? WHERE turn_id=? AND kind='tool_result'",
                               ("updated", json.dumps({"output": BIG_OUTPUT}), handle.turn_id))
                writer.execute("UPDATE messages SET content='reply' WHERE id=?", (mid,))
        return rows

    monkeypatch.setattr(trace_previews, "_rows", read_then_update)
    shown = store.get_message_trace(mid, compact=True)
    assert shown["trace_count"] == 1 and shown["trace"][0]["summary"] == "updated"
    assert shown["trace"][0]["content_truncated"]
    with closing(sqlite3.connect(store.db_path)) as db, db:
        assert db.execute("SELECT count(*) FROM trace_event_previews WHERE version=0").fetchone()[0] == 1
        # A 3.2.0-style connection can update the answer, replace events or delete them with foreign keys off.
        db.execute("UPDATE messages SET content='different' WHERE id=?", (mid,))
    assert store.get_trace_recovery_context(mid)["trace_count"] == 2
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("DELETE FROM trace_events WHERE turn_id=?", (handle.turn_id,))
        assert db.execute("SELECT count(*) FROM trace_event_previews").fetchone()[0] == 1
    assert store.get_trace_recovery_context(mid)["trace_count"] == 0


def test_failed_same_call_update_rolls_back_body_and_preview(tmp_path, monkeypatch):
    store = ChatStore(tmp_path)
    turn = _begin(store)
    store.append_trace_events(turn.turn_id, [_tool_result("c", BIG_OUTPUT)])
    previous = store.get_message_trace(turn.assistant_message_id, compact=True)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("interrupted preview write")

    with monkeypatch.context() as patch:
        patch.setattr(trace_previews, "save", fail)
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            store.append_trace_events(turn.turn_id, [_tool_result("c", "replacement")])
    assert store.get_message_trace(turn.assistant_message_id, compact=True) == previous
    detail = store.get_message_trace_event(turn.assistant_message_id, kind="tool_result", call_id="c")
    assert detail["event"]["payload"]["content"] == BIG_OUTPUT


def test_new_preview_can_rank_deeply_nested_json_accepted_by_plaintext_writer(tmp_path):
    store = ChatStore(tmp_path)
    turn = _begin(store)
    nested = [{"output": [], "text": " a"}, {"output": "b ", "text": "unused"}]
    for _ in range(550):
        nested = [nested]
    store.replace_trace_events(turn.turn_id, [
        {"kind": "tool_result", "call_id": "c", "payload": {"output": nested}},
        {"kind": "tool_result", "call_id": "c", "summary": "x"},
    ])
    assert store.get_message_trace(turn.assistant_message_id, compact=True)["trace"][0]["summary"] == ""
    detail = store.get_message_trace_event(turn.assistant_message_id, kind="tool_result", call_id="c")["event"]
    assert json.dumps(detail["payload"]) == json.dumps({"output": nested})


@pytest.mark.parametrize("payload_json", [None, '{ "output" : "原文\\n", "state" : "done" }'])
def test_compatible_reader_checks_tagged_body_and_continues_plaintext_writes(tmp_path, payload_json):
    store = ChatStore(tmp_path)
    handle = _begin(store)
    mid = handle.assistant_message_id
    store.append_trace_events(handle.turn_id, [_tool_result("r", "initial"), _tool_result("plain", "neighbor")])
    event_id = store.get_message_trace(mid)["trace"][0]["id"]
    summary = "你" * 1200
    data = summary.encode() + (payload_json or "").encode()
    lengths = struct.pack(">BQq", 1, len(summary.encode()), -1 if payload_json is None else len(payload_json.encode()))
    encoded = b"\x00OTR" + lengths + hashlib.sha256(lengths + data).digest() + zlib.compress(data)
    assert trace_previews.decode_body(event_id, "", encoded) == (summary, payload_json)
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE trace_events SET summary='',payload_json=? WHERE id=?", (encoded, event_id))
    event = store.get_message_trace_event(mid, event_id=event_id)["event"]
    assert event["summary"] == summary and event["payload"] == (json.loads(payload_json) if payload_json else None)
    mixed = store.get_message_trace(mid, compact=True)["trace"]
    assert mixed[0] == compact_trace_event({**event, "ordinal": 1})
    assert mixed[1]["summary"] == "neighbor"
    damaged = encoded[:-1]
    if payload_json is not None:
        # The total stays the same but the summary/payload boundary is corrupted.
        wrong_lengths = struct.pack(">BQq", 1, len(summary.encode()) - 1, len(payload_json.encode()) + 1)
        damaged = b"\x00OTR" + wrong_lengths + encoded[4 + len(lengths):]
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE trace_events SET payload_json=? WHERE id=?", (damaged, event_id))
    with pytest.raises(ValueError, match=event_id):
        store.get_message_trace(mid)
    store.append_trace_events(handle.turn_id, [_tool_result("r", "plain again")])
    with closing(sqlite3.connect(store.db_path)) as db:
        assert db.execute("SELECT summary,typeof(payload_json) FROM trace_events WHERE id=?",
                          (event_id,)).fetchone() == ("plain again", "text")


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
