"""Manage the pilot for new tool-result bodies in the active history store."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path

from bot import runtime_paths
from bot.storage_migration import StorageExclusiveGuard
from bot.update_state import FileLock, UpdateStore
from bot.web import trace_body_policy as pilot, trace_previews as traces
from scripts import _pytest_history_inventory as paths


def history_root() -> Path:
    location = paths.locations()
    locator = runtime_paths.read_storage_locator()
    journal = paths.plain_path(runtime_paths.get_storage_journal_path())
    if (locator and locator["state"] != "completed") or (journal.exists() and paths.read_object(journal).get("state") != "completed"):
        raise ValueError("storage migration is pending")
    return paths.plain_path(Path(location["storage"]) / "chat-history")


@contextmanager
def database(path: Path, *, writable: bool = False, immutable: bool = False):
    path = paths.plain_path(path)
    for suffix in ("-wal", "-shm", "-journal"):
        paths.plain_path(Path(str(path) + suffix))
    if writable and path.stat().st_nlink != 1:
        raise ValueError(f"workspace database has multiple hard links: {path}")
    mode = "rw" if writable else ("ro&immutable=1" if immutable else "ro")
    with closing(sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=15)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        if not writable:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")  # Count the policy and committed WAL rows at the same snapshot.
        yield conn


def _database_file(path: Path) -> bool:
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"unexpected non-regular history file: {path}")
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return True
    with path.open("rb") as stream:
        return stream.read(16) == b"SQLite format 3\x00"


def workspace_database(root: Path, workspace: str, *, create: bool = False) -> Path:
    workspaces = paths.plain_path(root / "workspaces")
    supplied = Path(workspace)
    if supplied.is_file():
        selected = paths.plain_path(supplied)
        if not selected.is_relative_to(root) or not _database_file(selected):
            raise ValueError("expected a project directory or a database inside active chat history")
        if create and not (selected.parent.parent == workspaces and paths.KEY.fullmatch(selected.parent.name)
                           and selected.name == "chat.sqlite"):
            raise ValueError("enable requires an active workspace database")
        return selected
    if supplied.parent == workspaces and paths.KEY.fullmatch(supplied.name):
        workspace = supplied.name
    is_key = paths.KEY.fullmatch(workspace) is not None
    key = workspace if is_key else runtime_paths.get_chat_workspace_key(workspace)
    folder = paths.workspace(workspaces, key)
    path = paths.plain_path(folder / "chat.sqlite")
    if not path.is_file() and create:
        # ChatStore also imports a legacy project DB before creating an empty history.
        from bot.web.chat_store import ChatStore
        working_dir = paths.metadata(folder) if is_key else workspace
        store = ChatStore(working_dir)
        if store.db_path != path:
            raise ValueError(f"workspace location changed: {key}")
        with closing(store._connect(create=True)):
            pass
    if not path.is_file():
        raise ValueError(f"workspace history database is missing: {key}")
    return path


def _legacy_blob(event_id, payload):
    try:
        if payload:
            json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"unreadable binary trace payload {event_id}") from exc


def decoded_text(row):
    summary, payload = traces.decode_body(row["id"], row["summary"], row["payload_json"])
    if payload:
        try:
            json.loads(payload)
        except (ValueError, RecursionError) as exc:
            raise ValueError(f"invalid decoded JSON for trace {row['id']}") from exc
    return summary, payload


def _inspect(conn, path: Path, verify: bool) -> dict:
    setting = pilot.policy(conn)
    result = {"workspace": path.parent.name, "database": str(path), "configured": setting is not None,
              "enabled": False, "compressed": 0, "encoded_bytes": 0, "legacy_json_blobs": 0}
    if setting is not None:
        result.update(enabled=pilot.enabled(conn, path.parent.name), rollback_install=setting[2])
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_events'").fetchone():
        return result
    for row in conn.execute("""SELECT rowid,id,substr(payload_json,1,4) AS prefix,length(payload_json) AS bytes
                               FROM trace_events WHERE typeof(payload_json)='blob'"""):
        if row["prefix"] == traces.BODY_MAGIC:
            result["compressed"] += 1
            result["encoded_bytes"] += row["bytes"]
            if verify:
                body = conn.execute("SELECT id,summary,payload_json FROM trace_events WHERE rowid=?", (row["rowid"],)).fetchone()
                decoded_text(body)
        else:
            payload = conn.execute("SELECT payload_json FROM trace_events WHERE rowid=?", (row["rowid"],)).fetchone()[0]
            _legacy_blob(row["id"], payload)
            result["legacy_json_blobs"] += 1
    return result


def inspect_workspace(path: Path, *, verify: bool = False) -> dict:
    watched = [path.parent, path, *(Path(str(path) + s) for s in ("-wal", "-shm", "-journal"))]
    before = paths.stamps(watched)
    if not any(before[2:]):
        # An ordinary read-only WAL connection can create empty sidecars on a quiet DB.
        # If a writer appeared during this pass, discard it and read a locked SQLite snapshot.
        try:
            with database(path, immutable=True) as conn:
                result = _inspect(conn, path, verify)
        except (OSError, ValueError, sqlite3.Error):
            if paths.stamps(watched) == before:
                raise
        else:
            if paths.stamps(watched) == before:
                return result
    with database(path) as conn:
        return _inspect(conn, path, verify)


def inventory(root: Path, *, verify: bool = False) -> dict:
    items, errors = [], []
    directories = [root] if root.exists() else []
    while directories:
        directory = directories.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError as exc:
            errors.append({"database": str(directory), "error": str(exc)})
            continue
        for entry in entries:
            try:
                path = paths.plain_path(entry)
                if path.is_dir():
                    directories.append(path)
                elif path.name.endswith(("-wal", "-journal", "-shm")):
                    if not path.with_name(path.name.rsplit("-", 1)[0]).exists():
                        raise ValueError("SQLite sidecar without its database")
                elif _database_file(path):
                    items.append(inspect_workspace(path, verify=verify))
            except (OSError, ValueError, sqlite3.Error) as exc:
                errors.append({"database": str(entry), "error": str(exc)})
    blockers = [item["database"] for item in items if item["configured"] or item["compressed"]]
    return {"root": str(root), "databases": len(items), "compressed": sum(item["compressed"] for item in items), "workspaces": items,
            "errors": errors, "blockers": blockers, "legacy_ready": not errors and not blockers}


def require_legacy_ready() -> None:
    with StorageExclusiveGuard():
        result = inventory(history_root())
    if not result["legacy_ready"]:
        raise ValueError("降级前请用 scripts.trace_body_compression check-legacy 检查所有工作区，关闭试点并展开压缩正文")


_PROBE = """
import hashlib
import json
import sqlite3
import struct
import sys
import zlib
from contextlib import closing
from pathlib import Path

