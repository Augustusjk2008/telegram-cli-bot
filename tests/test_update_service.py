from __future__ import annotations

import asyncio
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import app_settings, updater
from bot.update_service import UpdateService, UpdateServiceError
from bot.update_state import UpdateConflict, UpdateStore


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    return UpdateService(root, store=UpdateStore(root, state_root=tmp_path / "state"))


def test_public_status_keeps_execution_file_plans_out_of_polling_responses(service):
    large_plan = {f"runtime/python/file-{number}.py": "a" * 64 for number in range(2000)}
    service.store.mutate(lambda state: state.update(legacy_imported=True, job={
        "job_id": "payload", "phase": "ready", "manifest": {"files": large_plan},
        "original_hashes": large_plan, "prepared_hashes": large_plan, "source": {"path": "package.zip"},
    }))
    status = service.status()
    assert status["job"]["job_id"] == "payload"
    assert len(json.dumps(status)) < 5000
    assert service.store.read()["job"]["manifest"]["files"] == large_plan


def test_store_isolation_revision_and_standalone_import(tmp_path, monkeypatch):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    first, second = UpdateStore(tmp_path / "a"), UpdateStore(tmp_path / "b")
    assert first.root != second.root
    state = first.mutate(lambda s: s.update(job={"job_id": "one", "phase": "ready"}))
    assert state["job"]["revision"] == state["revision"] == 1
    with pytest.raises(UpdateConflict):
        first.mutate(lambda s: s.update(update_enabled=False), expected_revision=0)
    assert second.read()["job"] is None
    with pytest.raises(UpdateConflict):
        UpdateStore(tmp_path / "b", state_root=first.root).read()
    code = (
        "import importlib.util,sys; "
        "spec=importlib.util.spec_from_file_location('snapshot',sys.argv[1]); "
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m); "
        "s=m.UpdateStore(sys.argv[2],state_root=sys.argv[3]); "
        "s.mutate(lambda d:d.update(update_enabled=False)); "
        "assert not s.read()['update_enabled']; assert 'bot' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code, str(Path("bot/update_state.py").resolve()),
                             str(tmp_path / "standalone"), str(tmp_path / "standalone-state")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_store_serializes_parallel_writers(service):
    service.store.mutate(lambda s: s.update(count=0))
    def increment():
        for _ in range(10):
            service.store.mutate(lambda s: s.update(count=s["count"] + 1))
    workers = [threading.Thread(target=increment) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
    state = service.store.read()
    assert state["count"] == 40
    assert state["revision"] == 41


def test_legacy_claim_requires_install_owned_path(service, tmp_path):
    owned = service.repo_root / ".updates" / "update.zip"
    owned.parent.mkdir()
    owned.write_bytes(b"archive")
    app_settings._save_settings({"pending_update_path": str(owned), "pending_update_version": "9.0"})
    status = service.status()
    assert status["job"]["phase"] == "ready"
    assert status["job"]["requires_preparation"] is True
    other = UpdateService(tmp_path / "other", store=UpdateStore(tmp_path / "other", state_root=tmp_path / "other-state"))
    assert other.status()["job"] is None
    assert other.status()["legacy_notice"]
    assert app_settings._load_settings()["pending_update_path"] == str(owned)


def test_check_does_not_overwrite_settings_and_failure_marks_cache(service, monkeypatch):
    def fetch():
        app_settings.update_git_proxy_address("localhost:9123")
        return {"tag_name": "v9.0.0", "body": "release"}
    monkeypatch.setattr(updater, "_fetch_latest_release", fetch)
    assert service.check()["last_check"]["ok"] is True
    assert app_settings.get_git_proxy_settings()["address"] == "localhost:9123"
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: (_ for _ in ()).throw(OSError("network down")))
    state = service.check()
    assert state["last_check"]["ok"] is False
    assert state["last_check"]["cached"] is True
    assert state["last_available_version"] == "9.0.0"
    with pytest.raises(UpdateServiceError):
        service.start_online()
    assert service.status()["job"] is None


