from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from bot.update_state import UpdateStore
from scripts import update_bootstrap as bootstrap
from scripts import update_runner as runner


ROOT = Path(__file__).resolve().parents[1]


class Child:
    pid = 99999999
    returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode or 0


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv("TCB_UPDATE_CONTROL_ROOT", str(tmp_path / "control"))
    root = tmp_path / "installation"
    root.mkdir()
    (root / "VERSION").write_text("1.0.0")
    (root / ".env").write_text("private-token")
    store = UpdateStore(root, tmp_path / "state")
    job_dir = store.job_dir("job-1")
    stage = job_dir / "stage"
    stage.mkdir(parents=True)
    (stage / "VERSION").write_text("2.0.0")
    (root / "bot").mkdir()
    shutil.copy2(ROOT / "bot/update_state.py", root / "bot/update_state.py")
    job = {"job_id": "job-1", "phase": "waiting_restart", "current_version": "1.0.0",
           "target_version": "2.0.0", "staging_dir": str(stage), "files": ["VERSION"],
           "original_hashes": {"VERSION": runner._hash(root / "VERSION")},
           "backup_dir": str(job_dir / "transaction"), "python_executable": sys.executable,
           "previous_python_executable": sys.executable, "health_url": "http://127.0.0.1:19999/node/test/api/health",
           "health_base_path": "/node/test", "health_timeout": 0.03, "previous_instance_id": "old-instance"}
    store.mutate(lambda state: state.update(job=job))
    return root, store


def health(job, version, token, instance="new-instance"):
    return {"ok": True, "ready": True, "version": version, "update_job_id": job["job_id"],
            "update_health_token": token, "instance_id": instance, "base_path": "/node/test"}


def test_success_keeps_backup_until_matching_health(installation, monkeypatch):
    root, store = installation
    child = Child()
    tokens = []
    monkeypatch.setattr(runner, "_start_host", lambda r, p, s, j, t: tokens.append(t) or child)

    def probe(url, token):
        assert url.endswith("/node/test/api/health")
        assert store.read()["job"]["phase"] == "awaiting_health"
        assert (Path(store.read()["job"]["backup_dir"]) / "backup-000000").read_text() == "1.0.0"
        return health(store.read()["job"], "2.0.0", token)

    monkeypatch.setattr(runner, "read_health", probe)
    actual, python = runner.apply_job(root, store, "job-1")
    assert actual is child and python == sys.executable
    assert store.read()["job"]["phase"] == "succeeded"
    assert store.read()["job"]["result"]["version"] == "2.0.0"
    assert (root / "VERSION").read_text() == "2.0.0"
    assert (root / ".env").read_text() == "private-token"
    assert tokens[0]


def test_edits_after_preparation_are_preserved_by_runner_transaction(installation, monkeypatch):
    root, store = installation
    stage = Path(store.read()["job"]["staging_dir"])
    (root / "app.py").write_text("original application")
    (stage / "app.py").write_text("updated application")
    original = runner._hash(root / "app.py")
    def add_target(state):
        state["job"]["files"].append("app.py")
        state["job"]["original_hashes"]["app.py"] = original
    store.mutate(add_target)
    (root / "app.py").write_text("user edit after ready")
    monkeypatch.setattr(runner, "_start_host", lambda *args: Child())
    monkeypatch.setattr(runner, "read_health", lambda url, token: health(store.read()["job"], "1.0.0", token, "recovered"))
    runner.apply_job(root, store, "job-1")
    assert (root / "app.py").read_text() == "user edit after ready"
    assert (root / "VERSION").read_text() == "1.0.0"
    assert store.read()["job"]["phase"] == "rolled_back"
    assert "准备后文件发生变化" in store.read()["job"]["error"]


