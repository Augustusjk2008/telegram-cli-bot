from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bot import runtime_paths
from bot import storage_migration as migration_module
from bot.storage_migration import StorageMigrationError, StorageMigrationService


@pytest.fixture
def migration_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    target = tmp_path / "target"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(repo)
    monkeypatch.delenv("TCB_DATA_DIR", raising=False)
    runtime_paths.reset_runtime_path_cache_for_tests()
    return home, repo, target


def _make_sources(home: Path, *, with_sqlite: bool = True) -> tuple[Path, Path]:
    app = home / ".tcb" / "orbit-safe-claw"
    app.mkdir(parents=True)
    (app / "config.json").write_text(
        json.dumps(
            {
                "path": str(app / "attachments"),
                "text": str(app / "attachments"),
            }
        ),
        encoding="utf-8",
    )
    history = home / ".tcb" / "chat-history" / "workspaces" / "workspace-key"
    history.mkdir(parents=True)
    if with_sqlite:
        connection = sqlite3.connect(history / "chat.sqlite")
        connection.execute("CREATE TABLE messages (text TEXT NOT NULL)")
        connection.execute("INSERT INTO messages VALUES ('history survives')")
        connection.commit()
        connection.close()
    (home / ".tcb" / "chat-attachments").mkdir()
    return app, history


def _execute(service: StorageMigrationService, target: Path) -> dict[str, object]:
    plan = service.preview(str(target))
    assert plan["blockers"] == []
    assert service.begin(str(plan["id"]))["state"] == "stopping"
    return service.execute(str(plan["id"]))


