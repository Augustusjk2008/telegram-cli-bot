import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from bot import runtime_paths as paths
from bot.storage_migration import StorageExclusiveGuard, StorageMigrationError
from scripts import archive_pytest_history as tool


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TCB_PORTABLE_ROOT", str(tmp_path / "portable"))
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setenv("MANAGED_BOTS_FILE", str(tmp_path / "managed.json"))
    monkeypatch.setenv("WORKING_DIR", str(tmp_path / "business"))
    write_json(tmp_path / "managed.json", {"bots": []})
    paths.reset_runtime_path_cache_for_tests()
    yield tmp_path / "archives"
    paths.reset_runtime_path_cache_for_tests()


def create_history(wd):
    root = paths.get_chat_workspace_dir(wd)
    root.mkdir(parents=True)
    write_json(root / "workspace.json", {"workspace_key": root.name, "working_dir": str(wd),
                                         "normalized_working_dir": paths.normalize_workspace_dir(wd)})
    with closing(sqlite3.connect(root / "chat.sqlite")) as db, db:
        db.execute("CREATE TABLE messages(id TEXT,role TEXT,content TEXT)")
        db.execute("INSERT INTO messages VALUES ('m','assistant','recorded answer')")
    os.utime(root / "chat.sqlite", (1600000000, 1600000000))
    return root


def run(batch, action, *args):
    tool.main([action, "--batch-dir", str(batch), *map(str, args)])


def states(batch):
    with closing(sqlite3.connect(batch / "manifest.sqlite3")) as db:
        return {key: (state, reason) for key, state, reason in db.execute("SELECT key,state,reason FROM workspaces")}


def prepare(batch):
    run(batch, "scan", "--before", "2026-10-30")
    run(batch, "archive")
    run(batch, "verify")


def test_eligibility_checks_every_owner_and_reads_committed_wal(installation, tmp_path):
    pytest_run = tmp_path / "pytest-of-operator" / "pytest-7"
    work = {name: pytest_run / f"test_{name}0" for name in
            ("keep", "main", "disabled", "archived", "suspended", "json", "sql", "recent", "wal", "hash")}
    roots = {name: create_history(wd) for name, wd in work.items()}
    other = create_history(Path(tmp_path.anchor) / "projects" / "test_customer")
    write_json(paths.get_app_settings_path(), {"main_bot_profile": {"working_dir": str(work["main"])}})
    write_json(tmp_path / "managed.json", {"bots": [
        {"alias": "disabled", "working_dir": str(work["disabled"]), "enabled": False},
        {"alias": "archived", "working_dir": str(work["archived"]), "enabled": False, "archived": True},
        {"alias": "broken", "working_dir": str(work["suspended"]), "enabled": "invalid"}]})
    sessions = paths.get_session_store_path()
    write_json(sessions, {"1:2": {"working_dir": str(work["json"])}})
    cutoff = datetime(2026, 10, 30).timestamp()
    os.utime(roots["recent"] / "chat.sqlite", (cutoff, cutoff))
    (roots["wal"] / "chat.sqlite-journal").touch()
    meta = roots["hash"] / "workspace.json"
    write_json(meta, {**json.loads(meta.read_text()), "normalized_working_dir": "different"})
    before = {path: path.stat().st_mtime_ns for root in roots.values() for path in root.iterdir()}
    with closing(sqlite3.connect(sessions.with_suffix(".sqlite3"))) as sql:
        sql.execute("PRAGMA journal_mode=WAL")
        sql.execute("CREATE TABLE sessions(payload_json TEXT)")
        sql.execute("INSERT INTO sessions VALUES (?)", (json.dumps({"working_dir": str(work["sql"])}),))
        sql.commit()
        run(installation, "scan", "--before", "2026-10-30")
    snapshot = states(installation)
    for name in ("main", "disabled", "archived", "suspended", "json", "sql"):
        assert snapshot[roots[name].name] == ("skipped", "protected workspace")
    assert snapshot[roots["keep"].name][0] == "candidate"
    assert snapshot[roots["recent"].name][0] == "skipped"
    assert snapshot[other.name] == ("skipped", "outside pytest case")
    assert all(snapshot[roots[name].name][0] == "review" for name in ("wal", "hash"))
    assert all(path.stat().st_mtime_ns == ns for path, ns in before.items())


def test_incomplete_configuration_keeps_candidates_in_review(installation, tmp_path):
    source = create_history(tmp_path / "pytest-of-user" / "pytest-4" / "test_data0")
    (tmp_path / "managed.json").write_text("{")
    with pytest.raises(tool.inv.Review):
        run(installation, "scan", "--before", "2026-10-30")
    assert states(installation)[source.name][0] == "review"
    assert source.exists()


def test_links_and_out_of_bounds_paths(installation, tmp_path):
    source = create_history(tmp_path / "pytest-of-user" / "pytest-4" / "test_link0")
    external = tmp_path / "outside"
    external.mkdir()
    link = source / "nested"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(external), str(link))
    else:
        link.symlink_to(external, target_is_directory=True)
    run(installation, "scan", "--before", "2026-10-30")
    assert states(installation)[source.name][0] == "review"
    with pytest.raises(tool.inv.Review, match="overlap"):
        run(paths.get_active_storage_root() / "batch", "scan", "--before", "2026-10-30")
    with pytest.raises((tool.inv.Review, StorageMigrationError)):
        tool.members({"key": source.name, "files": json.dumps({"chat.sqlite": {}, "workspace.json": {},
                                                               "../outside": {}})})