@pytest.mark.parametrize("failure", ["import", "timeout", "wrong_instance", "wrong_version", "wrong_token", "not_ready"])
def test_failed_new_host_rolls_back_and_checks_old_host(installation, monkeypatch, failure):
    root, store = installation
    children = []

    def start(*args):
        child = Child()
        if not children and failure == "import":
            child.returncode = 1
        children.append(child)
        return child

    def probe(url, token):
        job = store.read()["job"]
        if len(children) == 2:
            return health(job, "1.0.0", token, "recovered-instance")
        payload = health(job, "2.0.0", token)
        if failure == "timeout":
            raise OSError("Unavailable")
        payload.update({"wrong_instance": {"instance_id": "old-instance"},
                        "wrong_version": {"version": "1.0.0"}, "wrong_token": {"update_health_token": "wrong"},
                        "not_ready": {"ready": False}}.get(failure, {}))
        return payload

    monkeypatch.setattr(runner, "_start_host", start)
    monkeypatch.setattr(runner, "read_health", probe)
    child, _ = runner.apply_job(root, store, "job-1")
    assert child is children[1]
    assert children[0].poll() is not None
    assert store.read()["job"]["phase"] == "rolled_back"
    assert store.read()["job"]["error"]
    assert (root / "VERSION").read_text() == "1.0.0"
    assert (root / ".env").read_text() == "private-token"


def test_failed_old_health_requires_manual_recovery(installation, monkeypatch):
    root, store = installation
    children = []
    monkeypatch.setattr(runner, "_start_host", lambda *args: children.append(Child()) or children[-1])
    monkeypatch.setattr(runner, "read_health", lambda *args: {})
    with pytest.raises(RuntimeError, match="timed out"):
        runner.apply_job(root, store, "job-1")
    job = store.read()["job"]
    assert job["phase"] == "recovery_required"
    assert job["result"]["recovery_command"][-1] == "job-1"
    assert (root / "VERSION").read_text() == "1.0.0"
    assert all(child.poll() is not None for child in children)


def test_prepared_job_and_changed_staging_are_not_applied(installation, monkeypatch):
    root, store = installation
    store.mutate(lambda state: state["job"].update(phase="ready"))
    with pytest.raises(RuntimeError, match="waiting_restart"):
        runner.apply_job(root, store, "job-1")
    store.mutate(lambda state: state["job"].update(phase="waiting_restart", prepared_hashes={"VERSION": "bad"}))
    started = []
    monkeypatch.setattr(runner, "_start_host", lambda *args: started.append(args) or Child())
    monkeypatch.setattr(runner, "read_health", lambda url, token: health(store.read()["job"], "1.0.0", token))
    runner.apply_job(root, store, "job-1")
    assert (root / "VERSION").read_text() == "1.0.0"
    assert len(started) == 1
    assert store.read()["job"]["phase"] == "rolled_back"
    assert "changed" in store.read()["job"]["error"]


def test_recovery_does_not_reopen_a_successful_transaction(installation):
    root, store = installation
    store.mutate(lambda state: state["job"].update(phase="succeeded"))
    with pytest.raises(RuntimeError, match="Only an interrupted"):
        runner.recover_job(root, store, "job-1", "manual command")
    assert store.read()["job"]["phase"] == "succeeded"


def test_host_and_supervisor_locks_remain_exclusive_after_state_relocation(installation, monkeypatch, tmp_path):
    from bot.update_state import begin_host_execution, UpdateConflict
    root, old_store = installation
    moved_store = UpdateStore(root, tmp_path / "moved-state")
    assert moved_store.execution_lock_root == old_store.execution_lock_root
    monkeypatch.delenv("CLI_BRIDGE_UPDATE_PROTOCOL", raising=False)
    with begin_host_execution(root):
        with pytest.raises(RuntimeError, match="owns this installation"):
            with runner.supervisor_lock(moved_store):
                pytest.fail("a direct host already owns this installation")
    with runner.supervisor_lock(moved_store):
        with pytest.raises(UpdateConflict):
            begin_host_execution(root)


def test_supervisor_follows_authenticated_state_handoff_after_storage_move(installation, monkeypatch, tmp_path):
    from bot.update_state import write_host_handoff
    root, old_store = installation
    moved_store = UpdateStore(root, tmp_path / "moved-state")
    moved_store.mutate(lambda state: state.update(job={"job_id": "moved-job", "phase": "waiting_restart"}))
    pointer = tmp_path / "handoff.json"
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF", str(pointer))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "nonce")
    write_host_handoff(moved_store.state_path, "moved-job")
    child = Child()
    child.pid, child.update_handoff_path, child.update_handoff_token = os.getpid(), pointer, "nonce"
    current = runner._store_after_host_exit(root, old_store, child, runner.UPDATE_EXIT_CODE)
    assert current.state_path == moved_store.state_path
    assert current.read()["job"]["job_id"] == "moved-job"
    assert not pointer.exists()


