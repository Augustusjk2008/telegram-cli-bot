from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import secrets

from bot.runtime_paths import (
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
    get_tunnel_state_path,
)
from bot.web.auth_store import WebAuthStore

MIGRATION_REPO_STATE_TO_USER_HOME = "001_repo_state_to_user_home"
MIGRATION_IDS = (MIGRATION_REPO_STATE_TO_USER_HOME,)
_LEGACY_APP_SETTING_KEYS = (
    "git_proxy_address",
    "git_proxy_port",
    "bot_avatar_names",
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
    if _repair_app_settings_from_legacy(legacy["app_settings"], get_app_settings_path()):
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


def _load_state() -> dict[str, Any]:
    return _read_json(get_migrations_state_path(), {"version": 1, "completed": [], "last_error": ""})


def _completed_ids(state: dict[str, Any]) -> set[str]:
    completed = state.get("completed")
    if not isinstance(completed, list):
        return set()
    return {str(item.get("id") or "") for item in completed if isinstance(item, dict)}


def _save_state(state: dict[str, Any]) -> None:
    state["version"] = 1
    _atomic_write_json(get_migrations_state_path(), state)


def run_pending_migrations(repo_root: str | Path | None = None) -> MigrationRunResult:
    root = Path(repo_root or Path.cwd()).expanduser().resolve()
    state = _load_state()
    completed_ids = _completed_ids(state)
    completed_now: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for migration_id in MIGRATION_IDS:
        if migration_id in completed_ids:
            skipped.append(migration_id)
            continue
        try:
            if migration_id == MIGRATION_REPO_STATE_TO_USER_HOME:
                detail = _run_repo_state_migration(root)
            else:
                detail = {}
            state.setdefault("completed", []).append(
                {
                    "id": migration_id,
                    "completed_at": _utc_now(),
                    "repo_root": str(root),
                    "data_root": str(get_app_data_root()),
                    "detail": detail,
                }
            )
            state["last_error"] = ""
            completed_now.append(migration_id)
            completed_ids.add(migration_id)
            _save_state(state)
        except Exception as exc:
            message = f"{migration_id}: {exc}"
            errors.append(message)
            state["last_error"] = message
            state["last_error_at"] = _utc_now()
            _save_state(state)
            raise

    try:
        completed_repairs = _completed_repair_targets(state)
        if completed_repairs and sorted(completed_repairs) != state.get("completed_repairs"):
            state["completed_repairs"] = sorted(completed_repairs)
            _save_state(state)
        repair_detail = _repair_polluted_targets(root, skip_targets=completed_repairs)
        if repair_detail["targets"]:
            state["completed_repairs"] = sorted(completed_repairs | set(repair_detail["targets"]))
            state["last_repair"] = {
                "repaired_at": _utc_now(),
                "repo_root": str(root),
                "data_root": str(get_app_data_root()),
                "detail": repair_detail,
            }
            _save_state(state)
    except Exception as exc:
        message = f"repair_polluted_targets: {exc}"
        errors.append(message)
        state["last_error"] = message
        state["last_error_at"] = _utc_now()
        _save_state(state)
        raise

    return MigrationRunResult(
        data_root=get_app_data_root(),
        state_path=get_migrations_state_path(),
        completed=completed_now,
        skipped=skipped,
        errors=errors,
    )


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
    run_pending_migrations(repo_root=args.repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
