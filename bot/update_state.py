"""Installation-scoped update journal; safe to copy beside the standalone runner."""
from __future__ import annotations

import hashlib
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import tempfile
import time


class UpdateConflict(RuntimeError):
    pass


def normalized_install_root(repo_root):
    return os.path.normcase(str(Path(repo_root).resolve()))


def installation_id(repo_root):
    return hashlib.sha256(normalized_install_root(repo_root).encode("utf-8")).hexdigest()[:24]


def execution_lock_root(repo_root):
    """A stable installation lock must survive application-data relocation."""
    base = os.environ.get("TCB_UPDATE_CONTROL_ROOT")
    if not base:
        base = str(Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "OrbitSafeClaw" / "updates")
    identity = hashlib.sha256(normalized_install_root(repo_root).encode()).hexdigest()[:20]
    directory = Path(base).resolve() / identity
    if directory.is_relative_to(Path(repo_root).resolve()):
        raise UpdateConflict("宿主锁与控制目录必须位于安装目录之外")
    return directory


def write_host_handoff(state_file, job_id=""):
    path_text = os.environ.get("CLI_BRIDGE_UPDATE_HANDOFF", "")
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state_file": str(Path(state_file).resolve()), "job_id": job_id,
               "host_pid": os.getpid(), "token": os.environ.get("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "")}
    fd, name = tempfile.mkstemp(prefix="handoff-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def begin_host_execution(repo_root):
    """Hold a host lease; direct launches also exclude an official supervisor."""
    directory = execution_lock_root(repo_root)
    official = (os.environ.get("CLI_BRIDGE_UPDATE_PROTOCOL") == "1"
                and os.environ.get("CLI_BRIDGE_UPDATE_SUPERVISOR_PID") == str(os.getppid()))
    stack = ExitStack()
    try:
        if not official:
            for name in ("CLI_BRIDGE_UPDATE_PROTOCOL", "CLI_BRIDGE_UPDATE_HANDOFF", "CLI_BRIDGE_UPDATE_HANDOFF_TOKEN",
                         "CLI_BRIDGE_UPDATE_SUPERVISOR_PID", "CLI_BRIDGE_UPDATE_JOB_ID", "CLI_BRIDGE_UPDATE_STATE_FILE",
                         "TCB_UPDATE_JOB_ID", "TCB_UPDATE_HEALTH_TOKEN"):
                os.environ.pop(name, None)
            stack.enter_context(FileLock(directory / "supervisor.lock", timeout=0))
        stack.enter_context(FileLock(directory / "host.lock", timeout=0))
        if official:
            # Resolve again in this fresh process: a storage migration may have moved state.
            store = UpdateStore(repo_root)
            os.environ["CLI_BRIDGE_UPDATE_STATE_FILE"] = str(store.state_path)
            write_host_handoff(store.state_path)
        return stack
    except BaseException:
        stack.close()
        raise


class FileLock:
    """OS-owned lock: process death releases ownership without deleting recovery files."""

    def __init__(self, path, timeout=30):
        self.path, self.timeout, self.handle = Path(path), timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        self.handle = handle
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    self.handle = None
                    raise UpdateConflict("更新操作正在由另一任务执行")
                time.sleep(0.025)

    def __exit__(self, *args):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class UpdateStore:
    def __init__(self, repo_root, state_root=None):
        self.repo_root = Path(repo_root).resolve()
        self.install_id = installation_id(self.repo_root)
        if state_root is None:
            from bot.runtime_paths import get_update_state_root
            state_root = get_update_state_root(self.repo_root)
        self.root = Path(state_root).resolve()
        self.state_path = self.root / "state.json"

    @property
    def execution_lock_root(self):
        return execution_lock_root(self.repo_root)

    def _read(self):
        if not self.state_path.exists():
            return {"schema_version": 1, "revision": 0, "install_id": self.install_id,
                    "install_root": normalized_install_root(self.repo_root),
                    "update_enabled": True, "last_check": {}, "job": None}
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if (state.get("schema_version") != 1 or state.get("install_id") != self.install_id
                or state.get("install_root") != normalized_install_root(self.repo_root)):
            raise UpdateConflict("更新状态与当前安装目录不匹配")
        if type(state.get("revision")) is not int:
            raise UpdateConflict("更新状态修订号无效")
        return state

    def read(self):
        with FileLock(self.root / "state.lock"):
            return self._read()

    def mutate(self, callback, expected_revision=None):
        with FileLock(self.root / "state.lock"):
            state = self._read()
            revision = state["revision"]
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != revision):
                raise UpdateConflict("更新状态已变化，请刷新后重试")
            callback(state)
            state.update(schema_version=1, revision=revision + 1, install_id=self.install_id,
                         install_root=normalized_install_root(self.repo_root))
            if isinstance(state.get("job"), dict):
                state["job"]["revision"] = state["revision"]
            fd, name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.state_path)
                if os.name != "nt":
                    directory = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                Path(name).unlink(missing_ok=True)
            return state

    def job_dir(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("更新任务 ID 无效")
        path = self.root / "jobs" / job_id
        if not path.resolve().is_relative_to(self.root):
            raise UpdateConflict("更新任务目录越界")
        return path