def test_supervisor_accepts_launcher_pid_handoff_on_all_platforms(installation, monkeypatch, tmp_path):
    from bot.update_state import write_host_handoff

    root, store = installation
    pointer = tmp_path / "handoff.json"
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF", str(pointer))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "venv-nonce")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_SUPERVISOR_PID", str(os.getpid()))
    write_host_handoff(store.state_path)

    child = Child()
    child.pid = os.getpid() + 1
    child.update_handoff_path = pointer
    child.update_handoff_token = "venv-nonce"
    current = runner._store_after_host_exit(root, store, child, runner.RESTART_EXIT_CODE)

    assert current.state_path == store.state_path
    assert not pointer.exists()


def test_supervisor_rejects_launcher_handoff_from_another_supervisor(installation, monkeypatch, tmp_path):
    from bot.update_state import write_host_handoff

    root, store = installation
    pointer = tmp_path / "handoff.json"
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF", str(pointer))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "venv-nonce")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_SUPERVISOR_PID", str(os.getpid() + 1))
    write_host_handoff(store.state_path)

    child = Child()
    child.pid = 99999998
    child.update_handoff_path = pointer
    child.update_handoff_token = "venv-nonce"
    with pytest.raises(RuntimeError, match="handoff identity mismatch"):
        runner._store_after_host_exit(root, store, child, runner.RESTART_EXIT_CODE)
    assert pointer.exists()


def test_official_child_registers_current_storage_location(installation, monkeypatch, tmp_path):
    from bot.update_state import begin_host_execution, FileLock, UpdateConflict
    root, old_store = installation
    moved = tmp_path / "new-storage" / "updates"
    pointer = tmp_path / "child-handoff.json"
    monkeypatch.setattr("bot.runtime_paths.get_update_state_root", lambda repo: moved)
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_SUPERVISOR_PID", str(os.getppid()))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_STATE_FILE", str(old_store.state_path))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF", str(pointer))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "child-nonce")
    with runner.supervisor_lock(old_store):
        with begin_host_execution(root):
            payload = json.loads(pointer.read_text())
            assert payload["state_file"] == str(moved / "state.json")
            assert payload["host_pid"] == os.getpid()
            assert os.environ["CLI_BRIDGE_UPDATE_STATE_FILE"] == payload["state_file"]
            with pytest.raises(UpdateConflict):
                with FileLock(old_store.execution_lock_root / "host.lock", timeout=0):
                    pytest.fail("the child must keep its host lease")


def test_official_child_accepts_handoff_when_windows_venv_changes_parent_pid(installation, monkeypatch, tmp_path):
    from bot.update_state import begin_host_execution
    root, old_store = installation
    moved = tmp_path / "new-storage" / "updates"
    pointer = old_store.execution_lock_root / "host-handoff-child-nonce.json"
    monkeypatch.setattr("bot.runtime_paths.get_update_state_root", lambda repo: moved)
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_SUPERVISOR_PID", "not-the-final-venv-parent")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_STATE_FILE", str(old_store.state_path))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF", str(pointer))
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "child-nonce")

    with runner.supervisor_lock(old_store):
        with begin_host_execution(root):
            payload = json.loads(pointer.read_text())
            assert payload["state_file"] == str(moved / "state.json")
            assert payload["host_pid"] == os.getpid()


def test_same_version_recovery_verifies_the_previous_build(installation, monkeypatch):
    root, store = installation
    (Path(store.read()["job"]["staging_dir"]) / "VERSION").write_text("1.0.0")
    store.mutate(lambda state: state["job"].update(target_version="1.0.0", manifest={"commit": "new-build"},
                                                  health={"build_id": "old-build"}))
    children = []
    def start(*args):
        child = Child()
        if not children:
            child.returncode = 1
        children.append(child)
        return child
    monkeypatch.setattr(runner, "_start_host", start)
    monkeypatch.setattr(runner, "read_health", lambda url, token: {
        **health(store.read()["job"], "1.0.0", token), "build_id": "old-build",
    })
    runner.apply_job(root, store, "job-1")
    assert store.read()["job"]["phase"] == "rolled_back"


