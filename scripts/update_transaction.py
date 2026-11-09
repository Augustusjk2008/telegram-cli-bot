"""Durable file transactions. Standard library only; copied with the recovery runner."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

# Windows access-denied, sharing and lock violations raised while a scanner or
# indexer briefly holds a file; other permission errors are never retried.
TRANSIENT_LOCK_WINERRORS = frozenset({5, 32, 33})
TRANSIENT_LOCK_RETRY_DELAYS = (0.1, 0.25, 0.5, 1.0, 2.0)


class RecoveryRequired(RuntimeError):
    """Recovery material is incomplete or a target changed outside the transaction."""


def retry_transient_lock(operation, *args):
    for delay in (*TRANSIENT_LOCK_RETRY_DELAYS, None):
        try:
            return operation(*args)
        except PermissionError as exc:
            if delay is None or getattr(exc, "winerror", None) not in TRANSIENT_LOCK_WINERRORS:
                raise
            time.sleep(delay)


def _executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def append_journal(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        length = handle.tell()
        if length:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                cursor = length
                while cursor:
                    start = max(0, cursor - 4096)
                    handle.seek(start)
                    block = handle.read(cursor - start)
                    newline = block.rfind(b"\n")
                    if newline >= 0:
                        handle.truncate(start + newline + 1)
                        break
                    cursor = start
                else:
                    handle.truncate(0)
        handle.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


def read_journal(path: Path) -> list[dict]:
    raw = path.read_bytes()
    records = []
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            # A torn final append cannot have authorized a destructive operation.
            break
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RecoveryRequired(f"事务日志损坏，保留恢复目录: {path}") from exc
        if not isinstance(record, dict):
            raise RecoveryRequired(f"事务日志记录无效: {path}")
        records.append(record)
    return records


def safe_target(root: Path, relative: str) -> Path:
    value = str(relative).replace("\\", "/")
    parts = value.split("/")
    if (not value or value.startswith("/") or any(
        part in {"", ".", ".."} or ":" in part or part.endswith((".", " "))
        for part in parts
    )):
        raise RecoveryRequired(f"非法更新路径: {relative}")
    target = root.joinpath(*parts)
    for candidate in (target, *target.parents):
        if candidate == root:
            break
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise RecoveryRequired(f"更新路径经过链接: {candidate}")
        if candidate != target and candidate.exists() and not candidate.is_dir():
            raise RecoveryRequired(f"更新路径的父级不是目录: {candidate}")
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RecoveryRequired(f"更新路径越界: {relative}") from exc
    return target


def durable_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    shutil.copystat(source, destination)
    sync_directory(destination.parent)


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.update-", dir=destination.parent)
    os.close(fd)
    staged = Path(name)
    try:
        durable_copy(source, staged)
        retry_transient_lock(os.replace, staged, destination)
        sync_directory(destination.parent)
    finally:
        staged.unlink(missing_ok=True)


class Transaction:
    def __init__(self, repo_root: Path, transaction_dir: Path):
        self.root = Path(repo_root).resolve()
        self.directory = Path(transaction_dir).resolve()
        self.journal = self.directory / "journal.jsonl"

    def _log(self, event: str, **fields) -> None:
        append_journal(self.journal, {"event": event, **fields})

    def _records(self) -> tuple[dict[str, dict], str]:
        records: dict[str, dict] = {}
        phase = ""
        if not self.journal.exists():
            raise RecoveryRequired(f"缺少事务日志: {self.directory}")
        for event in read_journal(self.journal):
            if event.get("event") == "begin":
                if event.get("schema_version") != 1 or Path(event.get("root", "")).resolve() != self.root:
                    raise RecoveryRequired("事务不属于当前安装")
                phase = "backing_up"
            relative = event.get("relative_path")
            if relative:
                safe_target(self.root, relative)
                records.setdefault(relative, {}).update(event)
            if event.get("event") in {"applied_all", "committed", "rolled_back"}:
                phase = event["event"]
        if not phase:
            raise RecoveryRequired(f"事务日志缺少身份信息: {self.directory}")
        return records, phase

    def backup(self, files: list[str], new_hashes: dict[str, str] | None = None,
               expected_hashes: dict | None = None) -> dict[str, dict]:
        if self.journal.exists():
            raise RecoveryRequired("事务已存在，请先恢复或创建新任务")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._log("begin", schema_version=1, root=str(self.root))
        records = {}
        for index, relative in enumerate(dict.fromkeys(files)):
            target = safe_target(self.root, relative)
            if target.exists() and not target.is_file():
                raise RecoveryRequired(f"更新目标不是普通文件: {relative}")
            existed = target.exists()
            old_hash = sha256(target) if existed else None
            if expected_hashes is not None and (relative not in expected_hashes or expected_hashes[relative] != old_hash):
                raise RecoveryRequired(f"准备后文件发生变化，请重新准备: {relative}")
            record = {
                "relative_path": relative, "target_path": str(target),
                "backup_path": str(self.directory / f"backup-{index:06d}") if existed else "",
                "existed": existed, "old_sha256": old_hash or "",
                "new_sha256": (new_hashes or {}).get(relative, ""),
            }
            self._log("backup_intent", **record)
            if existed:
                backup = Path(record["backup_path"])
                durable_copy(target, backup)
                if sha256(backup) != record["old_sha256"] or sha256(target) != record["old_sha256"]:
                    raise RecoveryRequired(f"备份校验失败: {relative}")
            self._log("backup_done", **record)
            records[relative] = record
        self._log("backups_complete")
        return records

    def apply(self, staging_dir: Path, files: list[str], delete_paths=(), *, expected_hashes=None) -> None:
        staging = Path(staging_dir).resolve()
        write_keys = {os.path.normcase(str(safe_target(self.root, path))) for path in files}
        delete_keys = {os.path.normcase(str(safe_target(self.root, path))) for path in delete_paths}
        if len(write_keys) != len(files) or write_keys & delete_keys:
            raise RecoveryRequired("更新计划含重复目标或写入/删除重叠")
        hashes = {relative: sha256(safe_target(staging, relative)) for relative in files}
        # A target that already holds the staged bytes needs neither a backup nor
        # a write, so downtime and backup size follow the changed files only.
        unchanged = {relative for relative in files
                     if self._already_current(relative, staging, hashes[relative], expected_hashes)}
        paths = [relative for relative in dict.fromkeys([*files, *delete_paths]) if relative not in unchanged]
        records = self.backup(paths, hashes, expected_hashes)
        if unchanged:
            self._log("unchanged_skipped", count=len(unchanged))
        for relative in paths:
            record = records[relative]
            target = safe_target(self.root, relative)
            # Check again immediately before replacing; never overwrite concurrent edits.
            if record["existed"]:
                if not target.is_file() or sha256(target) != record["old_sha256"]:
                    raise RecoveryRequired(f"备份后文件发生变化: {relative}")
            elif target.exists():
                raise RecoveryRequired(f"备份后新增同名文件: {relative}")
            self._log("apply_intent", **record)
            if relative in hashes:
                source = safe_target(staging, relative)
                if sha256(source) != hashes[relative]:
                    raise RecoveryRequired(f"暂存文件发生变化: {relative}")
                atomic_copy(source, target)
            elif target.exists():
                retry_transient_lock(target.unlink)
                sync_directory(target.parent)
            self._log("applied", **record)
        self._log("applied_all")

    def _already_current(self, relative: str, staging: Path, new_hash: str, expected_hashes) -> bool:
        target = safe_target(self.root, relative)
        if not target.is_file() or _executable(target) != _executable(safe_target(staging, relative)):
            return False
        current = sha256(target)
        # A target changed after preparation still reaches backup(), which rejects it.
        return current == new_hash and (expected_hashes is None or expected_hashes.get(relative, "") == current)

    def rollback(self) -> None:
        records, phase = self._records()
        if phase == "rolled_back":
            return
        if phase == "committed":
            raise RecoveryRequired("已确认成功的事务不能再次恢复")
        for relative, record in reversed(list(records.items())):
            target = safe_target(self.root, relative)
            if target.exists() and not target.is_file():
                raise RecoveryRequired(f"恢复目标不是文件: {relative}")
            current_hash = sha256(target) if target.exists() else ""
            old_hash = record.get("old_sha256", "")
            if record.get("existed"):
                if current_hash == old_hash:
                    self._log("restored", **{k: v for k, v in record.items() if k != "event"})
                    continue
                backup = Path(record.get("backup_path", ""))
                if backup.parent.resolve() != self.directory or not backup.is_file() or sha256(backup) != old_hash:
                    raise RecoveryRequired(f"恢复材料缺失或损坏: {relative}; {self.directory}")
                if current_hash and current_hash != record.get("new_sha256"):
                    raise RecoveryRequired(f"目标存在事务之外的修改，保留现场: {relative}")
                self._log("restore_intent", **{k: v for k, v in record.items() if k != "event"})
                atomic_copy(backup, target)
            elif target.exists():
                if current_hash != record.get("new_sha256"):
                    raise RecoveryRequired(f"新增目标发生变化，保留现场: {relative}")
                self._log("restore_intent", **{k: v for k, v in record.items() if k != "event"})
                retry_transient_lock(target.unlink)
                sync_directory(target.parent)
            self._log("restored", **{k: v for k, v in record.items() if k != "event"})
        self._log("rolled_back")

    def recover(self) -> None:
        _, phase = self._records()
        if phase not in {"committed", "rolled_back"}:
            self.rollback()

    def commit(self) -> None:
        _, phase = self._records()
        if phase not in {"applied_all", "committed"}:
            raise RecoveryRequired("文件事务尚未完成")
        if phase != "committed":
            self._log("committed")