def test_corrupt_published_archive_blocks_detach_and_restore(installation, tmp_path):
    source = create_history(tmp_path / "pytest-of-user" / "pytest-4" / "test_archive0")
    prepare(installation)
    with next(installation.glob("*.zip")).open("ab") as stream:
        stream.write(b"altered")
    with pytest.raises(tool.inv.Review, match="checksum"):
        run(installation, "detach")
    with pytest.raises(tool.inv.Review, match="checksum"):
        run(installation, "verify")
    with pytest.raises(tool.inv.Review, match="checksum"):
        run(installation, "restore", "--workspace", source.name, "--to", tmp_path / "recovered")
    assert source.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive directory rename")
def test_recheck_references_writers_and_full_source_fingerprints(installation, tmp_path):
    work = tmp_path / "pytest-of-user" / "pytest-4"
    locked, changed, claimed, linked = [
        create_history(work / f"test_{name}0") for name in ("locked", "changed", "claimed", "linked")
    ]
    prepare(installation)
    import _winapi
    saved = tmp_path / "saved"
    tool.move.publish(linked, saved)
    _winapi.CreateJunction(str(saved), str(linked))
    write_json(paths.get_session_store_path(), {"1:2": {"working_dir": str(work / "test_claimed0")}})
    path = changed / "workspace.json"
    info = path.stat()
    data = path.read_bytes()
    path.write_bytes(b"!" + data[1:])
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    with (locked / "chat.sqlite").open("rb"):
        run(installation, "detach")
    snapshot = states(installation)
    assert all(snapshot[root.name][0] == "held" and root.is_dir() for root in (locked, claimed, changed, linked))
    run(installation, "detach")
    assert states(installation)[locked.name][0] == "detached"


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive directory rename")
def test_crash_after_rename_resumes_and_single_restore_preserves_conflicts(installation, tmp_path):
    source = create_history(tmp_path / "pytest-of-user" / "pytest-4" / "test_resume0")
    write_json(source / "favorites.json", ["starred"])
    (source / "extra" / "empty").mkdir(parents=True)
    prepare(installation)
    with StorageExclusiveGuard(), pytest.raises(StorageMigrationError):
        run(installation, "detach")
    script = """
import os, sys
sys.path.insert(0, sys.argv[1])
from scripts import archive_pytest_history as tool
original = tool.move.detach_workspace
def interrupted(*args):
    original(*args)
    os._exit(37)
tool.move.detach_workspace = interrupted
tool.main(['detach', '--batch-dir', sys.argv[2]])
"""
    child = subprocess.run([sys.executable, "-c", script, str(tool.inv.REPO), str(installation)], cwd=tmp_path)
    assert child.returncode == 37
    assert not source.exists() and states(installation)[source.name][0] == "intent"
    run(installation, "detach")
    assert states(installation)[source.name][0] == "detached"
    # A new directory for the same workspace is owned by the active installation.
    source.mkdir()
    (source / "new").write_bytes(b"new")
    with pytest.raises(FileExistsError, match="conflict"):
        run(installation, "restore", "--workspace", source.name)
    assert (source / "new").read_bytes() == b"new"
    (source / "new").unlink()
    source.rmdir()
    run(installation, "restore", "--workspace", source.name)
    assert json.loads((source / "favorites.json").read_text()) == ["starred"]
    assert (source / "extra" / "empty").is_dir()
    assert states(installation)[source.name][0] == "restored"


def test_isolated_restore_from_zip_with_unavailable_live_storage(installation, tmp_path):
    source = create_history(tmp_path / "pytest-of-user" / "pytest-4" / "test_offline_restore0")
    prepare(installation)
    write_json(paths.get_storage_locator_path(), {"schema": 1, "datasetIdentity": "tcb", "state": "completed",
                                                  "targetRoot": str(tmp_path / "unavailable")})
    recovery = tmp_path / "recovery"
    run(installation, "restore", "--workspace", source.name, "--to", recovery)
    assert (recovery / source.name / "chat.sqlite").read_bytes() == (source / "chat.sqlite").read_bytes()


def test_child_chat_store_writes_to_the_pytest_home(tmp_path):
    target = paths.get_chat_history_db_path(tmp_path)
    # Check the destination before a real write, even if isolation regresses.
    script = """
import sys
from pathlib import Path
from bot.web.chat_store import ChatStore
wd, expected = sys.argv[1:]
store = ChatStore(wd)
assert store.db_path == Path(expected)
store.create_conversation(bot_id=1, bot_alias='test', user_id=2, cli_type='codex',
                          working_dir=wd, session_epoch=0, native_provider='codex')
"""
    assert target.is_relative_to(Path.home()) and Path.home().name.startswith("orbit-safe-claw-pytest-home-")
    subprocess.run([sys.executable, "-c", script, str(tmp_path), str(target)], cwd=tool.inv.REPO, check=True)
    assert target.is_file()