def test_interrupted_executor_refuses_live_orphan(installation, monkeypatch):
    root, store = installation
    store.mutate(lambda state: state["job"].update(phase="awaiting_health", child_pid=123))
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: True)
    with pytest.raises(RuntimeError, match="still running"):
        runner.recover_job(root, store, "job-1", "Interrupted")
    assert store.read()["job"]["phase"] == "recovery_required"
    assert (root / "VERSION").read_text() == "1.0.0"


def test_snapshot_works_without_bot_imports_and_portable_python_is_external(tmp_path, monkeypatch):
    root = tmp_path / "portable"
    (root / "scripts").mkdir(parents=True)
    (root / "bot").mkdir()
    for name in ("update_runner.py", "update_transaction.py", "update_package.py"):
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(ROOT / "bot/update_state.py", root / "bot/update_state.py")
    embedded = root / "runtime/python/python.exe"
    embedded.parent.mkdir(parents=True)
    embedded.write_bytes(b"control-runtime")
    (embedded.parent / "python313.dll").write_bytes(b"stdlib")
    monkeypatch.setattr(sys, "_base_executable", str(embedded))
    monkeypatch.setenv("TCB_UPDATE_CONTROL_ROOT", str(tmp_path / "external"))
    release = tmp_path / "new-release"
    shutil.copytree(root / "scripts", release / "scripts")
    shutil.copytree(root / "bot", release / "bot")
    snapshot = runner.freeze_runner(root, root / "data/jobs/job-1/runner", source_root=release)
    second = runner.freeze_runner(root, root / "data/jobs/job-2/runner", source_root=release)
    assert not Path(snapshot["control_python_executable"]).is_relative_to(root)
    assert Path(snapshot["control_python_executable"]).read_bytes() == embedded.read_bytes()
    assert snapshot["control_python_executable"] != second["control_python_executable"]
    assert not Path(second["control_python_executable"]).is_relative_to(root)
    assert set(snapshot["runner_hashes"]) == {"update_runner.py", "update_transaction.py", "update_package.py", "update_state.py"}
    result = subprocess.run([sys.executable, snapshot["runner_path"], "--help"], capture_output=True, text=True)
    assert result.returncode == 0


def test_actual_runtime_address_overrides_preparation_config():
    job = runner._effective_job({"health": {"host": "::", "port": 28888, "base_path": "/node/x"}})
    assert job["health_url"] == "http://[::1]:28888/node/x/api/health"


def test_confirmed_exit_handoff_survives_supervisor_interruption(installation, monkeypatch):
    root, store = installation
    store.mutate(lambda state: state["job"].update(host_exit_confirmed=True))
    monkeypatch.setattr(runner, "_start_host", lambda *args: pytest.fail("Must finish the confirmed handoff first"))
    monkeypatch.setattr(runner, "_verify_snapshot", lambda job: [sys.executable, "snapshot.py"])
    calls = []
    monkeypatch.setattr(runner.subprocess, "call", lambda command: calls.append(command) or 0)
    assert runner.supervise(root, store, sys.executable) == 0
    assert calls[0][-2:] == ["--job-id", "job-1"]
    assert (root / "VERSION").read_text() == "1.0.0"


def test_unconfirmed_interrupted_handoff_returns_to_ready(installation, monkeypatch):
    root, store = installation
    monkeypatch.setattr(runner, "_start_host", lambda *args: Child())
    assert runner.supervise(root, store, sys.executable) == 0
    assert store.read()["job"]["phase"] == "ready"
    assert (root / "VERSION").read_text() == "1.0.0"


def test_supervisor_ignores_reused_persisted_host_pid(installation, monkeypatch):
    root, store = installation
    store.mutate(lambda state: state.update(host_pid=12345))
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: True)
    started = []
    monkeypatch.setattr(runner, "_start_host", lambda *args: started.append(args) or Child())

    assert runner.supervise(root, store, sys.executable) == 0
    assert started


