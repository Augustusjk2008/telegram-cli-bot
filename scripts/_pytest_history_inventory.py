"""Read-only discovery of history directories and their current owners."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from bot import runtime_paths as paths
from bot.storage_migration import _validate_component


class Review(ValueError):
    """The item must stay where it is."""


KEY = re.compile(r"[0-9a-f]{64}")
REPO = Path(__file__).resolve().parents[1]
READ_ERRORS = (OSError, ValueError, RuntimeError, sqlite3.Error)


def reject_link(info: os.stat_result, path: Path) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise Review(f"link or reparse point: {path}")


def plain_path(path: Path) -> Path:
    path = path.expanduser()
    if ".." in path.parts:
        raise Review(f"parent traversal: {path}")
    path = path.absolute()
    for parent in (*reversed(path.parents), path):
        try:
            reject_link(parent.lstat(), parent)
        except FileNotFoundError:
            break
    if path.resolve() != path:
        raise Review(f"path resolves elsewhere: {path}")
    return path


def locations() -> dict[str, str]:
    locator = plain_path(paths.get_storage_locator_path())
    if locator.exists():
        raw = read_object(locator)
        for field in ("targetRoot", "storageRoot", "appDataRoot"):
            if raw.get(field):
                plain_path(Path(raw[field]))
    elif override := os.getenv(paths.TCB_DATA_DIR_ENV):
        plain_path(Path(override))
    # The host freezes its locator. A maintenance command needs a fresh read
    # after acquiring the migration lock, including pre-migration overrides.
    current = paths._resolve_active_storage()
    return {"storage": str(plain_path(current.storage_root)), "app": str(plain_path(current.app_data_root)),
            "locator": str(locator), "managed": str(Path(os.getenv("MANAGED_BOTS_FILE", "managed_bots.json")).expanduser().absolute())}


def outside(path: Path, roots: list[Path]) -> Path:
    path = plain_path(path)
    if any(path.is_relative_to(root) or root.is_relative_to(path) for root in roots):
        raise Review(f"directories overlap: {path}")
    return path


def workspace(parent: Path, key: str) -> Path:
    if not KEY.fullmatch(key):
        raise Review(f"invalid workspace key: {key}")
    result = parent / key
    if result.resolve() != result or result.parent != parent:
        raise Review(f"workspace resolves elsewhere: {result}")
    if os.path.lexists(result):
        reject_link(result.lstat(), result)
    return result


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Review(f"expected JSON object: {path}")
    return data


def digest(stream, output=None) -> str:
    value = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        value.update(chunk)
        if output is not None:
            output.write(chunk)
    return value.hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        reject_link(info, path)
        if info.st_nlink > 1:
            raise Review(f"file has multiple links: {path}")
        return digest(stream)


def readonly(path: Path):
    """Read committed WAL if present. Avoid creating sidecars on a quiet DB."""
    path = plain_path(path)
    suffix = "?mode=ro"
    wal = plain_path(Path(str(path) + "-wal"))
    shm = plain_path(Path(str(path) + "-shm"))
    if plain_path(Path(str(path) + "-journal")).exists():
        raise Review(f"rollback journal present: {path}")
    if wal.exists():
        if not shm.exists():
            raise Review(f"WAL without shared memory: {path}")
    else:
        suffix += "&immutable=1"
    return closing(sqlite3.connect(path.as_uri() + suffix, uri=True))


def protection_files(loc: dict) -> list[Path]:
    app = Path(loc["app"])
    legacy = paths.get_legacy_repo_state_paths(Path.cwd())
    session = app / "sessions" / "session_store.json"
    sql = session.with_suffix(".sqlite3")
    return [Path(loc["managed"]), app / "config" / "app_settings.json", legacy["app_settings"],
            session, legacy["sessions"], sql, Path(str(sql) + "-wal"), Path(str(sql) + "-journal"),
            Path.cwd() / ".env"]


def stamps(files: list[Path]) -> list:
    result = []
    for path in files:
        try:
            entry = path.lstat()
            reject_link(entry, path)
            result.append((entry.st_ino, entry.st_size, entry.st_mtime_ns))
        except FileNotFoundError:
            result.append(None)
    return result


def protection(loc: dict) -> dict:
    from bot.models import bot_profile_flags

    files = protection_files(loc)
    for path in files:
        plain_path(path)
    managed, settings, old_settings, sessions, old_sessions, sql = files[:6]
    initial = stamps(files)
    default = os.getenv("WORKING_DIR", os.getcwd())
    protected = {paths.get_chat_workspace_key(default)}
    profiles = []

    def add(value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise Review("missing working_dir in protection data")
        key = paths.get_chat_workspace_key(value.strip())
        protected.add(key)
        return key

    main = add(default)
    for path in (old_settings, settings):
        if path.exists():
            profile = read_object(path).get("main_bot_profile", {})
            if not isinstance(profile, dict):
                raise Review(f"invalid main Bot profile: {path}")
            key = add(profile.get("working_dir") or default)
            if path == settings:
                main = key
    raw = json.loads(managed.read_text(encoding="utf-8"))
    records = raw.get("bots") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise Review("invalid managed Bot list")
    for record in records:
        if not isinstance(record, dict):
            raise Review("invalid managed Bot record")
        key = add(record.get("working_dir") or default)
        try:
            enabled, archived = bot_profile_flags(record)
        except ValueError:
            enabled = archived = None  # Suspended or invalid flags still own history.
        alias = record.get("alias", "")
        if not isinstance(alias, str):
            raise Review("invalid managed Bot alias")
        profiles.append([alias, key, enabled, archived])
    for path in (sessions, old_sessions):
        if path.exists():
            for snapshot in read_object(path).values():
                if not isinstance(snapshot, dict):
                    raise Review(f"invalid session in {path}")
                add(snapshot.get("working_dir"))
    if sql.exists():
        with readonly(sql) as db:
            for (payload,) in db.execute("SELECT payload_json FROM sessions"):
                snapshot = json.loads(payload)
                if not isinstance(snapshot, dict):
                    raise Review(f"invalid session in {sql}")
                add(snapshot.get("working_dir"))
    if initial != stamps(files):
        raise Review("protection files changed during inventory")
    return {"main": main, "profiles": sorted(profiles, key=lambda p: (p[0], p[1])), "keys": sorted(protected),
            "sources": [str(path) for path, stamp in zip(files[:6], initial) if stamp is not None]}


def tree(directory: Path) -> dict:
    reject_link(directory.lstat(), directory)
    result = {}

    def visit(parent: Path, prefix: str) -> None:
        with os.scandir(parent) as entries:
            for entry in entries:
                _validate_component(entry.name)
                path = Path(entry.path)
                # NTFS directory enumeration can return a stale descendant mtime.
                info = path.lstat()
                reject_link(info, path)
                name = prefix + entry.name
                if stat.S_ISDIR(info.st_mode):
                    result[name + "/"] = {"size": 0, "mtime_ns": info.st_mtime_ns}
                    visit(path, name + "/")
                elif stat.S_ISREG(info.st_mode):
                    result[name] = {"size": info.st_size, "mtime_ns": info.st_mtime_ns}
                else:
                    raise Review(f"special file: {path}")

    visit(directory, "")
    return result


def metadata(directory: Path) -> str:
    data = read_object(directory / "workspace.json")
    wd = data.get("working_dir")
    if not isinstance(wd, str) or not Path(wd).is_absolute() or ".." in Path(wd).parts:
        raise Review("invalid metadata working_dir")
    if (data.get("workspace_key") != directory.name or paths.get_chat_workspace_key(wd) != directory.name
            or paths.normalize_workspace_dir(wd) != data.get("normalized_working_dir")):
        raise Review("workspace hash or normalized path mismatch")
    return wd


def pytest_case(wd: str) -> bool:
    parts = Path(wd).parts
    return any(re.fullmatch(r"pytest-of-.+", owner, re.I) and re.fullmatch(r"pytest-\d+", run, re.I)
               and re.fullmatch(r"test_.+", case, re.I) for owner, run, case in zip(parts, parts[1:], parts[2:]))


def inspect(directory: Path, protected: set, cutoff_ns: int, config_error: str) -> dict:
    files = {}
    wd = ""
    state = "skipped"
    try:
        files = tree(directory)
        if "chat.sqlite" not in files:
            raise Review("missing chat.sqlite")
        wd = metadata(directory)
        if directory.name in protected:
            reason = "protected workspace"
        elif not pytest_case(wd):
            reason = "outside pytest case"
        elif config_error:
            raise Review(config_error)
        elif files["chat.sqlite"]["mtime_ns"] >= cutoff_ns:
            reason = "database at or after cutoff"
        else:
            plain_path(Path(wd))
            if any(name.lower().endswith(("-wal", "-shm", "-journal")) for name in files):
                raise Review("SQLite sidecar present")
            for name, entry in files.items():
                if not name.endswith("/"):
                    entry["sha256"] = file_hash(directory / name)
            check_tree(directory, files)
            state, reason = "candidate", ""
    except READ_ERRORS as exc:
        state, reason = "review", str(exc)
    return {"key": directory.name, "working_dir": wd, "state": state, "reason": reason,
            "size": sum(v["size"] for v in files.values()), "db_size": files.get("chat.sqlite", {}).get("size", 0),
            "files": files if state == "candidate" else {}}


def check_tree(directory: Path, expected: dict, *, hashes: bool = False) -> None:
    found = tree(directory)
    if found.keys() != expected.keys():
        raise Review(f"workspace membership changed: {directory}")
    for name, entry in found.items():
        saved = expected[name]
        if entry["size"] != saved["size"] or entry["mtime_ns"] != saved["mtime_ns"]:
            raise Review(f"workspace file changed: {directory / name}")
        if hashes and not name.endswith("/") and file_hash(directory / name) != saved["sha256"]:
            raise Review(f"workspace hash changed: {directory / name}")
