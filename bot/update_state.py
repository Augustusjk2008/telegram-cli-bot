"""Installation-scoped update journal; safe to copy beside the standalone runner."""
from __future__ import annotations

import hashlib
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

logger = logging.getLogger(__name__)

JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
TERMINAL_JOB_PHASES = frozenset({"succeeded", "rolled_back", "failed", "cancelled"})
# Preparation phases own only their current job directory; any other phase
# (handoff, application, recovery or an unknown value) suspends pruning.
PREPARATION_JOB_PHASES = frozenset({"preparing", "ready"})
JOB_PRUNE_MIN_AGE_SECONDS = 24 * 3600
HOST_HANDOFF_ENV_NAMES = ("CLI_BRIDGE_UPDATE_HANDOFF", "CLI_BRIDGE_UPDATE_HANDOFF_TOKEN")
# The official host keeps its one-time handoff target here instead of in
# os.environ, which every agent, terminal and plugin child inherits.
_claimed_host_handoff: tuple[str, str] | None = None


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


def _claim_host_handoff():
    """Move the handoff target out of the environment inherited by children.

    A child that sees the path and token (for example a test run inside an
    agent session) can overwrite the live host's report, and the supervisor
    then rejects the next ordinary restart.
    """
    global _claimed_host_handoff
    path_text, token = (os.environ.pop(name, "") for name in HOST_HANDOFF_ENV_NAMES)
    _claimed_host_handoff = (path_text, token)


def _release_host_handoff():
    global _claimed_host_handoff
    _claimed_host_handoff = None


