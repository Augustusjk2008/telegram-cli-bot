"""Host-independent update supervisor. This file and its helpers use only stdlib."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import runpy
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse


RESTART_EXIT_CODE = 75
UPDATE_EXIT_CODE = 76
RECOVERY_EXIT_CODE = 78
RECOVERY_PHASES = {"applying", "awaiting_health", "rolling_back", "recovery_required"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load recovery module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _helpers(repo_root: Path):
    here = Path(__file__).resolve().parent
    state_file = here / "update_state.py"
    if not state_file.is_file():
        state_file = repo_root / "bot" / "update_state.py"
    return (_load("update_state", state_file).UpdateStore,
            _load("update_transaction", here / "update_transaction.py").Transaction)


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def control_root(repo_root: Path) -> Path:
    base = os.environ.get("TCB_UPDATE_CONTROL_ROOT")
    if not base:
        base = str(Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "OrbitSafeClaw" / "updates")
    identity = hashlib.sha256(os.path.normcase(str(repo_root.resolve())).encode()).hexdigest()[:20]
    root = Path(base).resolve() / identity
    if root.is_relative_to(repo_root.resolve()):
        raise RuntimeError("Recovery control directory must be outside the installation")
    return root


def freeze_runner(repo_root: Path, snapshot_dir: Path, *, source_root: Path | None = None) -> dict:
    """Freeze code and, when needed, a Windows control Python outside update targets."""
    repo_root, snapshot_dir = repo_root.resolve(), snapshot_dir.resolve()
    source_root = Path(source_root or repo_root).resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    sources = {"update_runner.py": source_root / "scripts" / "update_runner.py",
               "update_transaction.py": source_root / "scripts" / "update_transaction.py",
               "update_package.py": source_root / "scripts" / "update_package.py",
               "update_state.py": source_root / "bot" / "update_state.py"}
    hashes = {}
    for name, source in sources.items():
        target = snapshot_dir / name
        if target.exists() and _hash(target) != _hash(source):
            raise RuntimeError(f"Recovery snapshot is immutable: {target}")
        if not target.exists():
            shutil.copy2(source, target)
        hashes[name] = _hash(target)
    control_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    if control_python.is_relative_to(repo_root):
        identity = hashlib.sha256(str(snapshot_dir).encode()).hexdigest()[:20]
        destination = control_root(repo_root) / identity / "python"
        if destination.exists():
            raise RuntimeError(f"Control runtime already exists: {destination}")
        shutil.copytree(control_python.parent, destination, ignore=shutil.ignore_patterns("site-packages", "__pycache__"))
        control_python = destination / control_python.name
    if control_python.is_relative_to(repo_root):
        raise RuntimeError("Control Python cannot be inside the installation")
    return {"runner_path": str(snapshot_dir / "update_runner.py"),
            "control_python_executable": str(control_python), "runner_hashes": hashes}


def open_store(repo_root: Path, state_file: str = ""):
    store_type, _ = _helpers(repo_root)
    if state_file:
        store = store_type(repo_root, state_root=Path(state_file).resolve().parent)
    else:
        previous_path = list(sys.path)
        try:
            sys.path.insert(0, str(repo_root))
            store = store_type(repo_root)
        finally:
            sys.path[:] = previous_path
    if state_file and store.state_path.resolve() != Path(state_file).resolve():
        raise RuntimeError("Update state file does not match this installation")
    state = store.read()
    if Path(state["install_root"]).resolve() != repo_root.resolve():
        raise RuntimeError("Update state belongs to another installation")
    return store


@contextmanager
def supervisor_lock(store):
    """A separate lifetime lock prevents two launchers from starting/applying together."""
    store.execution_lock_root.mkdir(parents=True, exist_ok=True)
    handle = (store.execution_lock_root / "supervisor.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("Another official launcher owns this installation") from exc
    try:
        # An orphaned official child keeps this lock after its supervisor exits.
        state_module = sys.modules[store.__class__.__module__]
        with state_module.FileLock(store.execution_lock_root / "host.lock", timeout=0):
            pass
        yield
    finally:
        handle.close()


def _job(store, job_id: str) -> dict:
    job = store.read().get("job") or {}
    if not job_id or job.get("job_id") != job_id:
        raise RuntimeError("Update job no longer matches the requested handoff")
    return job


def _change(store, job_id: str, phase: str, **fields) -> dict:
    def mutate(state):
        if (state.get("job") or {}).get("job_id") != job_id:
            raise RuntimeError("Update job changed during execution")
        state["job"].update(phase=phase, **fields)
    state = store.mutate(mutate)
    print(f"[update] {job_id}: {phase}", flush=True)
    try:
        log = store.job_dir(job_id) / "runner.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": time.time(), "phase": phase, "error": fields.get("error", "")}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return state["job"]


def _host_command(repo_root: Path, python: str) -> list[str]:
    bootstrap = repo_root / "runtime" / "portable_bootstrap.py"
    if bootstrap.is_file():
        return [python, str(bootstrap), "bot", str(repo_root)]
    return [python, "-m", "bot"]


def _start_host(repo_root: Path, python: str, store, job_id="", token="", legacy=False):
    inherited = dict(os.environ)
    if job_id:
        inherited.update(_job(store, job_id).get("host_environment") or {})
    handoff_token = secrets.token_urlsafe(18)
    handoff_path = store.execution_lock_root / f"host-handoff-{handoff_token}.json"
    env = dict(inherited, CLI_BRIDGE_SUPERVISOR="1", CLI_BRIDGE_UPDATE_PROTOCOL="1",
               CLI_BRIDGE_UPDATE_STATE_FILE=str(store.state_path), CLI_BRIDGE_UPDATE_JOB_ID=job_id,
               CLI_BRIDGE_UPDATE_SUPERVISOR_PID=str(os.getpid()),
               CLI_BRIDGE_UPDATE_HANDOFF=str(handoff_path), CLI_BRIDGE_UPDATE_HANDOFF_TOKEN=handoff_token,
               CLI_BRIDGE_UPDATE_RUNNER_PATH=str(Path(__file__).resolve()),
               TCB_UPDATE_JOB_ID=job_id, TCB_UPDATE_HEALTH_TOKEN=token)
    command = _host_command(repo_root, python)
    if legacy:
        command = [python, str(Path(__file__).resolve()), "legacy-host", "--repo-root", str(repo_root),
                   "--state-file", str(store.state_path), "--job-id", job_id]
    child = subprocess.Popen(command, cwd=repo_root, env=env)
    child.update_handoff_path = handoff_path
    child.update_handoff_token = handoff_token
    # Do not persist the host PID: the store may be a pre-migration source whose
    # bytes storage migration verifies before cleanup, and host.lock already
    # proves host liveness.
    return child


def _store_after_host_exit(repo_root: Path, store, child, code: int):
    pointer = getattr(child, "update_handoff_path", None)
    if pointer is None or not Path(pointer).is_file():
        return store
    payload = json.loads(Path(pointer).read_text(encoding="utf-8"))
    try:
        host_pid = int(payload.get("host_pid"))
    except (TypeError, ValueError):
        host_pid = 0
    host_pid_matches = host_pid == child.pid
    if not host_pid_matches and host_pid > 0:
        # A platform launcher (for example a Windows venv redirector or a
        # POSIX wrapper/service entrypoint) can change the PID observed by
        # Popen while the handoff is written by the final interpreter. The
        # supervisor PID and one-time token still bind the handoff to this
        # supervisor and child launch, so accept that authenticated fallback.
        supervisor_pid = str(payload.get("supervisor_pid", "")).strip()
        # Older hosts do not emit supervisor_pid; their per-child token still
        # authenticates this handoff.
        host_pid_matches = not supervisor_pid or supervisor_pid == str(os.getpid())
    if not host_pid_matches or not secrets.compare_digest(
            str(payload.get("token", "")), child.update_handoff_token):
        raise RuntimeError("Host state handoff identity mismatch")
    current = open_store(repo_root, payload["state_file"])
    if code == UPDATE_EXIT_CODE and (current.read().get("job") or {}).get("job_id") != payload.get("job_id"):
        raise RuntimeError("Update handoff job identity mismatch")
    Path(pointer).unlink()
    return current


def _stop_child(child) -> None:
    # Only the child started by this supervisor is eligible for termination.
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=15)


def read_health(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"X-TCB-Update-Token": token})
    # Local probes must not be sent to configured HTTP proxies.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
        return json.load(response)


def verify_legacy_files(repo_root: Path, job: dict) -> None:
    package_path = Path(__file__).with_name("update_package.py")
    if not package_path.is_file():
        package_path = repo_root / "scripts/update_package.py"
    package = _load("update_package", package_path)
    actual = package.normalize_version((repo_root / "VERSION").read_text(encoding="utf-8-sig"))
    if actual != package.normalize_version(job["current_version"]):
        raise RuntimeError("Recovered VERSION does not match the previous release")
    hashes = job.get("previous_frontend_hashes") or {}
    if "front/dist/index.html" not in hashes:
        raise RuntimeError("No verified previous frontend entry is available")
    for relative, expected in hashes.items():
        path = (repo_root / relative).resolve()
        if not path.is_relative_to((repo_root / "front/dist").resolve()) or _hash(path) != expected:
            raise RuntimeError(f"Recovered frontend resource does not match: {relative}")
    base = job.get("frontend_base_path", job.get("health_base_path", ""))
    if "front/dist/build-info.json" in hashes:
        base = str(json.loads((repo_root / "front/dist/build-info.json").read_text(encoding="utf-8-sig")).get("base_path", base)).rstrip("/")

    class EntryAssets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag not in {"script", "link", "img"}:
                return
            attributes = dict(attrs)
            reference = attributes.get("src") or attributes.get("href") or ""
            url = urllib.parse.urlsplit(reference)
            if not reference or url.scheme or url.netloc or reference.startswith("#"):
                return
            relative = urllib.parse.unquote(url.path)
            if base and relative.startswith(base + "/"):
                relative = relative[len(base):]
            path = (repo_root / "front/dist" / relative.lstrip("/")).resolve()
            if not path.is_relative_to((repo_root / "front/dist").resolve()) or not path.is_file():
                raise RuntimeError(f"Recovered frontend entry references a missing resource: {reference}")
    EntryAssets().feed((repo_root / "front/dist/index.html").read_text(encoding="utf-8"))


def _instrument_legacy_health(module, repo_root: Path, job: dict) -> None:
    original = module.WebApiServer.health

    async def health(server, request):
        response = await original(server, request)
        payload = json.loads(response.text)
        token = os.environ.get("TCB_UPDATE_HEALTH_TOKEN", "")
        received = request.headers.get("X-TCB-Update-Token", "")
        if token and secrets.compare_digest(received, token):
            verify_legacy_files(repo_root, job)
            payload.update(version=job["current_version"], update_job_id=job["job_id"],
                           update_health_token=token, pid=os.getpid(), ready=payload.get("ok") is True)
            response.text = json.dumps(payload)
        return response
    module.WebApiServer.health = health


def legacy_host(repo_root: Path, store, job_id: str) -> int:
    """Run the old host with authenticated process identity on its existing health route."""
    job = _job(store, job_id)
    verify_legacy_files(repo_root, job)

    class HealthLoader(importlib.abc.Loader):
        def __init__(self, original):
            self.original = original

        def create_module(self, spec):
            return self.original.create_module(spec)

        def exec_module(self, module):
            self.original.exec_module(module)
            _instrument_legacy_health(module, repo_root, job)

    class HealthFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "bot.web.server":
                spec = importlib.machinery.PathFinder.find_spec(fullname, path)
                if spec is not None and spec.loader is not None:
                    spec.loader = HealthLoader(spec.loader)
                return spec
            return None

    sys.meta_path.insert(0, HealthFinder())
    sys.path.insert(0, str(repo_root))
    bootstrap = repo_root / "runtime/portable_bootstrap.py"
    if bootstrap.is_file():
        sys.argv = [str(bootstrap), "bot", str(repo_root)]
        runpy.run_path(str(bootstrap), run_name="__main__")
    else:
        sys.argv = ["bot"]
        runpy.run_module("bot", run_name="__main__")
    return 0


def wait_for_health(child, job: dict, version: str, token: str, *, legacy=False, recovering=False) -> dict:
    deadline = time.monotonic() + float(job.get("health_timeout", 90))
    error = "Health endpoint did not become ready"
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"Host exited before health confirmation (exit {child.returncode})")
        try:
            health = read_health(job["health_url"], token)
            instance = health.get("instance_id")
            if instance and instance not in job.setdefault("observed_instance_ids", []):
                job["observed_instance_ids"].append(instance)
            matches = (health.get("ok") is True and instance
                       and instance != job.get("previous_instance_id")
                       and instance not in job.get("rejected_instance_ids", [])
                       and health.get("base_path", "").rstrip("/") == job.get("health_base_path", "").rstrip("/"))
            if legacy:
                matches = (matches and health.get("ready") is True and health.get("pid") == child.pid
                           and str(health.get("version", "")).lstrip("vV") == str(version).lstrip("vV")
                           and health.get("update_job_id") == job["job_id"]
                           and secrets.compare_digest(str(health.get("update_health_token", "")), token)
                           and _pid_alive(child.pid))
            else:
                expected_build = ((job.get("health") or {}).get("build_id") if recovering
                                  else (job.get("manifest") or {}).get("commit"))
                matches = (matches and health.get("ready") is True
                           and str(health.get("version", "")).lstrip("vV") == str(version).lstrip("vV")
                           and health.get("update_job_id") == job["job_id"]
                           and secrets.compare_digest(str(health.get("update_health_token", "")), token)
                           and (not expected_build or health.get("build_id") == expected_build))
            if matches:
                return health
            error = "Health identity, version or readiness did not match the update"
        except (OSError, ValueError) as exc:
            error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Health confirmation timed out: {error}")


def _active_python(store, python: str) -> None:
    def mutate(state):
        state["python_executable"] = python
    store.mutate(mutate)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            status = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _effective_job(job: dict) -> dict:
    job = dict(job)
    health = job.get("health") or {}
    if health.get("host") and health.get("port"):
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(health["host"], health["host"])
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        base = str(health.get("base_path", job.get("health_base_path", ""))).rstrip("/")
        job.update(health_url=f'http://{host}:{int(health["port"])}{base}/api/health', health_base_path=base)
    return job


def _prune_finished_jobs(store) -> None:
    """Reclaim superseded job directories once this job is conclusively finished."""
    # Cleanup is best effort and must never turn a finished job into a failure.
    try:
        prune = getattr(store, "prune_job_dirs", None)
        if prune is not None:
            prune(runner_path=Path(__file__).resolve())
    except Exception as exc:
        print(f"[update] job cleanup skipped: {exc}", file=sys.stderr, flush=True)


def recover_job(repo_root: Path, store, job_id: str, error: str):
    job = _effective_job(_job(store, job_id))
    if job.get("phase") not in RECOVERY_PHASES:
        raise RuntimeError("Only an interrupted or failed application may be recovered")
    child = None
    _change(store, job_id, "rolling_back", error=error)
    try:
        if _pid_alive(int(job.get("child_pid") or 0)):
            raise RuntimeError("A previously launched host is still running; exit it before recovery")
        _, transaction_type = _helpers(repo_root)
        transaction = transaction_type(repo_root, Path(job["backup_dir"]))
        if (Path(job["backup_dir"]) / "journal.jsonl").exists() or job.get("transaction_started") is not False:
            transaction.recover()
        python = job["previous_python_executable"]
        token = secrets.token_urlsafe(32)
        legacy = bool(job.get("bootstrap_legacy"))
        if legacy:
            verify_legacy_files(repo_root, job)
        child = _start_host(repo_root, python, store, job_id, token, legacy)
        _change(store, job_id, "rolling_back", child_pid=child.pid)
        health = wait_for_health(child, job, job["current_version"], token,
                                 legacy=bool(job.get("bootstrap_legacy")), recovering=True)
        _active_python(store, python)
        _change(store, job_id, "rolled_back", result={"version": job["current_version"], "instance_id": health["instance_id"]})
        _prune_finished_jobs(store)
        return child, python
    except Exception as exc:
        _stop_child(child)
        _change(store, job_id, "recovery_required", error=f"{error}; recovery failed: {exc}",
                result={"recovery_command": recovery_command(repo_root, store, job)})
        raise


def recovery_command(repo_root: Path, store, job: dict) -> list[str]:
    return [job.get("control_python_executable", sys.executable), job.get("runner_path", str(Path(__file__).resolve())),
            "recover", "--repo-root", str(repo_root), "--state-file", str(store.state_path), "--job-id", job["job_id"]]


def apply_job(repo_root: Path, store, job_id: str):
    job = _effective_job(_job(store, job_id))
    if job.get("phase") != "waiting_restart":
        raise RuntimeError("Only an explicitly confirmed waiting_restart job may be applied")
    if Path(sys.executable).resolve().is_relative_to(repo_root):
        raise RuntimeError("Update executor Python must run outside the installation")
    _, transaction_type = _helpers(repo_root)
    transaction = transaction_type(repo_root, Path(job["backup_dir"]))
    child = None
    _change(store, job_id, "applying", transaction_started=False)
    try:
        if not isinstance(job.get("original_hashes"), dict):
            raise RuntimeError("Update job has no original file hashes; prepare the update again")
        for relative, expected in job.get("prepared_hashes", {}).items():
            if _hash(Path(job["staging_dir"]) / relative) != expected:
                raise RuntimeError(f"Prepared file changed: {relative}")
        transaction.apply(Path(job["staging_dir"]), job["files"], job.get("delete_paths", []),
                          expected_hashes=job["original_hashes"])
        _change(store, job_id, "awaiting_health", transaction_started=True)
        token = secrets.token_urlsafe(32)
        child = _start_host(repo_root, job["python_executable"], store, job_id, token)
        _change(store, job_id, "awaiting_health", child_pid=child.pid)
        health = wait_for_health(child, job, job["target_version"], token)
        # Keep backups until both health and state persistence have succeeded.
        _active_python(store, job["python_executable"])
        _change(store, job_id, "succeeded", error="", result={"version": job["target_version"], "instance_id": health["instance_id"]})
        try:
            transaction.commit()
        except Exception as exc:
            # Health and durable success already agree. Retain the backup if final
            # journal bookkeeping fails; the running new host remains authoritative.
            _change(store, job_id, "succeeded", error=f"Backup retained: {exc}")
        _prune_finished_jobs(store)
        return child, job["python_executable"]
    except Exception as exc:
        _stop_child(child)
        _change(store, job_id, "rolling_back", child_pid=0, rejected_instance_ids=job.get("observed_instance_ids", []))
        return recover_job(repo_root, store, job_id, str(exc))


def _verify_snapshot(job: dict) -> list[str]:
    runner = Path(job["runner_path"])
    for name, expected in job["runner_hashes"].items():
        if Path(name).name != name or _hash(runner.parent / name) != expected:
            raise RuntimeError("Recovery snapshot hash mismatch")
    return [job["control_python_executable"], str(runner)]


def supervise(repo_root: Path, store, python: str, *, action="supervise", job_id="") -> int:
    next_job = None
    with supervisor_lock(store):
        state = store.read()
        # supervisor_lock already verifies the installation's host.lock. A
        # host_pid left in older state files is ignored: the PID can be reused
        # by an unrelated process after the old host exits.
        job = state.get("job") or {}
        if action == "apply":
            child, python = apply_job(repo_root, store, job_id)
        elif action == "recover" or job.get("phase") in RECOVERY_PHASES:
            child, python = recover_job(repo_root, store, job_id or job["job_id"], "Interrupted update")
        elif job.get("phase") == "waiting_restart" and job.get("host_exit_confirmed"):
            next_job, child = job, None
        else:
            if job.get("phase") == "waiting_restart":
                _change(store, job["job_id"], "ready", error="Shutdown handoff was interrupted; confirm application again")
            child = _start_host(repo_root, python, store)
        while child is not None:
            code = child.wait()
            store = _store_after_host_exit(repo_root, store, child, code)
            if code == RESTART_EXIT_CODE:
                child = _start_host(repo_root, python, store)
                continue
            if code == UPDATE_EXIT_CODE:
                job = store.read().get("job") or {}
                if job.get("phase") != "waiting_restart" or not job.get("job_id"):
                    raise RuntimeError("Exit 76 without a confirmed update job")
                next_job = _change(store, job["job_id"], "waiting_restart", host_exit_confirmed=True, child_pid=0)
                break
            return code
    # Release the lifetime lock before handing control to the immutable job snapshot.
    command = _verify_snapshot(next_job)
    return subprocess.call([*command, "apply", "--repo-root", str(repo_root),
                            "--state-file", str(store.state_path), "--job-id", next_job["job_id"]])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launcher-info", "supervise", "apply", "recover", "legacy-host"))
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--state-file", default=os.environ.get("CLI_BRIDGE_UPDATE_STATE_FILE", ""))
    parser.add_argument("--job-id", default=os.environ.get("CLI_BRIDGE_UPDATE_JOB_ID", ""))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    try:
        store = open_store(root, args.state_file)
        if args.action == "legacy-host":
            return legacy_host(root, store, args.job_id)
        python = store.read().get("python_executable") or args.python
        if args.action == "launcher-info":
            pointer_dir = root / ".tcb" / "startup"
            pointer_dir.mkdir(parents=True, exist_ok=True)
            pointer = pointer_dir / "update-launcher.json"
            info = None
            if pointer.is_file():
                cached = json.loads(pointer.read_text(encoding="utf-8"))
                sources = {"update_runner.py": root / "scripts/update_runner.py",
                           "update_transaction.py": root / "scripts/update_transaction.py",
                           "update_package.py": root / "scripts/update_package.py",
                           "update_state.py": root / "bot/update_state.py"}
                if (Path(cached["control_python_executable"]).is_file()
                        and all(cached.get("runner_hashes", {}).get(name) == _hash(path) for name, path in sources.items())):
                    _verify_snapshot(cached)
                    info = cached
            if info is None:
                snapshot = control_root(root) / ("launcher-" + secrets.token_hex(8))
                info = freeze_runner(root, snapshot)
            info.update(state_file=str(store.state_path), python_executable=python)
            temporary = pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps(info), encoding="utf-8")
            os.replace(temporary, pointer)
            (pointer_dir / "update-control-python").write_text(info["control_python_executable"], encoding="utf-8")
            print(json.dumps(info))
            return 0
        return supervise(root, store, python, action=args.action, job_id=args.job_id)
    except Exception as exc:
        print(f"[update] {exc}", file=sys.stderr, flush=True)
        return RECOVERY_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