root, private = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from bot.web import chat_store, trace_previews
if (Path(chat_store.__file__).resolve() != root / 'bot/web/chat_store.py'
        or Path(trace_previews.__file__).resolve() != root / 'bot/web/trace_previews.py'):
    raise RuntimeError("incorrect reader installation")
store = chat_store.ChatStore(private / 'workspace')
if not store.db_path.is_relative_to(private):
    raise RuntimeError("probe database is outside temporary storage")
turn = store.begin_turn(bot_id=1, bot_alias='probe', user_id=2, agent_id='main', cli_type='codex',
                        working_dir=str(store.workspace_dir), session_epoch=0, user_text='probe', native_provider='codex')
summary = 'reader probe ' * 1000
payload = json.dumps({'output': summary})
lengths = struct.pack('>BQq', 1, len(summary.encode()), len(payload.encode()))
body = summary.encode() + payload.encode()
blob = bytes([0]) + b'OTR' + lengths + hashlib.sha256(lengths + body).digest() + zlib.compress(body)
store.append_trace_events(turn.turn_id, [{'kind': 'tool_result', 'call_id': 'probe', 'summary': 'initial'},
                                       {'kind': 'commentary', 'summary': 'plaintext'}])
with closing(sqlite3.connect(store.db_path)) as db, db:
    db.execute("UPDATE trace_events SET summary='',payload_json=? WHERE turn_id=? AND call_id='probe'", (blob, turn.turn_id))
message = turn.assistant_message_id
full = store.get_message_trace(message)['trace']
preview = store.get_message_trace(message, compact=True)['trace']
detail = store.get_message_trace_event(message, kind='tool_result', call_id='probe')['event']
if ([e['summary'] for e in full] != [summary, 'plaintext'] or not preview[0].get('content_truncated')
        or detail['payload'] != json.loads(payload)):
    raise ValueError("mixed-format read mismatch")