def write_host_handoff(state_file, job_id=""):
    if _claimed_host_handoff is not None:
        path_text, token = _claimed_host_handoff
    else:
        path_text, token = (os.environ.get(name, "") for name in HOST_HANDOFF_ENV_NAMES)
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_file": str(Path(state_file).resolve()),
        "job_id": job_id,
        "host_pid": os.getpid(),
        "supervisor_pid": os.environ.get("CLI_BRIDGE_UPDATE_SUPERVISOR_PID", ""),
        "token": token,
    }
    fd, name = tempfile.mkstemp(prefix="handoff-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _is_official_host(directory: Path) -> bool:
    """Recognize a host launched by the supervisor, including Windows venv hosts.

    A Windows venv executable can reparent the final interpreter process, so its
    ``os.getppid()`` may differ from the supervisor PID.  The supervisor's
    one-time handoff filename and token provide the fallback identity check.
    """
    if os.environ.get("CLI_BRIDGE_UPDATE_PROTOCOL") != "1":
        return False

    if os.environ.get("CLI_BRIDGE_UPDATE_SUPERVISOR_PID") == str(os.getppid()):
        return True

    handoff_text = os.environ.get("CLI_BRIDGE_UPDATE_HANDOFF", "").strip()
    token = os.environ.get("CLI_BRIDGE_UPDATE_HANDOFF_TOKEN", "").strip()
    if not handoff_text or not token:
        return False

    try:
        handoff_path = Path(handoff_text).resolve()
        return (
            handoff_path.parent == directory.resolve()
            and handoff_path.name == f"host-handoff-{token}.json"
            and not handoff_path.exists()
        )
    except (OSError, RuntimeError, ValueError):
        return False


def begin_host_execution(repo_root):
    """Hold a host lease; direct launches also exclude an official supervisor."""
    directory = execution_lock_root(repo_root)
    official = _is_official_host(directory)
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
            _claim_host_handoff()
            stack.callback(_release_host_handoff)
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
                    # ASCII-only JSON: Windows PowerShell 5.1 launchers may read
                    # this file with the ANSI code page (e.g. GBK).
                    json.dump(state, handle, ensure_ascii=True, indent=2)
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
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError("更新任务 ID 无效")
        path = self.root / "jobs" / job_id
        if not path.resolve().is_relative_to(self.root):
            raise UpdateConflict("更新任务目录越界")
        return path

    def prune_job_dirs(self, *, runner_path=None, lock_held=False, min_age_seconds=JOB_PRUNE_MIN_AGE_SECONDS):
        """Delete finished, unreferenced job directories; never raises.

        Callers must hold ``preparation.lock`` (``lock_held=True``) or let this
        method take it without waiting, so pruning cannot race a preparation.
        ``runner_path`` is the executor snapshot of the calling or supervising
        runner; a supervised host reads it from ``CLI_BRIDGE_UPDATE_RUNNER_PATH``.
        """
        try:
            if lock_held:
                return self._prune_job_dirs(runner_path, min_age_seconds)
            with FileLock(self.root / "preparation.lock", timeout=0):
                return self._prune_job_dirs(runner_path, min_age_seconds)
        except Exception as exc:
            logger.warning("Update job pruning skipped: %s", exc)
            return []

    def _prune_job_dirs(self, runner_path, min_age_seconds):
        jobs_root = self.root / "jobs"
        if _is_link(jobs_root) or not jobs_root.is_dir() or not self.state_path.is_file():
            return []
        runner = str(runner_path or os.environ.get("CLI_BRIDGE_UPDATE_RUNNER_PATH", ""))
        # A supervisor started before this contract may run from a job snapshot
        # that it loads helpers from later; its location is unknown.
        if os.environ.get("CLI_BRIDGE_UPDATE_PROTOCOL") == "1" and not runner:
            return []
        state = self.read()
        job = state.get("job")
        if job is not None and not isinstance(job, dict):
            return []
        current = (job or {}).get("job_id", "")
        phase = (job or {}).get("phase", "")
        if job and phase not in TERMINAL_JOB_PHASES | PREPARATION_JOB_PHASES:
            return []
        referenced = set()
        for value in [*_string_values(state), sys.executable, runner]:
            name = _job_name_for_path(jobs_root, value)
            if name:
                referenced.add(os.path.normcase(name))
        deleted = []
        now = time.time()
        for entry in sorted(os.scandir(jobs_root), key=lambda item: item.name):
            path = Path(entry.path)
            if (not JOB_ID_PATTERN.fullmatch(entry.name) or entry.name == current
                    or os.path.normcase(entry.name) in referenced
                    or _is_link(path) or not entry.is_dir(follow_symlinks=False)):
                continue
            try:
                if now - _latest_mtime(path) < min_age_seconds or not _transaction_released(path / "transaction"):
                    continue
                shutil.rmtree(path)
                deleted.append(entry.name)
            except OSError as exc:
                logger.warning("Cannot delete update job directory %s: %s", path, exc)
        return deleted


def _is_link(path):
    try:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            return True
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _string_values(value, depth=0):
    if depth > 16:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child, depth + 1)


def _job_name_for_path(jobs_root, value):
    """Return the job directory name containing an absolute path value."""
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return ""
    absolute = os.path.abspath(value)
    # Resolve only the parent: a POSIX venv python is a symlink to its base.
    candidates = {absolute, os.path.join(os.path.realpath(os.path.dirname(absolute)), os.path.basename(absolute))}
    roots = {os.path.abspath(jobs_root), os.path.realpath(jobs_root)}
    for candidate in candidates:
        for root in roots:
            try:
                relative = os.path.relpath(os.path.normcase(candidate), os.path.normcase(root))
            except ValueError:
                continue
            first = relative.split(os.sep, 1)[0]
            if first not in {"", ".", ".."} and not os.path.isabs(relative):
                return first
    return ""


def _latest_mtime(path):
    latest = path.lstat().st_mtime
    for child in os.scandir(path):
        latest = max(latest, child.stat(follow_symlinks=False).st_mtime)
    return latest


def _transaction_released(directory):
    """True only when no transaction exists or its journal ended conclusively."""
    if not os.path.lexists(directory):
        return True
    if _is_link(directory) or not directory.is_dir():
        return False
    journal = directory / "journal.jsonl"
    if not journal.is_file():
        return not any(directory.iterdir())
    final = ""
    for line in journal.read_bytes().splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return False
        if not isinstance(record, dict):
            return False
        if record.get("event") in {"begin", "applied_all", "committed", "rolled_back"}:
            final = record["event"]
    return final in {"committed", "rolled_back"}
