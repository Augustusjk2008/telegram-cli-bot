from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

try:
    from dotenv import dotenv_values, load_dotenv

    load_dotenv()
except ImportError:
    dotenv_values = None  # type: ignore[assignment]

_CHAT_ATTACHMENT_ALIAS_RE = re.compile(r"[^A-Za-z0-9._-]+")
TCB_DATA_DIR_ENV: Final = "TCB_DATA_DIR"
APP_DATA_DIR_NAME: Final = "orbit-safe-claw"
STORAGE_LOCATOR_SCHEMA: Final = 1
STORAGE_LOCATOR_FILENAME: Final = "storage.json"
STORAGE_JOURNAL_FILENAME: Final = "storage-migration.json"
STORAGE_PROGRESS_FILENAME: Final = "storage-migration-progress.json"


class StoragePathError(RuntimeError):
    """The persisted storage locator cannot be used safely."""


@dataclass(frozen=True)
class _ActiveStoragePaths:
    storage_root: Path
    app_data_root: Path
    locator: dict[str, Any] | None


_ACTIVE_STORAGE: _ActiveStoragePaths | None = None
_ACTIVE_STORAGE_FINGERPRINT: tuple[str, str, str, str] | None = None
_ACTIVE_STORAGE_LOCK = threading.RLock()


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _legacy_tcb_home_root() -> Path:
    return Path.home() / ".tcb"


def get_storage_locator_path() -> Path:
    """Return the small locator kept outside the movable data roots."""

    return _legacy_tcb_home_root() / STORAGE_LOCATOR_FILENAME


def get_storage_journal_path() -> Path:
    """Return the migration journal kept outside the movable data roots."""

    return _legacy_tcb_home_root() / STORAGE_JOURNAL_FILENAME


def get_storage_progress_path() -> Path:
    """Return the small live-progress file kept outside the movable roots."""

    return _legacy_tcb_home_root() / STORAGE_PROGRESS_FILENAME


def _canonical_path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute().resolve()


def _has_link_ancestor(path: Path) -> bool:
    current = path
    while True:
        try:
            if current.is_symlink() or bool(int(getattr(current.stat(), "st_file_attributes", 0)) & 0x4000):
                return True
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            return False
        current = parent