def _fake_preparation(monkeypatch, service, *, block=None, started=None):
    from bot import update_preparation
    calls = []
    def prepare(repo_root, package, job_dir, expected_version="", progress_callback=None):
        calls.append(str(package))
        if started:
            started.set()
        if block:
            block.wait(5)
        progress_callback({"phase": "validating"})
        staging = job_dir / "staging"
        staging.mkdir(exist_ok=True)
        return {"current_version": "1.0", "target_version": "2.0", "package_kind": "installer",
                "package_sha256": "abc", "staging_dir": str(staging), "files": [], "delete_paths": [],
                "manifest": {"migrations": {"backward_compatible": True}}}
    monkeypatch.setattr(updater, "prepare_update_payload", prepare)
    monkeypatch.setattr(update_preparation, "prepare_runtime", lambda repo, directory, prepared, **kwargs: {
        "python_executable": sys.executable, "previous_python_executable": sys.executable,
        "backup_dir": str(directory / "transaction")})
    return calls


@pytest.mark.asyncio
async def test_preparation_singleton_disconnect_cancel_retry(service, monkeypatch):
    release = threading.Event()
    started = threading.Event()
    calls = _fake_preparation(monkeypatch, service, block=release, started=started)
    status = service.start_offline("one.zip")
    assert await asyncio.to_thread(started.wait, 5)
    job_id = status["job"]["job_id"]
    assert service.start_offline("one.zip")["job"]["job_id"] == job_id
    with pytest.raises(UpdateServiceError):
        service.start_offline("two.zip")
    iterator = service.events(job_id)
    assert (await anext(iterator))["type"] == "job"
    await iterator.aclose()
    current = service.status()
    service.cancel(job_id, current["revision"])
    release.set()
    await asyncio.to_thread(service._worker.join, 5)
    assert service.status()["job"]["phase"] == "cancelled"
    new = service.retry(job_id, service.status()["revision"])
    events = [event async for event in service.events(new["job"]["job_id"])]
    await asyncio.to_thread(service._worker.join, 5)
    assert len(calls) == 2
    assert events[-1]["type"] == "done"
    assert events[-1]["status"]["job"]["phase"] == "ready"


def test_orphan_preparation_becomes_retryable_failure(service):
    service.status()
    job = service._new_job("orphan", {"path": "one.zip"})
    service.store.mutate(lambda s: s.update(job=job))
    assert service.status()["job"]["phase"] == "failed"


