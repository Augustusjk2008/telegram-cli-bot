from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import secrets

from bot.plugins.paths import default_plugins_root
from bot.runtime_paths import (
    _get_app_data_override,
    get_announcements_content_path,
    get_announcements_reads_path,
    get_app_data_root,
    get_app_settings_path,
    get_auth_accounts_dir,
    get_auth_register_codes_path,
    get_auth_secret_path,
    get_auth_username_index_path,
    get_lan_chat_config_path,
    get_lan_chat_messages_path,
    get_legacy_repo_state_paths,
    get_migrations_backup_root,
    get_migrations_state_path,
    get_permissions_accounts_dir,
    get_permissions_bots_path,
    get_session_store_path,
    get_tcb_home_root,
    get_tunnel_state_path,
)
from bot.web.auth_store import WebAuthStore

MIGRATION_REPO_STATE_TO_USER_HOME = "001_repo_state_to_user_home"
MIGRATION_PLUGIN_MANIFEST_V2 = "002_plugin_manifest_v2"
MIGRATION_LEGACY_CHAT_DATA = "003_legacy_chat_data_to_data_root"
MIGRATION_IDS = (MIGRATION_REPO_STATE_TO_USER_HOME, MIGRATION_PLUGIN_MANIFEST_V2, MIGRATION_LEGACY_CHAT_DATA)
_LEGACY_APP_SETTING_KEYS = (
    "git_proxy_address",
    "git_proxy_port",
    "main_bot_profile",
    "global_prompt_presets",
    "update_enabled",
)


@dataclass(frozen=True)
class MigrationRunResult:
    data_root: Path
    state_path: Path
    completed: list[str]
    skipped: list[str]
    errors: list[str]
    repairs: list[str] = field(default_factory=list)


class _MigrationRunLock:
    """无第三方依赖、由操作系统在进程退出时自动释放的跨进程迁移锁。"""

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._handle: Any | None = None
        self._owned = False

    def __enter__(self) -> "_MigrationRunLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a+b")
            _ensure_migration_lock_byte(self._handle)
        except OSError as exc:
            self._close()
            raise RuntimeError(f"无法创建迁移锁文件: {self.path}") from exc

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                acquired = _try_acquire_migration_lock(self._handle)
            except OSError as exc:
                self._close()
                raise RuntimeError(f"无法获取迁移运行锁: {self.path}") from exc
            if acquired:
                self._owned = True
                return self
            if time.monotonic() >= deadline:
                self._close()
                raise RuntimeError(f"迁移正在由另一进程执行: {self.path}")
            time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._close()

    def _close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if self._owned:
                try:
                    _release_migration_lock(handle)
                except OSError:
                    pass
        finally:
            self._owned = False
            self._handle = None
            try:
                handle.close()
            except OSError:
                pass


def _ensure_migration_lock_byte(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _try_acquire_migration_lock(handle: Any) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13, 36}:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _release_migration_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _copy_if_missing(source: Path, target: Path) -> bool:
    if not source.exists() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _looks_like_pytest_path(value: Any) -> bool:
    text = str(value or "").replace("\\", "/").casefold()
    return any(
        marker in text
        for marker in (
            "pytest-of-",
            "/pytest-",
            "/.pytest-tmp/",
            "test_main_bot_workdir_persists",
        )
    )


def _app_settings_needs_legacy_repair(source: dict[str, Any], target: dict[str, Any]) -> bool:
    source_profile = source.get("main_bot_profile")
    if not isinstance(source_profile, dict) or not source_profile:
        return False
    target_profile = target.get("main_bot_profile")
    if not isinstance(target_profile, dict) or not target_profile:
        return True
    return _looks_like_pytest_path(target_profile.get("working_dir"))


def _repair_app_settings_from_legacy(source: Path, target: Path) -> bool:
    if not source.exists() or not target.exists():
        return False
    source_data = _read_json(source, {})
    target_data = _read_json(target, {})
    if not _app_settings_needs_legacy_repair(source_data, target_data):
        return False
    merged = dict(target_data)
    for key in _LEGACY_APP_SETTING_KEYS:
        if key in source_data:
            merged[key] = source_data[key]
    _atomic_write_json(target, merged)
    return True