def test_supervisor_restart_does_not_rewrite_update_state(installation, monkeypatch):
    # After a storage migration the supervisor still holds the source state file;
    # rewriting it would block migration cleanup on every start.
    root, store = installation
    store.mutate(lambda state: state["job"].update(phase="ready"))
    before = store.state_path.read_bytes()
    codes = iter([runner.RESTART_EXIT_CODE, 0])

    def start(*args):
        child = Child()
        child.returncode = next(codes)
        return child

    monkeypatch.setattr(runner, "_start_host", start)
    assert runner.supervise(root, store, sys.executable) == 0
    assert store.state_path.read_bytes() == before


def test_service_supervisor_restarts_unexpected_host_exit(installation, monkeypatch):
    root, store = installation
    monkeypatch.setenv("CLI_BRIDGE_SERVICE_MODE", "1")
    codes = iter([1, 0])
    started = []

    def start(*args):
        child = Child()
        child.returncode = next(codes)
        started.append(child)
        return child

    monkeypatch.setattr(runner, "_start_host", start)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    assert runner.supervise(root, store, sys.executable) == 0
    assert len(started) == 2


def test_supervisor_stop_signal_terminates_host_before_returning_zero(installation, monkeypatch):
    root, store = installation

    class StopChild(Child):
        def wait(self, timeout=None):
            if self.returncode is None:
                runner.SUPERVISOR_STOP_EVENT.set()
                raise subprocess.TimeoutExpired("host", timeout)
            return self.returncode

    child = StopChild()
    monkeypatch.setattr(runner, "_start_host", lambda *args: child)
    assert runner.supervise(root, store, sys.executable) == 0
    assert child.returncode == -15


def test_update_runner_job_log_redacts_credentials(monkeypatch):
    monkeypatch.setenv("WEB_API_TOKEN", "secret-token")
    assert "secret-token" not in runner._redact_text("authorization: Bearer secret-token")
    assert "[REDACTED]" in runner._redact_text("authorization: Bearer secret-token")


@pytest.mark.parametrize("fail_new", [False, True])
def test_portable_handoff_with_real_non_listening_host_processes(installation, monkeypatch, fail_new):
    root, store = installation
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / "portable_bootstrap.py").write_text(
        "import sys,time\nprint('simulated portable host: ' + sys.argv[1], flush=True)\ntime.sleep(60)\n")
    children = []
    start = runner._start_host

    def tracked_start(*args):
        child = start(*args)
        children.append(child)
        return child

    def probe(url, token):
        version = (root / "VERSION").read_text()
        if fail_new and version == "2.0.0":
            raise OSError("Simulated new host health failure")
        return health(store.read()["job"], version, token, "portable-" + version)

    monkeypatch.setattr(runner, "_start_host", tracked_start)
    monkeypatch.setattr(runner, "read_health", probe)
    try:
        child, _ = runner.apply_job(root, store, "job-1")
        assert child.poll() is None
        assert len(children) == (2 if fail_new else 1)
        assert store.read()["job"]["phase"] == ("rolled_back" if fail_new else "succeeded")
        assert (root / "VERSION").read_text() == ("1.0.0" if fail_new else "2.0.0")
    finally:
        for child in children:
            runner._stop_child(child)


