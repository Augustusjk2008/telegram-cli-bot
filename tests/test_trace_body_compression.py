import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from bot import runtime_paths
from bot.update_migration_gate import validate_update_migrations
from bot.update_state import UpdateStore
from bot.web import trace_body_policy as pilot, trace_previews as traces
from bot.web.chat_store import ChatStore
from scripts import trace_body_compression as maintenance


def start(store):
    return store.begin_turn(bot_id=1, bot_alias="main", user_id=2, agent_id="main", cli_type="codex",
                            working_dir=str(store.workspace_dir), session_epoch=0, user_text="test", native_provider="codex")


def event(call, text, kind="tool_result"):
    return {"kind": kind, "call_id": call, "summary": text, "payload": {"output": text}}


def configure(store, rollback):
    with maintenance.database(store.db_path, writable=True) as c, c:
        c.execute("BEGIN IMMEDIATE")
        pilot.enable(c, store.workspace_key, rollback, pilot.program_digest(rollback))


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.setenv("TCB_PORTABLE_ROOT", str(tmp_path / "portable"))
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "app"))
    runtime_paths.reset_runtime_path_cache_for_tests()
    yield tmp_path
    runtime_paths.reset_runtime_path_cache_for_tests()


@pytest.fixture
def rollback(install):
    root = install / "rollback"
    shutil.copytree(pilot.PROGRAM_ROOT / "bot", root / "bot", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(pilot.PROGRAM_ROOT / "VERSION", root / "VERSION")
    return root


def test_encoder_counts_utf8_and_includes_framing_cost_and_falls_back(monkeypatch):
    text = "é" * (traces.MIN_BODY_BYTES // 2)
    assert traces.encode_body("e", text[:-1], None) == (text[:-1], None)
    summary, encoded = traces.encode_body("e", text, None)
    assert traces.decode_body("e", summary, encoded) == (text, None)
    assert isinstance(encoded, bytes) and len(encoded) < traces.MIN_BODY_BYTES
    monkeypatch.setattr(traces, "_compress_body", lambda body: b"x" * (len(body) - 1))
    assert traces.encode_body("e", text, None) == (text, None)

    def fail(_body):
        raise RuntimeError("codec unavailable")

    monkeypatch.setattr(traces, "_compress_body", fail)
    assert traces.encode_body("e", text, "null") == (text, "null")


def test_pilot_only_writes_new_live_results_in_its_workspace_and_checks_fallback(install, rollback, monkeypatch):
    store, other = ChatStore(install / "selected"), ChatStore(install / "other")
    turn, sibling = start(store), start(other)
    big = "工具输出" * 18000
    store.append_trace_events(turn.turn_id, [event("legacy", "short")])
    configure(store, rollback)
    store.append_trace_events(turn.turn_id, [event("new", "running"), event("call", big, "tool_call")])
    store.append_trace_events(turn.turn_id, [event("new", big), event("legacy", big)])
    other.append_trace_events(sibling.turn_id, [event("other", big)])
    recovered = start(store)
    store.replace_trace_events(recovered.turn_id, [event("recovered", big)])
    with maintenance.database(store.db_path) as c:
        types = dict(c.execute("SELECT call_id,typeof(payload_json) FROM trace_events"))
        assert types == {"legacy": "text", "new": "blob", "call": "text", "recovered": "text"}
    assert maintenance.inspect_workspace(other.db_path)["compressed"] == 0
    with monkeypatch.context() as patch:
        patch.setattr(traces, "decode_body", lambda *args: pytest.fail("a ready preview decoded the body"))
        assert store.get_message_trace(turn.assistant_message_id, compact=True)["trace"][1]["content_truncated"]
    assert store.get_message_trace_event(turn.assistant_message_id, kind="tool_result", call_id="new")["event"]["summary"] == big

    (rollback / "bot/web/trace_previews.py").unlink()
    store.append_trace_events(turn.turn_id, [event("missing_reader", big)])
    status = maintenance.inspect_workspace(store.db_path)
    assert status["configured"] and not status["enabled"] and status["compressed"] == 1
    with pytest.raises(ValueError, match="disable"):
        maintenance.restore(store.db_path, 1)
    with maintenance.database(store.db_path, writable=True) as c, c:
        c.execute("BEGIN IMMEDIATE")
        pilot.disable(c)
    assert maintenance.inspect_workspace(store.db_path)["compressed"] == 1


def test_restore_verifies_exact_text_and_null_in_atomic_restartable_batches(install):
    store = ChatStore(install / "archived-bot")
    h = start(store)
    values = [("é" * 41000, None), ("输出" * 30000, ' { "z" : "原文", "a" : 1 } '), ("X" * 80000, "")]
    with store._connect_for_write() as c:
        c.execute("INSERT INTO trace_events (id,turn_id,ordinal,kind,summary,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                  ("legacy-json", h.turn_id, 1, "event", "", b' {"readable":true} ', "now"))
        for i, (summary, payload) in enumerate(values, 2):
            _, encoded = traces.encode_body(str(i), summary, payload)
            assert isinstance(encoded, bytes)
            c.execute("INSERT INTO trace_events (id,turn_id,ordinal,kind,summary,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                      (str(i), h.turn_id, i, "tool_result", "", encoded, "now"))
        valid = encoded
        c.execute("UPDATE trace_events SET payload_json=? WHERE id='4'", (valid[:-1],))
    first = maintenance.restore(store.db_path, 1, max_batches=1)
    assert first["restored"] == 1 and first["compressed"] == 2
    with pytest.raises(ValueError, match="trace body 4"):
        maintenance.restore(store.db_path, 5)
    with maintenance.database(store.db_path, writable=True) as c, c:
        assert [tuple(row) for row in c.execute("SELECT id,typeof(payload_json) FROM trace_events ORDER BY ordinal")] == [
            ("legacy-json", "blob"), ("2", "null"), ("3", "blob"), ("4", "blob")]
        c.execute("UPDATE trace_events SET payload_json=? WHERE id='4'", (valid,))
    assert maintenance.restore(store.db_path, 1)["restored"] == 2
    with maintenance.database(store.db_path) as c:
        assert [tuple(row) for row in c.execute("SELECT summary,payload_json FROM trace_events WHERE ordinal>1 ORDER BY ordinal")] == values
    assert maintenance.restore(store.db_path, 1)["restored"] == 0


@pytest.mark.skipif(not hasattr(sqlite3.Connection, "setlimit"), reason="per-connection SQLite limit requires Python 3.11")
def test_pilot_cannot_admit_a_body_too_large_to_restore_to_plaintext(install, rollback, monkeypatch):
    store = ChatStore(install / "limit")
    turn = start(store)
    configure(store, rollback)
    connect = store._connect

    def limited(*, create):
        conn = connect(create=create)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 90 * 1024)
        return conn

    monkeypatch.setattr(store, "_connect", limited)
    with pytest.raises(sqlite3.DataError):
        store.append_trace_events(turn.turn_id, [event("oversize", "x" * 60000)])
    store.append_trace_events(turn.turn_id, [event("restorable", "x" * 40000)])
    assert maintenance.inspect_workspace(store.db_path)["compressed"] == 1


def test_legacy_check_includes_unlisted_databases_wal_and_unreadable_records(install):
    root = maintenance.history_root()
    archive = root / "unlisted" / "previous.copy"
    archive.parent.mkdir(parents=True)
    with closing(sqlite3.connect(archive)) as writer, writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE trace_events(id TEXT PRIMARY KEY,summary TEXT,payload_json TEXT)")
        writer.commit()
        _, encoded = traces.encode_body("e", "x" * traces.MIN_BODY_BYTES, None)
        writer.execute("INSERT INTO trace_events VALUES ('e','',?)", (encoded,))
        writer.commit()
        found = maintenance.inventory(root, verify=True)
        assert found["compressed"] == 1 and not found["legacy_ready"]
        assert found["blockers"] == [str(archive)]
        assert maintenance.workspace_database(root, str(archive)) == archive
        assert maintenance.restore(archive, 4)["restored"] == 1
    files_before = set(archive.parent.iterdir())
    assert maintenance.inspect_workspace(archive)["compressed"] == 0
    assert set(archive.parent.iterdir()) == files_before
    with sqlite3.connect(archive) as writer:
        writer.execute("UPDATE trace_events SET payload_json=? WHERE id='e'", (b"damaged binary",))
    report = maintenance.inventory(root)
    assert not report["legacy_ready"] and "trace payload e" in report["errors"][0]["error"]


def test_check_discards_quiet_snapshot_if_a_wal_writer_appears(install, monkeypatch):
    file = install / "chat.sqlite"
    with closing(sqlite3.connect(file)) as c, c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE trace_events(id TEXT PRIMARY KEY,summary TEXT,payload_json TEXT)")
    original = maintenance._inspect
    passes = []
    with closing(sqlite3.connect(file)) as writer:
        def concurrent_read(conn, path, verify):
            result = original(conn, path, verify)
            passes.append(result["compressed"])
            if len(passes) == 1:
                summary, encoded = traces.encode_body("new", "x" * traces.MIN_BODY_BYTES, None)
                with writer:
                    writer.execute("INSERT INTO trace_events VALUES ('new',?,?)", (summary, encoded))
            return result

        monkeypatch.setattr(maintenance, "_inspect", concurrent_read)
        assert maintenance.inspect_workspace(file)["compressed"] == 1
    assert passes == [0, 1]


def test_rollback_probe_and_managed_cross_version_provenance(install, rollback, monkeypatch):
    workspace = install / "new-project"
    workspace.mkdir()
    assert maintenance.main(["enable", "--workspace", str(workspace), "--rollback-install", str(rollback)]) == 0
    store = ChatStore(workspace)
    assert maintenance.inspect_workspace(store.db_path)["enabled"]
    assert maintenance.main(["disable", "--workspace", store.workspace_key]) == 0
    with pytest.raises(ValueError, match="separately retained"):
        maintenance.verified_rollback(pilot.PROGRAM_ROOT)
    current = install / "packaged"
    current.mkdir()
    (current / ".update-manifest.json").write_text(json.dumps({"commit": "target"}))
    monkeypatch.setattr(pilot, "PROGRAM_ROOT", current)
    state = UpdateStore(current)
    old_hashes = {name: hashlib.sha256((rollback / name).read_bytes()).hexdigest() for name in pilot.READER_FILES}
    old_hashes["bot/web/trace_previews.py"] = None  # The actual pre-update installation was original 3.2.0.
    state.mutate(lambda s: s.update(job={"phase": "succeeded", "manifest": {"commit": "target"}, "original_hashes": old_hashes}))
    with pytest.raises(ValueError, match="pre-update"):
        maintenance.verified_rollback(rollback)
    (current / ".update-manifest.json").unlink()
    (rollback / "bot/web/trace_previews.py").write_text("def decode_body(*args): return '', None\n", encoding="utf-8")
    with pytest.raises(ValueError, match="failed the mixed"):
        maintenance.verified_rollback(rollback)


def test_update_gate_requires_plaintext_and_closed_switch_for_legacy_target(install, rollback):
    current, target = install / "current", install / "legacy"
    for root in (current, target):
        (root / "bot/migrations").mkdir(parents=True)
        (root / "bot/migrations/runner.py").write_text("MIGRATION_IDS=('001',)\n")
    (current / "bot/web").mkdir()
    (current / "bot/web/trace_body_policy.py").touch()
    prepared = {"staging_dir": str(target), "manifest": {"migrations": {"backward_compatible": True}}}
    store = ChatStore(install / "history")
    h = start(store)
    configure(store, rollback)
    with pytest.raises(ValueError, match="check-legacy"):
        validate_update_migrations(current, prepared)
    store.append_trace_events(h.turn_id, [event("e", "x" * traces.MIN_BODY_BYTES)])
    with maintenance.database(store.db_path, writable=True) as c, c:
        c.execute("BEGIN IMMEDIATE")
        pilot.disable(c)
    with pytest.raises(ValueError, match="check-legacy"):
        validate_update_migrations(current, prepared)
    maintenance.restore(store.db_path, 2)
    validate_update_migrations(current, prepared)


def test_same_package_reinstalled_from_a_different_predecessor_needs_new_opt_in(install, rollback, monkeypatch):
    fallback = pilot.PROGRAM_ROOT
    monkeypatch.setattr(pilot, "PROGRAM_ROOT", rollback)
    (rollback / ".update-manifest.json").write_text(json.dumps({"commit": "same-pilot-build"}))
    updates = UpdateStore(rollback)
    updates.mutate(lambda state: state.update(job={"phase": "succeeded", "job_id": "first",
                                                  "manifest": {"commit": "same-pilot-build"}}))
    store = ChatStore(install / "project")
    handle = start(store)
    configure(store, fallback)
    assert maintenance.inspect_workspace(store.db_path)["enabled"]
    updates.mutate(lambda state: state["job"].update(job_id="reinstalled"))
    store.append_trace_events(handle.turn_id, [event("after-jump", "x" * traces.MIN_BODY_BYTES)])
    report = maintenance.inspect_workspace(store.db_path)
    assert report["configured"] and not report["enabled"] and report["compressed"] == 0