def test_snapshot_only_checks_source_roots_and_defers_full_inventory(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, _target = migration_context
    _make_sources(home, with_sqlite=False)

    def fail_full_walk(*_args: object, **_kwargs: object) -> tuple[list[dict[str, object]], int]:
        raise AssertionError("snapshot must not recursively scan source files")

    monkeypatch.setattr(migration_module, "_walk_source", fail_full_walk)
    snapshot = StorageMigrationService(repo).snapshot()

    assert snapshot["canMigrate"] is True
    assert snapshot["sizePending"] is True
    assert snapshot["totalBytes"] == 0


@pytest.mark.parametrize("with_sqlite", [False, True])
def test_preview_persists_manifest_and_execute_reuses_it(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    with_sqlite: bool,
) -> None:
    home, repo, target = migration_context
    _make_sources(home, with_sqlite=with_sqlite)
    service = StorageMigrationService(repo)
    plan = service.preview(str(target))

    journal = json.loads(runtime_paths.get_storage_journal_path().read_text(encoding="utf-8"))
    assert journal["state"] == "preparing"
    assert journal["plan"]["entries"]
    assert {"completedBytes", "totalBytes", "completedFiles", "totalFiles", "currentItem", "speedBytesPerSecond", "etaSeconds", "message"} <= set(journal)

    def fail_inventory(*_args: object, **_kwargs: object) -> tuple[list[dict[str, object]], int]:
        raise AssertionError("begin/execute must reuse the persisted preview manifest")

    monkeypatch.setattr(migration_module, "_walk_source", fail_inventory)
    restarted = StorageMigrationService(repo)
    assert restarted.begin(str(plan["id"]))["state"] == "stopping"
    job = restarted.execute(str(plan["id"]))
    assert job["state"] == "awaiting_restart"
    assert job["completedBytes"] == job["totalBytes"]
    assert job["completedFiles"] == job["totalFiles"]


def test_preview_ignores_sqlite_sidecar_that_closes_during_inventory(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    sidecar = app / "usage.sqlite3-wal"
    sidecar.write_bytes(b"volatile WAL")
    service = StorageMigrationService(repo)
    original_hash = migration_module._hash_file

    def disappear_during_hash(path: Path) -> str:
        if path == sidecar:
            sidecar.unlink()
            raise OSError(2, "No such file or directory", str(path))
        return original_hash(path)

    monkeypatch.setattr(migration_module, "_hash_file", disappear_during_hash)
    plan = service.preview(str(target))

    assert plan["blockers"] == []
    assert all(entry["relativePath"] != sidecar.name for entry in service._plans[plan["id"]]["entries"])


def test_copy_accepts_changed_sqlite_shared_memory_snapshot(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home)
    usage_db = app / "usage.sqlite3"
    connection = sqlite3.connect(usage_db)
    connection.execute("CREATE TABLE samples (value TEXT NOT NULL)")
    connection.execute("INSERT INTO samples VALUES ('kept')")
    connection.commit()
    connection.close()
    sidecar = app / "usage.sqlite3-shm"
    sidecar.write_bytes(b"preview shared memory")

    service = StorageMigrationService(repo)
    plan = service.preview(str(target))
    service.begin(str(plan["id"]))
    original_copyfile = migration_module.shutil.copyfile

    def copy_with_changed_shared_memory(source: str | Path, destination: str | Path) -> str:
        result = original_copyfile(source, destination)
        if Path(source) == sidecar:
            Path(destination).write_bytes(b"runtime shared memory")
        return result

    monkeypatch.setattr(migration_module.shutil, "copyfile", copy_with_changed_shared_memory)
    job = service.execute(str(plan["id"]))

    assert job["state"] == "awaiting_restart"
    assert (target / "orbit-safe-claw" / "usage.sqlite3-shm").read_bytes() == b"runtime shared memory"


def test_journal_progress_is_throttled_until_stage_changes(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _home, repo, _target = migration_context
    service = StorageMigrationService(repo)
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        migration_module,
        "_atomic_write_json",
        lambda _path, payload: writes.append(dict(payload)),
    )
    journal: dict[str, object] = {
        "state": "copying",
        "phase": "copying",
        "totalBytes": 64 * 1024 * 1024,
        "completedBytes": 0,
    }
    service._write_journal(journal, force=True)
    journal["completedBytes"] = 1
    service._write_journal(journal)
    assert len(writes) == 1

    journal["state"] = "rewriting"
    journal["phase"] = "rewriting"
    service._write_journal(journal)
    assert len(writes) == 2


@pytest.mark.parametrize("next_phase", ["copying", "rewriting"])
def test_live_progress_uses_small_restart_safe_sidecar(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    next_phase: str,
) -> None:
    _home, repo, _target = migration_context
    service = StorageMigrationService(repo)
    journal: dict[str, object] = {
        "schema": migration_module.STORAGE_SCHEMA,
        "datasetIdentity": migration_module.DATASET_IDENTITY,
        "id": "progress-job",
        "state": "copying",
        "phase": "copying",
        "totalBytes": 64 * 1024 * 1024,
        "completedBytes": 0,
    }
    service._write_journal(journal, force=True)
    monkeypatch.setattr(migration_module, "_JOURNAL_SECONDS", 0.0)
    journal["completedBytes"] = 1
    service._write_journal(journal)

    progress_path = runtime_paths.get_storage_progress_path()
    assert progress_path.is_file()
    old_progress = progress_path.read_bytes()
    restarted = StorageMigrationService(repo)
    assert restarted.status()["completedBytes"] == 1

    journal["state"] = journal["phase"] = next_phase
    journal["completedBytes"] = 2
    service._write_journal(journal, force=True)
    assert not progress_path.exists()
    progress_path.write_bytes(old_progress)
    recovered = StorageMigrationService(repo).status()
    assert recovered["state"] == next_phase
    assert recovered["completedBytes"] == 2


def test_copy_progress_does_not_rewrite_full_inventory(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    preview = service.preview(str(target))
    service.begin(str(preview["id"]))
    plan = service._plans[str(preview["id"])]
    journal = service._journal_payload(plan, "copying", "copying")
    clock = [100.0]
    writes: list[tuple[Path, dict[str, object]]] = []

    def write(_path: Path, payload: dict[str, object]) -> None:
        writes.append((_path, dict(payload)))
        clock[0] += 1.0  # Serializing a large inventory takes longer than one tick.

    monkeypatch.setattr(migration_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(migration_module, "_atomic_write_json", write)
    service._write_journal(journal, force=True)
    for completed in range(1, 6):
        clock[0] += 10.0
        journal["completedBytes"] = completed
        service._write_journal(journal)

    assert service.status()["completedBytes"] == 5
    journal_writes = [path for path, _payload in writes if path == runtime_paths.get_storage_journal_path()]
    assert len(journal_writes) == 1
    assert writes[0][1]["plan"]["entries"]
    assert all("plan" not in payload for path, payload in writes if path == runtime_paths.get_storage_progress_path())
    journal["state"] = journal["phase"] = "rewriting"
    service._write_journal(journal)
    assert len([path for path, _payload in writes if path == runtime_paths.get_storage_journal_path()]) == 2


def test_copy_speed_excludes_preview_confirmation_wait(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    clock = [100.0]
    monkeypatch.setattr(migration_module.time, "time", lambda: clock[0])
    preview = service.preview(str(target))
    clock[0] += 3600
    service.begin(str(preview["id"]))
    plan = service._plans[str(preview["id"])]
    plan["totalBytes"] = 4096
    journal = service._journal_payload(plan, "copying", "copying")
    service._write_journal(journal, force=True)
    clock[0] += 2
    journal["completedBytes"] = 2048
    service._write_journal(journal)

    assert service.status()["speedBytesPerSecond"] == 1024
    assert service.status()["etaSeconds"] == 2


@pytest.mark.parametrize("close_before_copy,nested", [(True, True), (False, True), (True, False)])
def test_migration_preserves_sqlite_writes_flushed_after_preview(
    migration_context: tuple[Path, Path, Path],
    close_before_copy: bool,
    nested: bool,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    sessions = app / "sessions" if nested else app
    sessions.mkdir(exist_ok=True)
    source = sessions / "session_store.sqlite3"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE messages (text TEXT NOT NULL)")
        connection.execute("INSERT INTO messages VALUES ('before preview')")
        connection.commit()
        service = StorageMigrationService(repo)
        preview = service.preview(str(target))
        assert preview["blockers"] == []
        connection.execute("INSERT INTO messages VALUES ('flushed on stop')")
        connection.commit()
        if close_before_copy:
            connection.close()

        service.begin(str(preview["id"]))
        assert service.execute(str(preview["id"]))["state"] == "awaiting_restart"
    finally:
        connection.close()

    runtime_paths.reset_runtime_path_cache_for_tests()
    assert StorageMigrationService(repo).finalize_startup()["state"] == "completed"
    copied = target / "orbit-safe-claw" / source.relative_to(app)
    with sqlite3.connect(copied) as migrated:
        assert migrated.execute("SELECT text FROM messages ORDER BY rowid").fetchall() == [
            ("before preview",), ("flushed on stop",),
        ]
    assert not app.exists()


def test_busy_sqlite_checkpoint_preserves_sources(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, history = _make_sources(home)
    connection = sqlite3.connect(history / "chat.sqlite")
    reader = sqlite3.connect(history / "chat.sqlite")
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        service = StorageMigrationService(repo)
        preview = service.preview(str(target))
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM messages").fetchall()
        connection.execute("INSERT INTO messages VALUES ('last write')")
        connection.commit()
        service.begin(str(preview["id"]))
        with pytest.raises(StorageMigrationError, match="WAL 合并"):
            service.execute(str(preview["id"]))
        assert not runtime_paths.get_storage_locator_path().exists()
        assert app.exists()
        assert connection.execute("SELECT count(*) FROM messages").fetchone() == (2,)
    finally:
        reader.close()
        connection.close()


@pytest.mark.parametrize("change", ["source_write", "target_wal_removed", "target_wal_corrupt"])
def test_wal_change_blocks_cleanup(
    migration_context: tuple[Path, Path, Path],
    change: str,
) -> None:
    home, repo, target = migration_context
    app, history = _make_sources(home)
    connection = sqlite3.connect(history / "chat.sqlite")
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO messages VALUES ('copied')")
        connection.commit()
        _execute(StorageMigrationService(repo), target)
        target_wal = target / "chat-history" / "workspaces" / "workspace-key" / "chat.sqlite-wal"
        if change == "source_write":
            connection.execute("INSERT INTO messages VALUES ('keep this write')")
            connection.commit()
        elif change == "target_wal_removed":
            target_wal.unlink()
        else:
            target_wal.write_bytes(b"corrupt WAL")

        runtime_paths.reset_runtime_path_cache_for_tests()
        with pytest.raises(StorageMigrationError):
            StorageMigrationService(repo).finalize_startup()
        assert app.exists()
        assert (history / "chat.sqlite").exists()
    finally:
        connection.close()


def test_success_copies_sqlite_and_deletes_sources_after_startup(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, history = _make_sources(home)
    service = StorageMigrationService(repo)

    job = _execute(service, target)

    assert job["state"] == "awaiting_restart"
    assert app.exists()
    assert history.exists()
    runtime_paths.reset_runtime_path_cache_for_tests()
    restarted = StorageMigrationService(repo)
    assert runtime_paths.get_app_data_root() == target / "orbit-safe-claw"
    assert restarted.finalize_startup()["state"] == "completed"
    assert not app.exists()
    assert not history.exists()

    copied_db = target / "chat-history" / "workspaces" / "workspace-key" / "chat.sqlite"
    connection = sqlite3.connect(copied_db)
    assert connection.execute("SELECT text FROM messages").fetchone() == ("history survives",)
    connection.close()
    copied_config = json.loads((target / "orbit-safe-claw" / "config.json").read_text(encoding="utf-8"))
    assert copied_config["path"] == str(target / "orbit-safe-claw" / "attachments")
    assert copied_config["text"] == str(app / "attachments")


def test_disk_space_block_preserves_sources(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    usage_type = type(migration_module.shutil.disk_usage(str(repo)))
    monkeypatch.setattr(migration_module.shutil, "disk_usage", lambda _path: usage_type(1, 1, 0))

    plan = StorageMigrationService(repo).preview(str(target))

    assert plan["blockers"]
    assert app.exists()
    assert not target.exists()


def test_copy_failure_preserves_sources_and_records_failed_state(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    plan = service.preview(str(target))
    service.begin(str(plan["id"]))

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(migration_module.shutil, "copyfile", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        service.execute(str(plan["id"]))

    assert app.exists()
    assert service.snapshot()["migration"]["state"] == "failed"  # type: ignore[index]


def test_hash_failure_preserves_sources(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    plan = service.preview(str(target))
    service.begin(str(plan["id"]))

    def fail_hash(_path: Path) -> str:
        raise OSError("hash failed")

    monkeypatch.setattr(migration_module, "_hash_file", fail_hash)
    with pytest.raises(OSError, match="hash failed"):
        service.execute(str(plan["id"]))
    assert app.exists()


def test_symlink_source_and_target_are_rejected(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    outside = home / "outside"
    outside.mkdir()
    try:
        (app / "linked").symlink_to(outside, target_is_directory=True)
        target.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前 Windows 环境不允许创建符号链接")

    service = StorageMigrationService(repo)
    source_link = service.preview(str(home / "other-target"))
    assert any("符号链接" in blocker or "junction" in blocker for blocker in source_link["blockers"])
    target_link = service.preview(str(target))
    assert any("符号链接" in blocker or "junction" in blocker for blocker in target_link["blockers"])


def test_target_overlap_and_nonempty_target_are_blocked(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)

    overlap = service.preview(str(app))
    assert any("重叠" in blocker for blocker in overlap["blockers"])

    target.mkdir()
    (target / "existing").write_text("keep", encoding="utf-8")
    nonempty = service.preview(str(target))
    assert any("空目录" in blocker for blocker in nonempty["blockers"])


def test_source_change_blocks_cleanup_then_retry_succeeds(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    _execute(service, target)
    source_file = app / "config.json"
    source_file.write_text("changed", encoding="utf-8")

    runtime_paths.reset_runtime_path_cache_for_tests()
    restarted = StorageMigrationService(repo)
    with pytest.raises(StorageMigrationError, match="发生变化"):
        restarted.finalize_startup()
    assert source_file.exists()
    assert restarted.snapshot()["migration"]["state"] == "cleanup_pending"  # type: ignore[index]

    source_file.write_text(
        json.dumps({"path": str(app / "attachments"), "text": str(app / "attachments")}),
        encoding="utf-8",
    )
    assert restarted.retry_cleanup()["state"] == "completed"
    assert not app.exists()


def test_precommit_interruption_keeps_source_and_missing_target_has_no_fallback(
    migration_context: tuple[Path, Path, Path],
) -> None:
    home, repo, target = migration_context
    app, _history = _make_sources(home, with_sqlite=False)
    service = StorageMigrationService(repo)
    plan = service.preview(str(target))
    service.begin(str(plan["id"]))

    runtime_paths.reset_runtime_path_cache_for_tests()
    assert StorageMigrationService(repo).finalize_startup()["state"] == "stopping"
    assert app.exists()
    assert not runtime_paths.get_storage_locator_path().exists()

    _execute(service, target)
    for child in target.iterdir():
        if child.is_dir():
            for nested in sorted(child.rglob("*"), reverse=True):
                if nested.is_file():
                    nested.unlink()
                elif nested.is_dir():
                    nested.rmdir()
            child.rmdir()
        else:
            child.unlink()
    target.rmdir()
    runtime_paths.reset_runtime_path_cache_for_tests()
    with pytest.raises(runtime_paths.StoragePathError):
        runtime_paths.get_app_data_root()