@pytest.mark.asyncio
async def test_online_release_bound_and_subscriber_disconnect_preserves_result(service, monkeypatch):
    release = {"tag_name": "v9.0.0", "assets": []}
    requested = []
    _fake_preparation(monkeypatch, service)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: release)
    def download(root, directory, selected, progress_callback=None):
        requested.append(selected)
        return directory / "download.zip"
    monkeypatch.setattr(updater, "_download_release_package", download)
    state = await asyncio.to_thread(service.start_online)
    events = service.events(state["job"]["job_id"])
    await anext(events)
    await events.aclose()
    await asyncio.to_thread(service._worker.join, 5)
    assert requested == [release]
    assert service.status()["job"]["phase"] == "ready"
    resumed = [item async for item in service.events(state["job"]["job_id"])]
    assert resumed[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_upload_success_uses_background_preparation(service, monkeypatch):
    _fake_preparation(monkeypatch, service)
    async def chunks():
        yield b"first"
        yield b"second"
    status = await service.upload("update.zip", chunks())
    await asyncio.to_thread(service._worker.join, 5)
    ready = service.status()["job"]
    assert ready["job_id"] == status["job"]["job_id"]
    assert ready["phase"] == "ready"
    assert Path(ready["package_path"]).read_bytes() == b"firstsecond"


def _ready(service):
    service.status()
    staging = service.store.job_dir("ready") / "staging"
    staging.mkdir(parents=True)
    job = service._new_job("ready", {"path": "one.zip"})
    job.update(phase="ready", staging_dir=str(staging), files=[], delete_paths=[],
               original_hashes={}, prepared_hashes={},
               python_executable=sys.executable, previous_python_executable=sys.executable,
               backup_dir=str(staging.parent / "backup"), manifest={"migrations": {"backward_compatible": True}})
    return service.store.mutate(lambda s: s.update(job=job))


def test_apply_requires_capability_revision_idle_and_actual_health_target(service, monkeypatch):
    state = _ready(service)
    exits = []
    kwargs = {"idle_check": lambda: "", "request_exit": lambda *args: exits.append(args)}
    monkeypatch.delenv("CLI_BRIDGE_UPDATE_PROTOCOL", raising=False)
    with pytest.raises(UpdateServiceError, match="启动"):
        service.request_apply("ready", state["revision"], **kwargs)
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    with pytest.raises(UpdateConflict):
        service.request_apply("ready", state["revision"] - 1, **kwargs)
    with pytest.raises(UpdateServiceError, match="busy"):
        service.request_apply("ready", state["revision"], **{**kwargs, "idle_check": lambda: "busy"})
    assert not exits
    result = service.request_apply("ready", state["revision"], **kwargs,
                                   health={"host": "0.0.0.0", "port": 19001, "base_path": "/node/test", "instance_id": "old"})
    assert result["job"]["phase"] == "waiting_restart"
    assert result["job"]["health_url"] == "http://127.0.0.1:19001/node/test/api/health"
    assert exits == [("ready", str(service.store.state_path))]
    with pytest.raises(UpdateServiceError):
        service.cancel("ready", result["revision"])
    service.fail_handoff("ready", "flush failed")
    assert service.status()["job"]["result"] == "handoff_failed"
    service.store.mutate(lambda s: s["job"].update(phase="applying"))
    service.fail_handoff("ready", "late callback")
    assert service.status()["job"]["phase"] == "applying"


@pytest.mark.parametrize("change", ["modified", "created", "deleted", "staging"])
def test_apply_rechecks_original_and_staged_files(service, monkeypatch, change):
    state = _ready(service)
    original = service.repo_root / "app.py"
    staged = Path(state["job"]["staging_dir"]) / "app.py"
    original.write_bytes(b"old")
    staged.write_bytes(b"new")
    def record(s):
        s["job"].update(files=["app.py"], original_hashes={"app.py": hashlib.sha256(b"old").hexdigest()},
                        prepared_hashes={"app.py": hashlib.sha256(b"new").hexdigest()})
    state = service.store.mutate(record)
    if change == "modified":
        original.write_bytes(b"local change")
    elif change == "created":
        state = service.store.mutate(lambda s: s["job"]["original_hashes"].update({"app.py": None}))
    elif change == "deleted":
        original.unlink()
    else:
        staged.write_bytes(b"corrupt")
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    with pytest.raises(UpdateServiceError):
        service.request_apply("ready", state["revision"], idle_check=lambda: "",
                              request_exit=lambda *args: pytest.fail("modified files must block host exit"))
    assert service.store.read()["job"]["phase"] == "ready"


def test_idle_callback_can_read_state_without_recursive_lock(service, monkeypatch):
    state = _ready(service)
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    reads = []
    def idle():
        reads.append(service.status()["job"]["phase"])
        return ""
    service.request_apply("ready", state["revision"], idle_check=idle, request_exit=lambda *args: None)
    assert reads == ["ready"]


def test_failed_announcement_is_retryable_without_changing_success(service, monkeypatch):
    _ready(service)
    service.store.mutate(lambda s: s["job"].update(phase="succeeded", result={"version": "9.0.0"},
                                                  package_path="package.zip", files=[".web_announcements.json"]))
    def fail(*args):
        raise OSError("announcements locked")
    monkeypatch.setattr(updater, "_sync_runtime_announcements_from_package", fail)
    service.status()
    service._announcement_worker.join(5)
    failed = service.store.read()["job"]
    assert failed["phase"] == "succeeded"
    assert failed["announcement_pending"] is True
    assert failed["announcement_error"] == "announcements locked"
    assert failed["result"] == {"version": "9.0.0"}
    completed = []
    monkeypatch.setattr(updater, "_sync_runtime_announcements_from_package", lambda *args: completed.append(args))
    service.store.mutate(lambda s: s["job"].update(announcement_retry_after=0))
    service.status()
    service._announcement_worker.join(5)
    success = service.status()["job"]
    assert success["phase"] == "succeeded"
    assert success["announcement_pending"] is False
    assert success["announcement_error"] == ""
    assert len(completed) == 1
    service.status()
    assert len(completed) == 1


def test_invalid_release_version_is_a_failed_check(service, monkeypatch):
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {"tag_name": "v9.0"})
    checked = service.check()
    assert checked["last_check"]["ok"] is False
    assert checked["last_check"]["cached"] is True
    with pytest.raises(UpdateServiceError):
        service.start_online()
    assert service.status()["job"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("latest,current,expected", [("3.0.2", "3.0.2", False), ("3.0.3-rc.1", "3.0.2", True),
                                                     ("bad", "3.0.2", False)])
async def test_automatic_check_uses_semantic_versions(service, monkeypatch, latest, current, expected):
    from bot.web.server import WebApiServer
    server = WebApiServer(object())
    server._update_service = service
    snapshot = {"update_enabled": True, "current_version": current, "last_available_version": latest,
                "last_check": {"ok": True, "cached": False, "release": {"tag_name": latest}}}
    monkeypatch.setattr(service, "check", lambda: snapshot)
    started = []
    monkeypatch.setattr(service, "start_online", lambda **kwargs: started.append(kwargs))
    await server._auto_refresh_update_status()
    assert bool(started) is expected


@pytest.mark.asyncio
async def test_handoff_blocks_shared_chat_cluster_and_storage(service, monkeypatch):
    from bot import config
    from bot.web import api_service
    from bot.web.server import WebApiServer
    from bot.web.api_common import WebApiError
    from bot.web.storage_migration_api import StorageMigrationApiError
    monkeypatch.setattr(config, "UPDATE_DRAINING", True)
    monkeypatch.setattr(config, "UPDATE_REQUESTED", False)
    session = SimpleNamespace(_lock=threading.RLock())
    with pytest.raises(WebApiError, match="交接"):
        with api_service._session_lifecycle_scope(session):
            pytest.fail("new chat must be rejected before reserving the session")
    with pytest.raises(WebApiError, match="交接"):
        await api_service.handle_cluster_mcp_tool(object(), "unused", "ask_agent", {})
    server = WebApiServer(object())
    server._update_service = service
    with pytest.raises(StorageMigrationApiError):
        await server.storage_migration_api.begin("plan", confirm_stop_all_agents=True)
    with pytest.raises(StorageMigrationApiError):
        await server.storage_migration_api.preview("unused-target")
    monkeypatch.setattr(config, "UPDATE_DRAINING", False)
    session = SimpleNamespace(is_processing=False, process=None, _lifecycle_operation="chat",
                              disable_persistence=lambda: None, terminate_process=lambda: None)
    monkeypatch.setitem(api_service.sessions, (1, 1, "main"), session)
    assert server._update_idle_reason() == "智能体仍有运行中的任务"


@pytest.mark.asyncio
async def test_api_apply_closes_shared_admission_before_delayed_exit(service, monkeypatch):
    from bot import config
    from bot.web.server import WebApiServer
    monkeypatch.setenv("CLI_BRIDGE_UPDATE_PROTOCOL", "1")
    monkeypatch.setattr(config, "UPDATE_DRAINING", False)
    monkeypatch.setattr(config, "UPDATE_REQUESTED", False)
    state = _ready(service)
    server = WebApiServer(object())
    server._update_service = service
    monkeypatch.setattr(server, "_with_capability", AsyncMock())
    monkeypatch.setattr(server, "_parse_json", AsyncMock(return_value={"revision": state["revision"]}))
    monkeypatch.setattr(server, "_update_idle_reason", lambda: "")
    def schedule(*args):
        assert config.UPDATE_DRAINING is True
        server._update_exit_pending = True
    monkeypatch.setattr(server, "_schedule_update_exit", schedule)
    request = SimpleNamespace(match_info={"job_id": "ready", "action": "apply"})
    from bot.web.api_common import WebApiError
    monkeypatch.setattr(server, "_parse_json", AsyncMock(return_value={"revision": state["revision"] - 1}))
    with pytest.raises(WebApiError):
        await server.admin_update_job_action(request)
    assert config.UPDATE_DRAINING is False
    monkeypatch.setattr(server, "_parse_json", AsyncMock(return_value={"revision": state["revision"]}))
    response = await server.admin_update_job_action(request)
    assert response.status == 202
    assert config.UPDATE_DRAINING is True
    assert config.UPDATE_REQUESTED is False
    assert service.store.read()["job"]["phase"] == "waiting_restart"


@pytest.mark.asyncio
async def test_upload_limit_and_disk_checks(service, monkeypatch):
    async def chunks():
        yield b"1234"
        yield b"5678"
    with pytest.raises(UpdateServiceError) as error:
        await service.upload("update.zip", chunks(), max_bytes=5)
    assert error.value.status == 413
    assert not list(service.store.root.rglob("*.part"))
    monkeypatch.setattr("bot.update_service.shutil.disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(UpdateServiceError) as error:
        await service.upload("update.zip", chunks())
    assert error.value.status == 507
    assert service.status()["job"]["phase"] == "failed"


@pytest.mark.asyncio
async def test_api_permissions_bool_revision_and_no_download_on_failed_check(service, monkeypatch):
    from bot.web.server import WebApiServer
    from bot.web.api_service import WebApiError
    server = WebApiServer(object())
    server._update_service = service
    denied = AsyncMock(side_effect=WebApiError(403, "forbidden", "denied"))
    monkeypatch.setattr(server, "_with_capability", denied)
    with pytest.raises(WebApiError) as error:
        await server.admin_update_download(None)
    assert error.value.status == 403
    monkeypatch.setattr(server, "_with_capability", AsyncMock())
    monkeypatch.setattr(server, "_parse_json", AsyncMock(return_value={"update_enabled": "false"}))
    with pytest.raises(WebApiError) as error:
        await server.admin_patch_update(None)
    assert error.value.status == 400
    monkeypatch.setattr(server, "_parse_json", AsyncMock(return_value={"revision": True}))
    with pytest.raises(WebApiError) as error:
        await server.admin_update_job_action(SimpleNamespace(match_info={"job_id": "missing", "action": "apply"}))
    assert error.value.status == 400
    monkeypatch.setattr(service, "check", lambda: {"last_check": {"ok": False, "cached": True}, "last_available_version": "9"})
    monkeypatch.setattr(service, "start_online", lambda **kwargs: pytest.fail("failed checks must not start a download"))
    await server._auto_refresh_update_status()


@pytest.mark.asyncio
async def test_storage_migration_rejects_update_before_stopping_agents(service, monkeypatch):
    from bot.web.server import WebApiServer
    from bot.web.storage_migration_api import StorageMigrationApiError
    server = WebApiServer(object())
    server._update_service = service
    _ready(service)
    stop = AsyncMock()
    server.storage_migration_api.stop_all_agents = stop
    with pytest.raises(StorageMigrationApiError) as error:
        await server.storage_migration_api.begin("plan", confirm_stop_all_agents=True)
    assert error.value.code == "update_busy"
    stop.assert_not_called()
