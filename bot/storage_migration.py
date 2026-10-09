from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from bot import runtime_paths


STORAGE_SCHEMA = 1
DATASET_IDENTITY = "tcb"
TARGET_MANIFEST_NAME = ".tcb-storage-manifest.json"
STORAGE_LOCK_NAME = ".storage.lock"
_CHUNK_BYTES = 1024 * 1024
_JSON_REFERENCE_KEYS = {
    "path",
    "root",
    "cwd",
    "working_dir",
    "workingDir",
    "data_dir",
    "dataDir",
    "directory",
    "workspace",
    "workspace_dir",
    "workspaceDir",
    "token_file",
    "tokenFile",
    "config_path",
    "configPath",
    "launcher_path",
    "launcherPath",
}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


class StorageMigrationError(RuntimeError):
    """A migration cannot continue without risking data integrity."""


MigrationError = StorageMigrationError


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().absolute().resolve()


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.stat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & 0x4000)  # FILE_ATTRIBUTE_REPARSE_POINT


def _has_link_ancestor(path: Path) -> bool:
    current = path
    while True:
        if _is_link(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _filesystem_name_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _validate_component(name: str) -> None:
    if not name or name in {".", ".."}:
        raise StorageMigrationError("存储路径包含无效名称")
    if any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        raise StorageMigrationError(f"存储路径包含跨平台不安全名称: {name}")
    if name[-1] in {".", " "}:
        raise StorageMigrationError(f"存储路径包含 Windows 不安全名称: {name}")
    if name.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise StorageMigrationError(f"存储路径包含 Windows 保留名称: {name}")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class StorageExclusiveGuard:
    """A process and cross-process exclusive lock for the TCB data set."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = _canonical(path or (runtime_paths._legacy_tcb_home_root() / STORAGE_LOCK_NAME))
        self._local_lock = threading.RLock()
        self._handle: Any | None = None
        self._depth = 0

    def acquire(self, timeout: float | None = 0.0) -> "StorageExclusiveGuard":
        with self._local_lock:
            if self._handle is not None:
                self._depth += 1
                return self
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            started = time.monotonic()
            while True:
                try:
                    self._try_lock(handle)
                    self._handle = handle
                    self._depth = 1
                    return self
                except (BlockingIOError, OSError) as exc:
                    if timeout is None or time.monotonic() - started < max(0.0, timeout):
                        time.sleep(0.05)
                        continue
                    handle.close()
                    raise StorageMigrationError(f"无法取得 TCB 存储锁: {self.path}") from exc

    def release(self) -> None:
        with self._local_lock:
            if self._handle is None:
                return
            self._depth -= 1
            if self._depth > 0:
                return
            handle = self._handle
            self._handle = None
            try:
                self._unlock(handle)
            finally:
                handle.close()

    def __enter__(self) -> "StorageExclusiveGuard":
        return self.acquire()

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.release()

    @staticmethod
    def _try_lock(handle: Any) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: Any) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


StorageLock = StorageExclusiveGuard


def _source_specs() -> list[dict[str, str]]:
    home = _canonical(runtime_paths._legacy_tcb_home_root())
    return [
        {
            "kind": "app_data",
            "label": "app-data",
            "path": str(_canonical(runtime_paths.get_legacy_app_data_root())),
            "targetRelativeRoot": runtime_paths.APP_DATA_DIR_NAME,
        },
        {"kind": "chat_history", "label": "chat-history", "path": str(home / "chat-history"), "targetRelativeRoot": "chat-history"},
        {"kind": "chat_attachments", "label": "chat-attachments", "path": str(home / "chat-attachments"), "targetRelativeRoot": "chat-attachments"},
        {"kind": "plugins", "label": "plugins", "path": str(home / "plugins"), "targetRelativeRoot": "plugins"},
        {"kind": "plugin_backups", "label": "plugin-backups", "path": str(home / ".plugin-backups"), "targetRelativeRoot": ".plugin-backups"},
        {"kind": "cluster_mcp", "label": "cluster-mcp", "path": str(home / "cluster-mcp"), "targetRelativeRoot": "cluster-mcp"},
    ]


def _path_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _relative_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return "/".join(relative.parts)


def _safe_manifest_relative(relative: str) -> tuple[str, ...]:
    normalized = str(relative or "")
    if not normalized:
        return ()
    candidate = normalized.replace("\\", "/")
    parts = tuple(candidate.split("/"))
    if any(not part or part in {".", ".."} for part in parts):
        raise StorageMigrationError("迁移清单包含越界路径")
    if Path(candidate).is_absolute() or (len(parts[0]) >= 2 and parts[0][1] == ":"):
        raise StorageMigrationError("迁移清单包含绝对路径")
    for part in parts:
        _validate_component(part)
    return parts


def _walk_source(root: Path, *, hash_files: bool) -> tuple[list[dict[str, Any]], int]:
    if not root.exists():
        return [], 0
    if _has_link_ancestor(root):
        raise StorageMigrationError(f"源目录包含符号链接或 junction: {root}")
    if not root.is_dir():
        raise StorageMigrationError(f"源路径不是目录: {root}")

    entries: list[dict[str, Any]] = [
        {
            "relativePath": "",
            "type": "dir",
            "size": 0,
            "sha256": "",
            "mode": stat.S_IMODE(root.stat().st_mode),
        }
    ]
    total_bytes = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(os.scandir(directory), key=lambda item: _filesystem_name_key(item.name))
        except OSError as exc:
            raise StorageMigrationError(f"无法读取源目录: {directory}") from exc
        aliases: set[str] = set()
        for child in children:
            _validate_component(child.name)
            alias = _filesystem_name_key(child.name)
            if alias in aliases:
                raise StorageMigrationError(f"源目录存在大小写或 Unicode 重名: {directory}")
            aliases.add(alias)
            child_path = Path(child.path)
            if _is_link(child_path):
                raise StorageMigrationError(f"源数据包含符号链接或 junction: {child_path}")
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise StorageMigrationError(f"无法读取源文件: {child_path}") from exc
            relative = _relative_path(root, child_path)
            if stat.S_ISDIR(child_stat.st_mode):
                entries.append(
                    {
                        "relativePath": relative,
                        "type": "dir",
                        "size": 0,
                        "sha256": "",
                        "mode": stat.S_IMODE(child_stat.st_mode),
                    }
                )
                stack.append(child_path)
            elif stat.S_ISREG(child_stat.st_mode):
                size = int(child_stat.st_size)
                entries.append(
                    {
                        "relativePath": relative,
                        "type": "file",
                        "size": size,
                        "sha256": _hash_file(child_path) if hash_files else "",
                        "mode": stat.S_IMODE(child_stat.st_mode),
                    }
                )
                total_bytes += size
            else:
                raise StorageMigrationError(f"源数据包含不支持的文件类型: {child_path}")
    entries.sort(key=lambda item: (item["relativePath"].count("/"), item["relativePath"].casefold(), item["type"]))
    return entries, total_bytes


def _fingerprint(specs: list[dict[str, str]], entries_by_label: dict[str, list[dict[str, Any]]]) -> str:
    payload = []
    for spec in specs:
        payload.append(
            {
                "label": spec["label"],
                "path": spec["path"],
                "targetRelativeRoot": spec["targetRelativeRoot"],
                "exists": bool(entries_by_label.get(spec["label"])),
                "entries": entries_by_label.get(spec["label"], []),
            }
        )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sqlite_paths(specs: list[dict[str, str]], entries_by_label: dict[str, list[dict[str, Any]]]) -> list[Path]:
    paths: list[Path] = []
    for spec in specs:
        root = Path(spec["path"])
        for entry in entries_by_label.get(spec["label"], []):
            if entry["type"] != "file" or entry["relativePath"].lower().endswith(("-wal", "-shm")):
                continue
            suffix = Path(entry["relativePath"]).suffix.lower()
            if suffix in {".sqlite", ".sqlite3", ".db"}:
                paths.append(root / Path(*entry["relativePath"].split("/")))
    return paths


def _validate_sqlite(path: Path, *, checkpoint: bool) -> None:
    try:
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise StorageMigrationError(f"SQLite 完整性校验失败: {path}")
            if checkpoint:
                # PASSIVE never deletes WAL frames.  The caller has already
                # stopped writers; the sidecar remains part of the manifest.
                connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        finally:
            connection.close()
    except StorageMigrationError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise StorageMigrationError(f"SQLite 数据库不可迁移: {path}") from exc


def _public_source(
    spec: dict[str, str],
    entries: list[dict[str, Any]],
    *,
    size_pending: bool = False,
) -> dict[str, Any]:
    result = {
        "kind": spec["kind"],
        "label": spec["label"],
        "path": spec["path"],
        "bytes": sum(int(entry["size"]) for entry in entries if entry["type"] == "file"),
        "fileCount": sum(1 for entry in entries if entry["type"] == "file"),
        "exists": bool(entries),
    }
    if size_pending:
        result["sizePending"] = True
    return result


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageMigrationError(f"迁移状态文件无效: {path}") from exc
    if not isinstance(value, dict):
        raise StorageMigrationError(f"迁移状态文件格式无效: {path}")
    return value


class StorageMigrationService:
    """Plan and execute an all-or-nothing TCB data-root relocation."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = _canonical(repo_root)
        runtime_paths.freeze_active_path_resolution()
        self._home_root = _canonical(runtime_paths._legacy_tcb_home_root())
        self.storage_guard = StorageExclusiveGuard(self._home_root / STORAGE_LOCK_NAME)
        self.guard = self.storage_guard
        self._plans: dict[str, dict[str, Any]] = {}

    def snapshot(self) -> dict[str, Any]:
        with self.storage_guard:
            locator = runtime_paths.read_storage_locator()
            journal = self._read_journal()
            specs = _source_specs()
            blockers: list[str] = []
            existing_sources: set[str] = set()
            for spec in specs:
                root = Path(spec["path"]).expanduser().absolute()
                if not root.exists():
                    continue
                if _is_link(root):
                    blockers.append(f"源目录包含符号链接或 junction: {root}")
                    continue
                if not root.is_dir():
                    blockers.append(f"源路径不是目录: {root}")
                    continue
                if not os.access(root, os.R_OK | os.X_OK):
                    blockers.append(f"源目录不可读: {root}")
                    continue
                existing_sources.add(spec["label"])
            if locator is not None:
                blockers.append("TCB 存储已提交迁移，需在新进程中继续清理")
            elif not existing_sources:
                blockers.append("未发现可迁移的 TCB 数据")

            blockers.extend(self._source_root_blockers(specs, deep=False))
            warnings = self._excluded_warnings()
            current_root = (
                str(locator.get("appDataRoot"))
                if locator is not None
                else str(runtime_paths.get_legacy_app_data_root())
            )
            sources = [
                _public_source(
                    spec,
                    [{"type": "dir", "size": 0}] if spec["label"] in existing_sources else [],
                    size_pending=spec["label"] in existing_sources,
                )
                for spec in specs
            ]
            return {
                "currentRoot": current_root,
                "sources": sources,
                "totalBytes": 0,
                "sizePending": bool(existing_sources),
                "canMigrate": locator is None and not blockers,
                "blockers": sorted(set(blockers)),
                "warnings": warnings,
                "migration": self._public_job(journal) if journal and journal.get("state") in self._public_states() else None,
            }

    def preview(self, target_root: str) -> dict[str, Any]:
        with self.storage_guard:
            locator = runtime_paths.read_storage_locator()
            if locator is not None:
                raise StorageMigrationError("TCB 存储已经提交迁移")
            specs = _source_specs()
            blockers: list[str] = []
            try:
                target = self._validate_target(target_root, specs)
            except StorageMigrationError as exc:
                target = _canonical(target_root)
                blockers.append(str(exc))

            entries_by_label: dict[str, list[dict[str, Any]]] = {}
            total_bytes = 0
            for spec in specs:
                try:
                    entries, size = _walk_source(Path(spec["path"]), hash_files=True)
                    entries_by_label[spec["label"]] = entries
                    total_bytes += size
                except StorageMigrationError as exc:
                    entries_by_label[spec["label"]] = []
                    blockers.append(str(exc))
            blockers.extend(self._source_root_blockers(specs))
            if not any(entries_by_label.values()):
                blockers.append("未发现可迁移的 TCB 数据")
            for path in _sqlite_paths(specs, entries_by_label):
                try:
                    _validate_sqlite(path, checkpoint=True)
                except StorageMigrationError as exc:
                    blockers.append(str(exc))
            free_bytes = self._free_bytes(target)
            required_bytes = total_bytes
            if free_bytes < required_bytes:
                blockers.append(f"目标磁盘空间不足: 需要 {required_bytes} 字节，可用 {free_bytes} 字节")

            plan_id = uuid.uuid4().hex
            entries = self._plan_entries(specs, entries_by_label, target)
            plan = {
                "id": plan_id,
                "targetRoot": str(target),
                "sourceSpecs": specs,
                "entries": entries,
                "sourceFingerprint": _fingerprint(specs, entries_by_label),
                "totalBytes": total_bytes,
                "requiredBytes": required_bytes,
                "freeBytes": free_bytes,
                "blockers": sorted(set(blockers)),
            }
            self._plans[plan_id] = plan
            self._write_journal(self._journal_payload(plan, "preview", "preview"))
            return {
                "id": plan_id,
                "targetRoot": str(target),
                "sources": [_public_source(spec, entries_by_label.get(spec["label"], [])) for spec in specs],
                "totalBytes": total_bytes,
                "requiredBytes": required_bytes,
                "freeBytes": free_bytes,
                "warnings": self._excluded_warnings(),
                "blockers": sorted(set(blockers)),
            }

    def begin(self, plan_id: str) -> dict[str, Any]:
        with self.storage_guard:
            locator = runtime_paths.read_storage_locator()
            if locator is not None:
                raise StorageMigrationError("TCB 存储已经提交迁移")
            plan = self._load_plan(plan_id)
            if plan["blockers"]:
                raise StorageMigrationError("迁移计划存在阻断项: " + "; ".join(plan["blockers"]))
            self._refresh_plan_entries(plan)
            journal = self._journal_payload(plan, "stopping", "stopping")
            self._write_journal(journal)
            return self._public_job(journal)

    def execute(self, plan_id: str) -> dict[str, Any]:
        with self.storage_guard:
            plan = self._load_plan(plan_id)
            journal = self._read_journal()
            if not journal or journal.get("id") != plan_id or journal.get("state") != "stopping":
                raise StorageMigrationError("迁移必须先通过 begin 进入 stopping 状态")
            try:
                self._refresh_plan_entries(plan)
                target = self._validate_target(plan["targetRoot"], plan["sourceSpecs"])
                copying = self._journal_payload(plan, "copying", "copying")
                self._write_journal(copying)
                target.mkdir(parents=True, exist_ok=True)
                self._copy_entries(plan, target)
                self._rewrite_structured_paths(plan, target)
                verifying = self._journal_payload(
                    plan,
                    "verifying",
                    "verifying",
                    progress_bytes=int(plan["totalBytes"]),
                )
                self._write_journal(verifying)
                manifest = self._build_manifest(plan, target)
                _atomic_write_json(target / TARGET_MANIFEST_NAME, manifest)
                self._verify_target_manifest(target, manifest)
                self._verify_sources_unchanged(plan, allow_missing=False)
                locator = self._build_locator(plan, target)
                _atomic_write_json(runtime_paths.get_storage_locator_path(), locator)
                awaiting = self._journal_payload(
                    plan,
                    "awaiting_restart",
                    "committed",
                    progress_bytes=int(plan["totalBytes"]),
                )
                self._write_journal(awaiting)
                return self._public_job(awaiting)
            except Exception as exc:
                failed = self._journal_payload(plan, "failed", "failed", error=str(exc))
                self._write_journal(failed)
                raise

    def finalize_startup(self) -> dict[str, Any]:
        with self.storage_guard:
            locator = runtime_paths.read_storage_locator()
            journal = self._read_journal()
            if locator is None:
                if journal and journal.get("state") in {"stopping", "copying", "verifying", "failed"}:
                    return self._public_job(journal)
                raise StorageMigrationError("没有已提交的 TCB 迁移可完成")
            try:
                target = _canonical(str(locator["targetRoot"]))
                manifest_value = locator.get("manifestPath")
                manifest_path = (
                    _canonical(str(manifest_value))
                    if isinstance(manifest_value, str) and manifest_value.strip()
                    else target / TARGET_MANIFEST_NAME
                )
                if manifest_path != target / TARGET_MANIFEST_NAME:
                    raise StorageMigrationError("迁移清单必须位于目标根目录")
                manifest = _read_json(manifest_path)
                if manifest is None:
                    raise StorageMigrationError(f"迁移目标缺少清单: {manifest_path}")
                self._verify_target_manifest(target, manifest)
                cleanup = self._journal_from_locator(locator, journal, "cleanup_pending", "cleanup")
                self._write_journal(cleanup)
                self._verify_sources_unchanged_from_manifest(manifest, allow_missing=True)
                deleted_bytes = self._cleanup_sources(manifest, cleanup)
                completed = self._journal_from_locator(
                    locator,
                    cleanup,
                    "completed",
                    "completed",
                    deleted_bytes=deleted_bytes,
                )
                self._write_journal(completed)
                locator["state"] = "completed"
                _atomic_write_json(runtime_paths.get_storage_locator_path(), locator)
                return self._public_job(completed)
            except Exception as exc:
                error_job = self._journal_from_locator(
                    locator,
                    self._read_journal() or journal,
                    "cleanup_pending",
                    "cleanup",
                    error=str(exc),
                )
                self._write_journal(error_job)
                locator["state"] = "cleanup_pending"
                _atomic_write_json(runtime_paths.get_storage_locator_path(), locator)
                raise

    def retry_cleanup(self) -> dict[str, Any]:
        return self.finalize_startup()

    @staticmethod
    def _public_states() -> set[str]:
        return {"stopping", "copying", "verifying", "awaiting_restart", "cleanup_pending", "completed", "failed"}

    def _read_journal(self) -> dict[str, Any] | None:
        path = runtime_paths.get_storage_journal_path()
        journal = _read_json(path)
        if journal is None:
            return None
        try:
            journal_schema = int(journal.get("schema", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise StorageMigrationError("TCB 迁移日志版本无效") from exc
        if journal_schema != STORAGE_SCHEMA or journal.get("datasetIdentity") != DATASET_IDENTITY:
            raise StorageMigrationError("TCB 迁移日志版本或数据集不匹配")
        return journal

    def _write_journal(self, journal: dict[str, Any]) -> None:
        _atomic_write_json(runtime_paths.get_storage_journal_path(), journal)

    def _source_root_blockers(self, specs: list[dict[str, str]], *, deep: bool = True) -> list[str]:
        blockers: list[str] = []
        roots: list[Path] = []
        for spec in specs:
            lexical_root = Path(spec["path"]).expanduser().absolute()
            root = _canonical(lexical_root)
            if root in roots:
                blockers.append(f"源目录重复: {root}")
            for other in roots:
                if _path_overlap(root, other):
                    blockers.append(f"源目录互相重叠: {root}")
            roots.append(root)
            if lexical_root.exists() and _is_link(lexical_root):
                blockers.append(f"源目录包含符号链接或 junction: {lexical_root}")
            if root.exists() and not root.is_dir():
                blockers.append(f"源路径不是目录: {root}")
            if root.exists() and not os.access(root, os.R_OK | os.X_OK):
                blockers.append(f"源目录不可读: {root}")
            for entry in root.rglob("pyvenv.cfg") if deep and root.exists() and root.is_dir() and not _has_link_ancestor(root) else ():
                if any(part.casefold() in {"venv", ".venv"} for part in entry.relative_to(root).parts[:-1]):
                    blockers.append(f"检测到无法安全搬迁的虚拟环境: {entry.parent}")
                    break
        return blockers

    def _excluded_warnings(self) -> list[str]:
        warnings: list[str] = []
        known = {
            "orbit-safe-claw",
            "chat-history",
            "chat-attachments",
            "plugins",
            ".plugin-backups",
            "cluster-mcp",
            "bin",
            runtime_paths.STORAGE_LOCATOR_FILENAME,
            runtime_paths.STORAGE_JOURNAL_FILENAME,
            STORAGE_LOCK_NAME,
        }
        if self._home_root.exists():
            for child in sorted(self._home_root.iterdir(), key=lambda item: item.name.casefold()):
                if child.name not in known:
                    warnings.append(f"未识别的 ~/.tcb 项已排除: {child.name}")
        repo_plugins = self.repo_root / ".plugins"
        if repo_plugins.exists():
            warnings.append(f"仓库插件目录已排除: {repo_plugins}")
        cache_candidates = [
            Path.home() / ".cache" / "cli-bridge" / "updates",
        ]
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            cache_candidates.append(Path(local_app_data) / "cli-bridge" / "updates")
        for cache in cache_candidates:
            if cache.exists():
                warnings.append(f"更新缓存已排除: {cache}")
        return warnings

    def _validate_target(self, target_root: str | Path, specs: list[dict[str, str]]) -> Path:
        target = _canonical(target_root)
        if _has_link_ancestor(Path(target_root).expanduser().absolute()):
            raise StorageMigrationError("目标路径包含符号链接或 junction")
        if target.parent == target:
            raise StorageMigrationError("不能使用文件系统根作为迁移目标")
        home = _canonical(Path.home())
        if target == home:
            raise StorageMigrationError("不能使用用户主目录作为迁移目标")
        if target == self.repo_root or target in self.repo_root.parents:
            raise StorageMigrationError("不能使用仓库或其上级目录作为迁移目标")
        if self.repo_root in target.parents:
            raise StorageMigrationError("不能把目标放在仓库工作区内")
        source_paths = [_canonical(spec["path"]) for spec in specs]
        if any(_path_overlap(target, source) for source in source_paths):
            raise StorageMigrationError("迁移目标与源目录重叠")
        for index, source in enumerate(source_paths):
            if any(_path_overlap(source, other) for other in source_paths[index + 1 :]):
                raise StorageMigrationError("源目录互相重叠")
        if target.exists():
            if not target.is_dir() or _is_link(target):
                raise StorageMigrationError("迁移目标不是安全目录")
            if not os.access(target, os.W_OK | os.X_OK):
                raise StorageMigrationError("迁移目标目录不可写")
            try:
                if any(target.iterdir()):
                    raise StorageMigrationError("迁移目标必须是空目录")
            except OSError as exc:
                raise StorageMigrationError("无法读取迁移目标") from exc
        elif not os.access(target.parent, os.W_OK | os.X_OK):
            raise StorageMigrationError("迁移目标父目录不可写")
        return target

    @staticmethod
    def _free_bytes(target: Path) -> int:
        parent = target if target.exists() else target.parent
        while not parent.exists() and parent.parent != parent:
            parent = parent.parent
        try:
            return int(shutil.disk_usage(str(parent)).free)
        except OSError:
            return 0

    def _plan_entries(
        self,
        specs: list[dict[str, str]],
        entries_by_label: dict[str, list[dict[str, Any]]],
        target: Path,
    ) -> list[dict[str, Any]]:
        del target
        entries: list[dict[str, Any]] = []
        for spec in specs:
            for entry in entries_by_label.get(spec["label"], []):
                item = dict(entry)
                relative = str(entry["relativePath"])
                item.update(
                    {
                        "sourceLabel": spec["label"],
                        "sourceRoot": spec["path"],
                        "targetRelativePath": "/".join(
                            part for part in (spec["targetRelativeRoot"], relative) if part
                        ),
                        "sourceSha256": entry["sha256"],
                    }
                )
                entries.append(item)
        return entries

    def _journal_payload(
        self,
        plan: dict[str, Any],
        state: str,
        phase: str,
        *,
        progress_bytes: int = 0,
        deleted_bytes: int = 0,
        error: str = "",
    ) -> dict[str, Any]:
        return {
            "schema": STORAGE_SCHEMA,
            "datasetIdentity": DATASET_IDENTITY,
            "id": plan["id"],
            "state": state,
            "phase": phase,
            "targetRoot": plan["targetRoot"],
            "sourceSpecs": plan["sourceSpecs"],
            "sourceFingerprint": plan["sourceFingerprint"],
            "totalBytes": int(plan["totalBytes"]),
            "requiredBytes": int(plan["requiredBytes"]),
            "progressBytes": int(progress_bytes),
            "deletedBytes": int(deleted_bytes),
            "error": error,
            "manifestPath": str(Path(plan["targetRoot"]) / TARGET_MANIFEST_NAME),
            "plan": {
                "id": plan["id"],
                "targetRoot": plan["targetRoot"],
                "sourceSpecs": plan["sourceSpecs"],
                "sourceFingerprint": plan["sourceFingerprint"],
                "totalBytes": plan["totalBytes"],
                "requiredBytes": plan["requiredBytes"],
                "freeBytes": plan["freeBytes"],
                "blockers": plan["blockers"],
            },
        }

    def _load_plan(self, plan_id: str) -> dict[str, Any]:
        normalized_id = str(plan_id or "").strip()
        if normalized_id in self._plans:
            return self._plans[normalized_id]
        journal = self._read_journal()
        plan = journal.get("plan") if journal else None
        if not isinstance(plan, dict) or str(plan.get("id")) != normalized_id:
            raise StorageMigrationError("迁移计划不存在或已失效")
        source_specs = plan.get("sourceSpecs")
        if not isinstance(source_specs, list) or any(not isinstance(item, dict) for item in source_specs):
            raise StorageMigrationError("迁移计划源目录无效")
        restored = dict(plan)
        restored["sourceSpecs"] = [dict(item) for item in source_specs]
        restored.setdefault("blockers", [])
        self._plans[normalized_id] = restored
        return restored

    def _refresh_plan_entries(self, plan: dict[str, Any]) -> None:
        entries_by_label: dict[str, list[dict[str, Any]]] = {}
        total_bytes = 0
        for spec in plan["sourceSpecs"]:
            entries, size = _walk_source(Path(spec["path"]), hash_files=True)
            entries_by_label[spec["label"]] = entries
            total_bytes += size
        for path in _sqlite_paths(plan["sourceSpecs"], entries_by_label):
            _validate_sqlite(path, checkpoint=True)
        current_fingerprint = _fingerprint(plan["sourceSpecs"], entries_by_label)
        if current_fingerprint != plan["sourceFingerprint"]:
            raise StorageMigrationError("确认迁移后源数据发生变化，请重新预览")
        plan["entries"] = self._plan_entries(plan["sourceSpecs"], entries_by_label, Path(plan["targetRoot"]))
        plan["totalBytes"] = total_bytes

    def _copy_entries(self, plan: dict[str, Any], target: Path) -> None:
        entries = plan["entries"]
        for spec in plan["sourceSpecs"]:
            source = Path(spec["path"])
            if source.exists():
                destination = target / Path(*spec["targetRelativeRoot"].split("/"))
                self._ensure_target_directory(destination)
                try:
                    shutil.copystat(source, destination, follow_symlinks=False)
                except OSError as exc:
                    raise StorageMigrationError(f"无法保留目录属性: {destination}") from exc
        progress = 0
        for entry in sorted(entries, key=lambda item: (item["type"] != "dir", item["targetRelativePath"].casefold())):
            source = Path(entry["sourceRoot"]) / Path(*entry["relativePath"].split("/")) if entry["relativePath"] else Path(entry["sourceRoot"])
            destination = target / Path(*entry["targetRelativePath"].split("/"))
            if entry["type"] == "dir":
                self._ensure_target_directory(destination)
                try:
                    shutil.copystat(source, destination, follow_symlinks=False)
                except OSError as exc:
                    raise StorageMigrationError(f"无法保留目录属性: {destination}") from exc
                continue
            if _has_link_ancestor(source) or not source.is_file():
                raise StorageMigrationError(f"复制前源文件不可用: {source}")
            self._ensure_target_directory(destination.parent)
            shutil.copyfile(source, destination)
            try:
                shutil.copystat(source, destination, follow_symlinks=False)
            except OSError as exc:
                raise StorageMigrationError(f"无法保留文件属性: {destination}") from exc
            if destination.stat().st_size != int(entry["size"]) or _hash_file(destination) != entry["sourceSha256"]:
                raise StorageMigrationError(f"复制校验失败: {destination}")
            progress += int(entry["size"])
            journal = self._read_journal()
            if journal is not None:
                journal["progressBytes"] = progress
                self._write_journal(journal)

    @staticmethod
    def _ensure_target_directory(path: Path) -> None:
        if _has_link_ancestor(path):
            raise StorageMigrationError(f"目标路径包含符号链接或 junction: {path}")
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir() or _is_link(path):
            raise StorageMigrationError(f"目标目录不可用: {path}")

    def _rewrite_structured_paths(self, plan: dict[str, Any], target: Path) -> None:
        mappings = [
            (_canonical(spec["path"]), target / Path(*spec["targetRelativeRoot"].split("/")))
            for spec in plan["sourceSpecs"]
        ]
        for entry in plan["entries"]:
            if entry["type"] != "file" or not str(entry["relativePath"]).lower().endswith(".json"):
                continue
            path = target / Path(*entry["targetRelativePath"].split("/"))
            try:
                if path.stat().st_size > 1024 * 1024:
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            changed, rewritten = self._rewrite_json_value(payload, mappings, depth=0, nodes=[0])
            if changed:
                _atomic_write_json(path, rewritten)

    def _rewrite_json_value(
        self,
        value: Any,
        mappings: list[tuple[Path, Path]],
        *,
        depth: int,
        nodes: list[int],
        key: str = "",
    ) -> tuple[bool, Any]:
        nodes[0] += 1
        if depth > 8 or nodes[0] > 10000:
            return False, value
        if isinstance(value, dict):
            changed = False
            output: dict[str, Any] = {}
            for name, child in value.items():
                child_changed, child_value = self._rewrite_json_value(
                    child, mappings, depth=depth + 1, nodes=nodes, key=str(name)
                )
                changed = changed or child_changed
                output[name] = child_value
            return changed, output
        if isinstance(value, list):
            changed = False
            output = []
            for child in value:
                child_changed, child_value = self._rewrite_json_value(
                    child, mappings, depth=depth + 1, nodes=nodes, key=key
                )
                changed = changed or child_changed
                output.append(child_value)
            return changed, output
        if isinstance(value, str) and key in _JSON_REFERENCE_KEYS:
            mapped = self._map_structured_path(value, mappings)
            if mapped != value:
                return True, mapped
        return False, value

    @staticmethod
    def _map_structured_path(value: str, mappings: list[tuple[Path, Path]]) -> str:
        if not os.path.isabs(os.path.expanduser(value)):
            return value
        try:
            candidate = _canonical(value)
        except (OSError, ValueError):
            return value
        for source, target in mappings:
            if candidate == source or source in candidate.parents:
                relative = candidate.relative_to(source)
                return str(target / relative)
        return value

    def _build_manifest(self, plan: dict[str, Any], target: Path) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for entry in plan["entries"]:
            item = dict(entry)
            if item["type"] == "file":
                destination = target / Path(*_safe_manifest_relative(str(item["targetRelativePath"])))
                item["targetSha256"] = _hash_file(destination)
                item["targetSize"] = destination.stat().st_size
            entries.append(item)
        return {
            "schema": STORAGE_SCHEMA,
            "datasetIdentity": DATASET_IDENTITY,
            "migrationId": plan["id"],
            "targetRoot": str(target),
            "sourceRoots": [spec["path"] for spec in plan["sourceSpecs"]],
            "sourceSpecs": plan["sourceSpecs"],
            "fileCount": sum(1 for entry in entries if entry["type"] == "file"),
            "totalBytes": sum(int(entry.get("size", 0) or 0) for entry in entries if entry["type"] == "file"),
            "entries": entries,
        }

    def _verify_target_manifest(self, target: Path, manifest: dict[str, Any]) -> None:
        if int(manifest.get("schema", 0) or 0) != STORAGE_SCHEMA or manifest.get("datasetIdentity") != DATASET_IDENTITY:
            raise StorageMigrationError("目标清单版本或数据集不匹配")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise StorageMigrationError("目标清单缺少 entries")
        if not target.is_dir() or _is_link(target):
            raise StorageMigrationError(f"迁移目标不可用: {target}")
        expected: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise StorageMigrationError("目标清单条目无效")
            relative = str(entry.get("targetRelativePath") or "")
            path = target / Path(*_safe_manifest_relative(relative)) if relative else target
            if _has_link_ancestor(path):
                raise StorageMigrationError(f"目标内容包含符号链接或 junction: {path}")
            if relative in expected:
                raise StorageMigrationError(f"目标清单包含重复路径: {relative}")
            if entry.get("type") == "dir":
                if not path.is_dir():
                    raise StorageMigrationError(f"目标目录缺失: {path}")
                expected[relative] = "dir"
            elif entry.get("type") == "file":
                if not path.is_file() or path.stat().st_size != int(entry.get("targetSize", entry.get("size", -1))):
                    raise StorageMigrationError(f"目标文件大小不匹配: {path}")
                if _hash_file(path) != str(entry.get("targetSha256") or ""):
                    raise StorageMigrationError(f"目标文件哈希不匹配: {path}")
                expected[relative] = "file"
            else:
                raise StorageMigrationError("目标清单包含未知条目类型")
        actual = self._walk_target(target)
        if actual != expected:
            raise StorageMigrationError("目标内容与清单不一致")
        for entry in entries:
            if entry.get("type") != "file" or str(entry.get("relativePath") or "").lower().endswith(("-wal", "-shm")):
                continue
            if Path(str(entry.get("relativePath") or "")).suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
                _validate_sqlite(target / Path(*_safe_manifest_relative(str(entry["targetRelativePath"]))), checkpoint=False)

    @staticmethod
    def _walk_target(root: Path) -> dict[str, str]:
        actual: dict[str, str] = {}
        stack = [root]
        while stack:
            directory = stack.pop()
            aliases: set[str] = set()
            for child in sorted(os.scandir(directory), key=lambda item: _filesystem_name_key(item.name)):
                if child.name == TARGET_MANIFEST_NAME:
                    continue
                _validate_component(child.name)
                alias = _filesystem_name_key(child.name)
                if alias in aliases:
                    raise StorageMigrationError(f"目标目录存在大小写或 Unicode 重名: {directory}")
                aliases.add(alias)
                path = Path(child.path)
                if _is_link(path):
                    raise StorageMigrationError(f"目标内容包含符号链接或 junction: {path}")
                relative = _relative_path(root, path)
                if child.is_dir(follow_symlinks=False):
                    actual[relative] = "dir"
                    stack.append(path)
                elif child.is_file(follow_symlinks=False):
                    actual[relative] = "file"
                else:
                    raise StorageMigrationError(f"目标包含不支持的文件类型: {path}")
        return actual

    def _verify_sources_unchanged(self, plan: dict[str, Any], *, allow_missing: bool) -> None:
        manifest = {
            "sourceSpecs": plan["sourceSpecs"],
            "entries": plan["entries"],
        }
        self._verify_sources_unchanged_from_manifest(manifest, allow_missing=allow_missing)

    def _verify_sources_unchanged_from_manifest(self, manifest: dict[str, Any], *, allow_missing: bool) -> None:
        specs = manifest.get("sourceSpecs")
        entries = manifest.get("entries")
        if not isinstance(specs, list) or not isinstance(entries, list):
            raise StorageMigrationError("迁移清单缺少源目录信息")
        expected_by_label: dict[str, dict[str, dict[str, Any]]] = {}
        for entry in entries:
            if isinstance(entry, dict):
                expected_by_label.setdefault(str(entry.get("sourceLabel") or ""), {})[str(entry.get("relativePath") or "")] = entry
        for spec in specs:
            if not isinstance(spec, dict):
                raise StorageMigrationError("迁移清单源目录无效")
            label = str(spec.get("label") or "")
            root = Path(str(spec.get("path") or ""))
            expected = expected_by_label.get(label, {})
            try:
                actual_entries, _ = _walk_source(root, hash_files=True)
            except StorageMigrationError:
                if allow_missing and not root.exists():
                    continue
                raise
            actual = {str(item["relativePath"]): item for item in actual_entries}
            for relative, expected_entry in expected.items():
                current = actual.get(relative)
                if current is None:
                    if allow_missing:
                        continue
                    raise StorageMigrationError(f"源数据在校验期间消失: {root / relative}")
                if current.get("type") != expected_entry.get("type") or current.get("size") != expected_entry.get("size") or current.get("sha256") != expected_entry.get("sourceSha256", expected_entry.get("sha256")):
                    raise StorageMigrationError(f"源数据在校验期间发生变化: {root / relative}")
            unexpected = set(actual) - set(expected)
            if unexpected:
                raise StorageMigrationError(f"源目录出现未纳入清单的新内容: {root / sorted(unexpected)[0]}")

    def _build_locator(self, plan: dict[str, Any], target: Path) -> dict[str, Any]:
        return {
            "schema": runtime_paths.STORAGE_LOCATOR_SCHEMA,
            "datasetIdentity": DATASET_IDENTITY,
            "state": "committed",
            "migrationId": plan["id"],
            "targetRoot": str(target),
            "storageRoot": str(target),
            "appDataRoot": str(target / runtime_paths.APP_DATA_DIR_NAME),
            "sourceRoots": [spec["path"] for spec in plan["sourceSpecs"]],
            "manifestPath": str(target / TARGET_MANIFEST_NAME),
        }

    def _journal_from_locator(
        self,
        locator: dict[str, Any],
        previous: dict[str, Any] | None,
        state: str,
        phase: str,
        *,
        deleted_bytes: int | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        base = dict(previous or {})
        base.update(
            {
                "schema": STORAGE_SCHEMA,
                "datasetIdentity": DATASET_IDENTITY,
                "id": str(locator.get("migrationId") or base.get("id") or ""),
                "state": state,
                "phase": phase,
                "targetRoot": str(locator["targetRoot"]),
                "sourceSpecs": base.get("sourceSpecs", []),
                "sourceFingerprint": base.get("sourceFingerprint", ""),
                "totalBytes": int(base.get("totalBytes", 0) or 0),
                "requiredBytes": int(base.get("requiredBytes", 0) or 0),
                "progressBytes": int(base.get("progressBytes", base.get("totalBytes", 0)) or 0),
                "deletedBytes": int(base.get("deletedBytes", 0) if deleted_bytes is None else deleted_bytes),
                "error": error,
                "manifestPath": str(locator.get("manifestPath") or Path(locator["targetRoot"]) / TARGET_MANIFEST_NAME),
            }
        )
        return base

    def _cleanup_sources(self, manifest: dict[str, Any], journal: dict[str, Any]) -> int:
        specs = [item for item in manifest.get("sourceSpecs", []) if isinstance(item, dict)]
        entries = [item for item in manifest.get("entries", []) if isinstance(item, dict)]
        deleted_bytes = 0
        for entry in entries:
            if entry.get("type") == "file":
                root = Path(str(entry.get("sourceRoot") or ""))
                relative = str(entry.get("relativePath") or "")
                path = root / Path(*_safe_manifest_relative(relative)) if relative else root
                if not path.exists():
                    deleted_bytes += int(entry.get("size", 0) or 0)
                    continue
                if _is_link(path) or not path.is_file():
                    raise StorageMigrationError(f"源文件清理目标类型不匹配: {path}")
                path.unlink()
                deleted_bytes += int(entry.get("size", 0) or 0)
                journal["deletedBytes"] = deleted_bytes
                self._write_journal(journal)
        directories = sorted(
            (entry for entry in entries if entry.get("type") == "dir" and entry.get("relativePath")),
            key=lambda item: str(item.get("relativePath")).count("/"),
            reverse=True,
        )
        for entry in directories:
            path = Path(str(entry["sourceRoot"])) / Path(*_safe_manifest_relative(str(entry["relativePath"])))
            if path.exists():
                if _is_link(path) or not path.is_dir():
                    raise StorageMigrationError(f"源目录清理目标类型不匹配: {path}")
                try:
                    path.rmdir()
                except OSError as exc:
                    raise StorageMigrationError(f"源目录清理失败: {path}") from exc
        for spec in specs:
            root = Path(str(spec.get("path") or ""))
            if root.exists():
                if _is_link(root) or not root.is_dir():
                    raise StorageMigrationError(f"源根清理目标类型不匹配: {root}")
                try:
                    root.rmdir()
                except OSError as exc:
                    raise StorageMigrationError(f"源根仍有未清理内容: {root}") from exc
        return deleted_bytes

    def _public_job(self, journal: dict[str, Any]) -> dict[str, Any]:
        specs = journal.get("sourceSpecs") or []
        return {
            "id": str(journal.get("id") or ""),
            "state": str(journal.get("state") or ""),
            "phase": str(journal.get("phase") or ""),
            "targetRoot": str(journal.get("targetRoot") or ""),
            "sourceRoots": [str(item.get("path")) for item in specs if isinstance(item, dict) and item.get("path")],
            "progressBytes": int(journal.get("progressBytes", 0) or 0),
            "totalBytes": int(journal.get("totalBytes", 0) or 0),
            "deletedBytes": int(journal.get("deletedBytes", 0) or 0),
            "error": str(journal.get("error") or ""),
        }
