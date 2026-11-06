"""One durable preparation job per installation, independent of HTTP subscribers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import threading
import time
import uuid

from bot.update_state import FileLock, UpdateConflict, UpdateStore

ACTIVE_PHASES = frozenset({"preparing", "ready", "waiting_restart", "applying", "awaiting_health",
                           "rolling_back", "recovery_required"})
APPLY_PHASES = ACTIVE_PHASES - {"preparing", "ready"}
UPLOAD_LIMIT = 4 * 1024**3
DISK_RESERVE = 64 * 1024**2
_EXECUTION_FIELDS = frozenset({"manifest", "files", "delete_paths", "prepared_hashes", "original_hashes",
                               "host_environment", "runner_hashes", "previous_frontend_hashes", "source"})


class UpdateServiceError(RuntimeError):
    def __init__(self, message, *, status=409, code="update_conflict"):
        super().__init__(message)
        self.status, self.code = status, code


class PreparationCancelled(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def launcher_capability(repo_root):
    root = Path(repo_root).resolve()
    supported = os.environ.get("CLI_BRIDGE_UPDATE_PROTOCOL", "").strip() == "1"
    command = "& '" + str(root / "start.ps1").replace("'", "''") + "'" if os.name == "nt" else "bash " + shlex.quote(str(root / "start.sh"))
    return {"supported": supported, "protocol": 1, "command": command,
            "reason": "" if supported else "当前启动方式未提供升级协议，请使用本安装的官方启动器"}


class UpdateService:
    def __init__(self, repo_root, *, store=None):
        self.repo_root = Path(repo_root).resolve()
        self.store = store or UpdateStore(self.repo_root)
        self._worker = None
        self._check_lock = threading.Lock()
        self._announcement_worker = None

    def _migrate_legacy(self):
        from bot import app_settings, updater
        if self.store.read().get("legacy_imported"):
            return
        legacy = app_settings._load_settings()
        raw_path = str(legacy.get("pending_update_path") or "")
        path = Path(raw_path).resolve() if raw_path else None
        cache_roots = [self.repo_root / updater.UPDATE_CACHE_DIR_NAME, updater._fallback_update_cache_dir(self.repo_root)]
        owned = path is not None and path.is_file() and any(
            root.resolve() == root.absolute() and path.is_relative_to(root.resolve()) for root in cache_roots
        )

        def migrate(state):
            if state.get("legacy_imported"):
                return
            state["legacy_imported"] = True
            state["update_enabled"] = legacy.get("update_enabled", True) is True
            if not state.get("job") and owned:
                job_id = uuid.uuid4().hex
                job = self._new_job(job_id, {"path": str(path), "version": legacy.get("pending_update_version", "")})
                job.update(phase="ready", target_version=legacy.get("pending_update_version", ""),
                           package_kind=legacy.get("pending_update_package_kind", ""),
                           package_sha256=legacy.get("pending_update_sha256", ""),
                           package_path=str(path), requires_preparation=True)
                state["job"] = job
            elif raw_path and not owned:
                state["legacy_notice"] = "旧待更新包归属无法确认，请重新选择本安装的更新包"
        self.store.mutate(migrate)

    def _new_job(self, job_id, source):
        from bot.version import APP_VERSION
        return {"job_id": job_id, "revision": 0, "phase": "preparing", "current_version": APP_VERSION,
                "target_version": "", "package_kind": "", "package_sha256": "", "progress": {},
                "error": "", "launcher": launcher_capability(self.repo_root), "backup_dir": "",
                "result": None, "job_dir": str(self.store.job_dir(job_id)), "source": source,
                "created_at": _now()}

    def status(self):
        from bot import updater
        from bot.version import APP_VERSION
        self._migrate_legacy()
        state = self.store.read()
        if (state.get("job") or {}).get("phase") == "preparing":
            try:
                with FileLock(self.store.root / "preparation.lock", timeout=0):
                    def interrupt(current):
                        if (current.get("job") or {}).get("phase") == "preparing":
                            current["job"].update(phase="failed", error="准备任务因宿主退出而中断，可重试")
                    state = self.store.mutate(interrupt)
            except UpdateConflict:
                pass
        state = self._schedule_announcements(state)
        job = state.get("job") or {}
        check = state.get("last_check") or {}
        release = check.get("release") or {}
        pending = job.get("phase") in ACTIVE_PHASES
        public_job = {key: value for key, value in job.items() if key not in _EXECUTION_FIELDS} if job else None
        return {**state, "job": public_job, "launcher": launcher_capability(self.repo_root), "current_version": APP_VERSION,
                "current_package_kind": updater.detect_update_package_kind(self.repo_root), "update_channel": "release",
                "last_checked_at": check.get("checked_at", ""),
                "last_available_version": str(release.get("tag_name") or "").lstrip("v"),
                "last_available_release_url": release.get("html_url", ""), "last_available_notes": release.get("body", ""),
                "pending_update_version": job.get("target_version", "") if pending else "",
                "pending_update_path": job.get("package_path", "") if pending else "",
                "pending_update_notes": (job.get("source", {}).get("release") or {}).get("body", "") if pending else "",
                "pending_update_platform": updater._pending_update_platform(job.get("package_kind", "")) if pending else "",
                "pending_update_package_kind": job.get("package_kind", "") if pending else "",
                "pending_update_sha256": job.get("package_sha256", "") if pending else "",
                "update_last_error": job.get("error") or check.get("error") or state.get("legacy_notice", "")}

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise UpdateServiceError("update_enabled 必须是布尔值", status=400, code="invalid_update_enabled")
        self._migrate_legacy()
        self.store.mutate(lambda state: state.update(update_enabled=enabled))
        return self.status()

    def check(self):
        from bot import updater
        from scripts.update_package import compare_versions
        from bot.version import APP_VERSION
        self._migrate_legacy()
        with self._check_lock:
            try:
                release = updater._fetch_latest_release()
                if not isinstance(release, dict) or not release.get("tag_name"):
                    raise ValueError("Release 缺少版本信息")
                available = compare_versions(release["tag_name"], APP_VERSION) > 0
                result = {"ok": True, "cached": False, "checked_at": _now(), "error": "", "release": release,
                          "update_available": available}
            except Exception as exc:
                result = {"ok": False, "cached": True, "checked_at": _now(), "error": str(exc),
                          "release": self.store.read().get("last_check", {}).get("release", {})}
            self.store.mutate(lambda state: state.update(last_check=result))
        return self.status()

    def _reserve(self, source, *, retry_job_id=None, expected_revision=None):
        self._migrate_legacy()
        lease = FileLock(self.store.root / "preparation.lock", timeout=0)
        try:
            lease.__enter__()
        except UpdateConflict as exc:
            current = self.status()
            if (self.store.read().get("job") or {}).get("source") == source and retry_job_id is None:
                return None, current
            raise UpdateServiceError("本安装已有准备任务正在执行") from exc
        try:
            def reserve(state):
                old = state.get("job") or {}
                if retry_job_id:
                    if old.get("job_id") != retry_job_id or old.get("phase") not in {"failed", "cancelled", "ready"}:
                        raise UpdateServiceError("该任务当前不能重试")
                elif old.get("phase") in ACTIVE_PHASES:
                    if old.get("source") == source:
                        return
                    raise UpdateServiceError("本安装已有更新任务，请先完成或取消")
                job_id = uuid.uuid4().hex
                state.pop("legacy_notice", None)
                state["job"] = self._new_job(job_id, source)
            before = self.store.read().get("job") or {}
            result = self.store.mutate(reserve, expected_revision=expected_revision)
            if (result.get("job") or {}).get("job_id") == before.get("job_id"):
                lease.__exit__()
                return None, self.status()
            self.store.job_dir(result["job"]["job_id"]).mkdir(parents=True, exist_ok=True)
            # The held preparation lease serializes cleanup with every preparation.
            self.store.prune_job_dirs(lock_held=True)
            return lease, self.status()
        except BaseException:
            lease.__exit__()
            raise

    def start_online(self, *, release=None):
        from scripts.update_package import compare_versions
        status = self.status()
        if (status.get("job") or {}).get("phase") in ACTIVE_PHASES:
            return status
        if release is None:
            status = self.check()
            if status["last_check"].get("ok") is not True:
                raise UpdateServiceError(status["last_check"]["error"], status=502, code="update_check_failed")
            release = status["last_check"]["release"]
        try:
            if compare_versions(release.get("tag_name", ""), status["current_version"]) < 0:
                raise ValueError("目标版本低于当前版本")
        except ValueError as exc:
            raise UpdateServiceError(str(exc), status=400, code="invalid_update_version") from exc
        return self._start({"release": release})

    def start_offline(self, path, version=""):
        if not str(path).strip():
            raise UpdateServiceError("离线包路径不能为空", status=400, code="missing_package_path")
        return self._start({"path": str(Path(path).expanduser().resolve()), "version": version})

    def _start(self, source, **kwargs):
        lease, status = self._reserve(source, **kwargs)
        if lease is not None:
            self._launch_worker(self._require_job(self.store.read(), status["job"]["job_id"]), lease)
        return status

    def _launch_worker(self, job, lease):
        self._worker = threading.Thread(target=self._prepare, args=(job, lease), daemon=True,
                                        name=f'update-{job["job_id"]}')
        self._worker.start()

    def _patch_job(self, job_id, **values):
        def patch(state):
            if (state.get("job") or {}).get("job_id") != job_id:
                raise PreparationCancelled("任务已被替换")
            if state["job"].get("phase") == "cancelled":
                raise PreparationCancelled("准备任务已取消")
            state["job"].update(values)
        return self.store.mutate(patch)

    def _prepare(self, job, lease):
        from bot import updater
        job_id, source = job["job_id"], job["source"]
        job_dir = self.store.job_dir(job_id)
        last_progress = 0.0

        def progress(value):
            nonlocal last_progress
            current = self.store.read().get("job") or {}
            if current.get("job_id") != job_id or current.get("phase") == "cancelled":
                raise PreparationCancelled("准备任务已取消")
            payload = dict(value) if isinstance(value, dict) else {"message": str(value)}
            if time.monotonic() - last_progress >= 0.1:
                self._patch_job(job_id, progress=payload)
                last_progress = time.monotonic()

        try:
            progress({"phase": "preparing", "message": "正在准备更新包"})
            if "release" in source:
                package = updater._download_release_package(self.repo_root, job_dir, source["release"], progress_callback=progress)
                expected = str(source["release"].get("tag_name") or "").lstrip("v")
            else:
                package, expected = Path(source["path"]), source.get("version", "")
            self._patch_job(job_id, package_path=str(package))
            prepared = updater.prepare_update_payload(self.repo_root, package, job_dir,
                                                      expected_version=expected, progress_callback=progress)
            from bot.update_migration_gate import validate_update_migrations
            validate_update_migrations(self.repo_root, prepared)
            from bot.update_preparation import prepare_runtime
            runtime = prepare_runtime(self.repo_root, job_dir, prepared, progress_callback=progress)
            prepared = {**prepared, **runtime}
            originals = dict(prepared.get("original_hashes") or {})
            for name in [*prepared["files"], *prepared.get("delete_paths", [])]:
                if name not in originals:
                    target = self.repo_root / name
                    if target.exists() or target.is_symlink():
                        raise ValueError(f"运行环境准备引入了未经所有权校验的覆盖目标: {name}")
                    originals[name] = None
            prepared["original_hashes"] = originals
            progress({"message": "准备完成"})
            self._patch_job(job_id, **{**prepared, "phase": "ready", "error": "",
                                      "requires_preparation": False, "progress": {"phase": "ready", "percent": 100}})
        except PreparationCancelled:
            pass
        except Exception as exc:
            try:
                self._patch_job(job_id, phase="failed", error=str(exc))
            except PreparationCancelled:
                pass
        finally:
            lease.__exit__()

    def cancel(self, job_id, revision):
        def cancel(state):
            job = self._require_job(state, job_id)
            if job["phase"] not in {"preparing", "ready"}:
                raise UpdateServiceError("应用或恢复期间不能取消任务")
            job.update(phase="cancelled", error="", result="cancelled")
        self.store.mutate(cancel, expected_revision=revision)
        return self.status()

    def retry(self, job_id, revision):
        job = self._require_job(self.store.read(), job_id)
        if "upload" in job.get("source", {}):
            raise UpdateServiceError("上传中断，请重新上传更新包", status=400, code="update_upload_required")
        return self._start(job["source"], retry_job_id=job_id, expected_revision=revision)

    @staticmethod
    def _require_job(state, job_id):
        job = state.get("job") or {}
        if job.get("job_id") != job_id:
            raise UpdateServiceError("更新任务不存在", status=404, code="update_job_not_found")
        return job

    def request_apply(self, job_id, revision, *, idle_check, request_exit, health=None):
        capability = launcher_capability(self.repo_root)
        if not capability["supported"]:
            raise UpdateServiceError(capability["reason"], code="update_launcher_unsupported")
        from bot.update_migration_gate import validate_update_migrations
        with FileLock(self.store.root / "preparation.lock", timeout=0):
            snapshot = self.store.read()
            job = self._require_job(snapshot, job_id)
            if type(revision) is not int or snapshot["revision"] != revision:
                raise UpdateConflict("更新状态已变化，请刷新后重试")
            if job["phase"] != "ready" or job.get("requires_preparation"):
                raise UpdateServiceError("任务尚未完成准备，请先重试准备")
            validate_update_migrations(self.repo_root, job)
            self._verify_apply_files(job)
            # The callback may read this store; never call it inside state.mutate.
            reason = idle_check()
            if reason:
                raise UpdateServiceError(str(reason), code="update_host_busy")
            def apply(state):
                job = self._require_job(state, job_id)
                if job["phase"] != "ready" or job.get("requires_preparation"):
                    raise UpdateServiceError("任务尚未完成准备，请先重试准备")
                for field in ("python_executable", "previous_python_executable", "staging_dir", "files", "manifest", "backup_dir"):
                    if field not in job:
                        raise UpdateServiceError(f"任务缺少执行器字段: {field}")
                job.update(phase="waiting_restart", launcher=capability, health=dict(health or {}),
                           previous_instance_id=(health or {}).get("instance_id", ""))
                if health:
                    host = health["host"]
                    host = "127.0.0.1" if host in {"0.0.0.0", ""} else "::1" if host == "::" else host
                    host = f"[{host}]" if ":" in host and not host.startswith("[") else host
                    base = health.get("base_path", "").rstrip("/")
                    job.update(health_url=f'http://{host}:{health["port"]}{base}/api/health', health_base_path=base)
            self.store.mutate(apply, expected_revision=revision)
        request_exit(job_id, str(self.store.state_path))
        return self.status()

    @staticmethod
    def _file_hash(path):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_apply_files(self, job):
        from scripts.update_package import normalize_path
        original = job.get("original_hashes")
        staged = job.get("prepared_hashes")
        if not isinstance(original, dict) or not isinstance(staged, dict):
            raise UpdateServiceError("更新任务缺少文件校验快照，请重新准备")
        for name in {*job.get("files", []), *job.get("delete_paths", [])}:
            normalized = normalize_path(name)
            path = self.repo_root / normalized
            if name not in original or path.resolve() != path.absolute():
                raise UpdateServiceError(f"原文件快照缺失或路径已变化: {name}")
            expected = original[name]
            if (expected is None and (path.exists() or path.is_symlink())) or (
                    expected is not None and (not path.is_file() or self._file_hash(path) != expected)):
                raise UpdateServiceError(f"准备后安装文件发生变化，请重新准备: {name}")
        staging = Path(job["staging_dir"]).resolve()
        for name in job.get("files", []):
            path = staging / normalize_path(name)
            if (name not in staged or path.resolve() != path.absolute() or not path.is_file()
                    or self._file_hash(path) != staged[name]):
                raise UpdateServiceError(f"暂存文件校验失败，请重新准备: {name}")

    def _schedule_announcements(self, state):
        job = state.get("job") or {}
        if (job.get("phase") != "succeeded" or job.get("announcement_pending") is False
                or float(job.get("announcement_retry_after", 0)) > time.time()):
            return state
        lease = FileLock(self.store.root / "announcements.lock", timeout=0)
        try:
            lease.__enter__()
        except UpdateConflict:
            return state
        try:
            def pending(current):
                active = current.get("job") or {}
                if active.get("job_id") != job["job_id"] or active.get("phase") != "succeeded":
                    raise UpdateConflict("公告所属升级任务已变化")
                active.update(announcement_pending=True)
            state = self.store.mutate(pending)
            self._announcement_worker = threading.Thread(target=self._sync_announcements,
                                                        args=(state["job"], lease), daemon=True)
            self._announcement_worker.start()
            return state
        except UpdateConflict:
            lease.__exit__()
            return self.store.read()
        except BaseException:
            lease.__exit__()
            raise

    def _sync_announcements(self, job, lease):
        try:
            error = ""
            try:
                from bot.updater import _sync_runtime_announcements_from_package
                _sync_runtime_announcements_from_package(Path(job.get("package_path", "")), job.get("files", []))
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            def complete(state):
                active = state.get("job") or {}
                if active.get("job_id") == job["job_id"] and active.get("phase") == "succeeded":
                    active.update(announcement_pending=bool(error), announcement_error=error,
                                  announcement_retry_after=time.time() + 60 if error else 0)
            self.store.mutate(complete)
        finally:
            lease.__exit__()

    def fail_handoff(self, job_id, error):
        def fail(state):
            job = state.get("job") or {}
            if job.get("job_id") == job_id and job.get("phase") == "waiting_restart":
                job.update(phase="failed", error=f"宿主退出与会话保存失败: {error}", result="handoff_failed")
        self.store.mutate(fail)

    async def events(self, job_id):
        revision = -1
        while True:
            status = await asyncio.to_thread(self.status)
            try:
                job = self._require_job(status, job_id)
            except UpdateServiceError as exc:
                yield {"type": "error", "code": exc.code, "message": str(exc)}
                return
            if status["revision"] != revision:
                revision = status["revision"]
                yield {"type": "job", "job": job, "status": status}
                if job.get("progress"):
                    yield {"type": "progress", **job["progress"]}
                if job["phase"] in {"ready", "succeeded", "cancelled", "rolled_back"}:
                    yield {"type": "done", "status": status}
                    return
                if job["phase"] in {"failed", "recovery_required"}:
                    yield {"type": "error", "message": job["error"], "status": status}
                    return
            await asyncio.sleep(0.1)

    async def upload(self, filename, chunks, *, max_bytes=UPLOAD_LIMIT):
        name = Path(str(filename).replace("\\", "/")).name
        if not name.lower().endswith((".zip", ".tar.gz", ".tgz")):
            raise UpdateServiceError("只支持 zip、tar.gz 或 tgz 更新包", status=400, code="invalid_update_package")
        lease, status = self._reserve({"upload": name, "nonce": uuid.uuid4().hex})
        job = status["job"]
        destination = self.store.job_dir(job["job_id"]) / name
        partial = destination.with_name(destination.name + ".part")
        total = 0
        try:
            with partial.open("xb") as handle:
                async for chunk in chunks:
                    total += len(chunk)
                    if total > max_bytes:
                        raise UpdateServiceError("上传超过更新包大小限制", status=413, code="update_upload_too_large")
                    if shutil.disk_usage(partial.parent).free < len(chunk) + DISK_RESERVE:
                        raise UpdateServiceError("更新缓存磁盘空间不足", status=507, code="update_disk_full")
                    self._patch_job(job["job_id"], progress={"phase": "uploading", "downloaded_bytes": total})
                    await asyncio.to_thread(handle.write, chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if not total:
                raise UpdateServiceError("上传的更新包为空", status=400, code="invalid_update_package")
            partial.replace(destination)
            updated = self._patch_job(job["job_id"], source={"path": str(destination), "version": ""})
            self._launch_worker(updated["job"], lease)
            lease = None
            return self.status()
        except BaseException as exc:
            partial.unlink(missing_ok=True)
            try:
                self._patch_job(job["job_id"], phase="failed", error=str(exc) or "上传中断")
            except PreparationCancelled:
                pass
            raise
        finally:
            if lease is not None:
                lease.__exit__()


_services = {}
_services_lock = threading.Lock()


def get_update_service(repo_root=None):
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    store = UpdateStore(root)
    key = str(store.state_path)
    with _services_lock:
        if key not in _services:
            _services[key] = UpdateService(root, store=store)
        return _services[key]
