import pytest

from scripts import update_transaction as transaction


def make_transaction(tmp_path):
    root, stage = tmp_path / "app", tmp_path / "stage"
    root.mkdir()
    stage.mkdir()
    for name in ("one", "two"):
        (root / name).write_text(f"old {name}")
        (stage / name).write_text(f"new {name}")
    return root, stage, transaction.Transaction(root, tmp_path / "recovery")


def test_second_backup_failure_keeps_originals_and_recovery_material(monkeypatch, tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    original = transaction.durable_copy

    def fail_second(source, target):
        if source == root / "two":
            raise OSError("disk full")
        original(source, target)

    monkeypatch.setattr(transaction, "durable_copy", fail_second)
    with pytest.raises(OSError, match="disk full"):
        tx.apply(stage, ["one", "two"])
    assert (root / "one").read_text() == "old one"
    assert (root / "two").read_text() == "old two"
    assert (tx.directory / "backup-000000").read_text() == "old one"
    tx.recover()
    tx.recover()


def test_replacement_interruption_and_repeated_recovery(monkeypatch, tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    original = transaction.atomic_copy

    def interrupt(source, target):
        original(source, target)
        raise KeyboardInterrupt()

    monkeypatch.setattr(transaction, "atomic_copy", interrupt)
    with pytest.raises(KeyboardInterrupt):
        tx.apply(stage, ["one", "two"])
    monkeypatch.setattr(transaction, "atomic_copy", original)
    transaction.Transaction(root, tx.directory).recover()
    transaction.Transaction(root, tx.directory).recover()
    assert (root / "one").read_text() == "old one"
    assert (root / "two").read_text() == "old two"


def test_restore_interruption_does_not_consume_backups(monkeypatch, tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    tx.apply(stage, ["one", "two"])
    original = transaction.atomic_copy

    def interrupt(source, target):
        original(source, target)
        raise KeyboardInterrupt()

    monkeypatch.setattr(transaction, "atomic_copy", interrupt)
    with pytest.raises(KeyboardInterrupt):
        tx.rollback()
    assert (tx.directory / "backup-000001").read_text() == "old two"
    monkeypatch.setattr(transaction, "atomic_copy", original)
    tx.recover()
    tx.recover()
    assert [p.read_text() for p in (root / "one", root / "two")] == ["old one", "old two"]


def test_missing_backup_never_deletes_current_target(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    tx.apply(stage, ["one"])
    (tx.directory / "backup-000000").unlink()
    with pytest.raises(transaction.RecoveryRequired, match="恢复材料"):
        tx.rollback()
    assert (root / "one").read_text() == "new one"


def test_torn_journal_record_can_be_recovered_and_retried(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    tx.apply(stage, ["one"])
    with tx.journal.open("ab") as handle:
        handle.write(b'{"event":"rest')
    tx.recover()
    tx.recover()
    assert (root / "one").read_text() == "old one"


def test_new_files_deleted_files_and_commit_are_recoverable(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    (stage / "new").write_text("added")
    tx.apply(stage, ["new"], delete_paths=["one"])
    tx.recover()
    assert not (root / "new").exists()
    assert (root / "one").read_text() == "old one"
    committed = transaction.Transaction(root, tmp_path / "committed")
    committed.apply(stage, ["two"])
    committed.commit()
    committed.recover()
    assert (root / "two").read_text() == "new two"


def test_edit_after_preparation_prevents_replacement(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    expected = {"one": transaction.sha256(root / "one")}
    (root / "one").write_text("user edit")
    with pytest.raises(transaction.RecoveryRequired, match="准备后文件发生变化"):
        tx.apply(stage, ["one"], expected_hashes=expected)
    tx.recover()
    assert (root / "one").read_text() == "user edit"


def test_transaction_rejects_overlapping_write_and_delete(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    with pytest.raises(transaction.RecoveryRequired, match="重叠"):
        tx.apply(stage, ["one"], delete_paths=["one"])
    assert (root / "one").read_text() == "old one"


def test_unchanged_targets_are_neither_backed_up_nor_rewritten(tmp_path):
    root, stage, tx = make_transaction(tmp_path)
    (root / "same").write_text("identical")
    (stage / "same").write_text("identical")
    (root / "tool").write_text("identical")
    (stage / "tool").write_text("identical")
    (stage / "tool").chmod(0o755)
    (root / "tool").chmod(0o644)
    untouched = (root / "same").stat().st_mtime_ns
    files = ["one", "same", "tool"]
    tx.apply(stage, files, expected_hashes={name: transaction.sha256(root / name) for name in files})
    assert (root / "same").stat().st_mtime_ns == untouched
    assert (root / "one").read_text() == "new one"
    assert (root / "tool").stat().st_mode & 0o111  # an executable-bit change is still applied
    records = transaction.read_journal(tx.journal)
    assert {r.get("relative_path") for r in records if r["event"] == "backup_done"} == {"one", "tool"}
    assert [r["count"] for r in records if r["event"] == "unchanged_skipped"] == [1]
    tx.recover()
    assert (root / "one").read_text() == "old one"
    assert (root / "same").read_text() == "identical"


def test_transient_windows_lock_is_retried_but_real_denials_are_not(monkeypatch, tmp_path):
    monkeypatch.setattr(transaction, "TRANSIENT_LOCK_RETRY_DELAYS", (0, 0))
    calls = []

    def locked_twice():
        calls.append(1)
        if len(calls) < 3:
            error = PermissionError(13, "in use")
            error.winerror = 32
            raise error
        return "done"

    assert transaction.retry_transient_lock(locked_twice) == "done"
    with pytest.raises(PermissionError):
        transaction.retry_transient_lock(lambda: (_ for _ in ()).throw(PermissionError(13, "denied")))