def _repair_permissions_bots_from_legacy(source: Path, target: Path) -> bool:
    if not source.exists() or not target.exists():
        return False
    source_data = _read_json(source, {"bots": {}})
    target_data = _read_json(target, {"bots": {}})
    source_bots = source_data.get("bots") if isinstance(source_data.get("bots"), dict) else {}
    target_bots = target_data.get("bots") if isinstance(target_data.get("bots"), dict) else {}
    if not source_bots or target_bots:
        return False
    _atomic_write_json(target, {"version": 1, "bots": source_bots})
    return True


def _repair_lan_messages_from_legacy(source: Path, target: Path) -> bool:
    if not source.exists() or not target.exists():
        return False
    source_data = _read_json(source, {})
    target_data = _read_json(target, {})
    source_messages = source_data.get("messages") if isinstance(source_data.get("messages"), list) else []
    target_messages = target_data.get("messages") if isinstance(target_data.get("messages"), list) else []
    if not source_messages or target_messages:
        return False
    _atomic_write_json(target, source_data)
    return True


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_legacy_files(paths: dict[str, Path]) -> tuple[Path | None, dict[str, str]]:
    existing = {name: path for name, path in paths.items() if path.exists() and path.is_file()}
    if not existing:
        return None, {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = get_migrations_backup_root() / stamp
    index: dict[str, str] = {}
    for name, source in existing.items():
        target = backup_dir / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        index[name] = str(target)
    return backup_dir, index


def _backup_migration_file(source: Path, migration_id: str, relative_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = get_migrations_backup_root() / migration_id / stamp / relative_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup_path)
    return backup_path


def _write_secret_permissions(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _ensure_target_auth_secret(source_secret_path: Path) -> None:
    target = get_auth_secret_path()
    if target.exists():
        return
    if source_secret_path.exists():
        _copy_if_missing(source_secret_path, target)
    else:
        _atomic_write_json(target, {"key": _b64encode(secrets.token_bytes(32))})
    _write_secret_permissions(target)


def _split_auth_accounts(users_path: Path, accounts_dir: Path, username_index_path: Path) -> bool:
    if not users_path.exists():
        return False
    raw = _read_json(users_path, {"items": []})
    items = raw.get("items")
    if not isinstance(items, list):
        items = []
    changed = False
    index: dict[str, str] = {}
    auth_store = WebAuthStore(
        users_path=accounts_dir,
        register_codes_path=get_auth_register_codes_path(),
        secret_path=get_auth_secret_path(),
    )
    accounts_dir.mkdir(parents=True, exist_ok=True)
    normalized_items = [dict(item) for item in items if isinstance(item, dict)]
    for item in normalized_items:
        if not isinstance(item, dict):
            continue
        account_id = str(item.get("account_id") or "").strip()
        if not account_id:
            continue
        username = str(item.get("username") or "").strip()
        if username:
            item["username_key"] = item.get("username_key") or auth_store._stable_lookup_key(username.casefold())
            item["username_enc"] = item.get("username_enc") or auth_store._encrypt_text(username)
            item.pop("username", None)
        auth_store._ensure_account_defaults(item, normalized_items)
        username_key = str(item.get("username_key") or "").strip()
        if username_key:
            index[username_key] = account_id
        account_path = accounts_dir / f"{account_id}.json"
        if account_path.exists():
            continue
        _atomic_write_json(account_path, {**item, "schema": "auth_account_v1"})
        changed = True
    if index and not username_index_path.exists():
        _atomic_write_json(username_index_path, {"version": 1, "items": index})
        changed = True
    elif not username_index_path.exists():
        _atomic_write_json(username_index_path, {"version": 1, "items": {}})
        changed = True
    return changed


def _migrate_register_codes(source: Path, target: Path) -> bool:
    if not source.exists() or target.exists():
        return False
    data = _read_json(source, {"items": []})
    auth_store = WebAuthStore(
        users_path=get_auth_accounts_dir(),
        register_codes_path=target,
        secret_path=get_auth_secret_path(),
    )
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    normalized = {"items": [dict(item) for item in items if isinstance(item, dict)]}
    for item in auth_store._items(normalized):
        legacy_created_by = str(item.get("created_by") or "").strip()
        if legacy_created_by and not str(item.get("created_by_enc") or "").strip():
            item["created_by_enc"] = auth_store._encrypt_text(legacy_created_by)
        auth_store._upgrade_register_code_item(item)
        auth_store._register_code_used_count(item)
        auth_store._register_code_max_uses(item)
        item.pop("used_by", None)
        item.pop("created_by", None)
    _atomic_write_json(target, normalized)
    return True


def _split_permissions(source: Path, accounts_dir: Path, bots_path: Path) -> bool:
    if not source.exists():
        return False
    data = _read_json(source, {"version": 1, "users": {}, "bots": {}})
    users = data.get("users") if isinstance(data.get("users"), dict) else {}
    bots = data.get("bots") if isinstance(data.get("bots"), dict) else {}
    changed = False
    accounts_dir.mkdir(parents=True, exist_ok=True)
    for account_id, item in users.items():
        if not isinstance(item, dict):
            continue
        target = accounts_dir / f"{account_id}.json"
        if target.exists():
            continue
        aliases = sorted({str(alias or "").strip().lower() for alias in item.get("allowed_bots", []) if str(alias or "").strip()})
        _atomic_write_json(
            target,
            {
                "version": 1,
                "account_id": str(account_id),
                "allowed_bots": aliases,
                "updated_at": str(item.get("updated_at") or ""),
            },
        )
        changed = True
    if bots and not bots_path.exists():
        _atomic_write_json(bots_path, {"version": 1, "bots": bots})
        changed = True
    elif not bots_path.exists():
        _atomic_write_json(bots_path, {"version": 1, "bots": {}})
        changed = True
    return changed


def _migrate_announcements(content_source: Path, reads_source: Path) -> bool:
    changed = _copy_if_missing(content_source, get_announcements_content_path())
    if reads_source.exists():
        changed = _copy_if_missing(reads_source, get_announcements_reads_path()) or changed
        return changed
    if not content_source.exists() or get_announcements_reads_path().exists():
        return changed
    content = _read_json(content_source, {})
    reads = content.get("reads")
    if isinstance(reads, dict):
        _atomic_write_json(get_announcements_reads_path(), {"version": 1, "updated_at": _utc_now(), "reads": reads})
        changed = True
    return changed


def _web_tunnel_env_has_absolute_override() -> bool:
    value = os.environ.get("WEB_TUNNEL_STATE_FILE", "").strip()
    return bool(value and Path(value).expanduser().is_absolute())


def _write_marker(repo_root: Path, completed: list[str], backup_dir: Path | None) -> None:
    marker_path = repo_root / ".migrated-to-tcb.json"
    marker = _read_json(marker_path, {"migrations": []})
    migrations = marker.get("migrations")
    if not isinstance(migrations, list):
        migrations = []
    seen = {str(item.get("id") or "") for item in migrations if isinstance(item, dict)}
    for migration_id in completed:
        if migration_id in seen:
            continue
        migrations.append(
            {
                "id": migration_id,
                "completed_at": _utc_now(),
                "data_root": str(get_app_data_root()),
                "backup_dir": str(backup_dir) if backup_dir else "",
            }
        )
    marker["migrations"] = migrations
    _atomic_write_json(marker_path, marker)


def _run_repo_state_migration(repo_root: Path) -> dict[str, Any]:
    legacy = get_legacy_repo_state_paths(repo_root)
    backup_dir, backup_index = _backup_legacy_files(legacy)
    changed_targets: list[str] = []

    if legacy["auth_secret"].exists() or legacy["users"].exists() or legacy["register_codes"].exists():
        auth_secret_existed = get_auth_secret_path().exists()
        _ensure_target_auth_secret(legacy["auth_secret"])
        if not auth_secret_existed:
            changed_targets.append("auth_secret")
    if _split_auth_accounts(legacy["users"], get_auth_accounts_dir(), get_auth_username_index_path()):
        changed_targets.append("auth_accounts")
    if _migrate_register_codes(legacy["register_codes"], get_auth_register_codes_path()):
        changed_targets.append("register_codes")
    if _split_permissions(legacy["permissions"], get_permissions_accounts_dir(), get_permissions_bots_path()):
        changed_targets.append("permissions")
    if _copy_if_missing(legacy["app_settings"], get_app_settings_path()):
        changed_targets.append("app_settings")
    if _copy_if_missing(legacy["sessions"], get_session_store_path()):
        changed_targets.append("sessions")
    if _migrate_announcements(legacy["announcements"], legacy["announcement_reads"]):
        changed_targets.append("announcements")
    if _copy_if_missing(legacy["lan_chat_config"], get_lan_chat_config_path()):
        changed_targets.append("lan_chat_config")
    if _copy_if_missing(legacy["lan_chat_messages"], get_lan_chat_messages_path()):
        changed_targets.append("lan_chat_messages")
    if not _web_tunnel_env_has_absolute_override() and _copy_if_missing(legacy["tunnel_state"], get_tunnel_state_path()):
        changed_targets.append("tunnel_state")

    _write_marker(repo_root, [MIGRATION_REPO_STATE_TO_USER_HOME], backup_dir)
    return {
        "targets": changed_targets,
        "backup_dir": str(backup_dir) if backup_dir else "",
        "backup_index": backup_index,
        "source_hashes": {
            key: _sha256_file(path)
            for key, path in legacy.items()
            if path.exists() and path.is_file()
        },
    }


def _plugin_manifest_backup_relative_path(plugins_root: Path, manifest_path: Path) -> Path:
    try:
        return Path("plugins") / manifest_path.relative_to(plugins_root)
    except ValueError:
        return Path("plugins") / manifest_path.parent.name / manifest_path.name


def _migrate_plugin_manifest_v1_to_v2(
    plugins_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root 必须是对象")
    if int(raw.get("schemaVersion") or 0) != 1:
        raise ValueError("manifest 不是 schemaVersion=1")
    runtime_raw = raw.get("runtime")
    if not isinstance(runtime_raw, dict):
        raise ValueError("runtime 必须是对象")
    if runtime_raw.get("permissions") is not None:
        raise ValueError("schemaVersion=1 不支持 runtime.permissions")
    if raw.get("configSchema") is not None:
        raise ValueError("schemaVersion=1 不支持 configSchema")
    if raw.get("catalogActions") is not None:
        raise ValueError("schemaVersion=1 不支持 catalogActions")
    config_raw = raw.get("config") or {}
    if not isinstance(config_raw, dict):
        raise ValueError("config 必须是对象")
    views_raw = raw.get("views") or []
    if not isinstance(views_raw, list):
        raise ValueError("views 必须是数组")
    if any(not isinstance(view, dict) for view in views_raw):
        raise ValueError("view 必须是对象")
    seen_view_ids: set[str] = set()
    for view in views_raw:
        view_id = str(view.get("id") or "").strip()
        if not view_id:
            raise ValueError("view.id 不能为空")
        if view_id in seen_view_ids:
            raise ValueError(f"重复的 view.id: {view_id}")
        seen_view_ids.add(view_id)
        if str(view.get("renderer") or "").strip() != "waveform":
            raise ValueError("schemaVersion=1 仅支持 waveform renderer")
    handlers_raw = raw.get("fileHandlers") or []
    if not isinstance(handlers_raw, list):
        raise ValueError("fileHandlers 必须是数组")
    if any(not isinstance(handler, dict) for handler in handlers_raw):
        raise ValueError("fileHandler 必须是对象")
    for handler in handlers_raw:
        view_id = str(handler.get("viewId") or "").strip()
        if view_id not in seen_view_ids:
            raise ValueError(f"fileHandler.viewId 未定义: {view_id}")
        extensions_raw = handler.get("extensions") or []
        if not isinstance(extensions_raw, list):
            raise ValueError("fileHandler.extensions 必须是数组")
        if any(not str(value or "").strip() for value in extensions_raw):
            raise ValueError("插件扩展名不能为空")

    relative_path = _plugin_manifest_backup_relative_path(plugins_root, manifest_path)
    backup_path = _backup_migration_file(manifest_path, MIGRATION_PLUGIN_MANIFEST_V2, relative_path)
    migrated: dict[str, Any] = {
        "schemaVersion": 2,
    }
    for key in ("id", "name", "version", "description", "enabled"):
        if key in raw:
            migrated[key] = raw[key]
    migrated["config"] = dict(config_raw)
    migrated["runtime"] = {
        "type": runtime_raw.get("type"),
        "entry": runtime_raw.get("entry"),
        "protocol": runtime_raw.get("protocol"),
        "permissions": {},
    }

    migrated["views"] = [
        {
            "id": view.get("id"),
            "title": view.get("title"),
            "renderer": view.get("renderer"),
            "viewMode": str(view.get("viewMode") or "").strip() or "snapshot",
            "dataProfile": str(view.get("dataProfile") or "").strip() or "light",
        }
        for view in views_raw
    ]
    migrated["fileHandlers"] = [
        {
            "id": handler.get("id"),
            "label": handler.get("label"),
            "extensions": list(handler.get("extensions") or []),
            "viewId": handler.get("viewId"),
        }
        for handler in handlers_raw
    ]
    _atomic_write_json(manifest_path, migrated)
    return {
        "path": str(manifest_path),
        "backup_path": str(backup_path),
        "plugin_id": str(raw.get("id") or manifest_path.parent.name),
    }


def _run_plugin_manifest_v2_migration() -> dict[str, Any]:
    plugins_root = default_plugins_root()
    migrated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    if not plugins_root.exists():
        return {
            "plugins_root": str(plugins_root),
            "migrated": migrated,
            "skipped": skipped,
            "invalid": invalid,
        }

    for manifest_path in sorted(plugins_root.glob("*/plugin.json")):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(manifest_path), "error": str(exc)})
            continue
        if not isinstance(raw, dict):
            invalid.append({"path": str(manifest_path), "error": "manifest root 必须是对象"})
            continue
        try:
            schema_version = int(raw.get("schemaVersion") or 0)
        except (TypeError, ValueError):
            invalid.append({"path": str(manifest_path), "error": f"无效 schemaVersion: {raw.get('schemaVersion')}"})
            continue
        if schema_version != 1:
            skipped.append({"path": str(manifest_path), "schemaVersion": str(raw.get("schemaVersion") or "")})
            continue
        try:
            migrated.append(_migrate_plugin_manifest_v1_to_v2(plugins_root, manifest_path))
        except ValueError as exc:
            invalid.append({"path": str(manifest_path), "error": str(exc)})

    return {
        "plugins_root": str(plugins_root),
        "migrated": migrated,
        "skipped": skipped,
        "invalid": invalid,
    }


def _run_legacy_chat_data_migration() -> dict[str, Any]:
    """Move legacy top-level chat data under an explicit TCB_DATA_DIR override.

    chat-history/chat-attachments roots honor TCB_DATA_DIR only when the
    override is set; migrate existing ~/.tcb data once so existing
    installations keep their history after enabling the override.
    """
    override = _get_app_data_override()
    if not override:
        return {"skipped_reason": "no_data_dir_override"}
    data_root = Path(override).expanduser().resolve()
    moved: list[str] = []
    kept_existing: list[str] = []
    for name in ("chat-history", "chat-attachments"):
        legacy_dir = get_tcb_home_root() / name
        if not legacy_dir.is_dir():
            continue
        target_dir = data_root / name
        if target_dir.exists():
            # 目标已有数据时保守跳过，避免覆盖；detail 中记录便于排查。
            kept_existing.append(name)
            continue
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_dir), str(target_dir))
        moved.append(name)
    return {"data_root": str(data_root), "moved": moved, "kept_existing": kept_existing}