def read_storage_locator() -> dict[str, Any] | None:
    """Read and validate the committed storage locator.

    A committed locator is authoritative.  In particular, a missing target is
    an explicit startup error and never causes a silent fallback to the old
    root.
    """

    path = get_storage_locator_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StoragePathError(f"无法读取 TCB 存储定位器: {path}") from exc
    if not isinstance(payload, dict):
        raise StoragePathError("TCB 存储定位器格式无效")
    try:
        schema = int(payload.get("schema", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise StoragePathError("TCB 存储定位器版本无效") from exc
    if schema != STORAGE_LOCATOR_SCHEMA:
        raise StoragePathError("TCB 存储定位器版本不受支持")
    if str(payload.get("datasetIdentity") or payload.get("dataset") or "") != "tcb":
        raise StoragePathError("TCB 存储定位器数据集不匹配")
    state = str(payload.get("state") or "").strip().lower()
    if state not in {"committed", "cleanup_pending", "completed"}:
        raise StoragePathError(f"TCB 存储定位器状态无效: {state or 'empty'}")

    target_value = payload.get("targetRoot") or payload.get("storageRoot")
    if not isinstance(target_value, str) or not target_value.strip():
        raise StoragePathError("TCB 存储定位器缺少 targetRoot")
    target_lexical = Path(target_value).expanduser().absolute()
    if _has_link_ancestor(target_lexical):
        raise StoragePathError("TCB 迁移目标包含符号链接或 junction")
    target_root = target_lexical.resolve()
    if not target_root.exists() or not target_root.is_dir():
        raise StoragePathError(f"TCB 迁移目标不存在或不可用: {target_root}")

    app_value = payload.get("appDataRoot")
    app_lexical = Path(app_value).expanduser().absolute() if isinstance(app_value, str) and app_value.strip() else target_root / APP_DATA_DIR_NAME
    if _has_link_ancestor(app_lexical):
        raise StoragePathError("TCB appDataRoot 包含符号链接或 junction")
    app_root = app_lexical.resolve()
    if app_root != target_root and target_root not in app_root.parents:
        raise StoragePathError("TCB 存储定位器的 appDataRoot 越界")

    normalized = dict(payload)
    normalized["targetRoot"] = str(target_root)
    normalized["storageRoot"] = str(target_root)
    normalized["appDataRoot"] = str(app_root)
    normalized["state"] = state
    return normalized


def _dotenv_data_dir() -> str:
    if dotenv_values is None:
        return ""
    try:
        return str(dotenv_values(Path.cwd() / ".env").get(TCB_DATA_DIR_ENV) or "").strip()
    except (OSError, UnicodeError):
        return ""


def _legacy_app_data_root() -> Path:
    override = os.environ.get(TCB_DATA_DIR_ENV, "").strip()
    if not override:
        override = _dotenv_data_dir()
    if override:
        return _canonical_path(override)
    return _legacy_tcb_home_root() / APP_DATA_DIR_NAME


def _configuration_fingerprint() -> tuple[str, str, str, str]:
    explicit = os.environ.get(TCB_DATA_DIR_ENV, "").strip()
    dotenv_override = _dotenv_data_dir()
    return (
        str(_legacy_tcb_home_root()),
        explicit,
        dotenv_override,
        str(Path.cwd()),
    )


def _resolve_active_storage() -> _ActiveStoragePaths:
    locator = read_storage_locator()
    override = os.environ.get(TCB_DATA_DIR_ENV, "").strip() or _dotenv_data_dir()
    if locator is not None:
        app_root = _canonical_path(str(locator["appDataRoot"]))
        if override and _canonical_path(override) != app_root:
            raise StoragePathError(
                "TCB_DATA_DIR 与已提交的存储定位器冲突；请移除旧覆盖后重新启动"
            )
        return _ActiveStoragePaths(_canonical_path(str(locator["targetRoot"])), app_root, locator)

    return _ActiveStoragePaths(_legacy_tcb_home_root(), _legacy_app_data_root(), None)


def _active_storage() -> _ActiveStoragePaths:
    global _ACTIVE_STORAGE, _ACTIVE_STORAGE_FINGERPRINT
    fingerprint = _configuration_fingerprint()
    with _ACTIVE_STORAGE_LOCK:
        if _ACTIVE_STORAGE is not None:
            if _ACTIVE_STORAGE_FINGERPRINT == fingerprint:
                return _ACTIVE_STORAGE
            if _ACTIVE_STORAGE.locator is not None:
                override = os.environ.get(TCB_DATA_DIR_ENV, "").strip() or _dotenv_data_dir()
                if override and _canonical_path(override) != _ACTIVE_STORAGE.app_data_root:
                    raise StoragePathError("TCB_DATA_DIR 与当前进程已冻结的存储定位器冲突")
                return _ACTIVE_STORAGE
        _ACTIVE_STORAGE = _resolve_active_storage()
        _ACTIVE_STORAGE_FINGERPRINT = fingerprint
        return _ACTIVE_STORAGE


def freeze_active_path_resolution() -> Path:
    """Freeze and return this process's current application data root."""

    return _active_storage().app_data_root


def reset_runtime_path_cache_for_tests() -> None:
    """Reset the process-local path cache for isolated tests."""

    global _ACTIVE_STORAGE, _ACTIVE_STORAGE_FINGERPRINT
    with _ACTIVE_STORAGE_LOCK:
        _ACTIVE_STORAGE = None
        _ACTIVE_STORAGE_FINGERPRINT = None


def get_tcb_home_root() -> Path:
    return _active_storage().storage_root


def get_active_storage_root() -> Path:
    return _active_storage().storage_root


def get_legacy_app_data_root() -> Path:
    """Return the pre-locator app root for migration inventory only."""

    return _legacy_app_data_root()


def get_app_data_root() -> Path:
    return _active_storage().app_data_root


def get_app_settings_path() -> Path:
    return get_app_data_root() / "config" / "app_settings.json"


def get_auth_secret_path() -> Path:
    return get_app_data_root() / "auth" / "secret.json"


def get_auth_accounts_dir() -> Path:
    return get_app_data_root() / "auth" / "accounts"


def get_theme_accounts_dir() -> Path:
    return get_app_data_root() / "themes" / "accounts"


def get_auth_username_index_path() -> Path:
    return get_app_data_root() / "auth" / "username_index.json"


def get_auth_register_codes_path() -> Path:
    return get_app_data_root() / "auth" / "register_codes.json"


def get_permissions_root() -> Path:
    return get_app_data_root() / "permissions"


def get_permissions_accounts_dir() -> Path:
    return get_permissions_root() / "accounts"


def get_permissions_bots_path() -> Path:
    return get_permissions_root() / "bots.json"


def get_session_store_path() -> Path:
    return get_app_data_root() / "sessions" / "session_store.json"


def get_native_agent_data_dir() -> Path:
    return get_app_data_root() / "native-agent"


def get_pi_session_store_path() -> Path:
    return get_native_agent_data_dir() / "pi_sessions.json"


def get_pi_workspace_history_diagnostics_dir() -> Path:
    return get_native_agent_data_dir() / "workspace-history-diagnostics"


def get_announcements_content_path() -> Path:
    return get_app_data_root() / "announcements" / "content.json"


def get_announcements_reads_path() -> Path:
    return get_app_data_root() / "announcements" / "reads.json"


def get_lan_chat_config_path() -> Path:
    return get_app_data_root() / "lan_chat" / "config.json"


def get_lan_chat_messages_path() -> Path:
    return get_app_data_root() / "lan_chat" / "messages.json"


def get_inline_completion_config_path() -> Path:
    return get_app_data_root() / "inline-completion" / "config.json"


def get_translation_config_path() -> Path:
    return get_app_data_root() / "chat-translation" / "config.json"


def get_codex_usage_db_path() -> Path:
    return get_app_data_root() / "codex-usage" / "usage.sqlite3"


def get_language_servers_root() -> Path:
    """托管语言服务器的运行态根目录，始终位于用户数据目录。"""

    return get_app_data_root() / "language-servers"


def get_language_server_managed_root() -> Path:
    """兼容性别名：返回语言服务器托管根目录。"""

    return get_language_servers_root()


def get_language_server_node_tools_dir() -> Path:
    """Pyright 与 TypeScript 服务共享的 Node 包目录。"""

    return get_language_servers_root() / "node"


def get_language_server_native_tools_dir() -> Path:
    """clangd 等平台原生归档的托管目录。"""

    return get_language_servers_root() / "native"


def get_tunnel_state_path() -> Path:
    return get_app_data_root() / "tunnel" / "state.json"


def get_web_runtime_state_path() -> Path:
    return get_app_data_root() / "web" / "runtime_state.json"


def get_migrations_state_path() -> Path:
    return get_app_data_root() / "migrations" / "state.json"


def get_migrations_backup_root() -> Path:
    return get_app_data_root() / "migrations" / "backups"


def get_legacy_repo_state_paths(repo_root: str | Path) -> dict[str, Path]:
    root = Path(repo_root).expanduser().resolve()
    return {
        "users": root / ".web_users.json",
        "auth_secret": root / ".web_auth_secret.json",
        "register_codes": root / ".web_register_codes.json",
        "permissions": root / ".web_permissions.json",
        "app_settings": root / ".web_admin_settings.json",
        "sessions": root / ".session_store.json",
        "announcements": root / ".web_announcements.json",
        "announcement_reads": root / ".web_announcement_reads.json",
        "lan_chat_config": root / ".web_lan_chat.json",
        "lan_chat_messages": root / ".web_lan_chat_messages.json",
        "tunnel_state": root / ".web_tunnel_state.json",
    }


def _normalize_chat_attachment_alias(alias: str) -> str:
    candidate = _CHAT_ATTACHMENT_ALIAS_RE.sub("-", str(alias or "").strip()).strip(".-_")
    return candidate or "main"


def get_chat_attachments_dir(alias: str, user_id: int) -> Path:
    return get_tcb_home_root() / "chat-attachments" / _normalize_chat_attachment_alias(alias) / str(user_id)


def get_legacy_project_chat_db_path(working_dir: str | Path) -> Path:
    return Path(str(working_dir)).expanduser() / Path(".tcb") / "state" / "chat.sqlite"


def normalize_workspace_dir(working_dir: str | Path) -> str:
    normalized = os.path.expanduser(str(working_dir))
    normalized = os.path.abspath(normalized)
    normalized = os.path.normpath(normalized)
    if _is_windows_platform():
        normalized = os.path.normcase(normalized)
    return normalized


def get_chat_workspace_key(working_dir: str | Path) -> str:
    normalized = normalize_workspace_dir(working_dir)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_chat_workspace_dir(working_dir: str | Path) -> Path:
    return get_tcb_home_root() / "chat-history" / "workspaces" / get_chat_workspace_key(working_dir)


def get_chat_history_db_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "chat.sqlite"


def get_chat_favorites_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "favorites.json"


def get_chat_workspace_metadata_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "workspace.json"