print('trace-reader-v1-ok')
"""


def verified_rollback(rollback: Path) -> tuple[Path, str]:
    root = paths.plain_path(rollback)
    if root == pilot.PROGRAM_ROOT:
        raise ValueError("specify the separately retained rollback installation")
    try:
        for name in pilot.READER_FILES:
            paths.plain_path(root / name)
        digest = pilot.program_digest(root)
    except OSError as exc:
        raise ValueError(f"rollback installation lacks a usable trace reader: {root}") from exc
    # For a managed upgrade the actual previous program is recorded by the updater.
    # A directly upgraded original 3.2.0 has no trace_previews.py in that snapshot.
    state_file = runtime_paths.get_update_state_root(pilot.PROGRAM_ROOT) / "state.json"
    state = UpdateStore(pilot.PROGRAM_ROOT).read() if state_file.exists() else {}
    job = state.get("job") or {}
    if job.get("phase") in {"waiting_restart", "applying", "awaiting_health", "rolling_back", "recovery_required"}:
        raise ValueError("the installation has an unfinished update or recovery")
    if job.get("phase") in {"preparing", "ready"}:
        from bot.update_migration_gate import reads_trace_v1
        if not job.get("staging_dir") or not reads_trace_v1(job["staging_dir"], job.get("manifest") or {}):
            raise ValueError("the pending update does not have a verified v1 reader")
    installed = pilot.PROGRAM_ROOT / ".update-manifest.json"
    if installed.is_file():
        from bot.update_migration_gate import trace_rollback_origin
        marker = paths.read_object(installed)
        for origin in (trace_rollback_origin(job), state.get("trace_rollback_origin")):
            if not origin or marker.get("commit") != origin["target_commit"]:
                continue
            if origin.get("target_manifest_sha256") and origin["target_manifest_sha256"] != hashlib.sha256(installed.read_bytes()).hexdigest():
                raise ValueError("installed manifest differs from this upgrade's rollback evidence")
            for name in pilot.READER_FILES:
                if origin["files"].get(name) != hashlib.sha256((root / name).read_bytes()).hexdigest():
                    raise ValueError(f"rollback reader differs from this installation's pre-update file: {name}")
            break
    with tempfile.TemporaryDirectory(prefix="orbit-trace-reader-") as tmp:
        private = Path(tmp).resolve()
        env = dict(os.environ, TCB_PORTABLE_ROOT=str(private), TCB_DATA_DIR=str(private / "app"), WORKING_DIR=str(private))
        probe = subprocess.run([sys.executable, "-I", "-B", "-c", _PROBE, str(root), str(private)],
                               cwd=private, env=env, capture_output=True, timeout=60)
    if probe.returncode or b"trace-reader-v1-ok" not in probe.stdout.splitlines() or pilot.program_digest(root) != digest:
        raise ValueError(f"rollback installation failed the mixed plaintext/v1 trace read: {root}")
    return root, digest


def restore(path: Path, batch_size: int, max_batches: int | None = None) -> dict:
    if batch_size < 1 or (max_batches is not None and max_batches < 1):
        raise ValueError("batch limits must be positive")
    restored = batches = 0
    last = None
    with database(path, writable=True) as conn:
        while max_batches is None or batches < max_batches:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if pilot.policy(conn) is not None:
                    raise ValueError("disable this workspace before restoring its bodies")
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_events'").fetchone():
                    break
                after = "" if last is None else " AND rowid>?"
                params = [traces.BODY_MAGIC, batch_size] if last is None else [traces.BODY_MAGIC, last, batch_size]
                rows = conn.execute(f"""SELECT rowid,id FROM trace_events WHERE typeof(payload_json)='blob'
                                        AND substr(payload_json,1,4)=? {after}
                                        ORDER BY rowid LIMIT ?""", params).fetchall()
                if not rows:
                    break
                for position, event_id in rows:
                    row = conn.execute("SELECT id,summary,payload_json FROM trace_events WHERE rowid=?", (position,)).fetchone()
                    summary, payload = decoded_text(row)
                    conn.execute("UPDATE trace_events SET summary=?,payload_json=? WHERE rowid=?", (summary, payload, position))
                    written = conn.execute("SELECT summary,payload_json FROM trace_events WHERE rowid=?", (position,)).fetchone()
                    if written is None or tuple(written) != (summary, payload):
                        raise ValueError(f"plaintext read-back mismatch: {event_id}")
                    restored += 1
                last = rows[-1][0]
            batches += 1
    return {"workspace": path.parent.name, "restored": restored, "committed_batches": batches, **inspect_workspace(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("status", "verify", "enable", "disable", "restore", "check-legacy"):
        sub = commands.add_parser(action)
        if action != "check-legacy":
            sub.add_argument("--workspace", required=action in {"enable", "disable", "restore"},
                             help="workspace directory, 64-character history key, or database path from status")
        if action == "enable":
            sub.add_argument("--rollback-install", required=True, type=Path, help="installed program retained for rollback")
        if action == "restore":
            sub.add_argument("--batch-size", type=int, default=32)
            sub.add_argument("--max-batches", type=int)
    args = parser.parse_args(argv)
    lock = (FileLock(runtime_paths.get_update_state_root(pilot.PROGRAM_ROOT) / "preparation.lock", timeout=0)
            if args.action == "enable" else nullcontext())
    with lock, StorageExclusiveGuard():
        root = history_root()
        if args.action == "check-legacy" or not args.workspace:
            data = inventory(root, verify=args.action == "verify")
            print(json.dumps(data, indent=2))
            return int(bool(data["errors"]) or (args.action == "check-legacy" and not data["legacy_ready"]))
        proof = verified_rollback(args.rollback_install) if args.action == "enable" else None
        path = workspace_database(root, args.workspace, create=proof is not None)
        if args.action in {"enable", "disable"}:
            with database(path, writable=True) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                if proof is not None:
                    pilot.enable(conn, path.parent.name, *proof)
                else:
                    pilot.disable(conn)
        data = (restore(path, args.batch_size, args.max_batches) if args.action == "restore"
                else inspect_workspace(path, verify=args.action == "verify"))
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