def _completed_repair_targets(state: dict[str, Any]) -> set[str]:
    completed: set[str] = set()
    repairs = state.get("completed_repairs")
    if isinstance(repairs, list):
        completed.update(str(item) for item in repairs if str(item).strip())
    last_repair = state.get("last_repair")
    if isinstance(last_repair, dict):
        detail = last_repair.get("detail")
        targets = detail.get("targets") if isinstance(detail, dict) else None
        if isinstance(targets, list):
            completed.update(str(item) for item in targets if str(item).strip())
    return completed


def _repair_polluted_targets(repo_root: Path, *, skip_targets: set[str] | None = None) -> dict[str, Any]:
    legacy = get_legacy_repo_state_paths(repo_root)
    repaired: list[str] = []
    skip_targets = skip_targets or set()
    if "app_settings" not in skip_targets and _repair_app_settings_from_legacy(
        legacy["app_settings"], get_app_settings_path()
    ):
        repaired.append("app_settings")
    if "permissions_bots" not in skip_targets and _repair_permissions_bots_from_legacy(
        legacy["permissions"], get_permissions_bots_path()
    ):
        repaired.append("permissions_bots")
    if "lan_chat_messages" not in skip_targets and _repair_lan_messages_from_legacy(
        legacy["lan_chat_messages"], get_lan_chat_messages_path()
    ):
        repaired.append("lan_chat_messages")
    return {"targets": repaired}


