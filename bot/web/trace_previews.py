"""Versioned SQLite projections for trace lists and single-event selection."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
import zlib
from contextlib import closing
from functools import lru_cache
from typing import Any, NamedTuple

from bot.web.trace_compaction import compact_trace_event, estimate_json_chars


VERSION = 1
SCHEMA = """
BEGIN;
CREATE TABLE IF NOT EXISTS trace_event_previews (
    event_id TEXT PRIMARY KEY REFERENCES trace_events(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    raw_type TEXT, title TEXT, tool_name TEXT, summary TEXT, payload_json TEXT,
    summary_chars INTEGER, payload_chars INTEGER,
    priority INTEGER NOT NULL, weight INTEGER NOT NULL, message_id TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trace_preview_insert AFTER INSERT ON trace_events BEGIN
    DELETE FROM trace_event_previews WHERE event_id=NEW.id;
    DELETE FROM trace_stats WHERE turn_id=NEW.turn_id;
END;
CREATE TRIGGER IF NOT EXISTS trace_preview_update AFTER UPDATE ON trace_events BEGIN
    DELETE FROM trace_event_previews WHERE event_id IN (OLD.id, NEW.id);
    DELETE FROM trace_stats WHERE turn_id IN (OLD.turn_id, NEW.turn_id);
END;
CREATE TRIGGER IF NOT EXISTS trace_preview_delete AFTER DELETE ON trace_events BEGIN
    DELETE FROM trace_event_previews WHERE event_id=OLD.id;
    DELETE FROM trace_stats WHERE turn_id=OLD.turn_id;
END;
COMMIT;
"""

MIN_BODY_BYTES = 64 * 1024
logger = logging.getLogger(__name__)

# The v1 checksum covers the version, byte boundaries and both UTF-8 strings.
BODY_MAGIC = b"\x00OTR"
BODY_LENGTHS = struct.Struct(">BQq")  # version, summary bytes, payload bytes (-1 = NULL)
BODY_COLUMNS = "id, ordinal, kind, raw_type, title, tool_name, call_id, summary, payload_json, created_at"


def _rle_deflate(data) -> bytes:
    compressor = zlib.compressobj(level=1, strategy=zlib.Z_RLE)
    return compressor.compress(data) + compressor.flush()


def _compress_body(body: bytes) -> bytes:
    # Large encoded tool output can spend most of the write searching for distant matches.
    # Compare one DEFLATE window before choosing a strategy for the full body.
    if len(body) >= 1024 * 1024:
        middle = len(body) // 2
        sample = memoryview(body)[middle:middle + 32768]
        if len(_rle_deflate(sample)) <= len(zlib.compress(sample, level=3)):
            return _rle_deflate(body)
    return zlib.compress(body, level=3)


@lru_cache(maxsize=1)
def _compiled_length_limit() -> int:
    # Python 3.10 exposes the compile option but not Connection.getlimit().
    with closing(sqlite3.connect(":memory:")) as conn:
        for (option,) in conn.execute("PRAGMA compile_options"):
            if option.startswith("MAX_LENGTH="):
                return int(option.partition("=")[2])
    return 1_000_000_000


def _plaintext_fits(conn: sqlite3.Connection, fields: tuple) -> bool:
    # A compressed insert must also be restorable as an ordinary SQLite record.
    limit = conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) if hasattr(conn, "getlimit") else _compiled_length_limit()
    overhead = 128  # Record header, serial-type varints and the integer ordinal.
    if 4 * sum(len(field) for field in fields) + overhead <= limit:
        return True
    encoding = conn.execute("PRAGMA encoding").fetchone()[0]
    return sum(len(field.encode(encoding)) for field in fields) + overhead <= limit


def encode_body(event_id: str, summary: str, payload_json: str | None) -> tuple[str, str | bytes | None]:
    if (len(summary) + len(payload_json or "")) * 4 < MIN_BODY_BYTES:
        return summary, payload_json
    try:
        summary_bytes = summary.encode("utf-8")
        payload_bytes = (payload_json or "").encode("utf-8")
        size = len(summary_bytes) + len(payload_bytes)
        if size >= MIN_BODY_BYTES:
            lengths = BODY_LENGTHS.pack(1, len(summary_bytes), -1 if payload_json is None else len(payload_bytes))
            body = summary_bytes + payload_bytes
            compressed = _compress_body(body)
            if len(BODY_MAGIC) + len(lengths) + 32 + len(compressed) < size:
                digest = hashlib.sha256(lengths)
                digest.update(body)
                return "", BODY_MAGIC + lengths + digest.digest() + compressed
    except Exception:
        # Projection and the ordinary plaintext write still use the original values.
        logger.warning("Writing trace %s as plaintext after compression failed", event_id)
    return summary, payload_json


def decode_body(event_id: str, summary: str, payload_json: str | bytes | None) -> tuple[str, str | bytes | None]:
    if not isinstance(payload_json, bytes) or not payload_json.startswith(BODY_MAGIC):
        return summary, payload_json
    try:
        checksum_at = len(BODY_MAGIC) + BODY_LENGTHS.size
        version, split, payload_size = BODY_LENGTHS.unpack_from(payload_json, len(BODY_MAGIC))
        checksum = payload_json[checksum_at:checksum_at + 32]
        if version != 1 or summary != "" or payload_size < -1:
            raise ValueError("invalid encoding header")
        size = split + max(0, payload_size)
        decoder = zlib.decompressobj()
        body = decoder.decompress(memoryview(payload_json)[checksum_at + 32:], size + 1)
        digest = hashlib.sha256(payload_json[len(BODY_MAGIC):checksum_at])
        digest.update(body)
        if not decoder.eof or decoder.unused_data or len(body) != size or digest.digest() != checksum:
            raise ValueError("length or checksum mismatch")
        return body[:split].decode("utf-8"), None if payload_size == -1 else body[split:].decode("utf-8")
    except (ValueError, struct.error, zlib.error, OverflowError) as exc:
        raise ValueError(f"Invalid compressed trace body {event_id}: {exc}") from exc


def full_event(row: sqlite3.Row) -> dict:
    event = dict(row)
    event["ordinal"] = int(event["ordinal"])
    stored_payload = event.pop("payload_json")
    summary, payload_json = decode_body(event["id"], event["summary"], stored_payload)
    event["summary"] = summary
    try:
        event["payload"] = json.loads(payload_json) if payload_json else None
    except ValueError as exc:
        if isinstance(stored_payload, bytes):
            raise ValueError(f"Invalid trace payload {event['id']}: {exc}") from exc
        raise
    return event


def _payload_text(payload: Any) -> str:
    # Lists concatenate their children. An object uses its first field that
    # emits any text. Keep the traversal off Python's stack for deeply nested JSON.
    parts = []
    stack = [(iter([payload]), None)]
    end = object()
    while stack:
        children, first_part = stack[-1]
        if first_part is not None and len(parts) > first_part:
            stack.pop()
            continue
        item = next(children, end)
        if item is end:
            stack.pop()
        elif isinstance(item, list):
            stack.append((iter(item), None))
        elif isinstance(item, dict):
            fields = [item[k] for k in ("output", "result", "content", "text", "message", "summary") if k in item]
            stack.append((iter(fields), len(parts)))
        elif item is not None and item != "":
            parts.append(str(item))
    return "".join(parts)


class Selection(NamedTuple):
    """Original ranking fields used after the transport preview has discarded content."""

    priority: int = 0
    weight: int = 0
    message_id: str = ""


def selection(event: dict, projected: dict | None = None) -> Selection:
    kind = str(event.get("kind") or "").strip()
    payload = event.get("payload")
    fields = payload if isinstance(payload, dict) else {}
    summary = str(event.get("summary") or "")
    if kind == "tool_result":
        state = str(fields.get("state") or fields.get("status") or "").strip().lower()
        terminal = state in {"completed", "done", "finished", "success", "error", "failed"}
        return Selection(int(terminal), max(len(_payload_text(payload).strip()), len(summary.strip())))
    if kind == "tool_call":
        chars = projected.get("payload_chars") if projected else None
        if chars is None:
            chars = estimate_json_chars(payload)
        return Selection(0, chars * 10 + len(summary) * 5)
    if kind == "commentary" and event.get("raw_type") == "message.text.reclassified":
        message_id = next((str(fields[k]).strip() for k in ("messageID", "message_id", "messageId") if fields.get(k)), "")
        switched = str(fields.get("reason") or "").strip() == "assistant-message-switched"
        return Selection(int(not switched), 0, message_id)
    return Selection()


def save(conn: sqlite3.Connection, event: dict, *, payload_json: str | None = None) -> None:
    preview = compact_trace_event(event)
    score = selection(event, preview)
    if preview.get("payload") is not None and (payload_json is None or "payload_chars" in preview):
        payload_json = json.dumps(preview["payload"], ensure_ascii=False)
    conn.execute("""
        INSERT OR REPLACE INTO trace_event_previews
            (event_id,version,raw_type,title,tool_name,summary,payload_json,summary_chars,payload_chars,
             priority,weight,message_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (event["id"], VERSION, event["raw_type"], event["title"], event["tool_name"], preview["summary"],
              payload_json, preview.get("summary_chars"), preview.get("payload_chars"), *score))


def write_event(conn: sqlite3.Connection, turn_id: str, ordinal: int, event_id: str, item: dict,
                created_at: str, *, update: bool = False, pilot: bool = False) -> None:
    kind = str(item.get("kind") or "unknown")
    call_id = str(item.get("call_id") or "")
    raw_type, title, tool_name, summary = (str(item.get(k) or "") for k in ("raw_type", "title", "tool_name", "summary"))
    payload = item.get("payload")
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    enrolled = pilot and kind == "tool_result"
    if enrolled and update:
        member = conn.execute("SELECT 1 FROM trace_body_pilot_events WHERE event_id=?", (event_id,)).fetchone()
        enrolled = member is not None
    stored_summary, stored_payload = summary, payload_json
    if enrolled and _plaintext_fits(conn, (event_id, turn_id, kind, raw_type, title, tool_name, call_id,
                                           summary, payload_json or "", created_at)):
        stored_summary, stored_payload = encode_body(event_id, summary, payload_json)
    if update:
        conn.execute("""UPDATE trace_events SET raw_type=?, title=?, tool_name=?, summary=?, payload_json=?, created_at=?
                        WHERE id=?""", (raw_type, title, tool_name, stored_summary, stored_payload, created_at, event_id))
    else:
        conn.execute("""INSERT INTO trace_events
                     (id,turn_id,ordinal,kind,raw_type,title,tool_name,call_id,summary,payload_json,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (event_id, turn_id, ordinal, kind, raw_type, title, tool_name, call_id, stored_summary, stored_payload, created_at))
        if enrolled:
            conn.execute("INSERT INTO trace_body_pilot_events(event_id) VALUES (?)", (event_id,))
    save(conn, {"id": event_id, "kind": kind, "raw_type": raw_type, "title": title, "tool_name": tool_name,
                "call_id": call_id, "summary": summary, "payload": json.loads(payload_json) if payload_json else None},
         payload_json=payload_json)


def read_body(conn: sqlite3.Connection, turn_id: str, event_id: str) -> dict:
    row = conn.execute(f"SELECT {BODY_COLUMNS} FROM trace_events WHERE turn_id=? AND id=?", (turn_id, event_id)).fetchone()
    if row is None:
        raise KeyError(event_id)
    return full_event(row)


def begin_write(conn: sqlite3.Connection) -> None:
    """Reserve the writer before deriving an ordinal or caching counts from a SELECT."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _rows(conn: sqlite3.Connection, turn_id: str, *, call: tuple[str, str] | None = None,
          stats: bool = False) -> list[sqlite3.Row]:
    # The existing covering index supplies identity and order without visiting the body table.
    where = "e.turn_id=?"
    args = [turn_id]
    fields = "e.id, e.ordinal, e.kind, e.call_id, e.created_at, p.version, p.priority, p.weight"
    if call is not None:
        where += " AND e.kind=? AND e.call_id=?"
        args.extend(call)
    else:
        fields += ", p.message_id, p.raw_type"
        if stats:
            # Normalization strips whitespace from kind. Only these kinds use summary for counts.
            fields += ", CASE WHEN instr(e.kind,'commentary') OR instr(e.kind,'reasoning') THEN p.summary END AS summary"
        else:
            fields += ", p.summary, p.title, p.tool_name, p.payload_json, p.summary_chars, p.payload_chars"
    return conn.execute(f"""
        SELECT {fields}
        FROM trace_events AS e INDEXED BY idx_trace_events_turn_kind_call
        LEFT JOIN trace_event_previews AS p ON p.event_id=e.id AND p.version=?
        WHERE {where} ORDER BY e.ordinal, e.created_at, e.id
        """, [VERSION, *args]).fetchall()


def _fill(conn: sqlite3.Connection, turn_id: str, rows: list[sqlite3.Row]) -> None:
    for row in rows:
        if row["version"] is None:
            save(conn, read_body(conn, turn_id, row["id"]))


def read_turn(conn: sqlite3.Connection, turn_id: str, *, stats: bool = False,
              backfill: bool) -> tuple[list[dict], dict[str, Selection]] | None:
    rows = _rows(conn, turn_id, stats=stats)
    if any(row["version"] is None for row in rows):
        if not backfill:
            return None
        _fill(conn, turn_id, rows)
        rows = _rows(conn, turn_id, stats=stats)
    events, scores = [], {}
    for row in rows:
        event = {k: row[k] for k in ("id", "ordinal", "kind", "call_id", "created_at", "raw_type", "summary")}
        event["ordinal"] = int(event["ordinal"])
        if not stats:
            event.update(title=row["title"], tool_name=row["tool_name"],
                         payload=json.loads(row["payload_json"]) if row["payload_json"] else None)
            for field in ("summary_chars", "payload_chars"):
                if row[field] is not None:
                    event[field] = row[field]
                    event["content_truncated"] = True
        scores[row["id"]] = Selection(row["priority"], row["weight"], row["message_id"])
        events.append(event)
    return events, scores


def detail(conn: sqlite3.Connection, turn_id: str, event_id: str, kind: str, call_id: str,
           *, backfill: bool) -> dict | None:
    target = None
    if event_id:
        target = conn.execute("SELECT id, kind, call_id FROM trace_events WHERE turn_id=? AND id=?",
                              (turn_id, event_id)).fetchone()
    if target is not None:
        kind, call_id = target["kind"], target["call_id"]
    if call_id and kind in {"tool_call", "tool_result"}:
        rows = _rows(conn, turn_id, call=(kind, call_id))
        if not rows:
            raise KeyError(event_id or call_id)
        if len(rows) > 1 and any(row["version"] is None for row in rows):
            if not backfill:
                return None  # Re-resolve the reference under a write transaction.
            _fill(conn, turn_id, rows)
            rows = _rows(conn, turn_id, call=(kind, call_id))
        selected = max(rows, key=lambda r: (r["priority"], r["weight"], r["ordinal"]))
        event_id = selected["id"]
    elif target is None:
        raise KeyError(event_id or call_id or turn_id)
    return read_body(conn, turn_id, event_id)
