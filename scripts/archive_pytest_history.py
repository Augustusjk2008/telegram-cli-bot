"""Archive confirmed pytest chat workspaces. Run from the installation root."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import ExitStack, closing, nullcontext
from datetime import date, datetime, time
from pathlib import Path

from bot import runtime_paths
from bot.storage_migration import StorageExclusiveGuard, _safe_manifest_relative
from scripts import _pytest_history_inventory as inv
from scripts import _pytest_history_move as move


PART_SIZE = 512
SCHEMA = """
CREATE TABLE batch(name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE workspaces(
    key TEXT PRIMARY KEY, working_dir TEXT, size INTEGER NOT NULL, db_size INTEGER NOT NULL,
    files TEXT NOT NULL, part INTEGER, state TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE INDEX by_part ON workspaces(part, state);
CREATE TABLE packs(part INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL, verified INTEGER NOT NULL);
CREATE TABLE moves(seq INTEGER PRIMARY KEY, key TEXT NOT NULL, action TEXT NOT NULL,
                   stamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
"""


def save(db, name, value):
    db.execute("INSERT OR REPLACE INTO batch VALUES (?, ?)", (name, json.dumps(value, ensure_ascii=False)))


def load(db, name):
    row = db.execute("SELECT value FROM batch WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else None


def history_root(loc):
    return inv.plain_path(Path(loc["storage"]) / "chat-history" / "workspaces")


def business(loc, owners, samples=None):
    root = history_root(loc)
    keys = sorted({owners["main"], *(row[1] for row in owners["profiles"])})
    matched = [key for key in keys if (root / key / "chat.sqlite").is_file()]
    messages = []
    # Keep only stable message IDs and content digests in the batch manifest.
    for key, message_id in (samples if samples is not None else ((key, None) for key in matched)):
        with inv.readonly(root / key / "chat.sqlite") as conn:
            if message_id is None:
                row = conn.execute("SELECT id, content FROM messages WHERE role='assistant' AND content<>'' "
                                   "ORDER BY rowid LIMIT 1").fetchone()
            else:
                row = conn.execute("SELECT id, content FROM messages WHERE id=?", (message_id,)).fetchone()
        if row:
            messages.append([key, row[0], hashlib.sha256(row[1].encode()).hexdigest()])
        if samples is None and len(messages) == 3:
            break
    return {"main": owners["main"], "profiles": owners["profiles"], "matched": matched, "messages": messages}


def scan(batch, loc, before):
    cutoff = int(datetime.combine(date.fromisoformat(before), time.min).timestamp()) * 1_000_000_000
    root = history_root(loc)
    if not root.is_dir():
        raise inv.Review(f"history directory missing: {root}")
    manifest = batch / "manifest.sqlite3"
    if manifest.exists() or any(p.name != ".archive.lock" for p in batch.iterdir()):
        raise inv.Review("scan requires a new batch directory")
    owners, baseline, config_error = {}, {}, ""
    try:
        owners = inv.protection(loc)
        baseline = business(loc, owners)
    except inv.READ_ERRORS as exc:
        config_error = str(exc)
    protected = set(owners.get("keys", []))
    pending = batch / "scan.partial"
    with closing(sqlite3.connect(pending)) as db:
        db.executescript(SCHEMA)
        save(db, "locations", loc)
        save(db, "before", before)
        save(db, "cutoff_ns", cutoff)
        save(db, "protection", owners)
        save(db, "business_before", baseline)
        save(db, "scan_error", config_error)
        index = 0
        for count, directory in enumerate(sorted(root.iterdir()), 1):
            row = inv.inspect(directory, protected, cutoff, config_error)
            part = None
            if row["state"] == "candidate":
                part = 1 + index // PART_SIZE
                index += 1
            db.execute("INSERT INTO workspaces VALUES (?,?,?,?,?,?,?,?)",
                       (row["key"], row["working_dir"], row["size"], row["db_size"],
                        json.dumps(row["files"], ensure_ascii=False), part, row["state"], row["reason"]))
            if count % 5000 == 0:
                print(f"scanned {count} workspaces", flush=True)
        db.commit()
    move.publish(pending, manifest)


def pack_path(batch, part):
    return inv.plain_path(batch / f"workspaces-{int(part):04d}.zip")


def members(row):
    if not inv.KEY.fullmatch(row["key"]):
        raise inv.Review("unsafe manifest workspace key")
    files = json.loads(row["files"])
    if not {"chat.sqlite", "workspace.json"} <= files.keys():
        raise inv.Review("incomplete workspace manifest")
    for name in files:
        parts = _safe_manifest_relative(name.removesuffix("/"))
        if not parts or "/".join(parts) != name.removesuffix("/"):
            raise inv.Review(f"unsafe archive member: {name}")
    return files


def pack_rows(db, part):
    return db.execute("SELECT * FROM workspaces WHERE part=? AND state NOT IN ('candidate','skipped','review') "
                      "ORDER BY key", (part,)).fetchall()


def check_zip(path, rows):
    with zipfile.ZipFile(path) as archive:
        names = set()
        for row in rows:
            for name, entry in members(row).items():
                full = row["key"] + "/" + name
                names.add(full)
                if full not in archive.NameToInfo or archive.getinfo(full).file_size != entry["size"]:
                    raise inv.Review(f"missing archive member or size mismatch: {full}")
                with archive.open(full) as stream:
                    if not name.endswith("/") and inv.digest(stream) != entry["sha256"]:
                        raise inv.Review(f"archive checksum mismatch: {full}")
        if len(names) != len(archive.infolist()) or names != set(archive.namelist()):
            raise inv.Review("unexpected or duplicate archive members")


def current_protection(db, loc):
    owners = inv.protection(loc)
    if not set(load(db, "protection")["sources"]) <= set(owners["sources"]):
        raise inv.Review("a protection source present at scan time is missing")
    return owners


def write_workspace(archive, source, row):
    files = members(row)
    inv.check_tree(source, files)
    for name, entry in files.items():
        member = row["key"] + "/" + name
        if name.endswith("/"):
            archive.writestr(member, b"")
        else:
            with move.reader(source / name) as stream, archive.open(member, "w", force_zip64=True) as dest:
                if inv.digest(stream, dest) != entry["sha256"]:
                    raise inv.Review(f"source checksum changed: {source / name}")
    inv.check_tree(source, files)


def archive(db, batch, loc):
    if problem := load(db, "scan_error"):
        raise inv.Review(problem)
    root = history_root(loc)
    parts = db.execute("SELECT DISTINCT part FROM workspaces WHERE state='candidate' ORDER BY part").fetchall()
    for (part,) in parts:
        target = pack_path(batch, part)
        temp = inv.plain_path(target.with_suffix(".zip.partial"))
        while rows := db.execute("SELECT * FROM workspaces WHERE part=? AND state='candidate' ORDER BY key",
                                 (part,)).fetchall():
            # A published ZIP may predate its manifest commit after a power loss.
            if not target.exists():
                owners = set(current_protection(db, loc)["keys"])
                with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as output:
                    for row in rows:
                        try:
                            if row["key"] in owners:
                                raise inv.Review("workspace now protected")
                            write_workspace(output, inv.workspace(root, row["key"]), row)
                        except inv.READ_ERRORS as exc:
                            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                                raise
                            with db:
                                db.execute("UPDATE workspaces SET state='review',reason=? WHERE key=?",
                                           (str(exc), row["key"]))
                            break
                    else:
                        row = None
                if row is not None:
                    temp.unlink()
                    continue
            pending = target if target.exists() else temp
            with pending.open("rb+") as stream:
                os.fsync(stream.fileno())
            check_zip(pending, rows)
            checksum, size = inv.file_hash(pending), pending.stat().st_size
            if pending == temp:
                move.publish(temp, target)
            with db:
                db.execute("INSERT INTO packs VALUES (?,?,?,0)", (part, checksum, size))
                db.execute("UPDATE workspaces SET state='packed' WHERE part=? AND state='candidate'", (part,))
                save(db, "samples", None)
            if part % 10 == 0 or part == parts[-1][0]:
                print(f"published archive {part}/{parts[-1][0]}", flush=True)
            break


def extract(row, archive, directory):
    files = members(row)
    directory.mkdir()
    for name, entry in files.items():
        path = directory / name
        if name.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(row["key"] + "/" + name) as src, path.open("xb") as out:
                if inv.digest(src, out) != entry["sha256"]:
                    raise inv.Review(f"restored content hash mismatch: {name}")
    # Create all descendants before restoring directory mtimes.
    for name in sorted(files, key=len, reverse=True):
        ns = files[name]["mtime_ns"]
        os.utime(directory / name, ns=(ns, ns))
    inv.check_tree(directory, files, hashes=True)
    with inv.readonly(directory / "chat.sqlite") as conn:
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise inv.Review(f"SQLite quick_check failed: {row['key']}")


def checked_pack(db, batch, part, stream):
    row = db.execute("SELECT sha256 FROM packs WHERE part=?", (part,)).fetchone()
    if not row or inv.digest(stream) != row[0]:
        with db:
            db.execute("UPDATE packs SET verified=-1 WHERE part=?", (part,))
        raise inv.Review(f"archive checksum mismatch: {pack_path(batch, part)}")
    stream.seek(0)


def verify(db, batch):
    parts = db.execute("SELECT part FROM packs ORDER BY part").fetchall()
    with db:
        db.execute("UPDATE packs SET verified=0")
        save(db, "samples", None)
    for (part,) in parts:
        try:
            with move.reader(pack_path(batch, part)) as stream:
                checked_pack(db, batch, part, stream)
                check_zip(stream, pack_rows(db, part))
        except inv.READ_ERRORS + (zipfile.BadZipFile,) as exc:
            with db:
                db.execute("UPDATE packs SET verified=-1 WHERE part=?", (part,))
            raise inv.Review(f"verification failed for archive {part}: {exc}") from exc
        with db:
            db.execute("UPDATE packs SET verified=1 WHERE part=?", (part,))
    samples = {}
    archived = "state IN ('packed','intent','detached','held','restored','failed')"
    for label, clause in (("small", "ORDER BY db_size,key"), ("large", "ORDER BY db_size DESC,key"),
                          ("additional_files", "AND (SELECT count(*) FROM json_each(files))>2 ORDER BY key")):
        row = db.execute(f"SELECT * FROM workspaces WHERE {archived} {clause} LIMIT 1").fetchone()
        if row:
            with tempfile.TemporaryDirectory(dir=batch) as tmp, move.reader(pack_path(batch, row["part"])) as stream:
                with zipfile.ZipFile(stream) as z:
                    extract(row, z, inv.workspace(Path(tmp), row["key"]))
            samples[label] = row["key"]
    with db:
        save(db, "samples", samples)
    print(json.dumps({"quick_check_samples": samples}), flush=True)


def check_location(db, loc):
    if inv.locations() != loc or load(db, "locations") != loc:
        raise inv.Review("active storage changed")
    journal = inv.plain_path(runtime_paths.get_storage_journal_path())
    locator = runtime_paths.read_storage_locator()
    if ((journal.exists() and inv.read_object(journal).get("state") != "completed")
            or (locator and locator["state"] != "completed")):
        raise inv.Review("storage migration pending")


def record_move(db, key, state, reason=""):
    db.execute("INSERT INTO moves(key, action) VALUES (?,?)", (key, state))
    db.execute("UPDATE workspaces SET state=?, reason=? WHERE key=?", (state, reason, key))


def detach(db, batch, loc, limit=None):
    if limit is not None and limit < 1:
        raise inv.Review("--limit must be positive")
    if load(db, "scan_error") or load(db, "samples") is None or db.execute(
        "SELECT 1 FROM workspaces WHERE state='candidate' UNION ALL SELECT 1 FROM packs WHERE verified<>1 LIMIT 1"
    ).fetchone():
        raise inv.Review("complete archive and verify before detaching")
    with StorageExclusiveGuard(), ExitStack() as parents:
        check_location(db, loc)
        root = history_root(loc)
        quarantine = inv.plain_path(batch / "quarantine")
        quarantine.mkdir(exist_ok=True)
        if root.stat().st_dev != quarantine.stat().st_dev:
            raise inv.Review("quarantine must be on the same volume as active history")
        parents.enter_context(move.pin_parent(root))
        parents.enter_context(move.pin_parent(quarantine))
        controls = inv.protection_files(loc)
        signature = inv.stamps(controls)
        protected = set(current_protection(db, loc)["keys"])

        def check_owner(key):
            nonlocal signature, protected
            current = inv.stamps(controls)
            if current[-1] != signature[-1]:
                raise inv.Review("installation environment changed; rerun detach")
            # An open WAL's timestamp can lag commits on Windows.
            if current != signature or current[6] is not None:
                protected = set(current_protection(db, loc)["keys"])
                signature = current
            if key in protected:
                raise inv.Review("workspace now protected")

        parts = db.execute("SELECT DISTINCT part FROM workspaces WHERE state IN ('packed','intent','held','failed') "
                           "ORDER BY part").fetchall()
        for (part,) in parts:
            rows = [r for r in pack_rows(db, part) if r["state"] in {"packed", "intent", "held", "failed"}]
            if limit is not None:
                rows = rows[:limit]
            with move.reader(pack_path(batch, part)) as stream:
                checked_pack(db, batch, part, stream)
                for start in range(0, len(rows), 64):
                    group = rows[start:start + 64]
                    with db:
                        for row in group:
                            record_move(db, row["key"], "intent")
                    with db:
                        for row in group:
                            key = row["key"]
                            if not inv.KEY.fullmatch(key):
                                raise inv.Review("unsafe manifest workspace key")
                            source, target = root / key, quarantine / key
                            try:
                                inv.workspace(root, key)
                                inv.workspace(quarantine, key)
                                files = members(row)
                                if row["state"] in {"intent", "failed"} and not source.exists() and target.is_dir():
                                    inv.check_tree(target, files, hashes=True)
                                    try:
                                        check_owner(key)
                                    except inv.Review:
                                        move.publish(target, source)
                                        raise
                                else:
                                    check_owner(key)
                                    move.detach_workspace(source, target, files, lambda: check_owner(key))
                            except inv.READ_ERRORS as exc:
                                if os.path.lexists(target) or not os.path.lexists(source):
                                    record_move(db, key, "failed", f"unresolved move: {exc}")
                                else:
                                    record_move(db, key, "held", str(exc))
                            else:
                                record_move(db, key, "detached")
            if part % 10 == 0 or part == parts[-1][0]:
                print(f"processed archive {part}/{parts[-1][0]}", flush=True)
            if limit is not None:
                limit -= len(rows)
                if limit == 0:
                    break
        before = load(db, "business_before")
        after = business(loc, current_protection(db, loc), [(r[0], r[1]) for r in before["messages"]])
        with db:
            save(db, "business_after", after)
        if after != before:
            raise inv.Review("business inventory or sampled message changed; see business_before/after in manifest")


def restore(db, batch, loc, key, to, live_roots=()):
    row = db.execute("SELECT * FROM workspaces WHERE key=?", (key,)).fetchone()
    if not row or row["state"] not in {"packed", "intent", "detached", "held", "restored", "failed"}:
        raise inv.Review("workspace does not have a published archive")
    with (StorageExclusiveGuard() if to is None else nullcontext()), ExitStack() as parents:
        if to is None:
            check_location(db, loc)
            parent = history_root(loc)
        else:
            parent = inv.outside(to, [Path(loc["storage"]), Path(loc["app"]), inv.REPO, batch / "quarantine", *live_roots])
            parent.mkdir(parents=True, exist_ok=True)
        parents.enter_context(move.pin_parent(parent))
        target = inv.workspace(parent, key)
        if os.path.lexists(target):
            raise FileExistsError(f"restore conflict: {target}")
        with move.reader(pack_path(batch, row["part"])) as stream:
            checked_pack(db, batch, row["part"], stream)
            with tempfile.TemporaryDirectory(dir=batch if to is None else parent) as tmp, zipfile.ZipFile(stream) as z:
                stage = inv.workspace(Path(tmp), key)
                extract(row, z, stage)
                with db:
                    db.execute("INSERT INTO moves(key,action) VALUES (?,?)",
                               (key, "restore_intent" if to is None else "export_intent"))
                move.publish(stage, target)
        with db:
            if to is None:
                record_move(db, key, "restored")
            else:
                db.execute("INSERT INTO moves(key,action) VALUES (?,'exported')", (key,))
        print(f"restored {target}", flush=True)


def report(db):
    def tally(where):
        row = db.execute("SELECT count(*),coalesce(sum(size),0),coalesce(sum(db_size),0) FROM workspaces WHERE "
                         + where).fetchone()
        return dict(zip(("count", "bytes", "database_bytes"), row))

    packed = "state IN ('packed','intent','detached','held','restored','failed')"
    before, after = load(db, "business_before"), load(db, "business_after")
    detached_copies = tally("key IN (SELECT key FROM moves WHERE action='detached')")
    deleted_copies = tally("key IN (SELECT key FROM moves WHERE action='quarantine_deleted')")
    cleanup = load(db, "cleanup") or {}
    free_after = cleanup.get("volume_free_after_cleanup", cleanup.get("volume_free_after_quarantine"))
    released = 0
    if cleanup:
        released = free_after - cleanup["volume_free_before"] if free_after is not None else None
    return {"candidate": tally("part IS NOT NULL"), "archived": tally(packed),
            "detached": tally("state='detached'"), "skipped": tally("state IN ('skipped','review','held')"),
            "failed": tally(f"state='failed' OR ({packed} AND part IN (SELECT part FROM packs WHERE verified=-1))"),
            "intent": tally("state='intent'"),
            "verified_packs": db.execute("SELECT count(*) FROM packs WHERE verified=1").fetchone()[0],
            "zip_bytes": db.execute("SELECT coalesce(sum(size),0) FROM packs").fetchone()[0],
            "deleted_from_quarantine": deleted_copies,
            "quarantine_bytes": detached_copies["bytes"] - deleted_copies["bytes"],
            "disk_bytes_released": released,
            "business": {"managed_bots": len(before["profiles"]), "workspace_databases": len(before["matched"]),
                         "sampled_messages": len(before["messages"]), "matches_after_detach": after == before if after else None}
                        if before else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("scan", "archive", "verify", "detach", "restore", "report"):
        sub = subs.add_parser(action)
        sub.add_argument("--batch-dir", required=True, type=Path)
        if action == "scan":
            sub.add_argument("--before", required=True, help="exclusive local date (YYYY-MM-DD)")
        if action == "detach":
            sub.add_argument("--limit", type=int, help="maximum number of workspaces for this invocation")
        if action == "restore":
            sub.add_argument("--workspace", required=True, help="workspace key from the manifest")
            sub.add_argument("--to", type=Path, help="isolated parent directory (default: active workspaces)")
    args = parser.parse_args(argv)
    active = args.action in {"scan", "archive", "detach"} or (args.action == "restore" and args.to is None)
    try:
        loc = inv.locations()
    except inv.READ_ERRORS:
        if active:
            raise
        loc = None  # An isolated restore can use the archive after loss of the installation.
    live_roots = [Path(loc["storage"]), Path(loc["app"])] if loc else []
    batch = inv.outside(args.batch_dir, [inv.REPO, *live_roots])
    if args.action == "scan":
        batch.mkdir(parents=True, exist_ok=True)
    manifest = inv.plain_path(batch / "manifest.sqlite3")
    if args.action != "scan" and not manifest.is_file():
        raise inv.Review("batch manifest does not exist")
    lock = nullcontext() if args.action == "report" else StorageExclusiveGuard(inv.plain_path(batch / ".archive.lock"))
    with lock:
        if args.action == "scan":
            scan(batch, loc, args.before)
        mode = "ro" if args.action == "report" else "rw"
        with closing(sqlite3.connect(manifest.as_uri() + "?mode=" + mode, uri=True)) as db:
            db.row_factory = sqlite3.Row
            recorded = load(db, "locations")
            inv.outside(batch, [Path(recorded["storage"]), Path(recorded["app"])])
            if active and recorded != loc:
                raise inv.Review("storage location or managed Bot configuration path changed")
            if args.action == "archive":
                archive(db, batch, loc)
            elif args.action == "verify":
                verify(db, batch)
            elif args.action == "detach":
                detach(db, batch, loc, args.limit)
            elif args.action == "restore":
                restore(db, batch, recorded, args.workspace, args.to, live_roots)
            summary = report(db)
            print(json.dumps(summary, indent=2), flush=True)
            if args.action == "detach" and summary["failed"]["count"]:
                raise inv.Review("unresolved moves; see workspaces.reason in the manifest")
            if problem := load(db, "scan_error"):
                raise inv.Review(problem)


if __name__ == "__main__":
    try:
        main()
    except inv.READ_ERRORS + (zipfile.BadZipFile,) as exc:
        sys.exit(str(exc))