def _load_state(state_path: Path | None = None) -> dict[str, Any]:
    path = state_path or get_migrations_state_path()
    if not path.exists():
        return {"version": 1, "completed": [], "last_error": ""}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"迁移状态文件无效，无法读取 JSON: {path}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"迁移状态文件无效，根必须是对象: {path}")
    version = state.get("version")
    if type(version) is not int or version != 1:
        raise ValueError(f"迁移状态文件无效，不支持的 version: {version!r}: {path}")
    completed = state.get("completed")
    if not isinstance(completed, list):
        raise ValueError(f"迁移状态文件无效，completed 必须是数组: {path}")
    for index, item in enumerate(completed):
        if not isinstance(item, dict):
            raise ValueError(f"迁移状态文件无效，completed[{index}] 必须是对象: {path}")
        migration_id = item.get("id")
        if not isinstance(migration_id, str) or not migration_id.strip():
            raise ValueError(f"迁移状态文件无效，completed[{index}].id 必须是非空字符串: {path}")
    completed_repairs = state.get("completed_repairs")
    if completed_repairs is not None:
        if not isinstance(completed_repairs, list):
            raise ValueError(f"迁移状态文件无效，completed_repairs 必须是数组: {path}")
        for index, target in enumerate(completed_repairs):
            if not isinstance(target, str) or not target.strip():
                raise ValueError(
                    f"迁移状态文件无效，completed_repairs[{index}] 必须是非空字符串: {path}"
                )
    last_repair = state.get("last_repair")
    if last_repair is not None:
        if not isinstance(last_repair, dict):
            raise ValueError(f"迁移状态文件无效，last_repair 必须是对象: {path}")
        detail = last_repair.get("detail")
        if not isinstance(detail, dict):
            raise ValueError(f"迁移状态文件无效，last_repair.detail 必须是对象: {path}")
        targets = detail.get("targets")
        if not isinstance(targets, list):
            raise ValueError(f"迁移状态文件无效，last_repair.detail.targets 必须是数组: {path}")
        for index, target in enumerate(targets):
            if not isinstance(target, str) or not target.strip():
                raise ValueError(
                    f"迁移状态文件无效，last_repair.detail.targets[{index}] 必须是非空字符串: {path}"
                )
    return state