@pytest.mark.parametrize("portable", [False, True])
def test_legacy_rollback_authenticates_actual_child_and_restored_frontend(installation, monkeypatch, portable):
    root, store = installation
    web = root / "bot/web"
    web.mkdir()
    (web / "__init__.py").write_text("")
    (web / "server.py").write_text('''import json,os
class Response:
    def __init__(self):
        self.text = json.dumps(dict(ok=True, instance_id='instance-' + str(os.getpid()), base_path='/node/test'))
class WebApiServer:
    async def health(self, request): return Response()
''')
    (root / "bot/__main__.py").write_text('''import asyncio,os,time
from pathlib import Path
from bot.web.server import WebApiServer
class Request:
    headers = {'X-TCB-Update-Token': os.environ['TCB_UPDATE_HEALTH_TOKEN']}
response = asyncio.run(WebApiServer().health(Request()))
Path('simulated-health.json').write_text(response.text)
print('legacy simulated host ready', flush=True)
time.sleep(60)
''')
    if portable:
        (root / "runtime").mkdir()
        (root / "runtime/portable_bootstrap.py").write_text("import runpy\nrunpy.run_module('bot', run_name='__main__')\n")
    (root / "front/dist/assets").mkdir(parents=True)
    (root / "front/dist/index.html").write_text('<script src="/old-hub/node/test/assets/old.js"></script>')
    (root / "front/dist/assets/old.js").write_text("old frontend")
    (root / "front/dist/build-info.json").write_text(json.dumps({"base_path": "/old-hub/node/test/"}))
    hashes = {name: runner._hash(root / name) for name in ("front/dist/index.html", "front/dist/assets/old.js", "front/dist/build-info.json")}
    store.mutate(lambda state: state["job"].update(bootstrap_legacy=True, previous_frontend_hashes=hashes,
                                                 health_timeout=2, frontend_base_path="/new-hub/node/test"))
    children = []
    start = runner._start_host

    def tracked_start(*args):
        child = start(*args)
        children.append(child)
        return child

    def probe(url, token):
        return json.loads((root / "simulated-health.json").read_text())

    monkeypatch.setattr(runner, "_start_host", tracked_start)
    monkeypatch.setattr(runner, "read_health", probe)
    try:
        recovered, _ = runner.apply_job(root, store, "job-1")
        payload = probe("", "")
        assert recovered.poll() is None and payload["pid"] == recovered.pid
        assert payload["version"] == "1.0.0" and payload["update_health_token"]
        assert payload["instance_id"] not in store.read()["job"]["rejected_instance_ids"]
        assert store.read()["job"]["phase"] == "rolled_back"
    finally:
        for child in children:
            runner._stop_child(child)


@pytest.mark.parametrize("wrong", ["pid", "version", "previous_instance", "failed_instance", "token"])
def test_legacy_health_rejects_unrelated_or_stale_service(installation, monkeypatch, wrong):
    _, store = installation
    job = store.read()["job"]
    job["rejected_instance_ids"] = ["failed-new-instance"]
    child = Child()
    child.pid = os.getpid()
    payload = {**health(job, "1.0.0", "token", "recovered-instance"), "pid": child.pid}
    payload.update({"pid": {"pid": child.pid + 1}, "version": {"version": "2.0.0"},
                    "previous_instance": {"instance_id": "old-instance"},
                    "failed_instance": {"instance_id": "failed-new-instance"},
                    "token": {"update_health_token": "unrelated"}}[wrong])
    monkeypatch.setattr(runner, "read_health", lambda *args: payload)
    with pytest.raises(RuntimeError, match="timed out"):
        runner.wait_for_health(child, job, "1.0.0", "token", legacy=True)


@pytest.mark.parametrize("wrong", ["version", "resource", "reference"])
def test_legacy_recovery_requires_restored_version_and_complete_assets(installation, wrong):
    root, store = installation
    (root / "front/dist").mkdir(parents=True)
    (root / "front/dist/index.html").write_text('<script src="/node/test/old.js"></script>')
    (root / "front/dist/old.js").write_text("old")
    job = store.read()["job"]
    job["previous_frontend_hashes"] = {name: runner._hash(root / name) for name in ("front/dist/index.html", "front/dist/old.js")}
    runner.verify_legacy_files(root, job)
    if wrong == "version":
        (root / "VERSION").write_text("2.0.0")
    elif wrong == "resource":
        (root / "front/dist/old.js").write_text("changed")
    else:
        (root / "front/dist/index.html").write_text('<script src="missing.js"></script>')
        job["previous_frontend_hashes"]["front/dist/index.html"] = runner._hash(root / "front/dist/index.html")
    with pytest.raises(RuntimeError):
        runner.verify_legacy_files(root, job)


