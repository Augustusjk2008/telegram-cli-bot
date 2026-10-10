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


def test_preview_persists_manifest_and_execute_reuses_it(
    migration_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, repo, target = migration_context
    _make_sources(home, with_sqlite=False)
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