def _completed_ids(state: dict[str, Any]) -> set[str]:
    completed = state.get("completed")
    if not isinstance(completed, list):
        return set()
    return {str(item.get("id") or "") for item in completed if isinstance(item, dict)}


def _save_state(state: dict[str, Any], state_path: Path | None = None) -> None:
    state["version"] = 1
    _atomic_write_json(state_path or get_migrations_state_path(), state)


def _migration_lock_path(state_path: Path) -> Path:
    return state_path.with_name(f"{state_path.name}.lock")


def _run_pending_migrations_locked(root: Path, data_root: Path, state_path: Path) -> MigrationRunResult:
    state = _load_state(state_path)
    completed_ids = _completed_ids(state)
    completed_now: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    repairs: list[str] = []

    for migration_id in MIGRATION_IDS:
        if migration_id in completed_ids:
            skipped.append(migration_id)
            continue
        try:
            if migration_id == MIGRATION_REPO_STATE_TO_USER_HOME:
                detail = _run_repo_state_migration(root)
            elif migration_id == MIGRATION_PLUGIN_MANIFEST_V2:
                detail = _run_plugin_manifest_v2_migration()
            elif migration_id == MIGRATION_LEGACY_CHAT_DATA:
                detail = _run_legacy_chat_data_migration()
            else:
                detail = {}
            state.setdefault("completed", []).append(
                {
                    "id": migration_id,
                    "completed_at": _utc_now(),
                    "repo_root": str(root),
                    "data_root": str(data_root),
                    "detail": detail,
                }
            )
            state["last_error"] = ""
            completed_now.append(migration_id)
            completed_ids.add(migration_id)
            _save_state(state, state_path)
        except Exception as exc:
            message = f"{migration_id}: {exc}"
            errors.append(message)
            state["last_error"] = message
            state["last_error_at"] = _utc_now()
            _save_state(state, state_path)
            raise

    try:
        completed_repairs = _completed_repair_targets(state)
        repair_detail = _repair_polluted_targets(root, skip_targets=completed_repairs)
        if repair_detail["targets"]:
            repairs = list(repair_detail["targets"])
            state["completed_repairs"] = sorted(completed_repairs | set(repair_detail["targets"]))
            state["last_repair"] = {
                "repaired_at": _utc_now(),
                "repo_root": str(root),
                "data_root": str(data_root),
                "detail": repair_detail,
            }
            _save_state(state, state_path)
    except Exception as exc:
        message = f"repair_polluted_targets: {exc}"
        errors.append(message)
        state["last_error"] = message
        state["last_error_at"] = _utc_now()
        _save_state(state, state_path)
        raise

    return MigrationRunResult(
        data_root=data_root,
        state_path=state_path,
        completed=completed_now,
        skipped=skipped,
        errors=errors,
        repairs=repairs,
    )


