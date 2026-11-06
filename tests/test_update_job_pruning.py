from __future__ import annotations

import json
import os
import sys
import time

import pytest

from bot import update_state
from bot.update_service import UpdateService
from bot.update_state import UpdateStore


OLD = time.time() - 3 * 24 * 3600


@pytest.fixture
def store(tmp_path, monkeypatch):
    for name in ("CLI_BRIDGE_UPDATE_PROTOCOL", "CLI_BRIDGE_UPDATE_RUNNER_PATH"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "install"
    root.mkdir()
    return UpdateStore(root, state_root=tmp_path / "state")


def _job(store, job_id, *, journal=None):
    path = store.job_dir(job_id)
    (path / "staging").mkdir(parents=True)
    (path / "package.zip").write_bytes(b"package")
    if journal is not None:
        (path / "transaction").mkdir()
        (path / "transaction" / "backup-000000").write_bytes(b"previous program")
        lines = [json.dumps({"event": "begin", "schema_version": 1}), *(json.dumps({"event": e}) for e in journal)]
        (path / "transaction" / "journal.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _age(path)
    return path


def _age(path):
    for item in [path, *path.rglob("*")]:
        if not item.is_symlink():
            os.utime(item, (OLD, OLD))


def _set_job(store, job_id, phase, **fields):
    store.mutate(lambda state: state.update(job={"job_id": job_id, "phase": phase,
                                                 "job_dir": str(store.job_dir(job_id)), **fields}))


def test_prunes_finished_unreferenced_jobs_and_keeps_current(store):
    superseded = _job(store, "old-success", journal=["applied_all", "committed"])
    failed = _job(store, "old-failed")
    current = _job(store, "current")
    _set_job(store, "current", "succeeded")

    assert sorted(store.prune_job_dirs()) == ["old-failed", "old-success"]
    assert not superseded.exists() and not failed.exists()
    assert current.is_dir()


@pytest.mark.parametrize("phase", ["awaiting_health", "unknown-phase"])
def test_handoff_application_recovery_and_unknown_phases_prune_nothing(store, phase):
    old = _job(store, "old-failed")
    _job(store, "current", journal=["applied_all"])
    _set_job(store, "current", phase)

    assert store.prune_job_dirs() == []
    assert old.is_dir()


def test_preparing_job_keeps_its_directory_and_prunes_superseded_jobs(store):
    old = _job(store, "old-cancelled")
    current = _job(store, "current")
    _set_job(store, "current", "preparing")

    assert store.prune_job_dirs() == ["old-cancelled"]
    assert not old.exists() and current.is_dir()


def test_keeps_job_referenced_by_active_python_environment(store):
    venv_job = _job(store, "venv-job", journal=["applied_all", "committed"])
    python = venv_job / "environment" / "bin" / "python"
    python.parent.mkdir(parents=True)
    try:
        # POSIX venv interpreters are symlinks to the base Python.
        python.symlink_to(sys.executable)
    except (OSError, NotImplementedError):
        python.write_bytes(b"venv launcher")
    _age(venv_job)
    _job(store, "current")
    store.mutate(lambda state: state.update(python_executable=str(python)))
    _set_job(store, "current", "succeeded", previous_python_executable="/usr/bin/python3")

    assert store.prune_job_dirs() == []
    assert venv_job.is_dir()


def test_keeps_job_containing_running_interpreter(store, monkeypatch):
    running = _job(store, "running-python")
    other = _job(store, "other")
    store.mutate(lambda state: state.update(job=None))
    monkeypatch.setattr(update_state.sys, "executable", str(running / "environment" / "bin" / "python"))
    assert store.prune_job_dirs() == ["other"]
    assert running.is_dir() and not other.exists()


def test_keeps_unreleased_transaction_backups(store):
    pending = _job(store, "pending-backup", journal=["applied_all"])
    rolled_back = _job(store, "rolled-back", journal=["rolled_back"])
    store.mutate(lambda state: state.update(job=None))

    assert store.prune_job_dirs() == ["rolled-back"]
    assert (pending / "transaction" / "backup-000000").is_file()
    assert not rolled_back.exists()


def test_skips_symlinked_entries_recent_jobs_and_invalid_names(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("user file")
    jobs = store.root / "jobs"
    jobs.mkdir(parents=True)
    try:
        (jobs / "linked-job").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")
    recent = store.job_dir("recent")
    recent.mkdir()
    invalid = jobs / "not a job"
    invalid.mkdir()
    _age(invalid)
    store.mutate(lambda state: state.update(job=None))

    assert store.prune_job_dirs() == []
    assert (outside / "keep.txt").read_text() == "user file"
    assert (jobs / "linked-job").is_symlink() and recent.is_dir() and invalid.is_dir()


def test_deletion_failure_is_logged_and_skipped(store, monkeypatch):
    old = _job(store, "locked")
    store.mutate(lambda state: state.update(job=None))

    def locked(path, *args, **kwargs):
        raise PermissionError(32, "being used by another process", str(path))

    monkeypatch.setattr(update_state.shutil, "rmtree", locked)
    assert store.prune_job_dirs() == []
    assert old.is_dir()


def test_supervised_host_requires_known_runner_snapshot(store, monkeypatch):
    runner_job = _job(store, "runner-job")
    store.mutate(lambda state: state.update(job=None))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    assert store.prune_job_dirs() == []
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_RUNNER_PATH", str(runner_job / "runner" / "update_runner.py"))
    assert store.prune_job_dirs() == []
    assert runner_job.is_dir()
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_RUNNER_PATH", str(store.root.parent / "control" / "update_runner.py"))
    assert store.prune_job_dirs() == ["runner-job"]


def test_busy_preparation_lock_and_unreadable_state_prune_nothing(store):
    old = _job(store, "old")
    store.mutate(lambda state: state.update(job=None))
    with update_state.FileLock(store.root / "preparation.lock", timeout=0):
        assert store.prune_job_dirs() == []
    store.state_path.write_text("{broken", encoding="utf-8")
    assert store.prune_job_dirs() == []
    assert old.is_dir()


def test_new_preparation_reservation_prunes_superseded_jobs(store):
    old = _job(store, "old-failed")
    _set_job(store, "old-failed", "failed")
    service = UpdateService(store.repo_root, store=store)
    lease, status = service._reserve({"path": "offline.zip", "version": ""})
    try:
        assert status["job"]["job_id"] != "old-failed"
        assert not old.exists()
        assert store.job_dir(status["job"]["job_id"]).is_dir()
    finally:
        lease.__exit__()


def test_runner_cleanup_never_fails_a_finished_job():
    from scripts import update_runner

    class Store:
        def prune_job_dirs(self, **kwargs):
            raise OSError("unexpected")

    update_runner._prune_finished_jobs(Store())
