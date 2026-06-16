from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Final

try:
    from dotenv import dotenv_values, load_dotenv

    load_dotenv()
except ImportError:
    dotenv_values = None  # type: ignore[assignment]

_CHAT_ATTACHMENT_ALIAS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH = Path(".tcb") / "state" / "chat.sqlite"
TCB_DATA_DIR_ENV: Final = "TCB_DATA_DIR"
APP_DATA_DIR_NAME: Final = "orbit-safe-claw"


def _is_windows_platform() -> bool:
    return os.name == "nt"


def get_tcb_home_root() -> Path:
    return Path.home() / ".tcb"


def get_app_data_root() -> Path:
    override = os.environ.get(TCB_DATA_DIR_ENV, "").strip()
    if not override and dotenv_values is not None:
        override = str(dotenv_values(Path.cwd() / ".env").get(TCB_DATA_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_tcb_home_root() / APP_DATA_DIR_NAME


def get_app_settings_path() -> Path:
    return get_app_data_root() / "config" / "app_settings.json"


def get_auth_secret_path() -> Path:
    return get_app_data_root() / "auth" / "secret.json"


def get_auth_accounts_dir() -> Path:
    return get_app_data_root() / "auth" / "accounts"


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
    return Path(str(working_dir)).expanduser() / _LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH


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


def get_chat_workspace_metadata_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "workspace.json"