def run_pending_migrations(repo_root: str | Path | None = None) -> MigrationRunResult:
    root = Path(repo_root or Path.cwd()).expanduser().resolve()
    data_root = get_app_data_root()
    state_path = get_migrations_state_path()
    with _MigrationRunLock(_migration_lock_path(state_path)):
        return _run_pending_migrations_locked(root, data_root, state_path)


def migration_diagnostics(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).expanduser().resolve()
    state = _load_state()
    legacy = get_legacy_repo_state_paths(root)
    return {
        "data_dir": str(get_app_data_root()),
        "completed_migrations": sorted(_completed_ids(state)),
        "last_error": str(state.get("last_error") or ""),
        "legacy_files": {name: path.exists() for name, path in legacy.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bot.migrations")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--repo-root", default=str(Path.cwd()))
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    try:
        result = run_pending_migrations(repo_root=args.repo_root)
    except Exception as exc:
        print(f"迁移失败：{exc}", file=sys.stderr)
        return 1
    if result.errors:
        print("迁移失败：")
        for error in result.errors:
            print(f"- {error}")
        return 1
    if result.completed:
        print("已完成迁移：")
        for migration_id in result.completed:
            print(f"- {migration_id}")
    if result.repairs:
        print("已修复：")
        for target in result.repairs:
            print(f"- {target}")
    if not result.completed and not result.repairs:
        print("检查完成，无待处理项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