def release_manifest(files):
    files.setdefault("scripts/update_package.py", (ROOT / "scripts/update_package.py").read_bytes())
    files.setdefault("VERSION", b"2.0.0")
    files.setdefault("requirements.txt", b"")
    files.setdefault("front/dist/index.html", b"<html>ready</html>")
    files.setdefault("front/dist/build-info.json", json.dumps({"schema_version": 1, "version": "2.0.0", "base_path": "", "api_base_url": ""}).encode())
    files.setdefault(".distribution.json", json.dumps({"packageKind": "installer", "version": "2.0.0", "platform": "windows-x64"}).encode())
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return {"schema_version": 1, "update_protocol": 1, "version": "2.0.0", "package_kind": "installer",
            "commit": "a" * 40, "dirty": False,
            "platform": "windows-x64", "architecture": "x64", "files": hashes,
            "dependencies": {"requirements_sha256": hashes["requirements.txt"]},
            "frontend": {"base_path": "", "files": {name: value for name, value in hashes.items() if name.startswith("front/dist/")}},
            "migrations": {"backward_compatible": True}}


@pytest.mark.parametrize("kind", ["zip", "tar.gz"])
def test_bootstrap_checks_package_before_executing_it(tmp_path, kind):
    import io
    import tarfile
    package = tmp_path / ("release." + kind)
    names = ["scripts/update_runner.py", "scripts/update_transaction.py", "scripts/update_bootstrap.py",
             "bot/update_state.py", "bot/update_preparation.py", "bot/updater.py"]
    files = {name: b"verified" for name in names}
    manifest = release_manifest(files)
    contents = {**files, ".update-manifest.json": json.dumps(manifest).encode()}
    if kind == "zip":
        with zipfile.ZipFile(package, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
    else:
        with tarfile.open(package, "w:gz") as archive:
            directory = tarfile.TarInfo(".")
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            for name, data in contents.items():
                member = tarfile.TarInfo("./" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    root = bootstrap.extract_verified(package, tmp_path / "out", bootstrap.digest(package))
    assert (root / "scripts/update_runner.py").read_bytes() == b"verified"
    with pytest.raises(RuntimeError, match="SHA-256"):
        bootstrap.extract_verified(package, tmp_path / "bad", "0" * 64)
    if kind == "zip":
        with zipfile.ZipFile(package, "a") as archive:
            archive.writestr("../old/.env", "overwrite")
        with pytest.raises(ValueError, match="非法"):
            bootstrap.extract_verified(package, tmp_path / "unsafe", bootstrap.digest(package))


def test_bootstrap_never_applies_while_host_still_answers(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(RuntimeError, match="Exit the old host"):
        bootstrap._require_stopped("http://127.0.0.1:9999/api/health")


def test_legacy_baseline_preserves_configs_and_rejects_modified_managed_extensions(tmp_path):
    from scripts.update_package import ownership_plan
    repo = tmp_path / "old-install"
    repo.mkdir()
    (repo / "VERSION").write_text("1.0.0")
    (repo / ".env").write_text("private")
    extension = "data/pi-home/.pi/agent/extensions/tcb-cluster.ts"
    (repo / extension).parent.mkdir(parents=True)
    (repo / extension).write_text("official-old")
    package = tmp_path / "old.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("VERSION", "1.0.0")
        archive.writestr(".env", "public-default")
        archive.writestr("data/pi-home/.pi/agent/models.json", "public-default")
        archive.writestr(extension, "official-old")
    bootstrap.establish_baseline(repo, package, bootstrap.digest(package), tmp_path / "work")
    baseline = json.loads((repo / ".update-baseline.json").read_text())
    assert set(baseline["files"]) == {"VERSION", extension}
    target = {"files": {"VERSION": hashlib.sha256(b"2.0.0").hexdigest(), extension: hashlib.sha256(b"official-new").hexdigest()},
              "managed_data_files": [extension]}
    assert extension in ownership_plan(repo, target)[0]
    (repo / extension).write_text("user-customized")
    with pytest.raises(ValueError, match="冲突"):
        ownership_plan(repo, target)
    assert (repo / ".env").read_text() == "private"


@pytest.mark.parametrize("has_git", [False, True])
def test_first_upgrade_prepares_using_new_package_code_without_importing_old_updater(tmp_path, has_git):
    repo = tmp_path / "legacy"
    (repo / "bot").mkdir(parents=True)
    if has_git:
        (repo / ".git").mkdir()
    (repo / "VERSION").write_text("1.0.0")
    (repo / "requirements.txt").write_text("")
    (repo / ".env").write_text("WEB_ENABLED=true\n")
    (repo / "bot/updater.py").write_text("raise RuntimeError('legacy apply must never be imported')")
    work = tmp_path / "work"
    state_root = tmp_path / "bootstrap-state"
    files = {name: (ROOT / name).read_bytes() for name in (
        "scripts/update_bootstrap.py", "scripts/update_runner.py", "scripts/update_transaction.py",
        "bot/update_state.py", "bot/update_preparation.py")}
    files.update({"VERSION": b"2.0.0", "requirements.txt": b"", "front/dist/index.html": b"<html>ready</html>",
                  "bot/config.py": b"WEB_HOST='127.0.0.1'\nWEB_PORT=13234\nWEB_BASE_PATH=''\n",
                  "bot/update_migration_gate.py": b"def validate_update_migrations(*args): pass\n",
                  "bot/runtime_paths.py": b"import os\nfrom pathlib import Path\ndef get_update_state_root(root): return Path(os.environ['TEST_BOOTSTRAP_STATE'])\n",
                  "bot/updater.py": b'''import json,zipfile
def prepare_update_payload(root, package, job_dir):
    stage = job_dir / 'staging'
    with zipfile.ZipFile(package) as archive: archive.extractall(stage)
    manifest = json.loads((stage / '.update-manifest.json').read_text())
    return dict(current_version='1.0.0', target_version='2.0.0', package_kind='installer',
                staging_dir=str(stage), files=[*manifest['files'], '.update-manifest.json'],
                delete_paths=[], manifest=manifest)
'''})
    manifest = release_manifest(files)
    package = tmp_path / "new.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(".update-manifest.json", json.dumps(manifest))
    env = dict(os.environ, TEST_BOOTSTRAP_STATE=str(state_root), TCB_UPDATE_CONTROL_ROOT=str(tmp_path / "control"))
    for name in ("TCB_STARTUP_FORCE_DEP_INSTALL", "TCB_STARTUP_SKIP_DEP_SYNC", "TCB_STARTUP_USE_SYSTEM_PYTHON"):
        env.pop(name, None)
    command = [sys.executable, str(ROOT / "scripts/update_bootstrap.py"), "--repo-root", str(repo),
               "--package", str(package), "--sha256", bootstrap.digest(package), "--work-dir", str(work)]
    if not has_git:
        original = tmp_path / "original.zip"
        with zipfile.ZipFile(original, "w") as archive:
            for name in ("VERSION", "requirements.txt", "bot/updater.py", ".env"):
                archive.write(repo / name, name)
        command += ["--baseline-package", str(original), "--baseline-sha256", bootstrap.digest(original)]
    result = subprocess.run(command,
                            cwd=repo, env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    state = UpdateStore(repo, state_root).read()
    assert state["job"]["phase"] == "ready"
    assert Path(state["job"]["runner_path"]).read_bytes() == files["scripts/update_runner.py"]
    assert (repo / "VERSION").read_text() == "1.0.0"
    assert "legacy apply" in (repo / "bot/updater.py").read_text()
    if not has_git:
        baseline = json.loads((repo / ".update-baseline.json").read_text())
        assert ".env" not in baseline["files"]
        assert baseline["files"]["bot/updater.py"] == runner._hash(repo / "bot/updater.py")


@pytest.mark.parametrize("wrong", ["sha256", "version"])
def test_bootstrap_rejects_unproven_baseline_without_writing_ownership(tmp_path, wrong):
    root = tmp_path / "old"
    root.mkdir()
    (root / "VERSION").write_text("1.0.0")
    package = tmp_path / "baseline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("VERSION", "1.0.0" if wrong == "sha256" else "2.0.0")
    checksum = "0" * 64 if wrong == "sha256" else bootstrap.digest(package)
    with pytest.raises((RuntimeError, ValueError)):
        bootstrap.establish_baseline(root, package, checksum, tmp_path / "work")
    assert not (root / ".update-baseline.json").exists()
